from __future__ import annotations

import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.api import router as api_router
from app.asr import create_transcriber
from app.capabilities import build_capabilities
from app.config import Settings, load_settings
from app.creator import CreatorPreviewCache
from app.jobs.cleanup import cleanup_old_temp_dirs
from app.jobs.processor import JobProcessor
from app.jobs.queue import TaskQueue
from app.llm import LLMProcessor
from app.metrics import ResourceSampler
from app.storage import SQLiteStore
from app.terminology import TerminologyStore
from app.web import router as web_router


def create_app(settings: Settings | None = None) -> FastAPI:
    loaded_settings = settings or load_settings()
    loaded_settings.ensure_directories()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        store = SQLiteStore(loaded_settings.db_path)
        store.recover_interrupted_jobs()
        cleanup_old_temp_dirs(loaded_settings.temp_dir, loaded_settings.app_temp_retention_hours)
        terms = TerminologyStore(loaded_settings.terms_path)
        transcriber = create_transcriber(loaded_settings)
        llm = LLMProcessor(loaded_settings, terms)
        processor = JobProcessor(
            settings=loaded_settings,
            store=store,
            transcriber=transcriber,
            llm=llm,
        )
        task_queue = TaskQueue(loaded_settings, processor)
        resource_sampler = ResourceSampler(loaded_settings, task_queue)
        creator_previews = CreatorPreviewCache(loaded_settings.creator_preview_ttl_seconds)
        app.state.settings = loaded_settings
        app.state.store = store
        app.state.terms = terms
        app.state.queue = task_queue
        app.state.resource_sampler = resource_sampler
        app.state.creator_previews = creator_previews
        app.state.started_monotonic = time.monotonic()
        app.state.capabilities = lambda: build_capabilities(loaded_settings)
        task_queue.start()
        resource_sampler.start()
        try:
            yield
        finally:
            resource_sampler.stop()
            task_queue.stop()

    app = FastAPI(title="yc-media-transcriber", version="0.1.0", lifespan=lifespan)
    frontend_dist = Path(__file__).resolve().parents[1] / "frontend" / "dist"
    if frontend_dist.exists():
        app.mount("/static", StaticFiles(directory=frontend_dist), name="frontend-static")
    app.include_router(api_router)
    app.include_router(web_router)

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok"}

    return app


app = create_app()
