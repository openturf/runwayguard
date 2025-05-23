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

def calculate_icing_risk(temp_c, metar_data):
    """Calculate icing risk based on temperature and conditions"""
    score = 0
    reasons = []
    
    weather = metar_data.get("weather", [])
    cloud_layers = metar_data.get("cloud_layers", [])
    dewpoint_c = metar_data.get("dewpoint_c")
    
    # Known icing conditions
    if any("FZ" in condition for condition in weather):
        score += 30
        reasons.append("Freezing precipitation reported")
    
    # Temperature range icing risk
    if -10 <= temp_c <= 2:
        if any(layer.get("type") in ["BKN", "OVC"] for layer in cloud_layers):
            if 0 <= temp_c <= 2:
                score += 25
                reasons.append("Prime icing conditions (0°C to +2°C with clouds)")
            else:
                score += 20
                reasons.append("Icing conditions possible (-10°C to 0°C with clouds)")
    
    # Enhanced icing risk with dewpoint spread
    if dewpoint_c is not None and temp_c is not None:
        dewpoint_spread = temp_c - dewpoint_c
        if dewpoint_spread <= 3 and -5 <= temp_c <= 5:
            if any(layer.get("type") in ["BKN", "OVC"] for layer in cloud_layers):
                score += 15
                reasons.append(f"High humidity (spread {dewpoint_spread}°C) with clouds in icing range")
    
    # Ice pellets or other icing indicators
    if any("IC" in condition or "PL" in condition for condition in weather):
        score += 20
        reasons.append("Ice pellets reported")
    
    return min(score, 30), reasons

def calculate_temperature_performance_risk(temp_c, da_diff):
    """Calculate risk from temperature extremes affecting performance"""
    score = 0
    reasons = []
    
    # Hot weather performance degradation
    if temp_c > 35:
        score += 15
        reasons.append(f"High temperature ({temp_c}°C) reduces engine performance")
    elif temp_c > 30:
        score += 10
        reasons.append(f"Elevated temperature ({temp_c}°C) affects performance")
    
    # Cold weather risks
    if temp_c < -20:
        score += 15
        reasons.append(f"Very cold temperature ({temp_c}°C) affects systems/performance")
    elif temp_c < -10:
        score += 10
        reasons.append(f"Cold temperature ({temp_c}°C) may affect systems")
    
    # Combined high DA and temperature
    if temp_c > 30 and da_diff > 1000:
        score += 10
        reasons.append("High temperature combined with elevated density altitude")
    
    return min(score, 25), reasons

def calculate_wind_shear_risk(metar_data, weather_data=None):
    """Calculate wind shear risk from weather conditions"""
    score = 0
    reasons = []
    
    weather = metar_data.get("weather", [])
    
    # Thunderstorm-related wind shear
    if any("TS" in condition for condition in weather):
        score += 25
        reasons.append("Thunderstorm wind shear risk")
    
    # Frontal activity indicators
    if any("SH" in condition for condition in weather):
        score += 15
        reasons.append("Shower activity indicates possible wind shear")
    
    # LLWS reports would be parsed from weather_data if available
    # This would require additional PIREP/AIRMET parsing
    
    return min(score, 25), reasons

def parse_enhanced_weather_conditions(metar_data):
    """Enhanced weather condition parsing for additional risks"""
    score = 0
    reasons = []
    
    weather = metar_data.get("weather", [])
    
    # Fog conditions
    if any("FG" in condition for condition in weather):
        score += 15
        reasons.append("Fog conditions reduce visibility")
    
    # Mist/haze
    if any("BR" in condition or "HZ" in condition for condition in weather):
        score += 5
        reasons.append("Mist or haze reducing visibility")
    
    # Dust/sand storms
    if any("DU" in condition or "SA" in condition or "DS" in condition for condition in weather):
        score += 20
        reasons.append("Dust or sand affecting visibility")
    
    # Volcanic ash
    if any("VA" in condition for condition in weather):
        score += 100  # Automatic extreme
        reasons.append("Volcanic ash - NO-GO condition")
    
    # Squall lines
    if any("SQ" in condition for condition in weather):
        score += 30
        reasons.append("Squall line activity")
    
    return score, reasons

def parse_notam_risks(notam_data, runway_id):
    """Parse NOTAMs for additional runway risks"""
    if not notam_data:
        return 0, []
    
    score = 0
    reasons = []
    
    # Get raw NOTAM text and validate it's not an error page
    notam_text = notam_data.get("raw_text", "").upper() if isinstance(notam_data, dict) else str(notam_data).upper()
    
    # Skip parsing if this looks like an HTML error page
    if any(html_indicator in notam_text for html_indicator in ["<!DOCTYPE", "<HTML>", "INVALID QUERY", "ERROR", "<TITLE>"]):
        return 0, []
    
    # Skip if no actual NOTAM content
    if len(notam_text.strip()) < 50 or "NOTAM" not in notam_text:
        return 0, []
    
    # Runway contamination
    if any(keyword in notam_text for keyword in ["SNOW", "ICE", "SLUSH", "WET", "CONTAMINATED"]):
        score += 20
        reasons.append("Runway contamination reported in NOTAMs")
    
    # Equipment outages
    if any(keyword in notam_text for keyword in ["ILS", "PAPI", "VASI", "LIGHTS", "BEACON"]):
        score += 10
        reasons.append("Navigation/lighting equipment outage")
    
    # Construction/obstacles
    if any(keyword in notam_text for keyword in ["CONSTRUCTION", "OBSTACLE", "WORK IN PROGRESS"]):
        score += 15
        reasons.append("Construction or obstacles reported")
    
    return min(score, 25), reasons

def calculate_rri(head, cross, gust_head, gust_cross, wind_speed, wind_gust, is_head, gust_is_head, da_diff, metar_data, lat=None, lon=None, rwy_heading=None, notam_data=None):
    score = 0
    contributors = {}
    
    # Get temperature for additional calculations
    temp_c = metar_data.get("temp_c", 15)
    
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
    
    # NEW: Icing risk assessment (max 30 points)
    icing_score, icing_reasons = calculate_icing_risk(temp_c, metar_data)
    if icing_score > 0:
        contributors["icing_conditions"] = {"score": icing_score, "value": icing_reasons, "unit": "conditions"}
        score += icing_score
    
    # NEW: Temperature performance risk (max 25 points)
    temp_perf_score, temp_perf_reasons = calculate_temperature_performance_risk(temp_c, da_diff)
    if temp_perf_score > 0:
        contributors["temperature_performance"] = {"score": temp_perf_score, "value": temp_perf_reasons, "unit": "conditions"}
        score += temp_perf_score
    
    # NEW: Wind shear risk (max 25 points)
    ws_score, ws_reasons = calculate_wind_shear_risk(metar_data)
    if ws_score > 0:
        contributors["wind_shear_risk"] = {"score": ws_score, "value": ws_reasons, "unit": "conditions"}
        score += ws_score
    
    # NEW: Enhanced weather conditions
    enhanced_wx_score, enhanced_wx_reasons = parse_enhanced_weather_conditions(metar_data)
    if enhanced_wx_score > 0:
        if enhanced_wx_score >= 100:
            contributors["volcanic_ash"] = {"score": enhanced_wx_score, "value": enhanced_wx_reasons, "unit": "conditions"}
            score = 100  # Automatic EXTREME
        else:
            contributors["enhanced_weather"] = {"score": enhanced_wx_score, "value": enhanced_wx_reasons, "unit": "conditions"}
            score += enhanced_wx_score
        
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
        
    # NEW: NOTAM risks (max 25 points)
    notam_score, notam_reasons = parse_notam_risks(notam_data, rwy_heading)
    if notam_score > 0:
        contributors["notam_risks"] = {"score": notam_score, "value": notam_reasons, "unit": "conditions"}
        score += notam_score
    
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