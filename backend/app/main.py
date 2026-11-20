import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.router import router as v1_router
from app.core.config import Settings, get_settings
from app.core.exceptions import register_exception_handlers
from app.core.logging_config import configure_logging
from app.database.mongodb import create_mongo_client
from app.services.chroma import initialize_chroma
from app.services.nexconn import NexconnClient


def create_nexconn_client(settings: Settings) -> NexconnClient:
    return NexconnClient(settings)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    configure_logging()
    settings = get_settings()
    logger = logging.getLogger("ai_teamspace")
    client = create_mongo_client(settings)
    nexconn_client = (
        create_nexconn_client(settings) if settings.nexconn_enabled else None
    )

    app.state.settings = settings
    app.state.logger = logger
    app.state.mongo_client = client
    app.state.nexconn_client = nexconn_client
    app.state.message_processor = None
    app.state.orchestration_semaphore = asyncio.Semaphore(
        settings.max_parallel_agents
    )
    app.state.revoked_token_indexes_ready = False
    app.state.revoked_token_indexes_lock = asyncio.Lock()
    app.state.chroma_ready = False
    if settings.chroma_enabled:
        if not (settings.gemini_api_key or settings.google_api_key).strip():
            logger.warning(
                "ChromaDB is enabled but Gemini embedding credentials are missing"
            )
        try:
            collection_name = await asyncio.to_thread(
                initialize_chroma, settings
            )
        except Exception as exc:
            logger.warning(
                "ChromaDB initialization failed",
                extra={"error_type": type(exc).__name__},
            )
        else:
            app.state.chroma_ready = True
            logger.info(
                "ChromaDB initialized",
                extra={"collection": collection_name},
            )
    if settings.nexconn_enabled:
        logger.info("Nexconn integration initialized")
    logger.info("AI TeamSpace API started")

    try:
        yield
    finally:
        if nexconn_client is not None:
            await nexconn_client.aclose()
        await client.close()
        logger.info("AI TeamSpace API stopped")


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="AI TeamSpace API",
        description="Backend API for the AI TeamSpace collaborative workspace.",
        version="0.1.0",
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.frontend_url],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(v1_router, prefix="/api/v1")
    register_exception_handlers(app)
    return app


app = create_app()
