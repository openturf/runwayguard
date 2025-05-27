"""
Runway Risk Intelligence Configuration

This module provides configuration options for the risk analysis system.
It allows fine-tuning of risk thresholds, enabling/disabling features,
and customizing the analysis for different aircraft categories and operational requirements.
- @awade12 may 20th 2025
"""

from typing import Dict, Any
from dataclasses import dataclass
from enum import Enum

class AircraftCategory(Enum):
    """Aircraft categories for performance-based risk assessment"""
    LIGHT = "light"           # Single-engine, < 12,500 lbs
    LIGHT_TWIN = "light_twin" # Twin-engine, < 12,500 lbs  
    TURBOPROP = "turboprop"   # Turboprop aircraft
    LIGHT_JET = "light_jet"   # Light jets, < 41,000 lbs
    HEAVY = "heavy"           # > 41,000 lbs

class RiskProfile(Enum):
    """Risk assessment profiles for different operational requirements"""
    CONSERVATIVE = "conservative"     # Lower risk tolerance, stricter thresholds
    STANDARD = "standard"            # Balanced risk assessment
    AGGRESSIVE = "aggressive"        # Higher risk tolerance for experienced pilots

@dataclass
class AdvancedRiskConfig:
    """Configuration class for risk analysis"""
    
    # Feature toggles
    enable_thermal_analysis: bool = True
    enable_stability_analysis: bool = True
    enable_performance_analysis: bool = True
    enable_precipitation_analysis: bool = True
    enable_turbulence_analysis: bool = True
    enable_trend_analysis: bool = True
    enable_risk_amplification: bool = True
    
    # Aircraft-specific settings
    aircraft_category: AircraftCategory = AircraftCategory.LIGHT
    runway_length_requirement: int = 2500  # Minimum runway length in feet
    
    # Risk profile
    risk_profile: RiskProfile = RiskProfile.STANDARD
    
    # Threshold multipliers based on risk profile
    @property
    def threshold_multiplier(self) -> float:
        """Get threshold multiplier based on risk profile"""
        multipliers = {
            RiskProfile.CONSERVATIVE: 0.7,  # Lower thresholds = higher sensitivity (more conservative)
            RiskProfile.STANDARD: 1.0,      # Standard thresholds
            RiskProfile.AGGRESSIVE: 1.4     # Higher thresholds = lower sensitivity (less conservative)
        }
        return multipliers[self.risk_profile]
    
    # Risk thresholds (can be adjusted based on operational requirements)
    thermal_gradient_thresholds: Dict[str, int] = None
    stability_index_thresholds: Dict[str, int] = None
    performance_risk_thresholds: Dict[str, int] = None
    turbulence_risk_thresholds: Dict[str, int] = None
    
    def __post_init__(self):
        """Initialize default thresholds if not provided"""
        if self.thermal_gradient_thresholds is None:
            self.thermal_gradient_thresholds = {
                "high_thermal_temp": int(25 * self.threshold_multiplier),
                "high_thermal_spread": int(10 * self.threshold_multiplier),
                "inversion_temp": int(5 * self.threshold_multiplier),
                "inversion_spread": int(3 * self.threshold_multiplier)
            }
        
        if self.stability_index_thresholds is None:
            self.stability_index_thresholds = {
                "convective_temp": int(20 * self.threshold_multiplier),
                "convective_spread": int(5 * self.threshold_multiplier),
                "mechanical_wind": int(20 * self.threshold_multiplier),
                "mechanical_spread": int(15 * self.threshold_multiplier)
            }
        
        if self.performance_risk_thresholds is None:
            base_length = int(self.runway_length_requirement * self.threshold_multiplier)
            self.performance_risk_thresholds = {
                "marginal_runway": base_length - 500,
                "concerning_runway": base_length - 200,
                "adequate_runway": base_length + 500,
                "high_da_threshold": int(3000 * self.threshold_multiplier),
                "moderate_da_threshold": int(2000 * self.threshold_multiplier)
            }
        
        if self.turbulence_risk_thresholds is None:
            self.turbulence_risk_thresholds = {
                "severe_gust_factor": 2.0 / self.threshold_multiplier,
                "significant_gust_factor": 1.5 / self.threshold_multiplier,
                "moderate_gust_factor": 1.3 / self.threshold_multiplier,
                "strong_wind_threshold": int(25 * self.threshold_multiplier),
                "fresh_wind_threshold": int(20 * self.threshold_multiplier)
            }

class ConfigurationManager:
    """Manages configuration for different operational scenarios"""
    
    @staticmethod
    def get_config_for_aircraft(aircraft_type: str, experience_level: str = "standard") -> AdvancedRiskConfig:
        """Get configuration optimized for specific aircraft type and pilot experience"""
        
        # Map aircraft types to categories
        aircraft_mapping = {
            "c172": AircraftCategory.LIGHT,
            "c182": AircraftCategory.LIGHT,
            "c210": AircraftCategory.LIGHT,
            "pa28": AircraftCategory.LIGHT,
            "pa34": AircraftCategory.LIGHT_TWIN,
            "be58": AircraftCategory.LIGHT_TWIN,
            "tbm": AircraftCategory.TURBOPROP,
            "pc12": AircraftCategory.TURBOPROP,
            "citation": AircraftCategory.LIGHT_JET,
            "king_air": AircraftCategory.TURBOPROP
        }
        
        # Map experience levels to risk profiles
        experience_mapping = {
            "student": RiskProfile.CONSERVATIVE,
            "private": RiskProfile.CONSERVATIVE,
            "instrument": RiskProfile.STANDARD,
            "commercial": RiskProfile.STANDARD,
            "atp": RiskProfile.AGGRESSIVE,
            "cfi": RiskProfile.STANDARD,
            "standard": RiskProfile.STANDARD
        }
        
        aircraft_category = aircraft_mapping.get(aircraft_type.lower(), AircraftCategory.LIGHT)
        risk_profile = experience_mapping.get(experience_level.lower(), RiskProfile.STANDARD)
        
        # Adjust runway requirements based on aircraft category
        runway_requirements = {
            AircraftCategory.LIGHT: 2000,
            AircraftCategory.LIGHT_TWIN: 2500,
            AircraftCategory.TURBOPROP: 3000,
            AircraftCategory.LIGHT_JET: 3500,
            AircraftCategory.HEAVY: 5000
        }
        
        return AdvancedRiskConfig(
            aircraft_category=aircraft_category,
            risk_profile=risk_profile,
            runway_length_requirement=runway_requirements[aircraft_category]
        )
    
    @staticmethod
    def get_config_for_conditions(conditions: Dict[str, Any]) -> AdvancedRiskConfig:
        """Get configuration optimized for specific weather conditions"""
        config = AdvancedRiskConfig()
        
        # Disable certain analyses if conditions don't warrant them
        if conditions.get("temp_c", 15) < 0 or conditions.get("temp_c", 15) > 35:
            # Better thermal analysis for extreme temperatures
            config.enable_thermal_analysis = True
        
        if conditions.get("wind_gust", 0) > conditions.get("wind_speed", 0) * 1.3:
            # Better turbulence analysis for gusty conditions
            config.enable_turbulence_analysis = True
        
        if any("TS" in w for w in conditions.get("weather", [])):
            # Conservative profile for thunderstorm conditions
            config.risk_profile = RiskProfile.CONSERVATIVE
        
        return config

# Default configuration instances
DEFAULT_CONFIG = AdvancedRiskConfig()
CONSERVATIVE_CONFIG = AdvancedRiskConfig(risk_profile=RiskProfile.CONSERVATIVE)
AGGRESSIVE_CONFIG = AdvancedRiskConfig(risk_profile=RiskProfile.AGGRESSIVE)

# Aircraft-specific configurations
LIGHT_AIRCRAFT_CONFIG = AdvancedRiskConfig(
    aircraft_category=AircraftCategory.LIGHT,
    runway_length_requirement=2000
)

TURBOPROP_CONFIG = AdvancedRiskConfig(
    aircraft_category=AircraftCategory.TURBOPROP,
    runway_length_requirement=3000,
    risk_profile=RiskProfile.STANDARD
)

JET_CONFIG = AdvancedRiskConfig(
    aircraft_category=AircraftCategory.LIGHT_JET,
    runway_length_requirement=3500,
    risk_profile=RiskProfile.AGGRESSIVE
) 