"""FastAPI application entry point."""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import settings
from app.database import init_db
from app.api import jobs, videos, downloads

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup / shutdown lifecycle."""
    logger.info("Starting up YouTube Transcript API...")
    await init_db()
    logger.info("Database initialized (SQLite).")
    yield
    logger.info("Shutting down...")


app = FastAPI(
    title="YouTube Transcript API",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        settings.FRONTEND_ORIGIN,
        "http://localhost:3000",
        "http://localhost:5173",
        "http://127.0.0.1:5500",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


app.include_router(jobs.router)
app.include_router(videos.router)
app.include_router(downloads.router)


@app.get("/")
async def root():
    """Health-check endpoint."""
    return {"status": "ok", "version": "1.0.0", "service": "YouTube Transcript API"}


@app.get("/debug/sources")
async def debug_sources():
    """Diagnostic: test each API source for a known video."""
    from app.services.invidious_service import InvidiousService
    svc = InvidiousService()
    results = {}

    # Piped
    try:
        info = await svc._piped_video_info("jNQXAC9IVRw")
        results["piped_video"] = "OK" if info else "empty"
    except Exception as e:
        results["piped_video"] = str(e)[:200]

    # Invidious
    try:
        data = await svc._call_invidious("/api/v1/videos/jNQXAC9IVRw")
        results["invidious_video"] = "OK" if data else "empty"
    except Exception as e:
        results["invidious_video"] = str(e)[:200]

    # yt-dlp
    try:
        import asyncio
        from app.services.youtube_extractor import YouTubeExtractor
        yt = YouTubeExtractor()
        info = await asyncio.to_thread(yt.extract_video_detail, "https://www.youtube.com/watch?v=jNQXAC9IVRw")
        results["ytdlp"] = "OK" if info else "empty"
    except Exception as e:
        results["ytdlp"] = str(e)[:200]

    return results


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Catch-all for unhandled exceptions."""
    logger.error(f"Unhandled error: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"error": "INTERNAL_ERROR", "message": "服务器内部错误，请稍后重试。"},
    )
