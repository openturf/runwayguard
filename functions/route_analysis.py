"""
Multi-Airport Route Analysis

This module handles comprehensive route-based risk assessment across multiple airports.
It evaluates weather conditions, runway risks, and provides strategic recommendations
for route planning, alternate selections, and fuel planning considerations.

Key features:
- Route-wide weather assessment and trends
- Comparative airport risk analysis
- Alternate airport recommendations
- En-route hazard identification
- Fuel planning considerations based on weather

The main function analyze_route() takes a list of airports and provides comprehensive
analysis for route planning and go/no-go decisions.
- @awade12 may 20th 2025
"""

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass

from .weather_fetcher import fetch_metar, fetch_taf, fetch_notams, fetch_stationinfo
from .getairportinfo import fetch_airport_info
from .core_calculations import calculate_advanced_rri, wind_components, density_alt, get_rri_category, get_status_from_rri
from .advanced_config import ConfigurationManager

logger = logging.getLogger(__name__)

@dataclass
class RouteWaypoint:
    """Represents a waypoint in the route analysis"""
    icao: str
    airport_info: Dict[str, Any]
    metar: Dict[str, Any]
    taf: Dict[str, Any]
    notams: Dict[str, Any]
    station_info: Dict[str, Any]
    best_runway_analysis: Dict[str, Any]
    route_position: str  # "departure", "en_route", "destination", "alternate"
    distance_nm: Optional[float] = None
    bearing_deg: Optional[float] = None

@dataclass
class RouteHazard:
    """Represents a weather hazard along the route"""
    hazard_type: str
    severity: str
    affected_airports: List[str]
    description: str
    recommendations: List[str]

class RouteAnalyzer:
    """Main class for route analysis functionality"""
    
    def __init__(self, aircraft_type: str = "light", pilot_experience: str = "standard"):
        self.config = ConfigurationManager.get_config_for_aircraft(aircraft_type, pilot_experience)
        self.aircraft_type = aircraft_type
        self.pilot_experience = pilot_experience
    
    async def analyze_route(self, airports: List[str], route_distances: Optional[List[float]] = None) -> Dict[str, Any]:
        """
        Comprehensive route analysis across multiple airports
        
        Args:
            airports: List of ICAO codes in route order [departure, waypoints..., destination]
            route_distances: Optional distances between airports in nautical miles
        
        Returns:
            Complete route analysis with recommendations
        """
        if len(airports) < 2:
            raise ValueError("Route analysis requires at least departure and destination airports")
        
        logger.info(f"Starting route analysis for {len(airports)} airports: {' -> '.join(airports)}")
        
        waypoints = await self._fetch_waypoint_data(airports, route_distances)
        
        route_assessment = self._assess_overall_route(waypoints)
        
        weather_trends = self._analyze_weather_trends(waypoints)
        
        hazards = self._identify_route_hazards(waypoints)
        
        alternates = await self._recommend_alternates(waypoints)
        
        fuel_considerations = self._calculate_fuel_considerations(waypoints, hazards)
        
        strategic_recommendations = self._generate_strategic_recommendations(
            waypoints, route_assessment, hazards, alternates
        )
        
        return {
            "route_summary": {
                "total_airports": len(airports),
                "departure": airports[0],
                "destination": airports[-1],
                "en_route_stops": airports[1:-1] if len(airports) > 2 else [],
                "total_distance_nm": sum(route_distances) if route_distances else None,
                "analysis_time": datetime.utcnow().isoformat(),
                "aircraft_config": {
                    "type": self.aircraft_type,
                    "experience_level": self.pilot_experience,
                    "risk_profile": self.config.risk_profile.value
                }
            },
            "waypoints": [self._serialize_waypoint(wp) for wp in waypoints],
            "route_assessment": route_assessment,
            "weather_trends": weather_trends,
            "hazards": [self._serialize_hazard(h) for h in hazards],
            "alternates": alternates,
            "fuel_considerations": fuel_considerations,
            "strategic_recommendations": strategic_recommendations
        }
    
    async def _fetch_waypoint_data(self, airports: List[str], distances: Optional[List[float]]) -> List[RouteWaypoint]:
        """Fetch all necessary data for route waypoints"""
        waypoints = []
        
        tasks = []
        for icao in airports:
            tasks.append(self._fetch_single_waypoint_data(icao))
        
        waypoint_data = await asyncio.gather(*tasks, return_exceptions=True)
        
        for i, (icao, data) in enumerate(zip(airports, waypoint_data)):
            if isinstance(data, Exception):
                logger.error(f"Failed to fetch data for {icao}: {data}")
                continue
            
            position = "departure" if i == 0 else "destination" if i == len(airports) - 1 else "en_route"
            distance = distances[i] if distances and i < len(distances) else None
            
            best_runway = self._analyze_best_runway(data["airport_info"], data["metar"])
            
            waypoint = RouteWaypoint(
                icao=icao,
                airport_info=data["airport_info"],
                metar=data["metar"],
                taf=data["taf"],
                notams=data["notams"],
                station_info=data["station_info"],
                best_runway_analysis=best_runway,
                route_position=position,
                distance_nm=distance
            )
            
            waypoints.append(waypoint)
        
        if not waypoints:
            raise ValueError("Failed to fetch data for any airports in the route")
        
        return waypoints
    
    async def _fetch_single_waypoint_data(self, icao: str) -> Dict[str, Any]:
        """Fetch all data for a single waypoint"""
        try:
            airport_info, metar, taf, notams, station_info = await asyncio.gather(
                fetch_airport_info(icao),
                fetch_metar(icao),
                fetch_taf(icao),
                fetch_notams(icao),
                fetch_stationinfo(icao)
            )
            
            return {
                "airport_info": airport_info,
                "metar": metar,
                "taf": taf,
                "notams": notams,
                "station_info": station_info
            }
        except Exception as e:
            logger.error(f"Error fetching data for {icao}: {e}")
            raise
    
    def _analyze_best_runway(self, airport_info: Dict, metar: Dict) -> Dict[str, Any]:
        """Analyze the best runway option for current conditions"""
        runways = airport_info.get("runways", [])
        if not runways:
            return {"error": "No runway data available"}
        
        field_elev = airport_info.get("elevation", 0)
        wind_dir = metar.get("wind_dir", 0)
        wind_speed = metar.get("wind_speed", 0)
        wind_gust = metar.get("wind_gust", 0)
        temp_c = metar.get("temp_c", 15)
        altim_in_hg = metar.get("altim_in_hg", 29.92)
        
        runway_analyses = []
        
        for runway in runways:
            rwy_heading = runway.get("heading")
            if rwy_heading is None:
                continue
            
            head, cross, is_head = wind_components(rwy_heading, wind_dir, wind_speed)
            da = density_alt(field_elev, temp_c, altim_in_hg)
            da_diff = da - field_elev
            
            rri, contributors = calculate_advanced_rri(
                head=head, cross=cross, gust_head=0, gust_cross=0,
                wind_speed=wind_speed, wind_gust=wind_gust,
                is_head=is_head, gust_is_head=True, da_diff=da_diff,
                metar_data=metar, runway_length=runway.get("length"),
                aircraft_category=self.aircraft_type
            )
            
            runway_analyses.append({
                "runway_id": runway.get("id"),
                "heading": rwy_heading,
                "length": runway.get("length"),
                "headwind_kt": head,
                "crosswind_kt": cross,
                "tailwind": not is_head,
                "rri": rri,
                "risk_category": get_rri_category(rri),
                "status": get_status_from_rri(rri)
            })
        
        if not runway_analyses:
            return {"error": "No valid runway data available for analysis"}
        
        best_runway = min(runway_analyses, key=lambda x: x["rri"])
        
        return {
            "best_runway": best_runway,
            "all_runways": runway_analyses,
            "density_altitude": da,
            "density_altitude_diff": da_diff
        }
    
    def _assess_overall_route(self, waypoints: List[RouteWaypoint]) -> Dict[str, Any]:
        """Assess overall route conditions and risks"""
        if not waypoints:
            return {
                "overall_status": "NO-GO",
                "overall_category": "EXTREME",
                "average_rri": 0,
                "maximum_rri": 0,
                "critical_airports": [],
                "total_airports_analyzed": 0,
                "error": "No waypoint data available"
            }
        
        total_score = 0
        max_score = 0
        critical_airports = []
        valid_airports = 0
        
        for wp in waypoints:
            runway_analysis = wp.best_runway_analysis
            if "error" in runway_analysis:
                logger.warning(f"Skipping {wp.icao} due to runway analysis error: {runway_analysis['error']}")
                continue
                
            best_runway = runway_analysis.get("best_runway", {})
            if not best_runway:
                logger.warning(f"No best runway data for {wp.icao}")
                continue
                
            rri = best_runway.get("rri", 0)
            total_score += rri
            max_score = max(max_score, rri)
            valid_airports += 1
            
            if rri > 75:
                critical_airports.append(wp.icao)
        
        if valid_airports == 0:
            return {
                "overall_status": "NO-GO",
                "overall_category": "EXTREME",
                "average_rri": 0,
                "maximum_rri": 0,
                "critical_airports": [],
                "total_airports_analyzed": 0,
                "error": "No valid runway analysis data available"
            }
        
        avg_score = total_score / valid_airports
        
        if max_score > 75 or len(critical_airports) > 0:
            overall_status = "NO-GO"
            overall_category = "EXTREME"
        elif max_score > 50 or avg_score > 40:
            overall_status = "CAUTION"
            overall_category = "HIGH"
        elif avg_score > 25:
            overall_status = "GOOD"
            overall_category = "MODERATE"
        else:
            overall_status = "GOOD"
            overall_category = "LOW"
        
        return {
            "overall_status": overall_status,
            "overall_category": overall_category,
            "average_rri": round(avg_score, 1),
            "maximum_rri": max_score,
            "critical_airports": critical_airports,
            "total_airports_analyzed": valid_airports
        }
    
    def _analyze_weather_trends(self, waypoints: List[RouteWaypoint]) -> Dict[str, Any]:
        """Analyze weather trends across the route"""
        if not waypoints:
            return {
                "pressure_trend": "unknown",
                "pressure_range": "N/A",
                "temperature_trend": "unknown", 
                "temperature_range": "N/A",
                "wind_range": "N/A",
                "common_weather": [],
                "error": "No waypoint data available"
            }
        
        pressures = []
        temperatures = []
        winds = []
        weather_conditions = set()
        
        for wp in waypoints:
            metar = wp.metar
            if metar:
                pressures.append(metar.get("altim_in_hg", 29.92))
                temperatures.append(metar.get("temp_c", 15))
                winds.append(metar.get("wind_speed", 0))
                weather_conditions.update(metar.get("weather", []))
        
        if not pressures:
            return {
                "pressure_trend": "unknown",
                "pressure_range": "N/A",
                "temperature_trend": "unknown",
                "temperature_range": "N/A", 
                "wind_range": "N/A",
                "common_weather": [],
                "error": "No valid weather data available"
            }
        
        pressure_trend = "stable"
        if len(pressures) > 1:
            pressure_diff = pressures[-1] - pressures[0]
            if pressure_diff < -0.1:
                pressure_trend = "falling"
            elif pressure_diff > 0.1:
                pressure_trend = "rising"
        
        temp_trend = "stable"
        if len(temperatures) > 1:
            temp_diff = temperatures[-1] - temperatures[0]
            if temp_diff < -5:
                temp_trend = "cooling"
            elif temp_diff > 5:
                temp_trend = "warming"
        
        return {
            "pressure_trend": pressure_trend,
            "pressure_range": f"{min(pressures):.2f} - {max(pressures):.2f}\"",
            "temperature_trend": temp_trend,
            "temperature_range": f"{min(temperatures)}°C - {max(temperatures)}°C",
            "wind_range": f"{min(winds)} - {max(winds)} kt",
            "common_weather": list(weather_conditions)
        }
    
    def _identify_route_hazards(self, waypoints: List[RouteWaypoint]) -> List[RouteHazard]:
        """Identify weather hazards affecting the route"""
        if not waypoints:
            return []
        
        hazards = []
        
        thunderstorm_airports = []
        icing_airports = []
        low_vis_airports = []
        high_wind_airports = []
        
        for wp in waypoints:
            metar = wp.metar
            if not metar:
                continue
                
            weather = metar.get("weather", [])
            wind_speed = metar.get("wind_speed", 0)
            wind_gust = metar.get("wind_gust", 0)
            visibility = metar.get("visibility")
            temp_c = metar.get("temp_c", 15)
            
            if any("TS" in w for w in weather):
                thunderstorm_airports.append(wp.icao)
            
            if -10 <= temp_c <= 2 and metar.get("cloud_layers"):
                icing_airports.append(wp.icao)
            
            if visibility is not None and visibility < 3:
                low_vis_airports.append(wp.icao)
            
            if wind_speed > 25 or wind_gust > 35:
                high_wind_airports.append(wp.icao)
        
        if thunderstorm_airports:
            hazards.append(RouteHazard(
                hazard_type="thunderstorms",
                severity="extreme",
                affected_airports=thunderstorm_airports,
                description="Active thunderstorms reported",
                recommendations=["Consider route deviation", "Wait for conditions to improve", "File alternate route"]
            ))
        
        if icing_airports:
            hazards.append(RouteHazard(
                hazard_type="icing",
                severity="high",
                affected_airports=icing_airports,
                description="Icing conditions possible",
                recommendations=["Verify anti-ice/de-ice equipment", "Consider altitude changes", "Monitor pilot reports"]
            ))
        
        if low_vis_airports:
            hazards.append(RouteHazard(
                hazard_type="low_visibility",
                severity="moderate",
                affected_airports=low_vis_airports,
                description="Reduced visibility conditions",
                recommendations=["Verify IFR currency", "Check approach minimums", "Consider VFR alternatives"]
            ))
        
        if high_wind_airports:
            hazards.append(RouteHazard(
                hazard_type="high_winds",
                severity="high",
                affected_airports=high_wind_airports,
                description="Strong winds or gusts reported",
                recommendations=["Review crosswind limits", "Consider runway orientation", "Monitor wind trends"]
            ))
        
        return hazards
    
    async def _recommend_alternates(self, waypoints: List[RouteWaypoint]) -> Dict[str, List[str]]:
        """Recommend alternate airports for destinations with poor conditions"""
        alternates = {}
        
        for wp in waypoints:
            if wp.route_position == "destination":
                rri = wp.best_runway_analysis.get("best_runway", {}).get("rri", 0)
                
                if rri > 50:
                    alternates[wp.icao] = [
                        "Consider nearby airports with better conditions",
                        "Verify fuel for alternate approach",
                        "Check alternate weather minimums"
                    ]
        
        return alternates
    
    def _calculate_fuel_considerations(self, waypoints: List[RouteWaypoint], hazards: List[RouteHazard]) -> Dict[str, Any]:
        """Calculate fuel planning considerations based on route conditions"""
        base_fuel_factor = 1.0
        
        for hazard in hazards:
            if hazard.hazard_type == "thunderstorms":
                base_fuel_factor += 0.2
            elif hazard.hazard_type == "high_winds":
                base_fuel_factor += 0.15
            elif hazard.hazard_type == "icing":
                base_fuel_factor += 0.1
        
        high_da_airports = [
            wp.icao for wp in waypoints 
            if wp.best_runway_analysis.get("density_altitude_diff", 0) > 2000
        ]
        
        if high_da_airports:
            base_fuel_factor += 0.1
        
        return {
            "fuel_factor": round(base_fuel_factor, 2),
            "additional_fuel_recommended": base_fuel_factor >= 1.1,
            "high_density_altitude_airports": high_da_airports,
            "considerations": [
                f"Consider {int((base_fuel_factor - 1) * 100)}% additional fuel for weather",
                "Verify alternate fuel requirements",
                "Account for possible holding or deviations"
            ] if base_fuel_factor >= 1.1 else ["Standard fuel planning adequate"]
        }
    
    def _generate_strategic_recommendations(self, waypoints: List[RouteWaypoint], 
                                          route_assessment: Dict, hazards: List[RouteHazard],
                                          alternates: Dict) -> List[str]:
        """Generate strategic recommendations for the route"""
        recommendations = []
        
        if route_assessment["overall_status"] == "NO-GO":
            recommendations.append("🚫 ROUTE NOT RECOMMENDED - Critical weather conditions present")
            recommendations.append("Consider delaying departure or selecting alternate route")
        
        elif route_assessment["overall_status"] == "CAUTION":
            recommendations.append("⚠️ PROCEED WITH CAUTION - Enhanced planning required")
            recommendations.append("Monitor weather developments closely")
        
        if len(hazards) > 2:
            recommendations.append("Multiple weather hazards present - consider comprehensive briefing")
        
        high_rri_airports = [
            wp.icao for wp in waypoints 
            if wp.best_runway_analysis.get("best_runway", {}).get("rri", 0) > 50
        ]
        
        if high_rri_airports:
            recommendations.append(f"Enhanced planning required for: {', '.join(high_rri_airports)}")
        
        if any(wp.best_runway_analysis.get("density_altitude_diff", 0) > 2000 for wp in waypoints):
            recommendations.append("High density altitude performance calculations recommended")
        
        if not recommendations:
            recommendations.append("✅ Route conditions are favorable for planned operations")
            recommendations.append("Standard flight planning procedures apply")
        
        return recommendations
    
    def _serialize_waypoint(self, wp: RouteWaypoint) -> Dict[str, Any]:
        """Serialize waypoint for JSON response"""
        return {
            "icao": wp.icao,
            "position": wp.route_position,
            "distance_nm": wp.distance_nm,
            "current_weather": {
                "wind_dir": wp.metar.get("wind_dir", 0),
                "wind_speed": wp.metar.get("wind_speed", 0),
                "wind_gust": wp.metar.get("wind_gust", 0),
                "temp_c": wp.metar.get("temp_c", 15),
                "altim_in_hg": wp.metar.get("altim_in_hg", 29.92),
                "visibility": wp.metar.get("visibility"),
                "ceiling": wp.metar.get("ceiling"),
                "weather": wp.metar.get("weather", [])
            },
            "runway_analysis": wp.best_runway_analysis,
            "airport_elevation": wp.airport_info.get("elevation")
        }
    
    def _serialize_hazard(self, hazard: RouteHazard) -> Dict[str, Any]:
        """Serialize hazard for JSON response"""
        return {
            "type": hazard.hazard_type,
            "severity": hazard.severity,
            "affected_airports": hazard.affected_airports,
            "description": hazard.description,
            "recommendations": hazard.recommendations
        }

async def analyze_route(airports: List[str], aircraft_type: str = "light", 
                       pilot_experience: str = "standard", 
                       route_distances: Optional[List[float]] = None) -> Dict[str, Any]:
    """
    Main entry point for route analysis
    
    Args:
        airports: List of ICAO codes in route order
        aircraft_type: Aircraft category for performance analysis
        pilot_experience: Pilot experience level for risk assessment
        route_distances: Optional distances between airports in NM
    
    Returns:
        Comprehensive route analysis
    """
    analyzer = RouteAnalyzer(aircraft_type, pilot_experience)
    return await analyzer.analyze_route(airports, route_distances) 