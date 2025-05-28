from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse
from dotenv import load_dotenv
import logging
import os
from starlette.exceptions import HTTPException as StarletteHTTPException

# Load environment variables
load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

import sentry_sdk
from sentry_sdk.integrations.asgi import SentryAsgiMiddleware

sentry_sdk.init(
    dsn=os.getenv("SENTRY_DSN"),
    send_default_pii=True,
    profile_lifecycle="trace",
    profile_session_sample_rate=1.0,
    traces_sample_rate=1.0,  # adjust sampling if needed
)

# App imports
from routes.v1.brief import router as brief_router, APIError
from routes.v1.printbrief import router as printbrief_router
from routes.v1.info import router as info_router
# from routes.v1.private.sms import router as sms_router -- soon
from functions.infrastructure.database import initialize_database, db_manager

# Lifespan for startup/shutdown events
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Initializing database connection...")
    try:
        db_initialized = await initialize_database()
        if db_initialized:
            logger.info("Database initialized successfully")
        else:
            logger.warning("Database initialization skipped - DATABASE_URL not configured or invalid")
            logger.warning("API will work without database functionality. Set DATABASE_URL to enable response storage and analytics.")
    except Exception as e:
        logger.error(f"Failed to initialize database: {str(e)}")
        logger.warning("API will continue without database functionality")
    
    yield
    
    logger.info("Closing database connection...")
    try:
        await db_manager.close()
        logger.info("Database connection closed successfully")
    except Exception as e:
        logger.error(f"Error closing database connection: {str(e)}")

# FastAPI app
app = FastAPI(title="runwayguard", version="0.3.0", lifespan=lifespan)

# Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(SentryAsgiMiddleware)

# Custom exception handlers
@app.exception_handler(APIError)
async def api_error_handler(request: Request, exc: APIError):
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": exc.message,
            "details": exc.details,
            "status_code": exc.status_code
        }
    )

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    event_id = sentry_sdk.capture_exception(exc)
    logger.exception(f"Unhandled exception: {exc}")
    return JSONResponse(
        status_code=500,
        content={
            "error": "Internal server error",
            "sentry_event_id": str(event_id)
        }
    )


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    logger.warning(f"HTTP exception: {exc.detail}")
    return PlainTextResponse(str(exc.detail), status_code=exc.status_code)

@app.get("/health")
async def health_check():
    return {"status": "ok"}

# Routes
app.include_router(brief_router, prefix="/v1")
app.include_router(printbrief_router, prefix="/v1")
app.include_router(info_router, prefix="/v1")
# app.include_router(sms_router, prefix="/v1") -- soon
