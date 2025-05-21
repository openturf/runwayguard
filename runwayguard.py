# RunwayGuard – minimal FastAPI micro‑service that calculates real‑time runway wind components
# and density altitude, optionally generating a plain‑English advisory via OpenAI.
#
# Usage (after installing dependencies):
#   uvicorn runwayguard:app --reload
# Requires: fastapi, uvicorn, requests, pydantic, python‑multipart, xmltodict, openai (optional), slowapi, httpx

import os
import math
import time
import re
import httpx
import asyncio
import logging
from datetime import datetime
from typing import Optional, Dict, Any, List, Union
from fastapi import FastAPI, HTTPException, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, validator
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from functions.time_factors import calculate_time_risk_factor
from functions.core_calculations import pressure_alt, density_alt, wind_components, gust_components, calculate_rri, get_rri_category, get_status_from_rri
from functions.probabilistic_rri import calculate_probabilistic_rri_monte_carlo
from dotenv import load_dotenv

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

load_dotenv()

API_BASE = os.getenv("FAA_API")
BUCKET_SECONDS = 60
_cached = {}

# Initialize rate limiter
limiter = Limiter(key_func=get_remote_address)
app = FastAPI(title="RunwayGuard", version="0.3.0")
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

class APIError(Exception):
    def __init__(self, message: str, status_code: int = 500, details: Optional[Dict[str, Any]] = None):
        self.message = message
        self.status_code = status_code
        self.details = details or {}
        super().__init__(self.message)

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

async def cached_fetch(key, url, parser=None):
    now = time.time()
    if key in _cached and now - _cached[key]["ts"] < BUCKET_SECONDS:
        return _cached[key]["data"]
    try:
        async with httpx.AsyncClient() as client:
            r = await client.get(url, timeout=10.0)
            r.raise_for_status()
    except httpx.RequestError as exc:
        raise RuntimeError(f"Fetch failed: {exc}") from exc
    
    data = await parser(r) if parser and asyncio.iscoroutinefunction(parser) else parser(r) if parser else r.json() if r.headers.get("content-type","").startswith("application/json") else r.text
    _cached[key] = {"ts": now, "data": data}
    return data

async def fetch_airport_info(icao):
    url = f"{API_BASE}/airport?ids={icao}"
    def parser(r):
        print(f"[airport_info] Response headers: {r.headers}")
        print(f"[airport_info] Response type: {type(r.text)}")
        if r.headers.get("content-type", "").startswith("application/json"):
            data = r.json()
            print(f"[airport_info] JSON data: {data}")
            elev = data.get("elevation") or None
            mag_dec = data.get("mag_dec") or None
            runways = data.get("runways") or []
            
            # Convert runway numbers to proper headings
            processed_runways = []
            for rwy in runways:
                if isinstance(rwy.get("id"), str) and "/" in rwy.get("id"):
                    rwy_nums = rwy["id"].split("/")
                    if len(rwy_nums) == 2:
                        try:
                            rwy1 = int(rwy_nums[0]) * 10
                            rwy2 = int(rwy_nums[1]) * 10
                            processed_runways.append({"id": rwy["id"], "heading": rwy1})
                        except ValueError:
                            print(f"[airport_info] Failed to parse runway numbers: {rwy}")
                            continue
                else:
                    processed_runways.append(rwy)
            
            return {"elevation": elev, "mag_dec": mag_dec, "runways": processed_runways}
        elif isinstance(r.text, str):
            text = r.text
            print(f"[airport_info] Text data: {text[:200]}")
            elev = None
            mag_dec = None
            runways = []
            for line in text.splitlines():
                if line.strip().startswith("Elevation:"):
                    try: elev = int(line.split(":",1)[-1].strip().split()[0])
                    except: pass
                if line.strip().startswith("Mag Declination:"):
                    try: mag_dec = line.split(":",1)[-1].strip()
                    except: pass
                if line.strip().startswith("Runway:"):
                    try:
                        parts = line.split(":",1)[-1].strip().split()
                        rwy_id = parts[0] if parts else None
                        align = None
                        for i, p in enumerate(parts):
                            if p == "Align:" and i+1 < len(parts):
                                try: align = int(parts[i+1])
                                except: pass
                        if rwy_id and align:
                            runways.append({"id": rwy_id, "heading": align})
                    except: pass
            return {"elevation": elev, "mag_dec": mag_dec, "runways": runways}
        else:
            print(f"[airport_info] Unexpected response type: {type(r.text)} value: {r.text}")
            return {"elevation": None, "mag_dec": None, "runways": []}
    return await cached_fetch(f"airport_{icao}", url, parser)

async def fetch_metar(icao):
    url = f"{API_BASE}/metar?ids={icao}&format=raw"
    def parser(r):
        print(f"[metar] Response headers: {r.headers}")
        print(f"[metar] Response type: {type(r.text)}")
        print(f"[metar] Raw response: {r.text[:500]}")
        
        metar_text = r.text.strip()
        if not metar_text:
            return {"obs_time": None, "wind_dir": 0, "wind_speed": 0, "altim_in_hg": 29.92, "temp_c": 15, "raw": None, "debug": "No METAR data returned"}
            
        data = {
            "obs_time": None, 
            "wind_dir": 0, 
            "wind_speed": 0, 
            "wind_gust": 0, 
            "altim_in_hg": 29.92, 
            "temp_c": 15, 
            "ceiling": None,
            "cloud_layers": [],
            "visibility": None,
            "weather": set(),
            "lightning": None,
            "raw": metar_text, 
            "debug": None
        }
        
        temp_c_found = False

        parts = metar_text.split()
        for i, part in enumerate(parts):
            # Date/time group is in format ddhhmmZ
            if part.endswith("Z") and len(part) == 7:
                data["obs_time"] = part
                
            # Wind information format: dddssGssKT where ddd=direction, ss=speed, G=gust indicator
            if "KT" in part:
                try:
                    if "G" in part:  # Has gust
                        gust_parts = part.split("G")
                        base_part = gust_parts[0]
                        data["wind_dir"] = int(base_part[:3])
                        data["wind_speed"] = int(base_part[3:])
                        data["wind_gust"] = int(gust_parts[1].replace("KT", ""))
                    elif len(part) >= 7:  # Basic wind group (dddssKT)
                        data["wind_dir"] = int(part[:3])
                        data["wind_speed"] = int(part[3:5])
                except ValueError:
                    pass
                    
            # Temperature/dewpoint group is in the format tt/dd where tt=temp
            if not temp_c_found and "/" in part and part.count('/') == 1:
                try:
                    temp_str, dew_str = part.split('/')
                    
                    # Validate format: Mxx or xx for temp and dew point parts
                    valid_temp_format = (temp_str.startswith('M') and len(temp_str) == 3 and temp_str[1:].isdigit()) or \
                                        (not temp_str.startswith('M') and len(temp_str) == 2 and temp_str.isdigit())
                    valid_dew_format = (dew_str.startswith('M') and len(dew_str) == 3 and dew_str[1:].isdigit()) or \
                                       (not dew_str.startswith('M') and len(dew_str) == 2 and dew_str.isdigit())

                    if valid_temp_format and valid_dew_format:
                        if temp_str.startswith("M"):
                            data["temp_c"] = -int(temp_str[1:])
                        else:
                            data["temp_c"] = int(temp_str)
                        temp_c_found = True
                except (ValueError, IndexError):
                    print(f"[metar] Failed to parse temperature from: {part}")
                    pass
                    
            # Visibility in statute miles
            if "SM" in part:
                try:
                    vis = part.replace("SM", "")
                    if "/" in vis:  # Fractional visibility
                        num, den = vis.split("/")
                        data["visibility"] = float(num) / float(den)
                    else:
                        data["visibility"] = float(vis)
                except ValueError:
                    pass
                    
            # Cloud layers
            if any(part.startswith(prefix) for prefix in ["SKC", "CLR", "FEW", "SCT", "BKN", "OVC"]):
                try:
                    # Extract cloud type and height
                    cloud_type = part[:3]
                    height = int(part[3:]) * 100
                    
                    # Add to cloud layers list
                    data["cloud_layers"].append({
                        "type": cloud_type,
                        "height": height
                    })
                    
                    # Set ceiling if it's BKN or OVC and lower than current ceiling
                    if part.startswith(("BKN", "OVC")):
                        if data["ceiling"] is None or height < data["ceiling"]:
                            data["ceiling"] = height
                except ValueError:
                    pass
                    
            # Lightning information and weather phenomena
            if "LTG" in part:
                data["lightning"] = part
                data["weather"].add(part)
                if i + 2 < len(parts) and "DSNT" in parts[i:i+2] and "ALQDS" in parts[i:i+3]:
                    data["weather"].add("LTG DSNT ALQDS")
                    
            # Significant weather phenomena
            if any(wx in part for wx in ["TS", "GR", "+", "FC", "SH", "FZ", "BR", "FG", "RA", "VCTS"]):
                data["weather"].add(part)
                
            # Thunderstorm timing
            if part.startswith("TSE") and len(part) >= 7:
                try:
                    data["weather"].add(part)
                except ValueError:
                    pass
                    
            # Altimeter is in the format Adddd where dddd is the pressure in hundredths
            if part.startswith("A") and len(part) == 5:
                try:
                    data["altim_in_hg"] = float(part[1:]) / 100
                except ValueError:
                    pass
        
        # Convert weather set back to list for JSON serialization
        data["weather"] = list(data["weather"])
        return data
    return await cached_fetch(f"metar_{icao}", url, parser)

async def fetch_taf(icao):
    url = f"{API_BASE}/taf?ids={icao}&format=json"
    def parser(r):
        try:
            taf_data = r.json()
        except Exception:
            taf_data = r.text
        if isinstance(taf_data, dict):
            taf = taf_data.get("data", [{}])[0]
            if not taf:
                return {"raw": "", "start_time": None, "end_time": None, "debug": "No TAF data returned"}
            return {"raw": taf.get("raw_text"), "start_time": taf.get("start_time"), "end_time": taf.get("end_time"), "debug": None}
        else:
            return {"raw": taf_data, "start_time": None, "end_time": None, "debug": "Text TAF fallback"}
    return await cached_fetch(f"taf_{icao}", url, parser)

async def fetch_stationinfo(icao):
    url = f"{API_BASE}/stationinfo?ids={icao}"
    def parser(r):
        try:
            data = r.json()
            if isinstance(data, dict):
                info = data.get("data", [{}])[0]
                return info
        except Exception:
            data = r.text
            if isinstance(data, str):
                info = {}
                for line in data.splitlines():
                    line = line.strip()
                    if ":" in line:
                        key, value = line.split(":", 1)
                        key = key.strip()
                        value = value.strip()
                        if key == "Latitude":
                            try:
                                info["latitude"] = float(value)
                            except ValueError:
                                pass
                        elif key == "Longitude":
                            try:
                                info["longitude"] = float(value)
                            except ValueError:
                                pass
                        elif key == "Elevation":
                            try:
                                info["elevation"] = int(value.split()[0])
                            except (ValueError, IndexError):
                                pass
                return info
        return {"raw": data}
    return await cached_fetch(f"stationinfo_{icao}", url, parser)

async def fetch_gairmet(icao):
    url = f"{API_BASE}/gairmet?format=json"
    def parser(r):
        try:
            data = r.json()
        except Exception:
            data = r.text
        if isinstance(data, dict):
            gairmet = data.get("data", [])
            if not gairmet:
                return []
            return [g for g in gairmet if icao in str(g)]
        return []
    return await cached_fetch(f"gairmet_{icao}", url, parser)

async def fetch_sigmet(icao):
    url = f"{API_BASE}/airsigmet?format=json"
    def parser(r):
        try:
            data = r.json()
        except Exception:
            data = r.text
        if isinstance(data, dict):
            sigmets = data.get("data", [])
            if not sigmets:
                return []
            return [s for s in sigmets if icao in str(s)]
        return []
    return await cached_fetch(f"sigmet_{icao}", url, parser)

async def fetch_pirep(icao):
    url = f"{API_BASE}/pirep?id={icao}&format=json"
    def parser(r):
        try:
            data = r.json()
        except Exception:
            data = r.text
        return data.get("data", []) if isinstance(data, dict) else []
    return await cached_fetch(f"pirep_{icao}", url, parser)

async def fetch_isigmet(icao):
    url = f"{API_BASE}/isigmet?format=json"
    def parser(r):
        try:
            data = r.json()
        except Exception:
            data = r.text
        if isinstance(data, dict):
            isigmet = data.get("data", [])
            if not isigmet:
                return []
            return [s for s in isigmet if icao in str(s)]
        return []
    return await cached_fetch(f"isigmet_{icao}", url, parser)

async def fetch_cwa(icao):
    url = f"{API_BASE}/cwa?format=json"
    def parser(r):
        try:
            data = r.json()
        except Exception:
            data = r.text
        if isinstance(data, list):
            return [c for c in data if icao in str(c)]
        return []
    return await cached_fetch(f"cwa_{icao}", url, parser)

async def fetch_windtemp(region="dfw"):
    url = f"{API_BASE}/windtemp?region={region}&format=json"
    def parser(r):
        try:
            data = r.json()
        except Exception:
            data = r.text
        return data if isinstance(data, dict) else {"raw": data}
    return await cached_fetch(f"windtemp_{region}", url, parser)

async def fetch_areafcst(region="aksouth"):
    url = f"{API_BASE}/areafcst?region={region}&format=json"
    def parser(r):
        try:
            data = r.json()
        except Exception:
            data = r.text
        return data if isinstance(data, dict) else {"raw": data}
    return await cached_fetch(f"areafcst_{region}", url, parser)

async def fetch_fcstdisc(cwa="dfw"):
    url = f"{API_BASE}/fcstdisc?cwa={cwa}&format=json"
    def parser(r):
        try:
            data = r.json()
        except Exception:
            data = r.text
        return data if isinstance(data, dict) else {"raw": data}
    return await cached_fetch(f"fcstdisc_{cwa}", url, parser)

async def fetch_mis(loc="dfw"):
    url = f"{API_BASE}/mis?loc={loc}&format=json"
    def parser(r):
        try:
            data = r.json()
        except Exception:
            data = r.text
        return data if isinstance(data, dict) else {"raw": data}
    return await cached_fetch(f"mis_{loc}", url, parser)

async def fetch_notams(icao):
    url = f"https://www.notams.faa.gov/dinsQueryWeb/queryRetrievalMapAction.do?reportType=RAW&retrieveLocId={icao}"
    def parser(r):
        try:
            text = r.text
            closed_runways = []
            for line in text.splitlines():
                if "RWY" in line and "CLOSED" in line:
                    parts = line.split("RWY")
                    if len(parts) > 1:
                        rwy = parts[1].split()[0].strip()
                        closed_runways.append(rwy)
            return {"closed_runways": closed_runways}
        except Exception as e:
            print(f"[notams] Failed to parse NOTAMs: {e}")
            return {"closed_runways": []}
    return await cached_fetch(f"notams_{icao}", url, parser)

def get_status_from_rri(rri):
    if rri >= 76:  # EXTREME risk
        return "NO-GO"
    elif rri > 50:  # HIGH risk
        return "CAUTION"
    else:
        return "GOOD"

class BriefRequest(BaseModel):
    icao: str
    
    @validator('icao')
    def validate_icao(cls, v):
        # Convert to uppercase for consistency
        v = v.upper()
        # Check if it matches ICAO airport code format (3-4 alphanumeric characters)
        if not re.match(r'^[A-Z0-9]{3,4}$', v):
            raise ValueError('ICAO code must be 3-4 alphanumeric characters')
        return v

### !!!where we initialize the app

@app.post("/brief")
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
                              is_head, gust_is_head, da_diff, metar, lat, lon, rwy_heading)
                
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
