"""
Weather Data Fetching

This module handles all the messy work of getting weather data from various FAA APIs
and parsing it into something useful. The main function you'll care about is fetch_metar()
which gets current weather conditions for an airport.

It also handles TAFs (forecasts), NOTAMs (airport notices), and various other weather
products like SIGMETs and PIREPs. The METAR parsing is pretty robust - it handles
all the weird edge cases in aviation weather reporting.

Everything is cached so we don't hammer the FAA servers, and it gracefully handles
when APIs are down or return weird data.
"""

import os
import logging
from typing import Dict, Any, Optional
from functions.infrastructure.caching import cached_fetch

logger = logging.getLogger(__name__)

API_BASE = os.getenv("FAA_API")


async def fetch_metar(icao: str) -> Dict[str, Any]:
    """Fetch and parse METAR data for an airport."""
    url = f"{API_BASE}/metar?ids={icao}&format=raw"
    def parser(r):
        logger.debug(f"[metar] Response headers: {r.headers}")
        logger.debug(f"[metar] Response type: {type(r.text)}")
        logger.debug(f"[metar] Raw response: {r.text[:500]}")
        
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
            "dewpoint_c": None,
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
            if part.endswith("Z") and len(part) == 7:
                data["obs_time"] = part
                
            if "KT" in part:
                try:
                    if "G" in part:
                        gust_parts = part.split("G")
                        base_part = gust_parts[0]
                        data["wind_dir"] = int(base_part[:3])
                        data["wind_speed"] = int(base_part[3:])
                        data["wind_gust"] = int(gust_parts[1].replace("KT", ""))
                    elif len(part) >= 7:
                        data["wind_dir"] = int(part[:3])
                        data["wind_speed"] = int(part[3:5])
                except ValueError:
                    pass
                    
            if not temp_c_found and "/" in part and part.count('/') == 1:
                try:
                    temp_str, dew_str = part.split('/')
                    
                    valid_temp_format = (temp_str.startswith('M') and len(temp_str) == 3 and temp_str[1:].isdigit()) or \
                                        (not temp_str.startswith('M') and len(temp_str) == 2 and temp_str.isdigit())
                    valid_dew_format = (dew_str.startswith('M') and len(dew_str) == 3 and dew_str[1:].isdigit()) or \
                                       (not dew_str.startswith('M') and len(dew_str) == 2 and dew_str.isdigit())

                    if valid_temp_format and valid_dew_format:
                        if temp_str.startswith("M"):
                            data["temp_c"] = -int(temp_str[1:])
                        else:
                            data["temp_c"] = int(temp_str)
                        
                        if dew_str.startswith("M"):
                            data["dewpoint_c"] = -int(dew_str[1:])
                        else:
                            data["dewpoint_c"] = int(dew_str)
                        temp_c_found = True
                except (ValueError, IndexError):
                    logger.warning(f"Failed to parse temperature from: {part}")
                    pass
                    
            if "SM" in part:
                try:
                    vis = part.replace("SM", "")
                    if "/" in vis:
                        num, den = vis.split("/")
                        data["visibility"] = float(num) / float(den)
                    else:
                        data["visibility"] = float(vis)
                except ValueError:
                    pass
                    
            if any(part.startswith(prefix) for prefix in ["SKC", "CLR", "FEW", "SCT", "BKN", "OVC"]):
                try:
                    cloud_type = part[:3]
                    height = int(part[3:]) * 100
                    
                    data["cloud_layers"].append({
                        "type": cloud_type,
                        "height": height
                    })
                    
                    if part.startswith(("BKN", "OVC")):
                        if data["ceiling"] is None or height < data["ceiling"]:
                            data["ceiling"] = height
                except ValueError:
                    pass
                    
            if "LTG" in part:
                data["lightning"] = part
                data["weather"].add(part)
                if i + 2 < len(parts) and "DSNT" in parts[i:i+2] and "ALQDS" in parts[i:i+3]:
                    data["weather"].add("LTG DSNT ALQDS")
                    
            if any(wx in part for wx in ["TS", "GR", "+", "FC", "SH", "FZ", "BR", "FG", "RA", "VCTS"]):
                data["weather"].add(part)
                
            if part.startswith("TSE") and len(part) >= 7:
                try:
                    data["weather"].add(part)
                except ValueError:
                    pass
                    
            if part.startswith("A") and len(part) == 5:
                try:
                    data["altim_in_hg"] = float(part[1:]) / 100
                except ValueError:
                    pass
        
        data["weather"] = list(data["weather"])
        return data
    return await cached_fetch(f"metar_{icao}", url, parser)

async def fetch_taf(icao: str) -> Dict[str, Any]:
    """Fetch and parse TAF data for an airport."""
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

async def fetch_notams(icao: str) -> Dict[str, Any]:
    """Fetch and parse NOTAMs for an airport."""
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
            return {"closed_runways": closed_runways, "raw_text": text}
        except Exception as e:
            logger.error(f"Failed to parse NOTAMs: {e}")
            return {"closed_runways": [], "raw_text": ""}
    return await cached_fetch(f"notams_{icao}", url, parser) 

async def fetch_mis(loc="dfw"):
    url = f"{API_BASE}/mis?loc={loc}&format=json"
    def parser(r):
        try:
            data = r.json()
        except Exception:
            data = r.text
        return data if isinstance(data, dict) else {"raw": data}
    return await cached_fetch(f"mis_{loc}", url, parser)


async def fetch_fcstdisc(cwa="dfw"):
    url = f"{API_BASE}/fcstdisc?cwa={cwa}&format=json"
    def parser(r):
        try:
            data = r.json()
        except Exception:
            data = r.text
        return data if isinstance(data, dict) else {"raw": data}
    return await cached_fetch(f"fcstdisc_{cwa}", url, parser)


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