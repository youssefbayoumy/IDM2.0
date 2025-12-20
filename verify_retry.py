
import asyncio
import os
import sys

# Add the project root to sys.path
sys.path.append(os.getcwd())

from engine.downloader import Downloader
from engine.models import DownloadItem, DownloadStatus

async def main():
    try:
        item = DownloadItem(id="test", url="http://google.com", filename="test.html", save_path=".")
        dl = Downloader(item)
        print("Instance created successfully")
        print(f"Max retries: {dl.MAX_RETRIES}")
        print("Verification script finished.")
    except Exception as e:
        print(f"Verification failed: {e}")
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(main())
