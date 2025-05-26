"""
Time-Based Risk Factors

This module calculates how sun position and time of day affect runway safety.
The main things it tracks are night operations risk, twilight conditions, and
sun glare that can blind pilots during takeoff or landing.

It does the heavy solar math to figure out exactly where the sun is relative
to your runway heading, then assigns risk points based on how much glare
you might encounter. Night and twilight operations also get additional risk
since visibility and depth perception are reduced.
"""

from datetime import datetime, timedelta
import math
from typing import Tuple

def calculate_sun_position(lat: float, lon: float, date: datetime) -> Tuple[float, float]:
    day_of_year = date.timetuple().tm_yday
    
    hour = date.hour + date.minute / 60.0 + date.second / 3600.0
    
    gamma = 2 * math.pi * (day_of_year - 1) / 365
    eqtime = 229.18 * (0.000075 + 0.001868 * math.cos(gamma) - 0.032077 * math.sin(gamma) 
             - 0.014615 * math.cos(2 * gamma) - 0.040849 * math.sin(2 * gamma))
    
    decl = 0.006918 - 0.399912 * math.cos(gamma) + 0.070257 * math.sin(gamma) \
           - 0.006758 * math.cos(2 * gamma) + 0.000907 * math.sin(2 * gamma) \
           - 0.002697 * math.cos(3 * gamma) + 0.00148 * math.sin(3 * gamma)
    
    time_offset = eqtime + 4 * lon
    tst = hour * 60 + time_offset
    solar_time = tst / 60
    
    hour_angle = (solar_time - 12) * 15
    hour_angle_rad = math.radians(hour_angle)
    lat_rad = math.radians(lat)
    decl_rad = decl
    
    zenith_angle = math.acos(math.sin(lat_rad) * math.sin(decl_rad) + 
                            math.cos(lat_rad) * math.cos(decl_rad) * math.cos(hour_angle_rad))
    azimuth = math.acos(((math.sin(lat_rad) * math.cos(zenith_angle)) - 
                        math.sin(decl_rad)) / (math.cos(lat_rad) * math.sin(zenith_angle)))
    
    if hour_angle > 0:
        azimuth = 2 * math.pi - azimuth
        
    return math.degrees(zenith_angle), math.degrees(azimuth)

def get_time_period(date: datetime, lat: float, lon: float) -> str:
    zenith, _ = calculate_sun_position(lat, lon, date)
    
    if zenith < 90:
        if zenith > 80:
            return "TWILIGHT"
        return "DAY"
    else:
        return "NIGHT"

def calculate_time_risk_factor(date: datetime, lat: float, lon: float, rwy_heading: float) -> dict:
    zenith, azimuth = calculate_sun_position(lat, lon, date)
    time_period = get_time_period(date, lat, lon)
    
    risk_points = 0
    risk_reasons = []
    
    if time_period == "NIGHT":
        risk_points += 20
        risk_reasons.append("Night operations")
    
    elif time_period == "TWILIGHT":
        risk_points += 15
        risk_reasons.append("Twilight conditions - reduced visibility and depth perception")
    
    if zenith < 90:
        rwy_azimuth = (90 - rwy_heading) % 360
        
        angle_diff = min((rwy_azimuth - azimuth) % 360, (azimuth - rwy_azimuth) % 360)
        
        if angle_diff <= 15 and zenith <= 20:
            risk_points += 25
            risk_reasons.append("Critical sun glare - sun directly ahead/behind")
        elif angle_diff <= 30 and zenith <= 30:
            risk_points += 15
            risk_reasons.append("Moderate sun glare")
    
    return {
        "time_risk_points": min(risk_points, 30),
        "time_period": time_period,
        "risk_reasons": risk_reasons,
        "sun_position": {
            "zenith": zenith,
            "azimuth": azimuth
        }
    } 