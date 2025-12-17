from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

class DownloadStatus(Enum):
    QUEUED = "Queued"
    DOWNLOADING = "Downloading"
    PAUSED = "Paused"
    COMPLETED = "Completed"
    ERROR = "Error"
    STOPPED = "Stopped"

@dataclass
class DownloadItem:
    id: str
    url: str
    filename: str
    save_path: str
    status: DownloadStatus = DownloadStatus.QUEUED
    total_size: int = 0
    downloaded_size: int = 0
    speed: float = 0.0  # bytes per second
    progress: float = 0.0 # 0.0 to 100.0
    error_message: Optional[str] = None
