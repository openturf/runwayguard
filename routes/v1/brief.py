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
- @awade12 may 20th 2025
"""

import os
import math
import time
import re
import logging
from datetime import datetime
from typing import Optional, Dict, Any, List
from pydantic import BaseModel, validator
from fastapi import Request, status, HTTPException
from fastapi.responses import JSONResponse

from fastapi import APIRouter
from slowapi import Limiter
from slowapi.util import get_remote_address
from functions.core.time_factors import calculate_time_risk_factor
from functions.core.core_calculations import pressure_alt, density_alt, wind_components, gust_components, calculate_rri, calculate_advanced_rri, get_rri_category, get_status_from_rri
from functions.core.probabilistic_rri import calculate_probabilistic_rri_monte_carlo, calculate_advanced_probabilistic_rri
from functions.data_sources.weather_fetcher import fetch_metar, fetch_taf, fetch_notams, fetch_stationinfo, fetch_gairmet, fetch_sigmet, fetch_isigmet, fetch_pirep, fetch_cwa, fetch_windtemp, fetch_areafcst, fetch_fcstdisc, fetch_mis
from functions.data_sources.getairportinfo import fetch_airport_info
from functions.core.route_analysis import analyze_route
from dotenv import load_dotenv
from functions.config.advanced_config import ConfigurationManager
from functions.infrastructure.database import get_database

load_dotenv()

logger = logging.getLogger(__name__)

router = APIRouter()

limiter = Limiter(key_func=get_remote_address)

def get_client_ip(request: Request) -> str:
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"

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

class RouteRequest(BaseModel):
    airports: List[str]
    aircraft_type: Optional[str] = "light"
    pilot_experience: Optional[str] = "standard"
    route_distances: Optional[List[float]] = None
    
    @validator('airports')
    def validate_airports(cls, v):
        if len(v) < 2:
            raise ValueError('Route must include at least departure and destination airports')
        if len(v) > 10:
            raise ValueError('Route analysis limited to 10 airports maximum')
        
        validated_airports = []
        for airport in v:
            airport = airport.upper()
            if not re.match(r'^[A-Z0-9]{3,4}$', airport):
                raise ValueError(f'Invalid ICAO code: {airport}')
            validated_airports.append(airport)
        return validated_airports
    
    @validator('route_distances')
    def validate_distances(cls, v, values):
        if v is not None:
            airports = values.get('airports', [])
            if len(v) != len(airports) - 1:
                raise ValueError('Route distances must have one less entry than airports')
            if any(d <= 0 for d in v):
                raise ValueError('All distances must be positive')
        return v
    

@router.post("/brief")
@limiter.limit("20/minute")
async def brief(request: Request, req: BriefRequest):
    start_time = time.time()
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
                    "help": "For API usage guidance, visit /v1/help",
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
                        "help": "For API usage guidance, visit /v1/help",
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
        
        taf = {"raw": "", "start_time": None, "end_time": None}
        stationinfo = {"latitude": None, "longitude": None}
        notams = {"closed_runways": [], "raw_text": ""}
        gairmet = []
        sigmet = []
        isigmet = []
        pirep = []
        cwa = []
        windtemp = {"raw": ""}
        areafcst = {"raw": ""}
        fcstdisc = {"raw": ""}
        mis = {"raw": ""}
        
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
                    aircraft_category=req.aircraft_type,
                    config=config
                )
                
                time_factors = calculate_time_risk_factor(datetime.utcnow(), lat, lon, rwy_heading) if lat and lon else None
                
                weather = metar.get("weather", [])
                ceiling = metar.get("ceiling")
                visibility = metar.get("visibility")
                
                probabilistic_analysis = None
                if lat is not None and lon is not None:
                    base_conditions = {
                        "wind_dir": wind_dir,
                        "wind_speed": wind_speed,
                        "wind_gust": wind_gust if wind_gust > 0 else 0,
                        "temp_c": temp_c,
                        "altim_in_hg": altim_in_hg
                    }
                    
                    if visibility is not None:
                        base_conditions["visibility"] = visibility
                    if ceiling is not None:
                        base_conditions["ceiling"] = ceiling
                    
                    try:
                        probabilistic_result = calculate_advanced_probabilistic_rri(
                            rwy_heading=rwy_heading,
                            base_conditions=base_conditions,
                            da_diff=da_diff,
                            metar_data=metar,
                            lat=lat,
                            lon=lon,
                            num_draws=1000,
                            include_temporal=True,
                            include_extremes=True,
                            runway_length=runway_length,
                            airport_elevation=field_elev,
                            aircraft_category=req.aircraft_type
                        )
                        
                        probabilistic_analysis = {
                            "percentiles": probabilistic_result.percentiles,
                            "statistics": probabilistic_result.statistics,
                            "risk_distribution": probabilistic_result.risk_distribution,
                            "confidence_intervals": probabilistic_result.confidence_intervals,
                            "sensitivity_analysis": probabilistic_result.sensitivity_analysis,
                            "extreme_scenarios": probabilistic_result.extreme_scenarios[:5],
                            "temporal_forecast": probabilistic_result.temporal_evolution,
                            "scenario_summary": {
                                "total_scenarios": len(probabilistic_result.scenario_clusters["normal"]) + 
                                                 len(probabilistic_result.scenario_clusters["deteriorating"]) + 
                                                 len(probabilistic_result.scenario_clusters["improving"]),
                                "deteriorating_scenarios": len(probabilistic_result.scenario_clusters["deteriorating"]),
                                "improving_scenarios": len(probabilistic_result.scenario_clusters["improving"])
                            }
                        }
                        
                        legacy_format = {
                            "rri_p05": probabilistic_result.percentiles["p05"],
                            "rri_p95": probabilistic_result.percentiles["p95"]
                        }
                        
                    except Exception as prob_error:
                        logger.warning(f"Advanced probabilistic analysis failed for {icao} runway {rwy_id}: {str(prob_error)}")
                        legacy_format = calculate_probabilistic_rri_monte_carlo(
                            rwy_heading=rwy_heading,
                            original_wind_dir=wind_dir,
                            original_wind_speed=wind_speed,
                            original_wind_gust=wind_gust,
                            da_diff=da_diff,
                            metar_data=metar,
                            lat=lat,
                            lon=lon
                        )
                        probabilistic_analysis = {
                            "error": "Advanced analysis unavailable - using legacy calculation",
                            "legacy_percentiles": legacy_format
                        }
                else:
                    legacy_format = {"rri_p05": None, "rri_p95": None}
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
            
            if probabilistic_analysis and "risk_distribution" in probabilistic_analysis:
                risk_dist = probabilistic_analysis["risk_distribution"]
                if risk_dist.get("no_go_probability", 0) > 0.1:
                    diagnostic_info["recommendations"]["operational_notes"].append(
                        f"Uncertainty analysis shows {risk_dist['no_go_probability']:.1%} chance of NO-GO conditions"
                    )
                elif risk_dist.get("extreme_risk", 0) > 0.2:
                    diagnostic_info["recommendations"]["operational_notes"].append(
                        f"Uncertainty analysis shows {risk_dist['extreme_risk']:.1%} chance of extreme risk conditions"
                    )
                
                if "sensitivity_analysis" in probabilistic_analysis:
                    most_sensitive = max(probabilistic_analysis["sensitivity_analysis"].items(), 
                                       key=lambda x: x[1], default=(None, 0))
                    if most_sensitive[0] and most_sensitive[1] > 2:
                        diagnostic_info["recommendations"]["operational_notes"].append(
                            f"Risk most sensitive to {most_sensitive[0].replace('_', ' ')} changes"
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
                    
                    uncertainty_info = "No uncertainty analysis available"
                    if probabilistic_analysis and "confidence_intervals" in probabilistic_analysis:
                        ci_90 = probabilistic_analysis["confidence_intervals"]["90_percent"]
                        uncertainty_info = f"90% confidence interval: {ci_90[0]:.0f}-{ci_90[1]:.0f} RRI"
                        
                        if "risk_distribution" in probabilistic_analysis:
                            risk_dist = probabilistic_analysis["risk_distribution"]
                            no_go_prob = risk_dist.get("no_go_probability", 0)
                            if no_go_prob > 0.05:
                                uncertainty_info += f"; {no_go_prob:.1%} chance NO-GO conditions"
                    
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
                        Uncertainty Analysis: {uncertainty_info}
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
                "rri_p05": legacy_format.get("rri_p05"),
                "rri_p95": legacy_format.get("rri_p95"),
                "probabilistic_analysis": probabilistic_analysis,
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
            
        processing_time = round(time.time() - start_time, 3)
        
        response_data = {
            "icao": icao,
            "processing_time_seconds": processing_time,
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
        }
        
        try:
            db = await get_database()
            if db.engine:
                await db.store_api_response(
                    endpoint="brief",
                    request_data=req.dict(),
                    response_data=response_data,
                    processing_time=processing_time,
                    client_ip=get_client_ip(request)
                )
            else:
                logger.info("Database not configured - skipping response storage")
        except Exception as e:
            logger.error(f"Failed to store response to database: {str(e)}")
        
        logger.info(f"Successfully processed brief for {icao} in {processing_time}s")
        return JSONResponse(response_data)
            
    except APIError as api_error:
        try:
            db = await get_database()
            if db.engine:
                await db.store_api_response(
                    endpoint="brief",
                    request_data=req.dict(),
                    response_data={},
                    processing_time=round(time.time() - start_time, 3),
                    client_ip=get_client_ip(request),
                    error_message=api_error.message
                )
        except Exception as e:
            logger.error(f"Failed to store error to database: {str(e)}")
        raise
    except Exception as e:
        processing_time = round(time.time() - start_time, 3)
        error_message = f"Internal server error: {str(e)}"
        
        try:
            db = await get_database()
            if db.engine:
                await db.store_api_response(
                    endpoint="brief",
                    request_data=req.dict(),
                    response_data={},
                    processing_time=processing_time,
                    client_ip=get_client_ip(request),
                    error_message=error_message
                )
        except Exception as db_error:
            logger.error(f"Failed to store error to database: {str(db_error)}")
        
        logger.exception(f"Unexpected error processing brief for {icao}")
        raise APIError(
            message="Internal server error",
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            details={
                "icao": icao,
                "error": str(e)
            }
        )

@router.post("/route")
@limiter.limit("10/minute")
async def route_analysis(request: Request, req: RouteRequest):
    """
    Multi-Airport Route Analysis
    
    Provides comprehensive weather and risk assessment across multiple airports
    for route planning, alternate selection, and strategic decision making.
    """
    route_airports = req.airports
    logger.info(f"Processing route analysis for {len(route_airports)} airports: {' -> '.join(route_airports)}")
    
    try:
        route_data = await analyze_route(
            airports=route_airports,
            aircraft_type=req.aircraft_type,
            pilot_experience=req.pilot_experience,
            route_distances=req.route_distances
        )
        
        response_data = {
            "service": "RunwayGuard Multi-Airport Route Analysis",
            "version": "2.0.0",
            "analysis_type": "route",
            "route_analysis": route_data
        }
        
        try:
            db = await get_database()
            if db.engine:  # Only store if database is properly configured
                await db.store_api_response(
                    endpoint="route",
                    request_data=req.dict(),
                    response_data=response_data,
                    client_ip=get_client_ip(request)
                )
            else:
                logger.info("Database not configured - skipping route response storage")
        except Exception as e:
            logger.error(f"Failed to store route response to database: {str(e)}")
        
        logger.info(f"Successfully processed route analysis for {' -> '.join(route_airports)}")
        return JSONResponse(response_data)
        
    except ValueError as e:
        error_message = f"Invalid route configuration: {str(e)}"
        
        try:
            db = await get_database()
            if db.engine:
                await db.store_api_response(
                    endpoint="route",
                    request_data=req.dict(),
                    response_data={},
                    client_ip=get_client_ip(request),
                    error_message=error_message
                )
        except Exception as db_error:
            logger.error(f"Failed to store route error to database: {str(db_error)}")
        
        logger.warning(f"Invalid route request: {str(e)}")
        raise APIError(
            message=error_message,
            status_code=status.HTTP_400_BAD_REQUEST,
            details={
                "airports": route_airports,
                "help": "For API usage guidance, visit /v1/help"
            }
        )
    except Exception as e:
        error_message = f"Internal server error during route analysis: {str(e)}"
        
        try:
            db = await get_database()
            if db.engine:
                await db.store_api_response(
                    endpoint="route",
                    request_data=req.dict(),
                    response_data={},
                    client_ip=get_client_ip(request),
                    error_message=error_message
                )
        except Exception as db_error:
            logger.error(f"Failed to store route error to database: {str(db_error)}")
        
        logger.exception(f"Unexpected error processing route analysis for {' -> '.join(route_airports)}")
        raise APIError(
            message="Internal server error during route analysis",
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            details={
                "airports": route_airports,
                "error": str(e)
            }
        )



@router.get("/analytics/recent")
@limiter.limit("30/minute")
async def get_recent_responses(
    request: Request,
    endpoint: Optional[str] = None,
    icao: Optional[str] = None,
    limit: int = 50
):
    """Get recent API responses from the database"""
    try:
        db = await get_database()
        if not db.engine:
            raise APIError(
                message="Database not configured",
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                details={
                    "error": "Database functionality requires DATABASE_URL to be configured",
                    "help": "Set DATABASE_URL environment variable with postgresql+asyncpg:// connection string"
                }
            )
            
        responses = await db.get_recent_responses(
            endpoint=endpoint,
            icao_code=icao,
            limit=min(limit, 100)
        )
        
        return JSONResponse({
            "recent_responses": responses,
            "filters_applied": {
                "endpoint": endpoint,
                "icao_filter": icao,
                "limit": limit
            },
            "total_returned": len(responses)
        })
        
    except APIError:
        raise
    except Exception as e:
        logger.error(f"Failed to retrieve recent responses: {str(e)}")
        raise APIError(
            message="Failed to retrieve analytics data",
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            details={"error": str(e)}
        )

@router.get("/analytics/stats")
@limiter.limit("30/minute")
async def get_usage_stats(request: Request, days: int = 30):
    """Get usage statistics from the database"""
    try:
        db = await get_database()
        if not db.engine:
            raise APIError(
                message="Database not configured",
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                details={
                    "error": "Database functionality requires DATABASE_URL to be configured",
                    "help": "Set DATABASE_URL environment variable with postgresql+asyncpg:// connection string"
                }
            )
            
        stats = await db.get_usage_stats(days=min(days, 365))
        
        return JSONResponse({
            "usage_statistics": stats,
            "period_days": days
        })
        
    except APIError:
        raise
    except Exception as e:
        logger.error(f"Failed to retrieve usage stats: {str(e)}")
        raise APIError(
            message="Failed to retrieve usage statistics",
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            details={"error": str(e)}
        )