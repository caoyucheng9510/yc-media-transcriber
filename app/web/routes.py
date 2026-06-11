from __future__ import annotations

from html import escape
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse, HTMLResponse


router = APIRouter()

FRONTEND_DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"
FRONTEND_INDEX = FRONTEND_DIST / "index.html"


@router.get("/", response_class=HTMLResponse)
def home():
    return _spa_entry("YC 音视频转录")


@router.get("/settings", response_class=HTMLResponse)
def settings():
    return _spa_entry("设置")


@router.get("/metrics", response_class=HTMLResponse)
def metrics():
    return _spa_entry("监控")


def _spa_entry(title: str) -> FileResponse | HTMLResponse:
    if FRONTEND_INDEX.exists():
        return FileResponse(FRONTEND_INDEX, media_type="text/html")

    return HTMLResponse(
        f"""
        <!doctype html>
        <html lang="zh-CN">
          <head>
            <meta charset="utf-8">
            <meta name="viewport" content="width=device-width, initial-scale=1">
            <title>{escape(title)}</title>
            <style>
              body {{
                margin: 0;
                min-height: 100vh;
                display: grid;
                place-items: center;
                background: #f7f4ee;
                color: #1f1d18;
                font-family: -apple-system, BlinkMacSystemFont, "PingFang SC", sans-serif;
              }}
              main {{
                max-width: 520px;
                border: 1px solid #ded8cc;
                border-radius: 8px;
                background: #fffdf8;
                padding: 24px;
              }}
              code {{
                font-family: SFMono-Regular, ui-monospace, monospace;
              }}
            </style>
          </head>
          <body>
            <main id="root">
              <h1>YC 音视频转录</h1>
              <p>前端资源尚未构建。请在仓库根目录运行 <code>npm --prefix frontend run build</code>。</p>
            </main>
          </body>
        </html>
        """
    )
