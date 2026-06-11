from __future__ import annotations

from app.config import Settings
from app.downloaders.base import Downloader
from app.downloaders.direct import DirectMediaDownloader
from app.downloaders.douyin import DouyinDownloader
from app.downloaders.xiaohongshu import XiaohongshuDownloader
from app.downloaders.xiaoyuzhou import XiaoyuzhouDownloader
from app.downloaders.ytdlp import YtDlpDownloader
from app.errors import AppError


class DownloaderFactory:
    def __init__(self, settings: Settings):
        self.settings = settings

    def create(self, platform: str) -> Downloader:
        if platform == "direct_media":
            return DirectMediaDownloader(self.settings)
        if platform == "youtube":
            return YtDlpDownloader(self.settings, "youtube")
        if platform == "bilibili":
            return YtDlpDownloader(self.settings, "bilibili")
        if platform == "xiaoyuzhou":
            return XiaoyuzhouDownloader(self.settings)
        if platform == "douyin":
            return DouyinDownloader(self.settings)
        if platform == "xiaohongshu":
            return XiaohongshuDownloader(self.settings)
        raise AppError("unsupported_platform", "该平台第一版暂不支持。", "downloading")
