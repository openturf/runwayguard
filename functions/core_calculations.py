"""
RunwayGuard Core Risk Calculations

This module handles all the heavy lifting for runway risk assessment. It takes weather data,
runway conditions, and aircraft performance factors to calculate a risk score from 0-100.

The main function you'll use is calculate_advanced_rri() which gives you the full analysis,
or calculate_rri() for the basic version. Everything else here supports those calculations.

Key components:
- Wind analysis (headwind/tailwind/crosswind/gusts)
- Density altitude effects on performance  
- Weather hazards (thunderstorms, icing, low visibility)
- Advanced atmospheric modeling for turbulence and thermal effects
- Risk amplification when multiple factors combine

The risk score maps to: 0-25 LOW, 26-50 MODERATE, 51-75 HIGH, 76-100 EXTREME
"""

import math
import numpy as np
from datetime import datetime, timedelta
from typing import Dict, List, Tuple, Optional, Any
from .time_factors import calculate_time_risk_factor

class AdvancedAtmosphericModel:
    """Advanced atmospheric condition modeling for enhanced risk assessment"""
    
    @staticmethod
    def calculate_thermal_gradient_risk(temp_c: float, dewpoint_c: Optional[float], time_of_day: str) -> Tuple[int, List[str]]:
        score = 0
        reasons = []
        
        if dewpoint_c is not None:
            dewpoint_spread = temp_c - dewpoint_c
            
            if temp_c > 25 and dewpoint_spread > 10 and time_of_day in ["afternoon", "midday"]:
                score += 15
                reasons.append(f"Strong thermal activity expected (temp {temp_c}°C, spread {dewpoint_spread}°C)")
            
            if temp_c < 5 and dewpoint_spread < 3 and time_of_day in ["early_morning", "late_evening"]:
                score += 10
                reasons.append("Temperature inversion conditions may cause low-level turbulence")
        
        return min(score, 20), reasons
    
    @staticmethod
    def calculate_stability_index(temp_c: float, dewpoint_c: Optional[float], wind_speed: int) -> Tuple[int, List[str]]:
        score = 0
        reasons = []
        
        if dewpoint_c is not None:
            dewpoint_spread = temp_c - dewpoint_c
            
            if temp_c > 20 and dewpoint_spread < 5:
                convective_risk = min(25, (30 - temp_c + (5 - dewpoint_spread)) * 2)
                if convective_risk > 0:
                    score += convective_risk
                    reasons.append("High convective potential - thunderstorm development possible")
            
            if wind_speed > 20 and dewpoint_spread > 15:
                score += 10
                reasons.append("Mechanical turbulence likely due to strong winds and dry conditions")
        
        return min(score, 30), reasons

class PerformanceRiskAnalyzer:
    """Advanced aircraft performance risk analysis"""
    
    @staticmethod
    def calculate_runway_performance_risk(runway_length: Optional[int], da_diff: int, 
                                        contamination: str = "dry") -> Tuple[int, List[str]]:
        score = 0
        reasons = []
        
        if runway_length is None:
            if da_diff > 2000:
                score = 15
                reasons.append("Runway length unknown - significant performance degradation likely at high density altitude")
            elif da_diff > 1000:
                score = 10
                reasons.append("Runway length unknown - monitor performance degradation at elevated density altitude")
            elif da_diff > 500:
                score = 5
                reasons.append("Runway length unknown - verify runway adequacy for current density altitude")
            return score, reasons
        
        contamination_multipliers = {
            "dry": 1.0,
            "wet": 1.15,
            "standing_water": 1.4,
            "slush": 1.6,
            "snow": 1.8,
            "ice": 2.2
        }
        
        effective_runway = runway_length / contamination_multipliers.get(contamination, 1.0)
        
        if da_diff > 1000:
            performance_degradation = 1 + (da_diff / 10000)
            effective_runway /= performance_degradation
            
            if da_diff > 3000:
                score += 20
                reasons.append(f"Significant performance degradation at {da_diff}ft density altitude")
            elif da_diff > 2000:
                score += 15
                reasons.append(f"Notable performance degradation at {da_diff}ft density altitude")
        
        if effective_runway < 2000:
            score += 30
            reasons.append(f"Runway performance marginal: {int(effective_runway)}ft effective length")
        elif effective_runway < 2500:
            score += 20
            reasons.append(f"Runway performance concerning: {int(effective_runway)}ft effective length")
        elif effective_runway < 3000:
            score += 10
            reasons.append(f"Runway performance adequate but tight: {int(effective_runway)}ft effective length")
        
        return min(score, 35), reasons
    
    @staticmethod
    def calculate_weight_performance_factor(da_diff: int, temp_c: float) -> float:
        isa_temp = 15 - (2 * (da_diff / 1000))
        temp_deviation = temp_c - isa_temp
        
        degradation_factor = 1 + (da_diff * 0.0001) + (max(0, temp_deviation) * 0.005)
        return degradation_factor

class WeatherRiskAnalyzer:
    """Advanced weather condition risk analysis"""
    
    @staticmethod
    def calculate_precipitation_intensity_risk(weather: List[str]) -> Tuple[int, List[str]]:
        score = 0
        reasons = []
        
        heavy_precip_types = {
            "+RA": ("Heavy rain", 20),
            "+SN": ("Heavy snow", 25),
            "+TSRA": ("Heavy thunderstorm rain", 35),
            "+FZRA": ("Heavy freezing rain", 40),
            "+PL": ("Heavy ice pellets", 30),
            "+GR": ("Heavy hail", 50)
        }
        
        moderate_precip_types = {
            "RA": ("Rain", 8),
            "SN": ("Snow", 12),
            "TSRA": ("Thunderstorm rain", 18),
            "FZRA": ("Freezing rain", 25),
            "PL": ("Ice pellets", 15)
        }
        
        light_precip_types = {
            "-RA": ("Light rain", 3),
            "-SN": ("Light snow", 5),
            "-FZRA": ("Light freezing rain", 15)
        }
        
        for condition in weather:
            for precip_code, (description, points) in heavy_precip_types.items():
                if precip_code in condition:
                    score += points
                    reasons.append(f"{description} significantly impacts visibility and runway conditions")
                    break
            else:
                for precip_code, (description, points) in moderate_precip_types.items():
                    if precip_code in condition:
                        score += points
                        reasons.append(f"{description} affects visibility and runway conditions")
                        break
                else:
                    for precip_code, (description, points) in light_precip_types.items():
                        if precip_code in condition:
                            score += points
                            reasons.append(f"{description} may affect runway conditions")
                            break
        
        return min(score, 50), reasons
    
    @staticmethod
    def calculate_turbulence_risk(wind_speed: int, wind_gust: int, terrain_factor: float = 1.0) -> Tuple[int, List[str]]:
        score = 0
        reasons = []
        
        if wind_gust > 0:
            gust_factor = wind_gust / max(wind_speed, 1)
            if gust_factor > 2.0:
                score += 20
                reasons.append(f"Severe gustiness: {wind_gust}kt gusts vs {wind_speed}kt steady")
            elif gust_factor > 1.5:
                score += 15
                reasons.append(f"Significant gustiness: {wind_gust}kt gusts vs {wind_speed}kt steady")
            elif gust_factor > 1.3:
                score += 10
                reasons.append(f"Moderate gustiness: {wind_gust}kt gusts vs {wind_speed}kt steady")
        
        if wind_speed > 25:
            score += 15
            reasons.append(f"Strong winds ({wind_speed}kt) likely causing turbulence")
        elif wind_speed > 20:
            score += 10
            reasons.append(f"Fresh winds ({wind_speed}kt) may cause turbulence")
        
        if terrain_factor > 1.0:
            terrain_score = int((terrain_factor - 1.0) * 20)
            score += terrain_score
            reasons.append("Terrain features may enhance turbulence")
        
        return min(score, 25), reasons

class RiskCorrelationEngine:
    """Advanced risk correlation and amplification analysis"""
    
    @staticmethod
    def calculate_risk_amplification(contributors: Dict[str, Any]) -> Tuple[int, List[str]]:
        amplification_score = 0
        reasons = []
        
        wind_risks = ["tailwind", "crosswind", "gust_differential", "gust_tailwind", "gust_crosswind"]
        weather_risks = ["thunderstorm", "lightning", "low_ceiling", "low_visibility", "icing_conditions"]
        performance_risks = ["density_altitude_diff", "temperature_performance"]
        
        wind_score = sum(contributors.get(risk, {}).get("score", 0) for risk in wind_risks)
        weather_score = sum(contributors.get(risk, {}).get("score", 0) for risk in weather_risks)
        performance_score = sum(contributors.get(risk, {}).get("score", 0) for risk in performance_risks)
        
        active_domains = sum([
            wind_score > 20,
            weather_score > 20,
            performance_score > 15
        ])
        
        if active_domains >= 2:
            amplification_score = min(15, active_domains * 5)
            reasons.append(f"Multiple risk domains active: amplified concern")
        
        if contributors.get("icing_conditions") and contributors.get("low_ceiling"):
            amplification_score += 10
            reasons.append("Icing conditions with low ceiling: instrument approach risk")
        
        if contributors.get("thunderstorm") and wind_score > 15:
            amplification_score += 15
            reasons.append("Thunderstorm with significant wind factors: extreme turbulence risk")
        
        if contributors.get("density_altitude_diff", {}).get("score", 0) > 20 and wind_score > 15:
            amplification_score += 10
            reasons.append("High density altitude with challenging winds: performance margins reduced")
        
        return min(amplification_score, 25), reasons

class PredictiveRiskModel:
    """Predictive modeling for evolving conditions"""
    
    @staticmethod
    def calculate_trend_risk(current_conditions: Dict, historical_trend: Optional[Dict] = None) -> Tuple[int, List[str]]:
        score = 0
        reasons = []
        
        if not historical_trend:
            return 0, []
        
        pressure_trend = historical_trend.get("pressure_trend")
        if pressure_trend:
            if pressure_trend < -0.1:
                score += 15
                reasons.append("Rapid pressure drop indicates approaching weather system")
            elif pressure_trend < -0.05:
                score += 8
                reasons.append("Pressure dropping - weather deterioration possible")
        
        temp_trend = historical_trend.get("temp_trend")
        current_hour = datetime.utcnow().hour
        if temp_trend and current_hour in range(14, 18):
            if temp_trend > 3 and current_conditions.get("temp_c", 0) > 25:
                score += 10
                reasons.append("Rapid afternoon heating increases convective activity risk")
        
        return min(score, 20), reasons

def pressure_alt(field_elev_ft, altim_in_hg):
    return field_elev_ft + (29.92 - altim_in_hg) * 1000

def density_alt(field_elev_ft, temp_c, altim_in_hg):
    if not isinstance(field_elev_ft, (int, float)) or not isinstance(temp_c, (int, float)) or not isinstance(altim_in_hg, (int, float)):
        print(f"[density_alt] Invalid inputs: elev={field_elev_ft}, temp={temp_c}, altim={altim_in_hg}")
        return 0
        
    if temp_c < -60 or temp_c > 50:
        print(f"[density_alt] Temperature out of range: {temp_c}°C")
        return 0
        
    pa = pressure_alt(field_elev_ft, altim_in_hg)
    isa_temp = 15 - 2 * (field_elev_ft / 1000)
    da = int(pa + 120 * (temp_c - isa_temp))
    
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
    score = 0
    reasons = []
    
    weather = metar_data.get("weather", [])
    cloud_layers = metar_data.get("cloud_layers", [])
    dewpoint_c = metar_data.get("dewpoint_c")
    
    if any("FZ" in condition for condition in weather):
        score += 30
        reasons.append("Freezing precipitation reported")
    
    if -10 <= temp_c <= 2:
        if any(layer.get("type") in ["BKN", "OVC"] for layer in cloud_layers):
            if 0 <= temp_c <= 2:
                score += 25
                reasons.append("Prime icing conditions (0°C to +2°C with clouds)")
            else:
                score += 20
                reasons.append("Icing conditions possible (-10°C to 0°C with clouds)")
    
    if dewpoint_c is not None and temp_c is not None:
        dewpoint_spread = temp_c - dewpoint_c
        if dewpoint_spread <= 3 and -5 <= temp_c <= 5:
            if any(layer.get("type") in ["BKN", "OVC"] for layer in cloud_layers):
                score += 15
                reasons.append(f"High humidity (spread {dewpoint_spread}°C) with clouds in icing range")
    
    if any("IC" in condition or "PL" in condition for condition in weather):
        score += 20
        reasons.append("Ice pellets reported")
    
    return min(score, 30), reasons

def calculate_temperature_performance_risk(temp_c, da_diff):
    score = 0
    reasons = []
    
    if temp_c > 35:
        score += 15
        reasons.append(f"High temperature ({temp_c}°C) reduces engine performance")
    elif temp_c > 30:
        score += 10
        reasons.append(f"Elevated temperature ({temp_c}°C) affects performance")
    
    if temp_c < -20:
        score += 15
        reasons.append(f"Very cold temperature ({temp_c}°C) affects systems/performance")
    elif temp_c < -10:
        score += 10
        reasons.append(f"Cold temperature ({temp_c}°C) may affect systems")
    
    if temp_c > 30 and da_diff > 1000:
        score += 10
        reasons.append("High temperature combined with elevated density altitude")
    
    return min(score, 25), reasons

def calculate_wind_shear_risk(metar_data, weather_data=None):
    score = 0
    reasons = []
    
    weather = metar_data.get("weather", [])
    
    if any("TS" in condition for condition in weather):
        score += 25
        reasons.append("Thunderstorm wind shear risk")
    
    if any("SH" in condition for condition in weather):
        score += 15
        reasons.append("Shower activity indicates possible wind shear")
    
    return min(score, 25), reasons

def parse_enhanced_weather_conditions(metar_data):
    score = 0
    reasons = []
    
    weather = metar_data.get("weather", [])
    
    if any("FG" in condition for condition in weather):
        score += 15
        reasons.append("Fog conditions reduce visibility")
    
    if any("BR" in condition or "HZ" in condition for condition in weather):
        score += 5
        reasons.append("Mist or haze reducing visibility")
    
    if any("DU" in condition or "SA" in condition or "DS" in condition for condition in weather):
        score += 20
        reasons.append("Dust or sand affecting visibility")
    
    if any("VA" in condition for condition in weather):
        score += 100
        reasons.append("Volcanic ash - NO-GO condition")
    
    if any("SQ" in condition for condition in weather):
        score += 30
        reasons.append("Squall line activity")
    
    return score, reasons

def parse_notam_risks(notam_data, runway_id):
    if not notam_data:
        return 0, []
    
    score = 0
    reasons = []
    
    notam_text = notam_data.get("raw_text", "").upper() if isinstance(notam_data, dict) else str(notam_data).upper()
    
    if any(html_indicator in notam_text for html_indicator in ["<!DOCTYPE", "<HTML>", "INVALID QUERY", "ERROR", "<TITLE>"]):
        return 0, []
    
    if len(notam_text.strip()) < 50 or "NOTAM" not in notam_text:
        return 0, []
    
    if any(keyword in notam_text for keyword in ["SNOW", "ICE", "SLUSH", "WET", "CONTAMINATED"]):
        score += 20
        reasons.append("Runway contamination reported in NOTAMs")
    
    if any(keyword in notam_text for keyword in ["ILS", "PAPI", "VASI", "LIGHTS", "BEACON"]):
        score += 10
        reasons.append("Navigation/lighting equipment outage")
    
    if any(keyword in notam_text for keyword in ["CONSTRUCTION", "OBSTACLE", "WORK IN PROGRESS"]):
        score += 15
        reasons.append("Construction or obstacles reported")
    
    return min(score, 25), reasons

def calculate_advanced_rri(head, cross, gust_head, gust_cross, wind_speed, wind_gust, is_head, gust_is_head, 
                          da_diff, metar_data, lat=None, lon=None, rwy_heading=None, notam_data=None,
                          runway_length=None, airport_elevation=None, terrain_factor=1.0, 
                          historical_trend=None, aircraft_category="light"):
    """
    Advanced Runway Risk Index calculation with enhanced modeling
    
    This is the new advanced version - the old calculate_rri function is maintained for backward compatibility
    """
    score = 0
    contributors = {}
    
    temp_c = metar_data.get("temp_c", 15)
    dewpoint_c = metar_data.get("dewpoint_c")
    weather = metar_data.get("weather", [])
    ceiling = metar_data.get("ceiling")
    visibility = metar_data.get("visibility")
    
    current_hour = datetime.utcnow().hour
    if 6 <= current_hour < 10:
        time_of_day = "early_morning"
    elif 10 <= current_hour < 14:
        time_of_day = "midday"
    elif 14 <= current_hour < 18:
        time_of_day = "afternoon"
    elif 18 <= current_hour < 22:
        time_of_day = "evening"
    else:
        time_of_day = "late_evening"
    
    atm_model = AdvancedAtmosphericModel()
    perf_analyzer = PerformanceRiskAnalyzer()
    weather_analyzer = WeatherRiskAnalyzer()
    correlation_engine = RiskCorrelationEngine()
    predictive_model = PredictiveRiskModel()
    
    if not is_head:
        tailwind_score = min(30, head * 6)
        if tailwind_score > 0:
            contributors["tailwind"] = {"score": tailwind_score, "value": head, "unit": "kt"}
            score += tailwind_score
    if cross > 0:
        crosswind_score = min(30, (cross / 15) * 30)
        if crosswind_score > 0:
            contributors["crosswind"] = {"score": crosswind_score, "value": cross, "unit": "kt"}
            score += crosswind_score
        
    if wind_gust > 0:
        gust_diff_val = wind_gust - wind_speed
        gust_diff_score = min(20, (gust_diff_val / 10) * 20)
        if gust_diff_score > 0:
            contributors["gust_differential"] = {"score": gust_diff_score, "value": gust_diff_val, "unit": "kt"}
            score += gust_diff_score
        
        if not gust_is_head:
            gust_tailwind_score = min(10, (gust_head / 10) * 10)
            if gust_tailwind_score > 0:
                contributors["gust_tailwind"] = {"score": gust_tailwind_score, "value": gust_head, "unit": "kt"}
                score += gust_tailwind_score
        if gust_cross > 0:
            gust_crosswind_score = min(10, (gust_cross / 20) * 10)
            if gust_crosswind_score > 0:
                contributors["gust_crosswind"] = {"score": gust_crosswind_score, "value": gust_cross, "unit": "kt"}
                score += gust_crosswind_score
            
    if da_diff > 0:
        da_score = min(30, (da_diff / 2000) * 30)
        if da_score > 0:
            contributors["density_altitude_diff"] = {"score": da_score, "value": da_diff, "unit": "ft"}
            score += da_score
    
    thermal_score, thermal_reasons = atm_model.calculate_thermal_gradient_risk(temp_c, dewpoint_c, time_of_day)
    if thermal_score > 0:
        contributors["thermal_gradient"] = {"score": thermal_score, "value": thermal_reasons, "unit": "conditions"}
        score += thermal_score
    
    stability_score, stability_reasons = atm_model.calculate_stability_index(temp_c, dewpoint_c, wind_speed)
    if stability_score > 0:
        contributors["atmospheric_stability"] = {"score": stability_score, "value": stability_reasons, "unit": "conditions"}
        score += stability_score
    
    contamination = "dry"
    if any("SN" in condition for condition in weather):
        contamination = "snow"
    elif any("FZRA" in condition for condition in weather):
        contamination = "ice"
    elif any("RA" in condition for condition in weather):
        contamination = "wet"
    elif notam_data and isinstance(notam_data, dict):
        notam_text = notam_data.get("raw_text", "").upper()
        if any(keyword in notam_text for keyword in ["ICE", "SLUSH"]):
            contamination = "ice"
        elif any(keyword in notam_text for keyword in ["SNOW"]):
            contamination = "snow"
        elif any(keyword in notam_text for keyword in ["WET", "STANDING WATER"]):
            contamination = "wet"
    
    perf_score, perf_reasons = perf_analyzer.calculate_runway_performance_risk(runway_length, da_diff, contamination)
    if perf_score > 0:
        contributors["runway_performance"] = {"score": perf_score, "value": perf_reasons, "unit": "conditions"}
        score += perf_score
    
    precip_score, precip_reasons = weather_analyzer.calculate_precipitation_intensity_risk(weather)
    if precip_score > 0:
        contributors["precipitation_intensity"] = {"score": precip_score, "value": precip_reasons, "unit": "conditions"}
        score += precip_score
    
    turb_score, turb_reasons = weather_analyzer.calculate_turbulence_risk(wind_speed, wind_gust, terrain_factor)
    if turb_score > 0:
        contributors["turbulence_risk"] = {"score": turb_score, "value": turb_reasons, "unit": "conditions"}
        score += turb_score
    
    if historical_trend:
        trend_score, trend_reasons = predictive_model.calculate_trend_risk(metar_data, historical_trend)
        if trend_score > 0:
            contributors["trend_analysis"] = {"score": trend_score, "value": trend_reasons, "unit": "conditions"}
            score += trend_score
    
    if lat is not None and lon is not None and rwy_heading is not None:
        time_factors = calculate_time_risk_factor(datetime.utcnow(), lat, lon, rwy_heading)
        if time_factors["time_risk_points"] > 0:
            contributors["time_of_day"] = {"score": time_factors["time_risk_points"], "value": time_factors["time_period"], "unit": "condition"}
            score += time_factors["time_risk_points"]
    
    icing_score, icing_reasons = calculate_icing_risk(temp_c, metar_data)
    if icing_score > 0:
        contributors["icing_conditions"] = {"score": icing_score, "value": icing_reasons, "unit": "conditions"}
        score += icing_score
    
    temp_perf_score, temp_perf_reasons = calculate_temperature_performance_risk(temp_c, da_diff)
    if temp_perf_score > 0:
        contributors["temperature_performance"] = {"score": temp_perf_score, "value": temp_perf_reasons, "unit": "conditions"}
        score += temp_perf_score
    
    ws_score, ws_reasons = calculate_wind_shear_risk(metar_data)
    if ws_score > 0:
        contributors["wind_shear_risk"] = {"score": ws_score, "value": ws_reasons, "unit": "conditions"}
        score += ws_score
    
    enhanced_wx_score, enhanced_wx_reasons = parse_enhanced_weather_conditions(metar_data)
    if enhanced_wx_score > 0:
        if enhanced_wx_score >= 100:
            contributors["volcanic_ash"] = {"score": enhanced_wx_score, "value": enhanced_wx_reasons, "unit": "conditions"}
            score = 100
        else:
            contributors["enhanced_weather"] = {"score": enhanced_wx_score, "value": enhanced_wx_reasons, "unit": "conditions"}
            score += enhanced_wx_score
    
    notam_score, notam_reasons = parse_notam_risks(notam_data, rwy_heading)
    if notam_score > 0:
        contributors["notam_risks"] = {"score": notam_score, "value": notam_reasons, "unit": "conditions"}
        score += notam_score
    
    if any("TS" in weather_condition for weather_condition in weather):
        contributors["thunderstorm"] = {"score": 100, "value": True, "unit": "boolean"}
        score = 100
        
    if any("LTG" in weather_condition for weather_condition in weather):
        contributors["lightning"] = {"score": 25, "value": True, "unit": "boolean"}
        score += 25
        
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
    
    if score < 100:
        if any("GR" in weather_condition for weather_condition in weather):
            contributors["hail"] = {"score": 40, "value": True, "unit": "boolean"}
            score += 40
        if any("FC" in weather_condition for weather_condition in weather):
            contributors["funnel_cloud"] = {"score": 100, "value": True, "unit": "boolean"}
            score = 100
        if any("FZ" in weather_condition for weather_condition in weather):
            contributors["freezing_precipitation"] = {"score": 30, "value": True, "unit": "boolean"}
            score += 30
        if any("+" in weather_condition for weather_condition in weather):
            contributors["heavy_precipitation"] = {"score": 20, "value": True, "unit": "boolean"}
            score += 20
    
    amplification_score, amplification_reasons = correlation_engine.calculate_risk_amplification(contributors)
    if amplification_score > 0:
        contributors["risk_amplification"] = {"score": amplification_score, "value": amplification_reasons, "unit": "conditions"}
        score += amplification_score
    
    return round(min(100, score)), contributors

def calculate_rri(head, cross, gust_head, gust_cross, wind_speed, wind_gust, is_head, gust_is_head, da_diff, metar_data, lat=None, lon=None, rwy_heading=None, notam_data=None):
    """
    Original RRI calculation function - maintained for backward compatibility
    For new implementations, use calculate_advanced_rri() for enhanced capabilities
    """
    score = 0
    contributors = {}
    
    temp_c = metar_data.get("temp_c", 15)
    
    if not is_head:
        tailwind_score = min(30, head * 6)
        if tailwind_score > 0:
            contributors["tailwind"] = {"score": tailwind_score, "value": head, "unit": "kt"}
            score += tailwind_score
    if cross > 0:
        crosswind_score = min(30, (cross / 15) * 30)
        if crosswind_score > 0:
            contributors["crosswind"] = {"score": crosswind_score, "value": cross, "unit": "kt"}
            score += crosswind_score
        
    if wind_gust > 0:
        gust_diff_val = wind_gust - wind_speed
        gust_diff_score = min(20, (gust_diff_val / 10) * 20)
        if gust_diff_score > 0:
            contributors["gust_differential"] = {"score": gust_diff_score, "value": gust_diff_val, "unit": "kt"}
            score += gust_diff_score
        
        if not gust_is_head:
            gust_tailwind_score = min(10, (gust_head / 10) * 10)
            if gust_tailwind_score > 0:
                contributors["gust_tailwind"] = {"score": gust_tailwind_score, "value": gust_head, "unit": "kt"}
                score += gust_tailwind_score
        if gust_cross > 0:
            gust_crosswind_score = min(10, (gust_cross / 20) * 10)
            if gust_crosswind_score > 0:
                contributors["gust_crosswind"] = {"score": gust_crosswind_score, "value": gust_cross, "unit": "kt"}
                score += gust_crosswind_score
            
    if da_diff > 0:
        da_score = min(30, (da_diff / 2000) * 30)
        if da_score > 0:
            contributors["density_altitude_diff"] = {"score": da_score, "value": da_diff, "unit": "ft"}
            score += da_score
        
    if lat is not None and lon is not None and rwy_heading is not None:
        time_factors = calculate_time_risk_factor(datetime.utcnow(), lat, lon, rwy_heading)
        if time_factors["time_risk_points"] > 0:
            contributors["time_of_day"] = {"score": time_factors["time_risk_points"], "value": time_factors["time_period"], "unit": "condition"}
            score += time_factors["time_risk_points"]
    
    icing_score, icing_reasons = calculate_icing_risk(temp_c, metar_data)
    if icing_score > 0:
        contributors["icing_conditions"] = {"score": icing_score, "value": icing_reasons, "unit": "conditions"}
        score += icing_score
    
    temp_perf_score, temp_perf_reasons = calculate_temperature_performance_risk(temp_c, da_diff)
    if temp_perf_score > 0:
        contributors["temperature_performance"] = {"score": temp_perf_score, "value": temp_perf_reasons, "unit": "conditions"}
        score += temp_perf_score
    
    ws_score, ws_reasons = calculate_wind_shear_risk(metar_data)
    if ws_score > 0:
        contributors["wind_shear_risk"] = {"score": ws_score, "value": ws_reasons, "unit": "conditions"}
        score += ws_score
    
    enhanced_wx_score, enhanced_wx_reasons = parse_enhanced_weather_conditions(metar_data)
    if enhanced_wx_score > 0:
        if enhanced_wx_score >= 100:
            contributors["volcanic_ash"] = {"score": enhanced_wx_score, "value": enhanced_wx_reasons, "unit": "conditions"}
            score = 100
        else:
            contributors["enhanced_weather"] = {"score": enhanced_wx_score, "value": enhanced_wx_reasons, "unit": "conditions"}
            score += enhanced_wx_score
        
    weather = metar_data.get("weather", [])
    ceiling = metar_data.get("ceiling")
    visibility = metar_data.get("visibility")
    
    if any("TS" in weather_condition for weather_condition in weather):
        contributors["thunderstorm"] = {"score": 100, "value": True, "unit": "boolean"}
        score = 100
        
    if any("LTG" in weather_condition for weather_condition in weather):
        contributors["lightning"] = {"score": 25, "value": True, "unit": "boolean"}
        score += 25
        
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
            
    if score < 100:
        if any("GR" in weather_condition for weather_condition in weather):
            contributors["hail"] = {"score": 40, "value": True, "unit": "boolean"}
            score += 40
        if any("FC" in weather_condition for weather_condition in weather):
            contributors["funnel_cloud"] = {"score": 100, "value": True, "unit": "boolean"}
            score = 100
        if any("FZ" in weather_condition for weather_condition in weather):
            contributors["freezing_precipitation"] = {"score": 30, "value": True, "unit": "boolean"}
            score += 30
        if any("+" in weather_condition for weather_condition in weather):
            contributors["heavy_precipitation"] = {"score": 20, "value": True, "unit": "boolean"}
            score += 20
        
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
    if rri >= 76:
        return "NO-GO"
    elif rri > 50:
        return "CAUTION"
    else:
        return "GOOD" 