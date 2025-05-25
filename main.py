# RunwayGuard – minimal FastAPI micro‑service that calculates real‑time runway wind components
# and density altitude, optionally generating a plain‑English advisory via OpenAI.
# Copyright by awade12(openturf.org)

from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi import Request
from dotenv import load_dotenv
import logging

load_dotenv()

# route initializations!
from routes.v1.brief import router as brief_router, APIError
from routes.v1.info import router as info_router
from functions.database import initialize_database, db_manager

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

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

app = FastAPI(title="runwayguard", version="0.3.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

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

app.include_router(brief_router, prefix="/v1")
app.include_router(info_router, prefix="/v1")
## uvicorn main:app --reload or uvicorn main:app --reload