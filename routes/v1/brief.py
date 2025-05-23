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
from fastapi import Request, status
from fastapi.responses import JSONResponse

from fastapi import APIRouter
from slowapi import Limiter
from slowapi.util import get_remote_address
from functions.time_factors import calculate_time_risk_factor
from functions.core_calculations import pressure_alt, density_alt, wind_components, gust_components, calculate_rri, get_rri_category, get_status_from_rri
from functions.probabilistic_rri import calculate_probabilistic_rri_monte_carlo
from functions.weather_fetcher import fetch_metar, fetch_taf, fetch_notams, fetch_stationinfo, fetch_gairmet, fetch_sigmet, fetch_isigmet, fetch_pirep, fetch_cwa, fetch_windtemp, fetch_areafcst, fetch_fcstdisc, fetch_mis
from functions.getairportinfo import fetch_airport_info
from dotenv import load_dotenv

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
    logger.info(f"Processing brief request for ICAO: {icao}")
    
    try:
        # Fetch airport info first to validate airport exists
        airport = await fetch_airport_info(icao)
        if not airport or not airport.get("elevation"):
            logger.warning(f"Airport data not found or incomplete for ICAO: {icao}")
            raise APIError(
                message="Airport not found or data incomplete",
                status_code=status.HTTP_404_NOT_FOUND,
                details={"icao": icao, "airport_data": airport}
            )
        
        logger.debug(f"Airport info retrieved for {icao}: {airport}")
        
        # Fetch all weather data
        try:
            metar = await fetch_metar(icao)
            if not metar or not metar.get("raw"):
                logger.warning(f"No METAR data available for ICAO: {icao}")
                raise APIError(
                    message="No current weather data available",
                    status_code=status.HTTP_404_NOT_FOUND,
                    details={"icao": icao, "metar_data": metar}
                )
        except Exception as e:
            logger.error(f"Error fetching METAR for {icao}: {str(e)}")
            raise APIError(
                message="Failed to fetch current weather data",
                status_code=status.HTTP_502_BAD_GATEWAY,
                details={"icao": icao, "error": str(e)}
            )
            
        # Fetch remaining data with individual error handling
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
            # Continue processing with available data, log the error
            
        # Process airport and weather data
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
                
            # Check if runway is closed
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
                
            # Get station coordinates from stationinfo
            lat = stationinfo.get("latitude")
            lon = stationinfo.get("longitude")
            
            try:
                da = density_alt(field_elev, temp_c, altim_in_hg)
                da_diff = da - field_elev
                head, cross, is_head = wind_components(rwy_heading, wind_dir, wind_speed)
                
                gust_head, gust_cross, gust_is_head = (0, 0, True)
                if wind_gust > 0:
                    gust_head, gust_cross, gust_is_head = gust_components(rwy_heading, wind_dir, wind_gust)
                
                # Calculate RRI with time factors
                rri, rri_contributors = calculate_rri(head, cross, gust_head, gust_cross, wind_speed, wind_gust, 
                              is_head, gust_is_head, da_diff, metar, lat, lon, rwy_heading, notams)
                
                # Get time-based risk factors for warnings
                time_factors = calculate_time_risk_factor(datetime.utcnow(), lat, lon, rwy_heading) if lat and lon else None
                
                # Calculate probabilistic RRI
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
            
            # Add new risk factor warnings
            if "icing_conditions" in rri_contributors:
                warnings.extend(rri_contributors["icing_conditions"]["value"])
            if "temperature_performance" in rri_contributors:
                warnings.extend(rri_contributors["temperature_performance"]["value"])
            if "wind_shear_risk" in rri_contributors:
                warnings.extend(rri_contributors["wind_shear_risk"]["value"])
            if "enhanced_weather" in rri_contributors:
                warnings.extend(rri_contributors["enhanced_weather"]["value"])
            if "notam_risks" in rri_contributors:
                warnings.extend(rri_contributors["notam_risks"]["value"])
            
            # Check weather conditions
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
                
            summary = None
            if os.getenv("OPENAI_API_KEY"):
                try:
                    import openai
                    import textwrap
                    openai.api_key = os.environ["OPENAI_API_KEY"]
                    gust_info = f", gusting {wind_gust} kt" if wind_gust > 0 else ""
                    weather_info = ", ".join(weather) if weather else "No significant weather"
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
                        Runway Risk Index: {rri}/100 ({get_rri_category(rri)} RISK)
                        Status: {get_status_from_rri(rri)}.
                        """
                    )
                    chat = openai.chat.completions.create(
                        model="gpt-3.5-turbo",
                        messages=[{"role": "user", "content": prompt}],
                        temperature=0.3,
                        max_tokens=40,
                    )
                    summary = chat.choices[0].message.content.strip()
                except Exception as e:
                    logger.error(f"Error generating OpenAI summary for {icao} runway {rwy_id}: {str(e)}")
                    summary = None
            
            runway_results.append({
                "runway": rwy_id,
                "heading": rwy_heading,
                "headwind_kt": head,
                "crosswind_kt": cross,
                "gust_headwind_kt": gust_head,
                "gust_crosswind_kt": gust_cross,
                "tailwind": not is_head,
                "gust_tailwind": not gust_is_head,
                "density_altitude_ft": da,
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