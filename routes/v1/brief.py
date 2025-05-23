"""
Main API Endpoint for Runway Risk Analysis

This is the heart of RunwayGuard - the /brief endpoint that takes an airport code
and gives you a comprehensive runway risk assessment. It pulls weather data,
calculates wind components, figures out density altitude effects, and runs
everything through the advanced risk analysis engine.

The endpoint handles different aircraft types and pilot experience levels to
adjust risk thresholds appropriately. It also generates plain English summaries
when OpenAI is configured, and provides detailed diagnostic information for
understanding why certain risk scores were assigned.

Rate limited to 20 requests per minute to keep things reasonable.
"""

import os
import math
import time
import re
import httpx
import asyncio
import logging
from datetime import datetime
from typing import Optional, Dict, Any
from pydantic import BaseModel, validator
from fastapi import Request, status, HTTPException
from fastapi.responses import JSONResponse

from fastapi import APIRouter
from slowapi import Limiter
from slowapi.util import get_remote_address
from functions.time_factors import calculate_time_risk_factor
from functions.core_calculations import pressure_alt, density_alt, wind_components, gust_components, calculate_rri, calculate_advanced_rri, get_rri_category, get_status_from_rri
from functions.probabilistic_rri import calculate_probabilistic_rri_monte_carlo
from functions.weather_fetcher import fetch_metar, fetch_taf, fetch_notams, fetch_stationinfo, fetch_gairmet, fetch_sigmet, fetch_isigmet, fetch_pirep, fetch_cwa, fetch_windtemp, fetch_areafcst, fetch_fcstdisc, fetch_mis
from functions.getairportinfo import fetch_airport_info
from dotenv import load_dotenv
from functions.advanced_config import ConfigurationManager

load_dotenv()

logger = logging.getLogger(__name__)

router = APIRouter()

limiter = Limiter(key_func=get_remote_address)


class APIError(Exception):
    def __init__(self, message: str, status_code: int = 500, details: Optional[Dict[str, Any]] = None):
        self.message = message
        self.status_code = status_code
        self.details = details or {}
        super().__init__(self.message)

class BriefRequest(BaseModel):
    icao: str
    aircraft_type: Optional[str] = "light"
    pilot_experience: Optional[str] = "standard"
    
    @validator('icao')
    def validate_icao(cls, v):
        v = v.upper()
        if not re.match(r'^[A-Z0-9]{3,4}$', v):
            raise ValueError('ICAO code must be 3-4 alphanumeric characters')
        return v
    

@router.post("/brief")
@limiter.limit("20/minute")
async def brief(request: Request, req: BriefRequest):
    icao = req.icao.upper()
    logger.info(f"Processing brief request for ICAO: {icao}, Aircraft: {req.aircraft_type}, Experience: {req.pilot_experience}")
    
    config = ConfigurationManager.get_config_for_aircraft(req.aircraft_type, req.pilot_experience)
    
    try:
        airport = await fetch_airport_info(icao)
        if not airport or not airport.get("elevation"):
            logger.warning(f"Airport data not found or incomplete for ICAO: {icao}")
            raise APIError(
                message="Airport not found or data incomplete",
                status_code=status.HTTP_404_NOT_FOUND,
                details={
                    "icao": icao, 
                    "airport_data": airport,
                    "help": "For API usage guidance, visit /v1/brief/help",
                    "suggestions": [
                        "Verify ICAO code is correct (e.g., KDFW, KGGG, KCNW)",
                        "Use 4-letter ICAO codes, not 3-letter IATA codes",
                        "Check if airport has published weather data"
                    ]
                }
            )
        
        logger.debug(f"Airport info retrieved for {icao}: {airport}")
        
        try:
            metar = await fetch_metar(icao)
            if not metar or not metar.get("raw"):
                logger.warning(f"No METAR data available for ICAO: {icao}")
                raise APIError(
                    message="No current weather data available",
                    status_code=status.HTTP_404_NOT_FOUND,
                    details={
                        "icao": icao, 
                        "metar_data": metar,
                        "help": "For API usage guidance, visit /v1/brief/help",
                        "suggestions": [
                            "Airport may not report weather conditions",
                            "Try a nearby airport with weather reporting",
                            "Verify airport is active and operational"
                        ]
                    }
                )
        except Exception as e:
            logger.error(f"Error fetching METAR for {icao}: {str(e)}")
            raise APIError(
                message="Failed to fetch current weather data",
                status_code=status.HTTP_502_BAD_GATEWAY,
                details={"icao": icao, "error": str(e)}
            )
            
        try:
            taf = await fetch_taf(icao)
            stationinfo = await fetch_stationinfo(icao)
            notams = await fetch_notams(icao)
            gairmet = await fetch_gairmet(icao)
            sigmet = await fetch_sigmet(icao)
            isigmet = await fetch_isigmet(icao)
            pirep = await fetch_pirep(icao)
            cwa = await fetch_cwa(icao)
            windtemp = await fetch_windtemp()
            areafcst = await fetch_areafcst()
            fcstdisc = await fetch_fcstdisc()
            mis = await fetch_mis()
        except Exception as e:
            logger.error(f"Error fetching supplementary data for {icao}: {str(e)}")
            
        field_elev = airport.get("elevation")
        runways = airport.get("runways", [])
        mag_dec = airport.get("mag_dec")
        wind_dir = metar.get("wind_dir", 0)
        wind_speed = metar.get("wind_speed", 0)
        wind_gust = metar.get("wind_gust", 0)
        altim_in_hg = metar.get("altim_in_hg", 29.92)
        temp_c = metar.get("temp_c", 15)
        closed_runways = notams.get("closed_runways", [])
        
        if not runways:
            logger.warning(f"No runway data available for ICAO: {icao}")
            raise APIError(
                message="No runway data available",
                status_code=status.HTTP_404_NOT_FOUND,
                details={"icao": icao}
            )
            
        runway_results = []
        for rwy in runways:
            rwy_id = rwy.get("id")
            rwy_heading = rwy.get("heading")
            
            if rwy_id is None or rwy_heading is None:
                logger.warning(f"Invalid runway data for {icao}: {rwy}")
                continue
                
            is_closed = any(rwy_id.startswith(crwy) or rwy_id.endswith(crwy) for crwy in closed_runways)
            if is_closed:
                runway_results.append({
                    "runway": rwy_id,
                    "heading": rwy_heading,
                    "headwind_kt": 0,
                    "crosswind_kt": 0,
                    "gust_headwind_kt": 0,
                    "gust_crosswind_kt": 0,
                    "tailwind": False,
                    "gust_tailwind": False,
                    "density_altitude_ft": density_alt(field_elev, temp_c, altim_in_hg),
                    "runway_risk_index": 100,
                    "risk_category": "EXTREME",
                    "status": "NO-GO",
                    "warnings": [f"Runway {rwy_id} CLOSED per NOTAM"],
                    "plain_summary": None
                })
                continue
                
            lat = stationinfo.get("latitude")
            lon = stationinfo.get("longitude")
            
            try:
                da = density_alt(field_elev, temp_c, altim_in_hg)
                da_diff = da - field_elev
                head, cross, is_head = wind_components(rwy_heading, wind_dir, wind_speed)
                
                gust_head, gust_cross, gust_is_head = (0, 0, True)
                if wind_gust > 0:
                    gust_head, gust_cross, gust_is_head = gust_components(rwy_heading, wind_dir, wind_gust)
                
                runway_length = rwy.get("length")
                
                terrain_factor = 1.0
                if field_elev > 5000:
                    terrain_factor = 1.2
                elif field_elev > 3000:
                    terrain_factor = 1.1
                
                rri, rri_contributors = calculate_advanced_rri(
                    head=head, 
                    cross=cross, 
                    gust_head=gust_head, 
                    gust_cross=gust_cross, 
                    wind_speed=wind_speed, 
                    wind_gust=wind_gust,
                    is_head=is_head, 
                    gust_is_head=gust_is_head, 
                    da_diff=da_diff, 
                    metar_data=metar, 
                    lat=lat, 
                    lon=lon, 
                    rwy_heading=rwy_heading, 
                    notam_data=notams,
                    runway_length=runway_length,
                    airport_elevation=field_elev,
                    terrain_factor=terrain_factor,
                    historical_trend=None,
                    aircraft_category=req.aircraft_type
                )
                
                time_factors = calculate_time_risk_factor(datetime.utcnow(), lat, lon, rwy_heading) if lat and lon else None
                
                probabilistic_rri_results = {"rri_p05": None, "rri_p95": None}
                if lat is not None and lon is not None:
                    probabilistic_rri_results = calculate_probabilistic_rri_monte_carlo(
                        rwy_heading=rwy_heading,
                        original_wind_dir=wind_dir,
                        original_wind_speed=wind_speed,
                        original_wind_gust=wind_gust,
                        da_diff=da_diff,
                        metar_data=metar,
                        lat=lat,
                        lon=lon
                    )
            except Exception as e:
                logger.error(f"Error calculating runway data for {icao} runway {rwy_id}: {str(e)}")
                continue

            warnings = []
            if time_factors:
                warnings.extend(time_factors["risk_reasons"])
            
            advanced_warning_contributors = [
                "icing_conditions", "temperature_performance", "wind_shear_risk", 
                "enhanced_weather", "notam_risks", "thermal_gradient", 
                "atmospheric_stability", "runway_performance", "precipitation_intensity",
                "turbulence_risk", "trend_analysis", "risk_amplification"
            ]
            
            for contributor in advanced_warning_contributors:
                if contributor in rri_contributors and isinstance(rri_contributors[contributor]["value"], list):
                    warnings.extend(rri_contributors[contributor]["value"])
            
            weather = metar.get("weather", [])
            ceiling = metar.get("ceiling")
            visibility = metar.get("visibility")

            if any("TS" in weather_condition for weather_condition in weather):
                warnings.append("Active thunderstorm in vicinity - NO-GO condition.")
            if any("LTG" in weather_condition for weather_condition in weather):
                if any(all(condition in weather_condition for condition in ["DSNT", "ALQDS"]) for weather_condition in weather):
                    warnings.append("Lightning observed in all quadrants.")
                else:
                    warnings.append("Lightning observed in vicinity.")
            if ceiling is not None and ceiling < 3000:
                warnings.append(f"Low ceiling: {ceiling} ft AGL.")
            if visibility is not None and visibility < 5:
                warnings.append(f"Reduced visibility: {visibility} SM.")
            if any("GR" in weather_condition for weather_condition in weather):
                warnings.append("Hail reported.")
            if any("FC" in weather_condition for weather_condition in weather):
                warnings.append("Funnel cloud reported - NO-GO condition.")
            if any("FZ" in weather_condition for weather_condition in weather):
                warnings.append("Freezing precipitation reported.")
            if any("+" in weather_condition for weather_condition in weather):
                warnings.append("Heavy precipitation reported.")
                    
            if da_diff > 2000:
                warnings.append(f"Density altitude {da} ft is > 2000 ft above field elevation.")
            
            if runway_length and da_diff > 1000:
                performance_factor = 1 + (da_diff / 10000)
                effective_length = int(runway_length / performance_factor)
                if effective_length < 2500:
                    warnings.append(f"Performance-adjusted runway length: {effective_length}ft - monitor closely.")
                elif runway_length is None and da_diff > 500:
                    warnings.append(f"Runway length unknown - verify performance calculations for {da_diff}ft density altitude difference.")
                
            diagnostic_info = {
                "conditions_assessment": "mild" if rri < 50 else "challenging",
                "primary_risk_factors": [
                    f"{contributor}: {rri_contributors[contributor]['score']} points" 
                    for contributor in rri_contributors 
                    if rri_contributors[contributor]['score'] > 5
                ],
                "data_availability": {
                    "runway_length": runway_length is not None,
                    "weather_conditions": len(weather) > 0,
                    "gusty_winds": wind_gust > wind_speed * 1.2,
                    "significant_temperature": temp_c > 30 or temp_c < 5,
                    "terrain_data": terrain_factor > 1.0
                },
                "advanced_factors_available": {
                    "thermal_analysis": temp_c > 30 or temp_c < 5,
                    "performance_analysis": runway_length is not None,
                    "turbulence_analysis": wind_gust > wind_speed * 1.3,
                    "precipitation_analysis": len(weather) > 0,
                    "terrain_effects": terrain_factor > 1.0
                },
                "configuration_impact": {
                    "risk_profile": config.risk_profile.value,
                    "threshold_adjustment": f"{config.threshold_multiplier:.1f}x normal thresholds",
                    "runway_requirement": f"{config.runway_length_requirement}ft minimum recommended"
                },
                "recommendations": {
                    "data_improvements": [],
                    "operational_notes": []
                }
            }
            
            if runway_length is None:
                diagnostic_info["recommendations"]["data_improvements"].append(
                    "Verify runway length from airport directory for performance calculations"
                )
            
            if da_diff > 1000:
                diagnostic_info["recommendations"]["operational_notes"].append(
                    f"Consider performance charts for {da_diff}ft density altitude"
                )
            
            if rri < 30 and len(weather) == 0:
                diagnostic_info["recommendations"]["operational_notes"].append(
                    "Excellent conditions - good opportunity for training or proficiency flights"
                )
            elif 30 <= rri < 50:
                diagnostic_info["recommendations"]["operational_notes"].append(
                    "Moderate conditions - good for maintaining proficiency with manageable challenges"
                )
            
            if wind_speed > 0 and wind_gust == 0:
                diagnostic_info["recommendations"]["operational_notes"].append(
                    "Steady winds reported - consider actual conditions may vary"
                )
            
            summary = None
            if os.getenv("OPENAI_API_KEY"):
                try:
                    import openai
                    import textwrap
                    openai.api_key = os.environ["OPENAI_API_KEY"]
                    gust_info = f", gusting {wind_gust} kt" if wind_gust > 0 else ""
                    weather_info = ", ".join(weather) if weather else "No significant weather"
                    
                    advanced_risks = []
                    for risk_type in ["thermal_gradient", "atmospheric_stability", "runway_performance", "precipitation_intensity", "turbulence_risk"]:
                        if risk_type in rri_contributors:
                            advanced_risks.append(f"{risk_type.replace('_', ' ').title()}: {rri_contributors[risk_type]['score']}")
                    
                    advanced_info = "; ".join(advanced_risks) if advanced_risks else "No advanced risk factors detected"
                    
                    prompt = textwrap.dedent(
                        f"""
                        Generate a single-sentence advisory for a GA pilot based on these data.
                        Airport: {icao}, Runway {rwy_id} ({rwy_heading}°).
                        Wind: {wind_speed} kt{gust_info} from {wind_dir}°.
                        Weather: {weather_info}
                        Ceiling: {ceiling if ceiling is not None else "unlimited"} ft
                        Visibility: {visibility if visibility is not None else "unlimited"} SM
                        Headwind: {head} kt {'(tailwind)' if not is_head else ''}.
                        Crosswind: {cross} kt.
                        Gust headwind: {gust_head} kt {'(tailwind)' if not gust_is_head else ''}.
                        Gust crosswind: {gust_cross} kt.
                        Density altitude: {da} ft.
                        Advanced Risk Analysis: {advanced_info}
                        Runway Risk Index: {rri}/100 ({get_rri_category(rri)} RISK)
                        Status: {get_status_from_rri(rri)}.
                        """
                    )
                    chat = openai.chat.completions.create(
                        model="gpt-3.5-turbo",
                        messages=[{"role": "user", "content": prompt}],
                        temperature=0.3,
                        max_tokens=50,
                    )
                    summary = chat.choices[0].message.content.strip()
                except Exception as e:
                    logger.error(f"Error generating OpenAI summary for {icao} runway {rwy_id}: {str(e)}")
                    summary = None
            
            runway_results.append({
                "runway": rwy_id,
                "heading": rwy_heading,
                "length": runway_length,
                "headwind_kt": head,
                "crosswind_kt": cross,
                "gust_headwind_kt": gust_head,
                "gust_crosswind_kt": gust_cross,
                "tailwind": not is_head,
                "gust_tailwind": not gust_is_head,
                "density_altitude_ft": da,
                "density_altitude_diff_ft": da_diff,
                "terrain_factor": terrain_factor,
                "runway_risk_contributors": rri_contributors,
                "runway_risk_index": rri,
                "risk_category": get_rri_category(rri),
                "status": get_status_from_rri(rri),
                "rri_p05": probabilistic_rri_results.get("rri_p05"),
                "rri_p95": probabilistic_rri_results.get("rri_p95"),
                "weather": weather,
                "ceiling": ceiling,
                "visibility": visibility,
                "warnings": warnings,
                "time_factors": time_factors,
                "plain_summary": summary,
                "advanced_analysis": {
                    "thermal_conditions": rri_contributors.get("thermal_gradient", {}).get("value", []),
                    "atmospheric_stability": rri_contributors.get("atmospheric_stability", {}).get("value", []),
                    "runway_performance": rri_contributors.get("runway_performance", {}).get("value", []),
                    "precipitation_analysis": rri_contributors.get("precipitation_intensity", {}).get("value", []),
                    "turbulence_analysis": rri_contributors.get("turbulence_risk", {}).get("value", []),
                    "risk_amplification": rri_contributors.get("risk_amplification", {}).get("value", []),
                    "diagnostic_info": diagnostic_info
                }
            })
            
        if not runway_results:
            logger.error(f"No valid runway data could be processed for {icao}")
            raise APIError(
                message="Failed to process runway data",
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                details={"icao": icao}
            )
            
        logger.info(f"Successfully processed brief for {icao}")
        return JSONResponse({
            "icao": icao,
            "aircraft_config": {
                "type": req.aircraft_type,
                "experience_level": req.pilot_experience,
                "category": config.aircraft_category.value,
                "risk_profile": config.risk_profile.value,
                "runway_requirement_ft": config.runway_length_requirement,
                "threshold_multiplier": config.threshold_multiplier
            },
            "airport_info": airport,
            "metar": metar,
            "taf": taf,
            "stationinfo": stationinfo,
            "notams": notams,
            "gairmet": gairmet,
            "sigmet": sigmet,
            "isigmet": isigmet,
            "pirep": pirep,
            "cwa": cwa,
            "windtemp": windtemp,
            "areafcst": areafcst,
            "fcstdisc": fcstdisc,
            "mis": mis,
            "runway_briefs": runway_results
        })
            
    except APIError:
        raise
    except Exception as e:
        logger.exception(f"Unexpected error processing brief for {icao}")
        raise APIError(
            message="Internal server error",
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            details={
                "icao": icao,
                "error": str(e)
            }
        )

@router.get("/brief/help")
@limiter.limit("60/minute")
async def brief_help(request: Request):
    return JSONResponse({
        "service": "RunwayGuard Advanced Runway Risk Intelligence (ARRI)",
        "version": "2.0.0",
        "description": "Professional aviation risk assessment system with advanced weather analysis, performance modeling, and multi-factor risk correlation",
        
        "quick_start": {
            "basic_request": {
                "method": "POST",
                "endpoint": "/v1/brief",
                "example": {
                    "icao": "KGGG"
                },
                "description": "Get comprehensive runway risk analysis for any airport"
            }
        },
        
        "request_parameters": {
            "required": {
                "icao": {
                    "type": "string",
                    "description": "4-letter ICAO airport code (e.g., KDFW, KGGG, KCNW)",
                    "examples": ["KDFW", "KGGG", "KCNW", "KLAX", "KJFK"],
                    "validation": "3-4 alphanumeric characters"
                }
            },
            "optional": {
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
            }
        },
        
        "response_features": {
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
        
        "support": {
            "documentation": "https://github.com/andrewwade/runwayguard",
            "api_version": "v1",
            "rate_limits": "20 requests per minute per IP",
            "contact": "See GitHub repository for issues and contributions"
        }
    })