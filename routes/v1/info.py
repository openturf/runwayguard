"""
This route is used to get information about the API.
- @awade12 may 20th 2025
"""

from fastapi import APIRouter
from datetime import datetime

router = APIRouter()

@router.get("/info")
async def get_info():
    return {
        "name": "RunwayGuard",
        "version": "0.3.0",
        "description": "Real-time runway risk assessment powered by advanced meteorological analysis and machine learning",
        "status": "operational",
        "timestamp": datetime.utcnow().isoformat(),
        "features": {
            "risk_assessment": {
                "runway_risk_index": "0-100 score based on multiple factors",
                "density_altitude": "Precise computation with temperature and pressure",
                "wind_analysis": "Advanced headwind/crosswind calculations",
                "time_factors": "Solar position and visibility considerations"
            },
            "weather_integration": {
                "metar": "Current conditions",
                "taf": "Forecasts",
                "pireps": "Pilot reports",
                "sigmets": "Significant meteorological conditions",
                "gairmets": "General aviation advisories"
            },
            "risk_categories": ["LOW", "MODERATE", "HIGH", "EXTREME"],
            "ai_features": "Plain-English advisories powered by GPT-3.5"
        },
        "documentation": "https://github.com/awade12/runwayguard"
    }