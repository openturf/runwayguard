#!/usr/bin/env python3
"""
Advanced Runway Risk Analysis - Usage Example

This script demonstrates the enhanced capabilities of the Advanced Runway Risk Intelligence (ARRI) system.
It shows how to use the new advanced features for more sophisticated risk assessment.
"""

import sys
import os
sys.path.append(os.path.join(os.path.dirname(__file__), '..', '..'))

from functions.core_calculations import (
    calculate_rri, calculate_advanced_rri, 
    wind_components, gust_components, density_alt
)
from functions.advanced_config import (
    ConfigurationManager, AircraftCategory, RiskProfile,
    DEFAULT_CONFIG, CONSERVATIVE_CONFIG
)

def demonstrate_basic_vs_advanced():
    """Compare basic RRI vs Advanced RRI for the same conditions"""
    
    print("=== BASIC vs ADVANCED RRI COMPARISON ===\n")
    
    # Sample conditions
    runway_heading = 90  # Runway 09
    wind_direction = 120  # Wind from 120°
    wind_speed = 15
    wind_gust = 22
    field_elevation = 1200
    temperature = 28  # Hot day
    altimeter = 29.85
    
    # Sample METAR data
    metar_data = {
        "temp_c": temperature,
        "dewpoint_c": 22,
        "wind_dir": wind_direction,
        "wind_speed": wind_speed,
        "wind_gust": wind_gust,
        "altim_in_hg": altimeter,
        "weather": ["RA"],  # Light rain
        "ceiling": 2500,
        "visibility": 8,
        "cloud_layers": [{"type": "BKN", "base": 2500}]
    }
    
    # Calculate wind components
    da = density_alt(field_elevation, temperature, altimeter)
    da_diff = da - field_elevation
    head, cross, is_head = wind_components(runway_heading, wind_direction, wind_speed)
    gust_head, gust_cross, gust_is_head = gust_components(runway_heading, wind_direction, wind_gust)
    
    print(f"Conditions:")
    print(f"  Airport elevation: {field_elevation} ft")
    print(f"  Temperature: {temperature}°C")
    print(f"  Density altitude: {da} ft ({da_diff:+d} ft)")
    print(f"  Wind: {wind_speed}G{wind_gust} kt from {wind_direction}°")
    print(f"  Runway 09: Headwind {head}kt, Crosswind {cross}kt")
    print(f"  Weather: Light rain, ceiling 2500 ft, visibility 8 SM\n")
    
    # Basic RRI calculation
    basic_rri, basic_contributors = calculate_rri(
        head, cross, gust_head, gust_cross, wind_speed, wind_gust,
        is_head, gust_is_head, da_diff, metar_data,
        lat=40.7128, lon=-74.0060, rwy_heading=runway_heading
    )
    
    print(f"BASIC RRI: {basic_rri}")
    print("Contributors:")
    for contributor, data in basic_contributors.items():
        print(f"  {contributor}: {data['score']} points")
    print()
    
    # Advanced RRI calculation
    advanced_rri, advanced_contributors = calculate_advanced_rri(
        head, cross, gust_head, gust_cross, wind_speed, wind_gust,
        is_head, gust_is_head, da_diff, metar_data,
        lat=40.7128, lon=-74.0060, rwy_heading=runway_heading,
        runway_length=4500, airport_elevation=field_elevation,
        terrain_factor=1.1, aircraft_category="light"
    )
    
    print(f"ADVANCED RRI: {advanced_rri}")
    print("Contributors:")
    for contributor, data in advanced_contributors.items():
        print(f"  {contributor}: {data['score']} points")
        if isinstance(data['value'], list) and data['value']:
            for reason in data['value']:
                print(f"    - {reason}")
    print()
    
    improvement = advanced_rri - basic_rri
    print(f"Advanced analysis detected {improvement:+d} additional risk points")
    print()

def demonstrate_aircraft_configurations():
    """Show how different aircraft configurations affect risk assessment"""
    
    print("=== AIRCRAFT-SPECIFIC CONFIGURATIONS ===\n")
    
    aircraft_types = [
        ("Cessna 172", "c172", "private"),
        ("Piper Seneca", "pa34", "commercial"),
        ("TBM 940", "tbm", "instrument"),
        ("Citation CJ4", "citation", "atp")
    ]
    
    for aircraft_name, aircraft_code, pilot_level in aircraft_types:
        config = ConfigurationManager.get_config_for_aircraft(aircraft_code, pilot_level)
        
        print(f"{aircraft_name} ({pilot_level} pilot):")
        print(f"  Category: {config.aircraft_category.value}")
        print(f"  Risk Profile: {config.risk_profile.value}")
        print(f"  Runway Requirement: {config.runway_length_requirement} ft")
        print(f"  Threshold Multiplier: {config.threshold_multiplier:.1f}x")
        print()

def demonstrate_risk_amplification():
    """Show risk amplification in dangerous condition combinations"""
    
    print("=== RISK AMPLIFICATION DEMONSTRATION ===\n")
    
    # Scenario: High density altitude + gusty crosswinds + icing conditions
    dangerous_metar = {
        "temp_c": 1,  # Near freezing
        "dewpoint_c": 0,  # High humidity
        "wind_dir": 45,  # 45° crosswind to runway 09
        "wind_speed": 18,
        "wind_gust": 28,  # Strong gusts
        "altim_in_hg": 29.65,  # Low pressure
        "weather": ["FZRA", "BKN020"],  # Freezing rain, broken clouds
        "ceiling": 1200,
        "visibility": 3,
        "cloud_layers": [{"type": "BKN", "base": 1200}]
    }
    
    field_elev = 3500  # High elevation airport
    da = density_alt(field_elev, 1, 29.65)
    da_diff = da - field_elev
    head, cross, is_head = wind_components(90, 45, 18)
    gust_head, gust_cross, gust_is_head = gust_components(90, 45, 28)
    
    rri, contributors = calculate_advanced_rri(
        head, cross, gust_head, gust_cross, 18, 28,
        is_head, gust_is_head, da_diff, dangerous_metar,
        runway_length=3200, airport_elevation=field_elev,
        terrain_factor=1.3  # Mountainous terrain
    )
    
    print("DANGEROUS CONDITIONS SCENARIO:")
    print(f"  High altitude airport ({field_elev} ft)")
    print(f"  Density altitude: {da} ft ({da_diff:+d} ft)")
    print(f"  Strong gusty crosswinds: {cross}G{gust_cross} kt")
    print(f"  Freezing rain with low ceiling/visibility")
    print(f"  Mountainous terrain (factor: 1.3)")
    print()
    
    print(f"EXTREME RRI: {rri}")
    print("\nRisk Amplification Factors:")
    
    amplification_contributors = [
        "icing_conditions", "low_ceiling", "low_visibility",
        "crosswind", "gust_crosswind", "density_altitude_diff",
        "turbulence_risk", "risk_amplification"
    ]
    
    for contributor in amplification_contributors:
        if contributor in contributors:
            data = contributors[contributor]
            print(f"  {contributor.replace('_', ' ').title()}: {data['score']} points")
            if isinstance(data['value'], list):
                for reason in data['value']:
                    print(f"    - {reason}")
    print()

def demonstrate_configuration_impact():
    """Show how risk profiles affect the same conditions"""
    
    print("=== RISK PROFILE IMPACT ===\n")
    
    # Standard challenging conditions
    metar_data = {
        "temp_c": 32,  # Hot
        "dewpoint_c": 25,
        "wind_dir": 110,
        "wind_speed": 20,
        "wind_gust": 0,
        "altim_in_hg": 29.88,
        "weather": [],
        "ceiling": None,
        "visibility": 10
    }
    
    conditions = {
        "Conservative (Student Pilot)": CONSERVATIVE_CONFIG,
        "Standard (Instrument Pilot)": DEFAULT_CONFIG,
        "Aggressive (ATP)": ConfigurationManager.get_config_for_aircraft("citation", "atp")
    }
    
    print("Same conditions, different risk tolerances:")
    print("Hot day (32°C), 20kt crosswind to runway 09\n")
    
    for description, config in conditions.items():
        # Simulate how thresholds would affect scoring
        base_temp_score = 10  # Base temperature risk
        adjusted_score = int(base_temp_score / config.threshold_multiplier)
        
        print(f"{description}:")
        print(f"  Threshold multiplier: {config.threshold_multiplier:.1f}x")
        print(f"  Temperature risk: {adjusted_score} points (vs {base_temp_score} base)")
        print(f"  Risk tolerance: {config.risk_profile.value}")
        print()

if __name__ == "__main__":
    print("Advanced Runway Risk Intelligence (ARRI) - Demonstration\n")
    print("=" * 60)
    
    demonstrate_basic_vs_advanced()
    print("=" * 60)
    
    demonstrate_aircraft_configurations()
    print("=" * 60)
    
    demonstrate_risk_amplification()
    print("=" * 60)
    
    demonstrate_configuration_impact()
    
    print("Demo complete! See docs/advanced_risk_analysis.md for full documentation.") 