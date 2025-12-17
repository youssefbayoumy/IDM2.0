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
    level=logging.INFO, 
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

    async def get_file_info(self):
        logger.info(f"Getting info for {self.item.url}")
        headers = {"User-Agent": "IDM-Clone/1.0"}
        async with aiohttp.ClientSession(headers=headers) as session:
            try:
                async with session.head(self.item.url, allow_redirects=True, timeout=30) as response:
                    # Resolve redirects
                    self.item.url = str(response.url)
                    self.item.total_size = int(response.headers.get('Content-Length', 0))
                    
                    if response.status >= 400:
                        raise Exception(f"HTTP Error {response.status}: {response.reason}")

                    # Try to guess filename from header or url
                    if not self.item.filename:
                        content_disposition = response.headers.get('Content-Disposition')
                        if content_disposition and 'filename=' in content_disposition:
                            self.item.filename = content_disposition.split('filename=')[1].strip('"')
                        else:
                            self.item.filename = os.path.basename(self.item.url) or "downloaded_file"
                    
                    self.full_path = os.path.join(self.item.save_path, self.item.filename)
                    logger.info(f"Resolved filename: {self.item.filename}, Size: {self.item.total_size}")
                    
            except asyncio.TimeoutError:
                raise Exception("Connection timed out while getting file info")
            except Exception as e:
                logger.error(f"Error getting file info: {e}")
                self.item.status = DownloadStatus.ERROR
                self.item.error_message = str(e)
                raise e

    async def download_chunk(self, chunk_id, start_byte, end_byte):
        part_file = f"{self.full_path}.part{chunk_id}"
        current_size = 0
        
        # Resume logic
        if os.path.exists(part_file):
            current_size = os.path.getsize(part_file)
            if current_size >= (end_byte - start_byte + 1):
                 return
            
        headers = {
            'Range': f'bytes={start_byte + current_size}-{end_byte}',
            'User-Agent': 'IDM-Clone/1.0'
        }
        
        try:
            async with self.session.get(self.item.url, headers=headers, timeout=60) as response:
                if response.status >= 400:
                     raise Exception(f"HTTP {response.status} for chunk {chunk_id}")
                
                async with aiofiles.open(part_file, 'ab') as f:
                    async for data in response.content.iter_chunked(1024 * 64): # 64KB chunks
                        if self._paused or self._cancelled:
                            return
                        await f.write(data)
                        self.item.downloaded_size += len(data)
        except Exception as e:
            logger.error(f"Chunk {chunk_id} failed: {e}")
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
                self.full_path = os.path.join(self.item.save_path, self.item.filename)

            if self.item.total_size == 0 or not self.item.filename:
                await self.get_file_info()
            
            # Re-ensure in case get_file_info updated it
            if self.item.filename:
                self.full_path = os.path.join(self.item.save_path, self.item.filename)
            
            self.session = aiohttp.ClientSession(headers={"User-Agent": "IDM-Clone/1.0"})
            
            monitor_task = asyncio.create_task(self.monitor_speed())

            chunk_size = self.item.total_size // self.num_chunks
            tasks = []
            
            for i in range(self.num_chunks):
                start = i * chunk_size
                end = start + chunk_size - 1 if i < self.num_chunks - 1 else self.item.total_size - 1
                tasks.append(self.download_chunk(i, start, end))
                
            await asyncio.gather(*tasks)
            
            if not self._paused and not self._cancelled:
                 self.merge_files()
                 self.item.status = DownloadStatus.COMPLETED
                 logger.info(f"Download completed: {self.item.id}")

            monitor_task.cancel()
                 
        except Exception as e:
            error_msg = str(e).strip()
            if not error_msg:
                error_msg = repr(e)
            
            logger.error(f"Download failed {self.item.id}: {error_msg}")
            self.item.status = DownloadStatus.ERROR
            self.item.error_message = error_msg
        finally:
            if self.session:
                await self.session.close()

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
