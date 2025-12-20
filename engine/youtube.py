import asyncio
import yt_dlp
import os
import logging
from engine.models import DownloadItem, DownloadStatus

logger = logging.getLogger(__name__)

class YouTubeDownloader:
    def __init__(self, item: DownloadItem):
        self.item = item
        self._cancelled = False
        self._paused = False # yt-dlp doesn't support pause easily in this way, but we'll track it.

    async def start(self):
        self.item.status = DownloadStatus.DOWNLOADING
        logger.info(f"Starting YouTube download: {self.item.url}")
        
        # We need to run yt-dlp in a thread because it's blocking
        loop = asyncio.get_event_loop()
        try:
            await loop.run_in_executor(None, self._download)
            if not self._cancelled and self.item.status != DownloadStatus.ERROR:
                 self.item.status = DownloadStatus.COMPLETED
                 self.item.progress = 100.0
                 logger.info(f"YouTube download completed: {self.item.filename}")
        except Exception as e:
            logger.error(f"YouTube download failed: {e}")
            self.item.status = DownloadStatus.ERROR
            self.item.error_message = str(e)

    def _progress_hook(self, d):
        if self._cancelled:
            raise Exception("Download Cancelled")

        if d['status'] == 'downloading':
            try:
                # Update item stats
                total = d.get('total_bytes') or d.get('total_bytes_estimate') or 0
                downloaded = d.get('downloaded_bytes', 0)
                
                self.item.total_size = total
                self.item.downloaded_size = downloaded
                
                if total > 0:
                    self.item.progress = (downloaded / total) * 100
                
                # Speed is sometimes provided
                speed = d.get('speed')
                if speed:
                    self.item.speed = speed
                
                # Filename might be available now
                if not self.item.filename and d.get('filename'):
                     self.item.filename = os.path.basename(d['filename'])

            except Exception as e:
                logger.error(f"Error in progress hook: {e}")

        elif d['status'] == 'finished':
            self.item.progress = 100.0
            if not self.item.filename and d.get('filename'):
                 self.item.filename = os.path.basename(d['filename'])

    def _download(self):
        ydl_opts = {
            'format': 'best',
            'outtmpl': os.path.join(self.item.save_path, '%(title)s.%(ext)s'),
            'progress_hooks': [self._progress_hook],
            'quiet': True,
            'nocheckcertificate': True,
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            # First extract info to set title if possible (though outtmpl handles file naming)
            # functionality is wrapped in download
            ydl.download([self.item.url])

    def pause(self):
        # yt-dlp doesn't support pausing effectively when running like this.
        # We can simulate it by cancelling (raising exception in hook) and later restarting?
        # For now, we will just mark as PAUSED but it won't actually stop the thread immediately 
        # unless we raise in the hook.
        # Let's try to raise in hook if paused?
        # But resuming would mean restarting from scratch or supported resume?
        # yt-dlp supports resume if file exists.
        # So we can "stop" it and restart later.
        self._cancelled = True # Treat pause as stop for this simple implementation?
        # Or just ignore pause for MVP.
        pass

    def stop(self):
        self._cancelled = True
