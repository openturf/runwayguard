## rri algorithm

import math
from datetime import datetime
from .time_factors import calculate_time_risk_factor

def pressure_alt(field_elev_ft, altim_in_hg):
    return field_elev_ft + (29.92 - altim_in_hg) * 1000

def density_alt(field_elev_ft, temp_c, altim_in_hg):
    # Validate inputs
    if not isinstance(field_elev_ft, (int, float)) or not isinstance(temp_c, (int, float)) or not isinstance(altim_in_hg, (int, float)):
        print(f"[density_alt] Invalid inputs: elev={field_elev_ft}, temp={temp_c}, altim={altim_in_hg}")
        return 0
        
    # Sanity check temperature (-60°C to +50°C)
    if temp_c < -60 or temp_c > 50:
        print(f"[density_alt] Temperature out of range: {temp_c}°C")
        return 0
        
    pa = pressure_alt(field_elev_ft, altim_in_hg)
    isa_temp = 15 - 2 * (field_elev_ft / 1000)
    da = int(pa + 120 * (temp_c - isa_temp))
    
    # Sanity check result (-1000 to +20000 ft)
    if da < -1000 or da > 20000:
        print(f"[density_alt] Result out of range: {da}ft")
        return 0
        
    return da

def wind_components(rwy_heading_deg, wind_dir_deg, wind_speed_kt):
    rad_diff = math.radians((wind_dir_deg - rwy_heading_deg) % 360)
    head = wind_speed_kt * math.cos(rad_diff)
    cross = wind_speed_kt * math.sin(rad_diff)
    return round(abs(head)), round(abs(cross)), head >= 0

def gust_components(rwy_heading_deg, wind_dir_deg, gust_speed_kt):
    rad_diff = math.radians((wind_dir_deg - rwy_heading_deg) % 360)
    head = gust_speed_kt * math.cos(rad_diff)
    cross = gust_speed_kt * math.sin(rad_diff)
    return round(abs(head)), round(abs(cross)), head >= 0

def calculate_rri(head, cross, gust_head, gust_cross, wind_speed, wind_gust, is_head, gust_is_head, da_diff, metar_data, lat=None, lon=None, rwy_heading=None):
    score = 0
    contributors = {}
    
    # Base wind components (max 30 points)
    if not is_head:
        tailwind_score = min(30, head * 6)  # 5kt tailwind = 30 points
        if tailwind_score > 0:
            contributors["tailwind"] = {"score": tailwind_score, "value": head, "unit": "kt"}
            score += tailwind_score
    if cross > 0:
        crosswind_score = min(30, (cross / 15) * 30)  # 15kt crosswind = 30 points
        if crosswind_score > 0:
            contributors["crosswind"] = {"score": crosswind_score, "value": cross, "unit": "kt"}
            score += crosswind_score
        
    # Gust factors (max 40 points)
    if wind_gust > 0:
        gust_diff_val = wind_gust - wind_speed
        gust_diff_score = min(20, (gust_diff_val / 10) * 20)  # 10kt differential = 20 points
        if gust_diff_score > 0:
            contributors["gust_differential"] = {"score": gust_diff_score, "value": gust_diff_val, "unit": "kt"}
            score += gust_diff_score
        
        if not gust_is_head:
            gust_tailwind_score = min(10, (gust_head / 10) * 10)  # 10kt gust tailwind = 10 points
            if gust_tailwind_score > 0:
                contributors["gust_tailwind"] = {"score": gust_tailwind_score, "value": gust_head, "unit": "kt"}
                score += gust_tailwind_score
        if gust_cross > 0:
            gust_crosswind_score = min(10, (gust_cross / 20) * 10)  # 20kt gust crosswind = 10 points
            if gust_crosswind_score > 0:
                contributors["gust_crosswind"] = {"score": gust_crosswind_score, "value": gust_cross, "unit": "kt"}
                score += gust_crosswind_score
            
    # Density altitude factor (max 30 points)
    if da_diff > 0:
        da_score = min(30, (da_diff / 2000) * 30)  # 2000ft above field = 30 points
        if da_score > 0:
            contributors["density_altitude_diff"] = {"score": da_score, "value": da_diff, "unit": "ft"}
            score += da_score
        
    # Time of day factors (max 30 points)
    if lat is not None and lon is not None and rwy_heading is not None:
        time_factors = calculate_time_risk_factor(datetime.utcnow(), lat, lon, rwy_heading)
        if time_factors["time_risk_points"] > 0:
            contributors["time_of_day"] = {"score": time_factors["time_risk_points"], "value": time_factors["time_period"], "unit": "condition"}
            score += time_factors["time_risk_points"]
        
    # Weather phenomena (can push score above 100)
    weather = metar_data.get("weather", [])
    ceiling = metar_data.get("ceiling")
    visibility = metar_data.get("visibility")
    
    # Thunderstorm handling (automatic EXTREME)
    if any("TS" in weather_condition for weather_condition in weather):
        contributors["thunderstorm"] = {"score": 100, "value": True, "unit": "boolean"}
        score = 100  # Active thunderstorm = automatic EXTREME
        
    # Lightning adds significant risk
    if any("LTG" in weather_condition for weather_condition in weather):
        contributors["lightning"] = {"score": 25, "value": True, "unit": "boolean"}
        score += 25  # Lightning presence increases risk
        
    # Ceiling factors (if not already EXTREME)
    if score < 100 and ceiling is not None:
        ceiling_score = 0
        if ceiling < 500:
            ceiling_score = 40
        elif ceiling < 1000:
            ceiling_score = 30
        elif ceiling < 2000:
            ceiling_score = 20
        elif ceiling < 3000:
            ceiling_score = 10
        if ceiling_score > 0:
            contributors["low_ceiling"] = {"score": ceiling_score, "value": ceiling, "unit": "ft AGL"}
            score += ceiling_score
            
    # Visibility factors (if not already EXTREME)
    if score < 100 and visibility is not None:
        visibility_score = 0
        if visibility < 1:
            visibility_score = 40
        elif visibility < 2:
            visibility_score = 30
        elif visibility < 3:
            visibility_score = 20
        elif visibility < 5:
            visibility_score = 10
        if visibility_score > 0:
            contributors["low_visibility"] = {"score": visibility_score, "value": visibility, "unit": "SM"}
            score += visibility_score
            
    # Other significant weather (if not already EXTREME)
    if score < 100:
        if any("GR" in weather_condition for weather_condition in weather):  # Hail
            contributors["hail"] = {"score": 40, "value": True, "unit": "boolean"}
            score += 40
        if any("FC" in weather_condition for weather_condition in weather):  # Funnel cloud
            contributors["funnel_cloud"] = {"score": 100, "value": True, "unit": "boolean"}
            score = 100  # Automatic EXTREME
        if any("FZ" in weather_condition for weather_condition in weather):  # Freezing precip
            contributors["freezing_precipitation"] = {"score": 30, "value": True, "unit": "boolean"}
            score += 30
        if any("+" in weather_condition for weather_condition in weather):   # Heavy precip
            contributors["heavy_precipitation"] = {"score": 20, "value": True, "unit": "boolean"}
            score += 20
        
    return round(min(100, score)), contributors

def get_rri_category(rri):
    if rri <= 25:
        return "LOW"
    elif rri <= 50:
        return "MODERATE"
    elif rri <= 75:
        return "HIGH"
    else:
        return "EXTREME"

def get_status_from_rri(rri):
    if rri >= 76:  # EXTREME risk
        return "NO-GO"
    elif rri > 50:  # HIGH risk
        return "CAUTION"
    else:
        return "GOOD" 