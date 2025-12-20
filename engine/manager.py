import asyncio
import uuid
import os
from typing import Dict, List
from engine.models import DownloadItem, DownloadStatus
from engine.downloader import Downloader

class DownloadManager:
    def __init__(self, download_dir: str):
        self.download_dir = download_dir
        self.downloads: Dict[str, DownloadItem] = {}
        self.downloaders: Dict[str, Downloader] = {}
        self.tasks: Dict[str, asyncio.Task] = {}
        
        # API Server
        from engine.api_server import APIServer
        self.api_server = APIServer(self)
        self.api_task = None

        if not os.path.exists(download_dir):
            os.makedirs(download_dir)
            
    async def start_server(self):
        if not self.api_task:
            await self.api_server.start()

    def add_download(self, url: str, headers: Dict[str, str] = None) -> str:
        download_id = str(uuid.uuid4())
        item = DownloadItem(
            id=download_id,
            url=url,
            filename="", # Will be determined later
            save_path=self.download_dir,
            headers=headers or {}
        )
        self.downloads[download_id] = item
        return download_id

    async def start_download(self, download_id: str):
        if download_id not in self.downloads:
            return

        item = self.downloads[download_id]
        
        # If already downloading, ignore
        if item.status == DownloadStatus.DOWNLOADING:
            return

        # Create downloader if not exists or create new one
        if "youtube.com" in item.url or "youtu.be" in item.url:
            from engine.youtube import YouTubeDownloader
            downloader = YouTubeDownloader(item)
        else:
            downloader = Downloader(item)
            
        self.downloaders[download_id] = downloader
        
        # Create task
        task = asyncio.create_task(downloader.start())
        task.add_done_callback(lambda t: self._on_download_complete(download_id, t))
        self.tasks[download_id] = task
        
    def _on_download_complete(self, download_id: str, task: asyncio.Task):
        if download_id not in self.downloads:
            return
            
        item = self.downloads[download_id]
        
        # Check if we need to retry
        if item.status == DownloadStatus.ERROR:
            # Only retry if it was a timeout OR we made some progress (interrupted download)
            # This prevents infinite loops on 404s or 403s where we haven't started.
            error_msg = (item.error_message or "").lower()
            is_timeout = "time" in error_msg # Covers "timeout", "timed out"
            has_progress = item.downloaded_size > 0
            
            if (is_timeout or has_progress) and item.retry_count < item.max_retries:
                item.retry_count += 1
                item.status = DownloadStatus.RETRYING
                # Schedule retry
                asyncio.create_task(self._retry_download(download_id))
    
    async def _retry_download(self, download_id: str):
        await asyncio.sleep(3) # Wait 3 seconds
        await self.start_download(download_id)
        
        # We don't await here, we let it run in background
        # But we need to handle completion/exceptions potentially.
        # For MVP, the TUI will poll the status.

    def pause_download(self, download_id: str):
        if download_id in self.downloaders:
            self.downloaders[download_id].pause()

    def stop_download(self, download_id: str):
        if download_id in self.downloaders:
            self.downloaders[download_id].stop()
        if download_id in self.tasks:
             self.tasks[download_id].cancel()

    def get_downloads(self) -> List[DownloadItem]:
        return list(self.downloads.values())
