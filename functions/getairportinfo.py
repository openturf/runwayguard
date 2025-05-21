from functions.caching import cached_fetch
import os
from dotenv import load_dotenv


load_dotenv()

API_BASE = os.getenv("FAA_API")

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