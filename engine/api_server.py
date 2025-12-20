
import asyncio
from aiohttp import web
import logging
import json

logger = logging.getLogger(__name__)

class APIServer:
    def __init__(self, download_manager, host='127.0.0.1', port=6800):
        self.download_manager = download_manager
        self.host = host
        self.port = port
        self.app = web.Application()
        self.app.router.add_post('/add', self.handle_add_download)
        self.app.router.add_get('/test', self.handle_test) # For basic connectivity check
        self.runner = None
        self.site = None

    async def handle_test(self, request):
        return web.json_response({"status": "ok", "message": "IDM Server is running"})

    async def handle_add_download(self, request):
        try:
            data = await request.json()
            url = data.get('url')
            filename = data.get('filename')
            headers = data.get('headers', {}) # User-Agent, Cookies, etc.
            
            if not url:
                return web.json_response({"error": "Missing URL"}, status=400)

            # In a real app, we'd pass headers to the specific download item
            # For now, we'll just add the url. 
            # TODO: Update DownloadManager to accept headers if needed
            
            download_id = self.download_manager.add_download(url, headers=headers)
            
            # If filename provided, update it immediately? 
            # DownloadManager usually resolves it, but we can hint it.
            if filename:
                if download_id in self.download_manager.downloads:
                    self.download_manager.downloads[download_id].filename = filename

            # Auto start
            await self.download_manager.start_download(download_id)

            logger.info(f"Received download via API: {url}")
            logger.debug(f"Received headers: {headers}")
            return web.json_response({"status": "added", "id": download_id})
        except Exception as e:
            logger.error(f"API Error: {e}")
            return web.json_response({"error": str(e)}, status=500)

    async def start(self):
        self.runner = web.AppRunner(self.app)
        await self.runner.setup()
        self.site = web.TCPSite(self.runner, self.host, self.port)
        await self.site.start()
        logger.info(f"API Server started on http://{self.host}:{self.port}")

    async def stop(self):
        if self.site:
            await self.site.stop()
        if self.runner:
            await self.runner.cleanup()
