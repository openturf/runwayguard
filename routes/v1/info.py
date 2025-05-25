"""
API Information and Help Endpoints

This route provides general information about the RunwayGuard API 
and comprehensive help documentation for using the runway analysis endpoints.
- @awade12(openturf.org)
"""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from datetime import datetime
from slowapi import Limiter
from slowapi.util import get_remote_address

router = APIRouter()

limiter = Limiter(key_func=get_remote_address)

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

@router.get("/help")
@limiter.limit("60/minute")
async def brief_help(request: Request):
    return JSONResponse({
        "service": "RunwayGuard Advanced Runway Risk Intelligence (ARRI)",
        "version": "2.0.0",
        "description": "Professional aviation risk assessment system with advanced weather analysis, performance modeling, and multi-factor risk correlation",
        
        "quick_start": {
            "single_airport": {
                "method": "POST",
                "endpoint": "/v1/brief",
                "example": {
                    "icao": "KGGG"
                },
                "description": "Get comprehensive runway risk analysis for any airport"
            },
            "route_analysis": {
                "method": "POST",
                "endpoint": "/v1/route",
                "example": {
                    "airports": ["KGGG", "KDFW", "KHOU"],
                    "aircraft_type": "c172",
                    "route_distances": [180, 240]
                },
                "description": "Multi-airport route analysis with weather trends and strategic planning"
            }
        },
        
        "request_parameters": {
            "single_airport": {
                "required": {
                    "icao": {
                        "type": "string",
                        "description": "4-letter ICAO airport code (e.g., KDFW, KGGG, KCNW)",
                        "examples": ["KDFW", "KGGG", "KCNW", "KLAX", "KJFK"],
                        "validation": "3-4 alphanumeric characters"
                    }
                }
            },
            "route_analysis": {
                "required": {
                    "airports": {
                        "type": "array",
                        "description": "List of ICAO codes in route order [departure, waypoints..., destination]",
                        "examples": [["KGGG", "KDFW"], ["KCNW", "KGGG", "KDFW", "KHOU"]],
                        "validation": "2-10 valid ICAO codes"
                    }
                },
                "optional": {
                    "route_distances": {
                        "type": "array",
                        "description": "Distances between airports in nautical miles",
                        "example": [180, 120, 240],
                        "validation": "One less entry than airports, all positive numbers"
                    }
                }
            },
            "shared_optional": {
                "aircraft_type": {
                    "type": "string", 
                    "default": "light",
                    "description": "Aircraft category for performance analysis",
                    "options": {
                        "c172": "Cessna 172 (Light Single)",
                        "pa34": "Piper Seneca (Light Twin)", 
                        "tbm": "TBM Series (High-Performance Turboprop)",
                        "citation": "Citation Jets (Light Jet)",
                        "light": "Generic Light Aircraft",
                        "heavy": "Heavy Aircraft"
                    },
                    "example": "c172"
                },
                "pilot_experience": {
                    "type": "string",
                    "default": "standard", 
                    "description": "Pilot experience level affects risk thresholds",
                    "options": {
                        "student": "Student Pilot (Conservative 0.8x thresholds)",
                        "private": "Private Pilot (Conservative 0.8x thresholds)", 
                        "instrument": "Instrument Rated (Standard 1.0x thresholds)",
                        "commercial": "Commercial Pilot (Standard 1.0x thresholds)",
                        "atp": "ATP/Professional (Aggressive 1.2x thresholds)"
                    },
                    "example": "commercial"
                }
            }
        },
        
        "example_requests": {
            "basic": {
                "description": "Simple airport analysis",
                "request": {"icao": "KDFW"},
                "curl": "curl -X POST /v1/brief -H 'Content-Type: application/json' -d '{\"icao\": \"KDFW\"}'"
            },
            "student_pilot": {
                "description": "Conservative risk assessment for training",
                "request": {"icao": "KGGG", "aircraft_type": "c172", "pilot_experience": "student"},
                "curl": "curl -X POST /v1/brief -H 'Content-Type: application/json' -d '{\"icao\": \"KGGG\", \"aircraft_type\": \"c172\", \"pilot_experience\": \"student\"}'"
            },
            "professional": {
                "description": "High-performance aircraft analysis",
                "request": {"icao": "KCNW", "aircraft_type": "tbm", "pilot_experience": "commercial"},
                "curl": "curl -X POST /v1/brief -H 'Content-Type: application/json' -d '{\"icao\": \"KCNW\", \"aircraft_type\": \"tbm\", \"pilot_experience\": \"commercial\"}'"
            },
            "simple_route": {
                "description": "Basic two-airport route analysis",
                "request": {"airports": ["KGGG", "KDFW"]},
                "curl": "curl -X POST /v1/route -H 'Content-Type: application/json' -d '{\"airports\": [\"KGGG\", \"KDFW\"]}'"
            },
            "complex_route": {
                "description": "Multi-stop route with distances and aircraft type",
                "request": {"airports": ["KCNW", "KGGG", "KDFW", "KHOU"], "aircraft_type": "tbm", "route_distances": [180, 120, 240]},
                "curl": "curl -X POST /v1/route -H 'Content-Type: application/json' -d '{\"airports\": [\"KCNW\", \"KGGG\", \"KDFW\", \"KHOU\"], \"aircraft_type\": \"tbm\", \"route_distances\": [180, 120, 240]}'"
            }
        },
        
        "response_features": {
            "single_airport": {
                "runway_risk_index": "0-100 point risk score with category (LOW/MODERATE/HIGH/EXTREME)",
                "status": "GO/CAUTION/NO-GO operational recommendation", 
                "advanced_analysis": {
                    "thermal_conditions": "Temperature gradient and convective risk analysis",
                    "atmospheric_stability": "Stability index and turbulence prediction",
                    "runway_performance": "Aircraft-specific performance assessment", 
                    "precipitation_analysis": "Enhanced weather impact evaluation",
                    "turbulence_analysis": "Wind shear and mechanical turbulence risk",
                    "risk_amplification": "Multi-factor risk correlation detection"
                },
                "diagnostic_info": {
                    "conditions_assessment": "Overall condition severity (mild/challenging)",
                    "primary_risk_factors": "Top contributing risk factors with scores",
                    "data_availability": "Status of available data sources",
                    "recommendations": "Specific operational guidance and data verification needs"
                },
                "aircraft_configuration": "Applied risk profile and threshold adjustments",
                "weather_data": "Current METAR, TAF, NOTAMs, PIREPs, SIGMETs, and more"
            },
            "route_analysis": {
                "route_summary": "Overview of entire route with departure, destination, and stops",
                "waypoints": "Detailed analysis for each airport including best runway selection",
                "route_assessment": "Overall route status (GO/CAUTION/NO-GO) and risk distribution",
                "weather_trends": "Pressure, temperature, and wind patterns across the route",
                "hazards": "Identified weather hazards with affected airports and recommendations",
                "alternates": "Recommended alternate airports for problematic destinations",
                "fuel_considerations": "Fuel planning adjustments based on weather and performance",
                "strategic_recommendations": "High-level planning guidance and go/no-go decisions"
            }
        },
        
        "risk_assessment_capabilities": {
            "basic_factors": [
                "Wind components (headwind/crosswind/tailwind)",
                "Gust effects and differential analysis", 
                "Density altitude performance impact",
                "Time-of-day solar angle effects"
            ],
            "advanced_factors": [
                "Thermal gradient and convective activity", 
                "Atmospheric stability indexing",
                "Runway contamination and performance degradation",
                "Precipitation intensity and type analysis",
                "Turbulence prediction with terrain effects",
                "Multi-domain risk amplification",
                "Icing condition assessment",
                "Temperature performance modeling",
                "Wind shear risk evaluation",
                "NOTAM-based operational risks"
            ]
        },
        
        "operational_guidance": {
            "risk_categories": {
                "LOW (0-25)": "Excellent conditions - ideal for training",
                "MODERATE (26-50)": "Manageable conditions - standard operations", 
                "HIGH (51-75)": "Challenging conditions - exercise caution",
                "EXTREME (76-100)": "Dangerous conditions - consider alternatives"
            },
            "status_meanings": {
                "GO": "Conditions are suitable for planned operations",
                "CAUTION": "Proceed with heightened awareness and preparation", 
                "NO-GO": "Conditions exceed safe operational limits"
            }
        },
        
        "data_sources": [
            "FAA METAR (current weather observations)",
            "TAF (terminal area forecasts)", 
            "NOTAMs (notices to airmen)",
            "PIREPs (pilot reports)",
            "SIGMETs/AIRMETs (significant meteorology)",
            "Airport facility information",
            "Winds/temperature aloft forecasts"
        ],
        
        "route_analysis_capabilities": {
            "multi_airport_assessment": "Analyze up to 10 airports in a single route",
            "weather_trend_analysis": "Track pressure, temperature, and wind patterns across route",
            "hazard_identification": "Identify thunderstorms, icing, low visibility, and high winds",
            "strategic_planning": "Route-wide go/no-go recommendations with rationale",
            "fuel_planning": "Weather-adjusted fuel requirements and considerations",
            "alternate_recommendations": "Suggest alternates for airports with poor conditions",
            "performance_correlation": "Account for density altitude and aircraft performance across route"
        },
        
        "use_cases": {
            "cross_country_flights": "Analyze entire route for VFR or IFR cross-country planning",
            "training_flights": "Student pilot route analysis with conservative risk assessment",
            "commercial_operations": "Professional route planning with performance optimization",
            "alternate_selection": "Compare multiple destination options for weather conditions",
            "fuel_planning": "Weather-based fuel requirement calculations",
            "dispatch_operations": "Fleet management and route optimization decisions"
        },
        
        "support": {
            "documentation": "https://github.com/awade12/runwayguard",
            "api_version": "v1",
            "rate_limits": {
                "single_airport": "20 requests per minute per IP",
                "route_analysis": "10 requests per minute per IP"
            },
            "contact": "See GitHub repository for issues and contributions"
        }
    })