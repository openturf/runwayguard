# RunwayGuard – minimal FastAPI micro‑service that calculates real‑time runway wind components
# and density altitude, optionally generating a plain‑English advisory via OpenAI.

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi import Request
from dotenv import load_dotenv
load_dotenv()

# route initializations!
from routes.v1.brief import router as brief_router, APIError
from routes.v1.info import router as info_router

app = FastAPI(title="runwayguard", version="0.3.0")

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