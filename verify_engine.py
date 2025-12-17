import asyncio
import time
from engine.manager import DownloadManager
from engine.models import DownloadStatus

async def main():
    manager = DownloadManager("downloads")
    
    # URL for a 5MB test file
    url = "http://speedtest.tele2.net/5MB.zip" 
    print(f"Adding download: {url}")
    
    dl_id = manager.add_download(url)
    
    print(f"Starting download {dl_id}...")
    await manager.start_download(dl_id)
    
    start_time = time.time()
    
    while True:
        item = manager.downloads[dl_id]
        
        # Calculate simple speed
        elapsed = time.time() - start_time
        if elapsed > 0:
            speed = item.downloaded_size / elapsed / 1024 / 1024 # MB/s
        else:
            speed = 0
            
        progress = (item.downloaded_size / item.total_size * 100) if item.total_size > 0 else 0
        
        print(f"Status: {item.status.value}, Progress: {progress:.2f}%, "
              f"Size: {item.downloaded_size}/{item.total_size}, Speed: {speed:.2f} MB/s", end='\r')
        
        if item.status in [DownloadStatus.COMPLETED, DownloadStatus.ERROR, DownloadStatus.STOPPED]:
            print(f"\nFinal Status: {item.status.value}")
            if item.error_message:
                print(f"Error: {item.error_message}")
            break
            
        await asyncio.sleep(0.5)

if __name__ == "__main__":
    asyncio.run(main())
