import asyncio
import os
import aiohttp
import aiofiles
from engine.models import DownloadItem, DownloadStatus
import time
import logging

# Configure logging
logging.basicConfig(
    filename='idm.log', 
    level=logging.DEBUG, 
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class Downloader:
    def __init__(self, item: DownloadItem, num_chunks: int = 8):
        self.item = item
        self.num_chunks = num_chunks
        self.session = None
        self._paused = False
        self._cancelled = False
        self.MAX_RETRIES = 5
        self.RETRY_DELAY = 1.0

    def sanitize_filename(self, filename):
        import re
        # Remove invalid characters
        filename = re.sub(r'[<>:"/\\|?*]', '_', filename)
        # Collapse multiple underscores
        filename = re.sub(r'_+', '_', filename)
        
        # Heuristic: If filename is ridiculously long (e.g. > 50 chars) and contains '=', it might be a query string leak.
        if len(filename) > 50 and ('=' in filename or '_cf_chl_tk' in filename):
            # Try to clean up Cloudflare/Query string garbage
            # 1. Look for known problematic markers
            for marker in ['_cf_chl_tk', '___cf_chl_tk', '?']:
                if marker in filename:
                    filename = filename.split(marker)[0].strip('_')
                    # Restore extension if it was lost? Usually lost.
                    # Try to guess extension from what's left
                    break
            
            # 2. General truncation with extension check
            parts = filename.split('.')
            if len(parts) > 1:
                ext = parts[-1]
                if len(ext) < 10: # Valid extension
                     name = ".".join(parts[:-1])
                     if len(name) > 64:
                         name = name[:64]
                     return f"{name}.{ext}"
            else:
                 # No extension? Just truncate
                 if len(filename) > 64:
                     filename = filename[:64]
        
        # Basic truncation
        if len(filename) > 200:
            filename = filename[:200]
            
        return filename.strip('_')


    async def handle_data_uri(self):
        try:
            logger.info("Handling data URI download")
            import base64
            
            header, data = self.item.url.split(',', 1)
            # header e.g., "data:image/jpeg;base64"
            mime_type = header.split(':')[1].split(';')[0]
            
            # Guess extension
            import mimetypes
            ext = mimetypes.guess_extension(mime_type) or ".bin"
            
            if not self.item.filename:
                self.item.filename = f"download_{int(time.time())}{ext}"
            
            self.item.filename = self.sanitize_filename(self.item.filename)
            self.full_path = os.path.join(self.item.save_path, self.item.filename)
            
            decoded_data = base64.b64decode(data)
            self.item.total_size = len(decoded_data)
            
            # Write to file
            async with aiofiles.open(self.full_path, 'wb') as f:
                await f.write(decoded_data)
            
            self.item.downloaded_size = self.item.total_size
            self.item.progress = 100
            self.item.status = DownloadStatus.COMPLETED
            logger.info(f"Data URI download completed: {self.item.filename}")
            
        except Exception as e:
            logger.error(f"Failed to process data URI: {e}")
            self.item.status = DownloadStatus.ERROR
            self.item.error_message = f"Invalid Data URI: {str(e)}"

    async def get_file_info(self):
        logger.info(f"Getting info for {self.item.url}")
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
            "Accept-Encoding": "gzip, deflate",
            "Accept-Language": "en-US,en;q=0.9",
            "Sec-Ch-Ua": '"Not_A Brand";v="8", "Chromium";v="120", "Google Chrome";v="120"',
            "Sec-Ch-Ua-Mobile": "?0",
            "Sec-Ch-Ua-Platform": '"Windows"',
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none",
            "Sec-Fetch-User": "?1",
            "Upgrade-Insecure-Requests": "1",
            "Connection": "keep-alive"
        }
        
        if self.item.headers:
            cleaned_custom = {k: v for k, v in self.item.headers.items() if v}
            
            # If extension provides a User-Agent, we MUST use it to match the cookies/session.
            # However, if we use an external UA, our hardcoded Client Hints (Chrome 120) might mismatch.
            # Safe bet: If using external UA, DROP our hardcoded Client Hints to avoid being flagged as a liar.
            if "User-Agent" in cleaned_custom:
                # Remove our hardcoded hints
                headers = {k: v for k, v in headers.items() if not k.lower().startswith("sec-ch-ua")}
                
            headers.update(cleaned_custom)
            
        # Ensure Referer is set if missing (some sites block empty referer)
        if "Referer" not in headers:
            from urllib.parse import urlparse
            parsed = urlparse(self.item.url)
            headers["Referer"] = f"{parsed.scheme}://{parsed.netloc}/"
        
        last_error = None
        for attempt in range(self.MAX_RETRIES):
            try:
                # Log request for debugging
                logger.debug(f"Attempt {attempt+1}: HEAD {self.item.url}")
                logger.debug(f"Request Headers: {headers}")

                async with aiohttp.ClientSession(headers=headers, trust_env=True) as session:
                    async with session.head(self.item.url, allow_redirects=True, timeout=30) as response:
                        logger.debug(f"Response Status: {response.status}")
                        logger.debug(f"Response Headers: {response.headers}")

                        # Handle Retryable Server Errors
                        if response.status in [500, 502, 503, 504]:
                            logger.warning(f"Server Error {response.status}. Retrying...")
                            raise aiohttp.ClientError(f"Server Error {response.status}")

                        # Resolve redirects
                        new_url = str(response.url)
                        if new_url != self.item.url:
                            # If redirected to a new domain, check if we should clear cookies
                            from urllib.parse import urlparse
                            old_domain = urlparse(self.item.url).netloc
                            new_domain = urlparse(new_url).netloc
                            
                            if old_domain != new_domain:
                                logger.info(f"Redirected to new domain: {new_domain}. Clearing cookies.")
                                if "Cookie" in self.item.headers:
                                    del self.item.headers["Cookie"]
                                if "Referer" in self.item.headers:
                                    del self.item.headers["Referer"]
                                    
                        self.item.url = new_url
                        self.item.total_size = int(response.headers.get('Content-Length', 0))
                        
                        if response.status >= 400:
                            if response.status in [403, 405]:
                                logger.warning(f"HEAD returned {response.status}, switching to GET for file info...")
                                raise Exception("SwitchToGet")
                            raise Exception(f"HTTP Error {response.status}: {response.reason}")

                        # Try to guess filename from header or url
                        if not self.item.filename:
                            content_disposition = response.headers.get('Content-Disposition')
                            if content_disposition and 'filename=' in content_disposition:
                                self.item.filename = content_disposition.split('filename=')[1].strip('"')
                            else:
                                self.item.filename = os.path.basename(self.item.url) or "downloaded_file"
                        
                        self.item.filename = self.sanitize_filename(self.item.filename)
                        self.full_path = os.path.join(self.item.save_path, self.item.filename)
                        logger.info(f"Resolved filename: {self.item.filename}, Size: {self.item.total_size}")
                        return # Success

            except (asyncio.TimeoutError, aiohttp.ClientError) as e:
                last_error = e
                last_error = e
                logger.warning(f"Attempt {attempt + 1}/{self.MAX_RETRIES} failed for info: {e}. Retrying...")
                if attempt < self.MAX_RETRIES - 1:
                    await asyncio.sleep(self.RETRY_DELAY * (attempt + 1)) # Exponential backoffish
                continue
            except Exception as e:
                if str(e) == "SwitchToGet":
                    try:
                        # Fallback to GET
                        logger.info("Falling back to GET for info")
                        async with aiohttp.ClientSession(headers=headers, trust_env=True) as session:
                            async with session.get(self.item.url, allow_redirects=True, timeout=30) as response:
                                logger.debug(f"GET Response Status: {response.status}")
                                if response.status == 403:
                                    logger.warning("GET with robust headers failed (403). Trying minimalist headers.")
                                    raise Exception("TryMinimalist")
                                    
                                if response.status >= 400:
                                    logger.error(f"GET also failed with {response.status}")
                                    self.item.status = DownloadStatus.ERROR
                                    self.item.error_message = f"HTTP Error {response.status}"
                                    raise Exception(f"HTTP Error {response.status}")
                                
                                # Resolve redirects
                                new_url = str(response.url)
                                # (Redirect logic duplicated simple version)
                                if new_url != self.item.url:
                                    self.item.url = new_url
                                    
                                self.item.total_size = int(response.headers.get('Content-Length', 0))
                                
                                if not self.item.filename:
                                    content_disposition = response.headers.get('Content-Disposition')
                                    if content_disposition and 'filename=' in content_disposition:
                                        self.item.filename = content_disposition.split('filename=')[1].strip('"')
                                    else:
                                        self.item.filename = os.path.basename(self.item.url) or "downloaded_file"
                                        
                                self.item.filename = self.sanitize_filename(self.item.filename)
                                self.full_path = os.path.join(self.item.save_path, self.item.filename)
                                logger.info(f"Resolved filename via GET: {self.item.filename}, Size: {self.item.total_size}")
                                return
                    except Exception as get_e:
                        if str(get_e) == "TryMinimalist":
                            try:
                                # Minimalist retry
                                mini_headers = {
                                    "User-Agent": headers.get("User-Agent", "Mozilla/5.0"),
                                    "Accept": "*/*"
                                }
                                logger.info("Retrying with minimalist headers...")
                                async with aiohttp.ClientSession(headers=mini_headers, trust_env=True) as session:
                                    async with session.get(self.item.url, allow_redirects=True, timeout=30) as response:
                                        if response.status >= 400:
                                             raise Exception(f"Minimalist failed: {response.status}")
                                             
                                        # Success logic duplicated
                                        self.item.url = str(response.url)
                                        self.item.total_size = int(response.headers.get('Content-Length', 0))
                                        if not self.item.filename:
                                            self.item.filename = os.path.basename(self.item.url) or "downloaded_file"
                                        self.item.filename = self.sanitize_filename(self.item.filename)
                                        self.full_path = os.path.join(self.item.save_path, self.item.filename)
                                        logger.info(f"Resolved with minimalist: {self.item.filename}")
                                        
                                        # UPDATE default headers to minimalist for chunks
                                        self.item.headers = mini_headers
                                        return
                            except Exception as min_e:
                                logger.error(f"Minimalist retry failed: {min_e}")
                                # Final Fallback: CURL
                                try:
                                    logger.info("Trying fallback to CURL for info...")
                                    await self.fetch_info_with_curl()
                                    return
                                except Exception as curl_e:
                                    logger.error(f"CURL fallback failed: {curl_e}")
                                    e = min_e # Keep original error or minimalist error
                        else:
                            logger.error(f"GET info failed: {get_e}")
                            e = get_e # Propagate the real error

                logger.error(f"Error getting file info: {e}")
                # DEBUG: Write headers to file to debug 401 errors
                try:
                    with open("debug_headers.log", "w") as f:
                        f.write(f"URL: {self.item.url}\n")
                        f.write(f"Headers: {headers}\n")
                        f.write(f"Error: {e}\n")
                except:
                    pass
                
                self.item.status = DownloadStatus.ERROR
                self.item.error_message = str(e)
                raise e
        
        # If we exhausted retries
        error_msg = f"Connection timed out while getting file info after {self.MAX_RETRIES} attempts. Last error: {last_error}"
        logger.error(error_msg)
        raise Exception(error_msg)

    async def fetch_info_with_curl(self):
        # Run curl -I -L -k <url> to get headers
        # -I: Head only
        # -L: Follow redirects
        # -k: Insecure/Skip SSL (sometimes needed for misconfigured sites, helpful for avoiding strict SSL checks)
        # --user-agent: Use a standard UA
        # Prepare headers for CURL to pass WAFs
        # Start with default browser-like headers
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
            "Accept-Language": "en-US,en;q=0.9",
        }
        
        # Merge custom headers (contains Cookies, correct UA, etc.)
        if self.item.headers:
            cleaned_custom = {k: v for k, v in self.item.headers.items() if v}
            # If using external UA, drop hardcoded hints (though curl doesn't send hints by default unless we add them)
            # We just overwrite/update
            headers.update(cleaned_custom)
            
        # Ensure Referer
        if "Referer" not in headers:
            from urllib.parse import urlparse
            p = urlparse(self.item.url)
            headers["Referer"] = f"{p.scheme}://{p.netloc}/"

        cmd = [
            "curl.exe", 
            "-I", 
            "-L", 
            "-k",
            "--compressed", # Handle gzip/deflate
        ]
        
        for k, v in headers.items():
            cmd.extend(["-H", f"{k}: {v}"])
            
        cmd.append(self.item.url)
        
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        
        stdout, stderr = await process.communicate()
        
        if process.returncode != 0:
            raise Exception(f"Curl failed with code {process.returncode}: {stderr.decode(errors='ignore')}")
            
        output = stdout.decode(errors='ignore')
        lines = output.splitlines()
        
        # Parse headers from the LAST response (curl -L might show multiple)
        # We need to find the block of headers corresponding to the final 200 OK (or actual file response)
        # But simpler logic: iterate lines, update state
        
        content_length = 0
        filename = None
        final_url = self.item.url # Curl doesn't easily report final URL in -I unless we parse 'Location' headers sequentially
        
        # To get final URL reliably with curl -I -L, we look at the last Location header, 
        # BUT header order matters.
        # Alternative: use curl -w "%{url_effective}" to get final URL. 
        # But let's stick to parsing headers for now or use a second call if needed.
        
        for line in lines:
            line = line.strip()
            if not line: continue
            if ':' in line:
                key, value = line.split(':', 1)
                key = key.strip().lower()
                value = value.strip()
                
                if key == 'content-length':
                    try:
                        content_length = int(value)
                    except: pass
                elif key == 'content-disposition':
                    if 'filename=' in value:
                        filename = value.split('filename=')[1].strip('"')
                        
        self.item.total_size = content_length
        if filename:
            self.item.filename = filename
        
        if not self.item.filename:
             self.item.filename = os.path.basename(self.item.url) or "downloaded_file"

        self.item.filename = self.sanitize_filename(self.item.filename)
        self.full_path = os.path.join(self.item.save_path, self.item.filename)
        
        logger.info(f"Resolved via CURL: {self.item.filename}, Size: {self.item.total_size}")
        
        # If curl worked, we trust its ability to connect. 
        # We might want to use curl for chunks too? 
        # For now, let's assume getting info unblocked us (e.g. valid cookie set?) or just updated the URL logic.
        # If aiohttp fails chunks, we are still stuck.
        # But often HEAD is blocked while GET (chunk) is not? Let's hope.

    async def download_chunk(self, chunk_id, start_byte, end_byte):
        part_file = f"{self.full_path}.part{chunk_id}"
        current_size = 0
        
        # Resume logic
        if os.path.exists(part_file):
            current_size = os.path.getsize(part_file)
            if end_byte != -1 and current_size >= (end_byte - start_byte + 1):
                 return
            
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "*/*",
            "Accept-Encoding": "gzip, deflate",
            "Accept-Language": "en-US,en;q=0.9",
            "Sec-Ch-Ua": '"Not_A Brand";v="8", "Chromium";v="120", "Google Chrome";v="120"',
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "same-origin",
            "Connection": "keep-alive"
        }
        
        # Construct Range header
        if end_byte == -1:
            # If end_byte is -1, we want from start+current to end
            headers['Range'] = f'bytes={start_byte + current_size}-'
        else:
            headers['Range'] = f'bytes={start_byte + current_size}-{end_byte}'
            
            headers['Range'] = f'bytes={start_byte + current_size}-{end_byte}'
            
        if self.item.headers:
             cleaned = {k: v for k, v in self.item.headers.items() if v}
             
             # If using external UA, drop hardcoded hints to avoid mismatch
             if "User-Agent" in cleaned:
                 headers = {k: v for k, v in headers.items() if not k.lower().startswith("sec-ch-ua")}
                 
             headers.update(cleaned)

        if "Referer" not in headers:
            from urllib.parse import urlparse
            p = urlparse(self.item.url)
            headers["Referer"] = f"{p.scheme}://{p.netloc}/"
        
        for attempt in range(self.MAX_RETRIES):
            try:
                async with self.session.get(self.item.url, headers=headers, timeout=60) as response:
                    if response.status in [500, 502, 503, 504]:
                        logger.warning(f"Chunk {chunk_id} Server Error {response.status}. Retrying...")
                        raise aiohttp.ClientError(f"Server Error {response.status}")
                    
                    if response.status >= 400:
                            raise Exception(f"HTTP {response.status} for chunk {chunk_id}")
                    
                    async with aiofiles.open(part_file, 'ab') as f:
                        async for data in response.content.iter_chunked(1024 * 64): # 64KB chunks
                            if self._paused or self._cancelled:
                                return
                            await f.write(data)
                            self.item.downloaded_size += len(data)
                            # Update chunk progress
                            downloaded_chunk = os.path.getsize(part_file)
                            total_chunk = end_byte - start_byte + 1
                            if total_chunk > 0:
                                pct = (downloaded_chunk / total_chunk) * 100
                                self.item.chunk_progress[chunk_id] = pct
                                # logger.debug(f"Updated chunk {chunk_id}: {pct}%")
                return # Success if finished
            except (asyncio.TimeoutError, aiohttp.ClientError) as e:
                logger.warning(f"Chunk {chunk_id} attempt {attempt + 1}/{self.MAX_RETRIES} failed: {e}. Retrying...")
                if attempt < self.MAX_RETRIES - 1:
                     await asyncio.sleep(self.RETRY_DELAY * (attempt + 1))
                else:
                     logger.error(f"Chunk {chunk_id} failed after {self.MAX_RETRIES} retries: {e}")
                     raise e
            except Exception as e:
                logger.error(f"Chunk {chunk_id} failed with non-retryable error: {e}")
                raise e

    async def monitor_speed(self):
        last_size = self.item.downloaded_size
        while self.item.status == DownloadStatus.DOWNLOADING:
            await asyncio.sleep(1)
            current_size = self.item.downloaded_size
            self.item.speed = (current_size - last_size) # bytes/sec
            last_size = current_size
            if self.item.total_size > 0:
                self.item.progress = (current_size / self.item.total_size) * 100

    async def start(self):
        self.item.status = DownloadStatus.DOWNLOADING
        logger.info(f"Starting download: {self.item.id} - {self.item.url}")
        try:
            # Ensure full_path is set
            if self.item.filename:
                self.item.filename = self.sanitize_filename(self.item.filename)
                self.full_path = os.path.join(self.item.save_path, self.item.filename)

            if self.item.url.startswith('data:'):
                await self.handle_data_uri()
                return

            if self.item.total_size == 0 or not self.item.filename:
                await self.get_file_info()
            
            # Re-ensure in case get_file_info updated it
            # Re-ensure in case get_file_info updated it
            if self.item.filename:
                 self.full_path = os.path.join(self.item.save_path, self.item.filename)
            
            self.session = aiohttp.ClientSession(headers={"User-Agent": "IDM-Clone/1.0"}, trust_env=True)
            
            monitor_task = asyncio.create_task(self.monitor_speed())

            # If total_size is 0 (unknown), we force single chunk download
            if self.item.total_size <= 0:
                logger.warning("Total size is unknown or 0. Forcing single-threaded download.")
                self.num_chunks = 1
                # For unknown size, we pass a special sentinel or handle it in download_chunk
                # But download_chunk expects byte ranges. 
                # We need a new method or modify download_chunk to handle "download until EOF"
                # Let's modify logic to just use one 'chunk' that covers everything.
                # In common HTTP, if we don't know size, we can't really do Range requests easily unless we know start.
                # If we send Range: bytes=0-, it might work.
                tasks = [self.download_chunk(0, 0, -1)] # -1 indicates "until end"
            else:
                
                # Heuristic for auto-threading
                if self.item.total_size < 1024 * 1024: # < 1MB
                    self.num_chunks = 1
                elif self.item.total_size < 50 * 1024 * 1024: # 1-50MB
                    self.num_chunks = 4
                elif self.item.total_size < 500 * 1024 * 1024: # 50-500MB
                    self.num_chunks = 8
                elif self.item.total_size < 1024 * 1024 * 1024: # 500-1GB
                    self.num_chunks = 16
                else: # > 1GB
                    self.num_chunks = 32
                    
                logger.info(f"Auto-configured {self.num_chunks} threads for size {self.item.total_size}")
                
                chunk_size = self.item.total_size // self.num_chunks
                tasks = []
                
                for i in range(self.num_chunks):
                    start = i * chunk_size
                    end = start + chunk_size - 1 if i < self.num_chunks - 1 else self.item.total_size - 1
                    tasks.append(self.download_chunk(i, start, end))
                    
            # Initialize chunk progress
            self.item.chunk_progress = {i: 0.0 for i in range(self.num_chunks)}

            await asyncio.gather(*tasks)
            if not self._paused and not self._cancelled:
                 self.merge_files()
                 self.item.status = DownloadStatus.COMPLETED
                 self.item.chunk_progress = {i: 100.0 for i in range(self.num_chunks)} # Ensure all show 100%
                 logger.info(f"Download completed: {self.item.id}")

            monitor_task.cancel()
                 
        except Exception as e:
            error_msg = str(e).strip()
            if not error_msg:
                error_msg = repr(e)
            
            logger.error(f"Download failed {self.item.id}: {error_msg}")
            
            # Check for 403/Forbidden specific errors to trigger strict fallback
            if "403" in error_msg or "Forbidden" in error_msg:
                logger.info("Triggering System Curl Fallback for download...")
                try:
                    await self.download_with_curl()
                    self.item.status = DownloadStatus.COMPLETED
                    logger.info(f"Download completed via CURL: {self.item.id}")
                    return
                except Exception as curl_e:
                    logger.error(f"Curl download also failed: {curl_e}")
                    error_msg = f"Curl failed: {curl_e}"
            
            self.item.status = DownloadStatus.ERROR
            self.item.error_message = error_msg
        finally:
            if self.session:
                await self.session.close()

    async def download_with_curl(self):
        # Fallback for strict sites
        # curl -L -k -o <path> <url>
        
        # Ensure directory exists
        os.makedirs(os.path.dirname(self.full_path), exist_ok=True)
        
        # Prepare headers
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "*/*",
            "Accept-Language": "en-US,en;q=0.9",
        }
        
        if self.item.headers:
             cleaned = {k: v for k, v in self.item.headers.items() if v}
             headers.update(cleaned)

        if "Referer" not in headers:
            from urllib.parse import urlparse
            p = urlparse(self.item.url)
            headers["Referer"] = f"{p.scheme}://{p.netloc}/"
            
        cmd = [
            "curl.exe",
            "-L",
            "-k",
            "--compressed",
            "-o", self.full_path,
        ]
        
        for k, v in headers.items():
            cmd.extend(["-H", f"{k}: {v}"])
            
        cmd.append(self.item.url)
        
        logger.info(f"Running curl: {' '.join(cmd)}")
        
        process = await asyncio.create_subprocess_exec(
            *cmd,
            # We don't pipe stdout/stderr vigorously to avoid blocking buffer, 
            # but we could capture for error logging
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        
        # Wait for completion
        # TODO: Parse progress from stderr? Curl writes progress to stderr.
        # For now, just wait.
        stdout, stderr = await process.communicate()
        
        if process.returncode != 0:
             raise Exception(f"Curl exited with {process.returncode}: {stderr.decode(errors='ignore')}")
             
        # Check if file exists and has size
        if not os.path.exists(self.full_path) or os.path.getsize(self.full_path) == 0:
             raise Exception("Curl finished but file is empty or missing.")
             
        # Verification: Check if we downloaded a Cloudflare error page despite status 0
        try:
            # Re-check file size - if it's still tiny (< 50KB), suspicious. valid 5GB file won't be that small.
            current_size = os.path.getsize(self.full_path)
            
            is_html_garbage = False
            if current_size < 50 * 1024: # Less than 50KB
                with open(self.full_path, 'rb') as f:
                    head = f.read(4096).decode('utf-8', errors='ignore')
                    
                if "<!DOCTYPE html>" in head or "<html" in head:
                     if any(x in head.lower() for x in ["cloudflare", "challenge", "just a moment", "attention required", "security check"]):
                         is_html_garbage = True
            
            if is_html_garbage:
                logger.warning("Detected Cloudflare Challenge Page in download. Token mismatch likely.")
                
                # First Retry: Clean URL
                if '?' in self.item.url:
                    logger.info("Retrying CURL with CLEAN URL (stripping query parameters)...")
                    clean_url = self.item.url.split('?')[0]
                    cmd[-1] = clean_url
                    
                    process = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
                    await process.communicate()
                    
                    # Re-verify size
                    if os.path.exists(self.full_path) and os.path.getsize(self.full_path) > 50 * 1024:
                         logger.info("Clean URL retry successful (size > 50KB).")
                         is_html_garbage = False
                
                # If still garbage, give up and open browser
                if is_html_garbage:
                     logger.error("CURL failed to bypass Cloudflare. Asking user for manual help.")
                     
                     # Create a local HTML file to break the automated loop
                     help_path = os.path.join(self.item.save_path, f"manual_download_helper.html")
                     try:
                         with open(help_path, "w", encoding="utf-8") as f:
                             f.write(f"""
                             <html>
                             <head><title>Download Help</title></head>
                             <body style="font-family: sans-serif; padding: 20px;">
                                 <h2>IDM Clone - Download Help</h2>
                                 <p>We were unable to verify the file content (Cloudflare/Antibot detected).</p>
                                 <p>Please click the link below to download the file manually:</p>
                                 <p><a href="{self.item.url}" style="font-size: 1.2em; font-weight: bold;">{self.item.url}</a></p>
                                 <p><em>If the extension intercepts this again, please disable it temporarily for this site.</em></p>
                             </body>
                             </html>
                             """)
                         
                         import webbrowser
                         webbrowser.open(f"file://{os.path.abspath(help_path)}")
                     except Exception as e:
                         logger.error(f"Failed to create help file: {e}")
                         
                     raise Exception("Bypass failed. Please use the manual download helper opened in your browser.")

        except Exception as e:
            logger.warning(f"Error verifies/retry download content: {e}")
            if "Opened in browser" in str(e):
                raise e # Propagate manual intervention error


        self.item.downloaded_size = os.path.getsize(self.full_path)
        self.item.total_size = self.item.downloaded_size
        self.item.progress = 100

    def merge_files(self):
        with open(self.full_path, 'wb') as outfile:
            for i in range(self.num_chunks):
                part_file = f"{self.full_path}.part{i}"
                if os.path.exists(part_file):
                    with open(part_file, 'rb') as infile:
                        outfile.write(infile.read())
                    os.remove(part_file)

    def pause(self):
        self._paused = True
        self.item.status = DownloadStatus.PAUSED

    def stop(self):
        self._cancelled = True
        self.item.status = DownloadStatus.STOPPED

    def _ask_save_path(self, initial_filename):
        try:
            import tkinter as tk
            from tkinter import filedialog
            
            # Create hidden root
            root = tk.Tk()
            root.withdraw()
            root.attributes('-topmost', True) # Bring to front
            
            # Suggest initial dir (e.g. downloads)
            initial_dir = self.item.save_path if os.path.exists(self.item.save_path) else os.path.expanduser("~/Downloads")
            
            file_path = filedialog.asksaveasfilename(
                parent=root,
                initialdir=initial_dir,
                initialfile=initial_filename,
                title="Save Download As..."
            )
            
            root.destroy()
            return file_path
        except Exception as e:
            logger.error(f"Failed to open save dialog: {e}")
            # Fallback to default if dialog fails
            return os.path.join(self.item.save_path, initial_filename)
