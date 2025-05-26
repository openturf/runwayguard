"""
Advanced Probabilistic Runway Risk Analysis

Sophisticated Monte Carlo simulation system for runway risk assessment under uncertainty.
Uses realistic weather perturbation models, correlated parameter variations, and advanced
statistical analysis to provide comprehensive risk confidence intervals.

Key capabilities:
- Realistic weather parameter correlations and constraints
- Multi-dimensional uncertainty propagation
- Temporal evolution modeling for forecast scenarios
- Risk distribution analysis with detailed percentiles
- Scenario clustering and extreme event identification
- Sensitivity analysis for critical parameters

Copyright by awade12(openturf.org)
"""

import random
import math
import numpy as np
from typing import Dict, List, Tuple, Optional, Any
from dataclasses import dataclass
from datetime import datetime, timedelta
from .core_calculations import (
    calculate_rri, calculate_advanced_rri, wind_components, gust_components,
    density_alt, get_rri_category, get_status_from_rri
)

def convert_numpy_types(obj):
    """Convert NumPy types to native Python types for JSON serialization"""
    if isinstance(obj, np.integer):
        return int(obj)
    elif isinstance(obj, np.floating):
        return float(obj)
    elif isinstance(obj, np.ndarray):
        return obj.tolist()
    elif isinstance(obj, dict):
        return {key: convert_numpy_types(value) for key, value in obj.items()}
    elif isinstance(obj, list):
        return [convert_numpy_types(item) for item in obj]
    elif isinstance(obj, tuple):
        return tuple(convert_numpy_types(item) for item in obj)
    else:
        return obj

@dataclass
class WeatherPerturbationModel:
    """Realistic weather parameter perturbation constraints"""
    wind_dir_std: float = 8.0
    wind_speed_std: float = 3.0
    temp_std: float = 2.0
    pressure_std: float = 0.02
    visibility_factor: float = 0.15
    ceiling_factor: float = 0.20
    gust_correlation: float = 0.85
    
    def __post_init__(self):
        self.wind_dir_bounds = (-15, 15)
        self.wind_speed_bounds = (-5, 8)
        self.temp_bounds = (-4, 4)
        self.pressure_bounds = (-0.05, 0.05)

@dataclass
class ProbabilisticResult:
    """Comprehensive probabilistic analysis results"""
    percentiles: Dict[str, float]
    statistics: Dict[str, float]
    risk_distribution: Dict[str, float]
    extreme_scenarios: List[Dict]
    sensitivity_analysis: Dict[str, float]
    confidence_intervals: Dict[str, Tuple[float, float]]
    scenario_clusters: Dict[str, List[Dict]]
    temporal_evolution: Optional[List[Dict]] = None

class AdvancedWeatherPerturber:
    """Sophisticated weather parameter perturbation with realistic correlations"""
    
    def __init__(self, model: WeatherPerturbationModel):
        self.model = model
        
    def perturb_correlated_weather(self, base_conditions: Dict, scenario_type: str = "normal") -> Dict:
        """Generate realistic correlated weather perturbations"""
        perturbed = base_conditions.copy()
        
        if scenario_type == "deteriorating":
            bias_factors = {
                "wind_speed": 1.5,
                "wind_gust": 1.8,
                "visibility": 0.7,
                "ceiling": 0.8
            }
        elif scenario_type == "improving":
            bias_factors = {
                "wind_speed": 0.7,
                "wind_gust": 0.6,
                "visibility": 1.3,
                "ceiling": 1.2
            }
        else:
            bias_factors = {key: 1.0 for key in ["wind_speed", "wind_gust", "visibility", "ceiling"]}
        
        wind_dir_delta = np.random.normal(0, self.model.wind_dir_std)
        wind_dir_delta = np.clip(wind_dir_delta, *self.model.wind_dir_bounds)
        perturbed["wind_dir"] = (base_conditions["wind_dir"] + wind_dir_delta) % 360
        
        wind_speed_delta = np.random.normal(0, self.model.wind_speed_std) * bias_factors["wind_speed"]
        wind_speed_delta = np.clip(wind_speed_delta, *self.model.wind_speed_bounds)
        perturbed["wind_speed"] = max(0, base_conditions["wind_speed"] + wind_speed_delta)
        
        if base_conditions.get("wind_gust", 0) > 0:
            base_gust_diff = base_conditions["wind_gust"] - base_conditions["wind_speed"]
            gust_correlation_noise = np.random.normal(0, 1) * (1 - self.model.gust_correlation)
            gust_delta = wind_speed_delta * self.model.gust_correlation + gust_correlation_noise
            gust_delta *= bias_factors["wind_gust"]
            
            new_gust_diff = max(0, base_gust_diff + gust_delta)
            perturbed["wind_gust"] = perturbed["wind_speed"] + new_gust_diff
        else:
            if perturbed["wind_speed"] > 15 and random.random() < 0.3:
                perturbed["wind_gust"] = perturbed["wind_speed"] + random.uniform(3, 8)
        
        temp_delta = np.random.normal(0, self.model.temp_std)
        temp_delta = np.clip(temp_delta, *self.model.temp_bounds)
        perturbed["temp_c"] = base_conditions["temp_c"] + temp_delta
        
        if "altim_in_hg" in base_conditions:
            pressure_delta = np.random.normal(0, self.model.pressure_std)
            pressure_delta = np.clip(pressure_delta, *self.model.pressure_bounds)
            perturbed["altim_in_hg"] = base_conditions["altim_in_hg"] + pressure_delta
        
        if "visibility" in base_conditions and base_conditions["visibility"] is not None:
            vis_factor = 1 + np.random.normal(0, self.model.visibility_factor) * bias_factors["visibility"]
            vis_factor = max(0.1, vis_factor)
            perturbed["visibility"] = max(0.25, base_conditions["visibility"] * vis_factor)
        
        if "ceiling" in base_conditions and base_conditions["ceiling"] is not None:
            ceiling_factor = 1 + np.random.normal(0, self.model.ceiling_factor) * bias_factors["ceiling"]
            ceiling_factor = max(0.1, ceiling_factor)
            perturbed["ceiling"] = max(100, base_conditions["ceiling"] * ceiling_factor)
        
        return perturbed

class ScenarioGenerator:
    """Generate diverse weather scenarios for comprehensive analysis"""
    
    @staticmethod
    def generate_temporal_scenarios(base_conditions: Dict, hours_ahead: int = 6) -> List[Dict]:
        """Generate time-evolved weather scenarios"""
        scenarios = []
        
        for hour in range(1, hours_ahead + 1):
            scenario = base_conditions.copy()
            
            diurnal_temp_change = 3 * math.sin((hour * math.pi) / 12)
            scenario["temp_c"] += diurnal_temp_change
            
            if "wind_speed" in scenario:
                wind_evolution = random.uniform(0.8, 1.3) ** hour
                scenario["wind_speed"] = max(0, scenario["wind_speed"] * wind_evolution)
                
                if scenario.get("wind_gust", 0) > 0:
                    gust_evolution = random.uniform(0.7, 1.4) ** hour
                    scenario["wind_gust"] = max(scenario["wind_speed"], 
                                               scenario["wind_gust"] * gust_evolution)
            
            if random.random() < 0.1 * hour:
                scenario["weather"] = scenario.get("weather", []) + ["BR"]
            
            scenarios.append({
                "conditions": scenario,
                "time_offset": hour,
                "confidence": max(0.3, 1.0 - (hour * 0.15))
            })
        
        return scenarios
    
    @staticmethod
    def generate_extreme_scenarios(base_conditions: Dict) -> List[Dict]:
        """Generate extreme but plausible weather scenarios"""
        scenarios = []
        
        wind_extreme = base_conditions.copy()
        wind_extreme["wind_speed"] = min(50, base_conditions["wind_speed"] * 1.8)
        if wind_extreme["wind_speed"] > 15:
            wind_extreme["wind_gust"] = wind_extreme["wind_speed"] + random.uniform(8, 15)
        scenarios.append({"type": "wind_extreme", "conditions": wind_extreme, "probability": 0.05})
        
        visibility_extreme = base_conditions.copy()
        if "visibility" in visibility_extreme and visibility_extreme["visibility"]:
            visibility_extreme["visibility"] = max(0.25, visibility_extreme["visibility"] * 0.3)
            visibility_extreme["weather"] = visibility_extreme.get("weather", []) + ["FG"]
        scenarios.append({"type": "visibility_extreme", "conditions": visibility_extreme, "probability": 0.08})
        
        temp_extreme_hot = base_conditions.copy()
        temp_extreme_hot["temp_c"] += random.uniform(8, 15)
        scenarios.append({"type": "temperature_extreme_hot", "conditions": temp_extreme_hot, "probability": 0.03})
        
        temp_extreme_cold = base_conditions.copy()
        temp_extreme_cold["temp_c"] -= random.uniform(10, 20)
        if temp_extreme_cold["temp_c"] < 2:
            temp_extreme_cold["weather"] = temp_extreme_cold.get("weather", []) + ["FZRA"]
        scenarios.append({"type": "temperature_extreme_cold", "conditions": temp_extreme_cold, "probability": 0.03})
        
        return scenarios

class StatisticalAnalyzer:
    """Advanced statistical analysis of Monte Carlo results"""
    
    @staticmethod
    def calculate_comprehensive_statistics(samples: List[float]) -> Dict[str, float]:
        """Calculate detailed statistical measures"""
        if not samples:
            return {}
        
        samples_array = np.array(samples)
        
        return {
            "mean": float(np.mean(samples_array)),
            "median": float(np.median(samples_array)),
            "std": float(np.std(samples_array)),
            "variance": float(np.var(samples_array)),
            "skewness": float(StatisticalAnalyzer._calculate_skewness(samples_array)),
            "kurtosis": float(StatisticalAnalyzer._calculate_kurtosis(samples_array)),
            "min": float(np.min(samples_array)),
            "max": float(np.max(samples_array)),
            "range": float(np.max(samples_array) - np.min(samples_array)),
            "iqr": float(np.percentile(samples_array, 75) - np.percentile(samples_array, 25))
        }
    
    @staticmethod
    def _calculate_skewness(data: np.ndarray) -> float:
        """Calculate skewness of distribution"""
        if len(data) < 3:
            return 0.0
        mean = np.mean(data)
        std = np.std(data)
        if std == 0:
            return 0.0
        return np.mean(((data - mean) / std) ** 3)
    
    @staticmethod
    def _calculate_kurtosis(data: np.ndarray) -> float:
        """Calculate kurtosis of distribution"""
        if len(data) < 4:
            return 0.0
        mean = np.mean(data)
        std = np.std(data)
        if std == 0:
            return 0.0
        return np.mean(((data - mean) / std) ** 4) - 3
    
    @staticmethod
    def calculate_percentiles(samples: List[float], percentiles: List[float] = None) -> Dict[str, float]:
        """Calculate specified percentiles"""
        if percentiles is None:
            percentiles = [1, 5, 10, 25, 50, 75, 90, 95, 99]
        
        if not samples:
            return {f"p{p:02d}": None for p in percentiles}
        
        samples_array = np.array(samples)
        return {f"p{p:02d}": float(np.percentile(samples_array, p)) for p in percentiles}
    
    @staticmethod
    def analyze_risk_distribution(samples: List[float]) -> Dict[str, float]:
        """Analyze distribution across risk categories"""
        if not samples:
            return {}
        
        total = len(samples)
        distribution = {
            "low_risk": sum(1 for s in samples if s <= 25) / total,
            "moderate_risk": sum(1 for s in samples if 25 < s <= 50) / total,
            "high_risk": sum(1 for s in samples if 50 < s <= 75) / total,
            "extreme_risk": sum(1 for s in samples if s > 75) / total
        }
        
        distribution["no_go_probability"] = sum(1 for s in samples if s >= 76) / total
        distribution["caution_probability"] = sum(1 for s in samples if 51 <= s <= 75) / total
        distribution["good_probability"] = sum(1 for s in samples if s <= 50) / total
        
        return distribution

class SensitivityAnalyzer:
    """Sensitivity analysis for parameter importance"""
    
    @staticmethod
    def calculate_parameter_sensitivity(base_conditions: Dict, rwy_heading: float, 
                                      da_diff: float, metar_data: Dict, 
                                      lat: float, lon: float) -> Dict[str, float]:
        """Calculate sensitivity of RRI to each parameter"""
        base_head, base_cross, base_is_head = wind_components(
            rwy_heading, base_conditions["wind_dir"], base_conditions["wind_speed"]
        )
        base_gust_head, base_gust_cross, base_gust_is_head = gust_components(
            rwy_heading, base_conditions["wind_dir"], base_conditions.get("wind_gust", 0)
        )
        
        base_rri, _ = calculate_rri(
            base_head, base_cross, base_gust_head, base_gust_cross,
            base_conditions["wind_speed"], base_conditions.get("wind_gust", 0),
            base_is_head, base_gust_is_head, da_diff, metar_data, lat, lon, rwy_heading, None
        )
        
        sensitivities = {}
        
        perturbation_configs = {
            "wind_dir": 10,
            "wind_speed": 5,
            "wind_gust": 5,
            "temp_c": 3
        }
        
        for param, delta in perturbation_configs.items():
            if param not in base_conditions:
                continue
                
            perturbed_conditions = base_conditions.copy()
            perturbed_conditions[param] += delta
            
            if param == "temp_c":
                new_metar = metar_data.copy()
                new_metar["temp_c"] = perturbed_conditions["temp_c"]
                perturbed_rri, _ = calculate_rri(
                    base_head, base_cross, base_gust_head, base_gust_cross,
                    base_conditions["wind_speed"], base_conditions.get("wind_gust", 0),
                    base_is_head, base_gust_is_head, da_diff, new_metar, lat, lon, rwy_heading, None
                )
            else:
                wind_dir = perturbed_conditions.get("wind_dir", base_conditions["wind_dir"])
                wind_speed = perturbed_conditions.get("wind_speed", base_conditions["wind_speed"])
                wind_gust = perturbed_conditions.get("wind_gust", base_conditions.get("wind_gust", 0))
                
                head, cross, is_head = wind_components(rwy_heading, wind_dir, wind_speed)
                gust_head, gust_cross, gust_is_head = gust_components(rwy_heading, wind_dir, wind_gust)
                
                perturbed_rri, _ = calculate_rri(
                    head, cross, gust_head, gust_cross, wind_speed, wind_gust,
                    is_head, gust_is_head, da_diff, metar_data, lat, lon, rwy_heading, None
                )
            
            sensitivity = abs(perturbed_rri - base_rri) / delta
            sensitivities[param] = sensitivity
        
        return sensitivities

def calculate_advanced_probabilistic_rri(
    rwy_heading: float,
    base_conditions: Dict,
    da_diff: float,
    metar_data: Dict,
    lat: float,
    lon: float,
    num_draws: int = 1000,
    include_temporal: bool = False,
    include_extremes: bool = True,
    runway_length: Optional[int] = None,
    airport_elevation: Optional[int] = None,
    aircraft_category: str = "light"
) -> ProbabilisticResult:
    """
    Advanced probabilistic RRI calculation with comprehensive uncertainty analysis
    """
    
    perturbation_model = WeatherPerturbationModel()
    weather_perturber = AdvancedWeatherPerturber(perturbation_model)
    scenario_generator = ScenarioGenerator()
    statistical_analyzer = StatisticalAnalyzer()
    sensitivity_analyzer = SensitivityAnalyzer()
    
    rri_samples = []
    scenario_details = []
    
    for i in range(num_draws):
        scenario_type = "normal"
        if i < num_draws * 0.1:
            scenario_type = "deteriorating"
        elif i < num_draws * 0.2:
            scenario_type = "improving"
        
        perturbed_conditions = weather_perturber.perturb_correlated_weather(
            base_conditions, scenario_type
        )
        
        perturbed_metar = metar_data.copy()
        perturbed_metar["temp_c"] = perturbed_conditions["temp_c"]
        if "visibility" in perturbed_conditions:
            perturbed_metar["visibility"] = perturbed_conditions["visibility"]
        if "ceiling" in perturbed_conditions:
            perturbed_metar["ceiling"] = perturbed_conditions["ceiling"]
        
        if "altim_in_hg" in perturbed_conditions and airport_elevation:
            new_da_diff = density_alt(
                airport_elevation, 
                perturbed_conditions["temp_c"], 
                perturbed_conditions["altim_in_hg"]
            ) - airport_elevation
        else:
            new_da_diff = da_diff
        
        head, cross, is_head = wind_components(
            rwy_heading, perturbed_conditions["wind_dir"], perturbed_conditions["wind_speed"]
        )
        
        gust_head, gust_cross, gust_is_head = (0, 0, True)
        if perturbed_conditions.get("wind_gust", 0) > 0:
            gust_head, gust_cross, gust_is_head = gust_components(
                rwy_heading, perturbed_conditions["wind_dir"], perturbed_conditions["wind_gust"]
            )
        
        if runway_length and airport_elevation:
            rri_score, contributors = calculate_advanced_rri(
                head, cross, gust_head, gust_cross,
                perturbed_conditions["wind_speed"], perturbed_conditions.get("wind_gust", 0),
                is_head, gust_is_head, new_da_diff, perturbed_metar,
                lat, lon, rwy_heading, None, runway_length, airport_elevation,
                1.0, None, aircraft_category
            )
        else:
            rri_score, contributors = calculate_rri(
                head, cross, gust_head, gust_cross,
                perturbed_conditions["wind_speed"], perturbed_conditions.get("wind_gust", 0),
                is_head, gust_is_head, new_da_diff, perturbed_metar,
                lat, lon, rwy_heading, None
            )
        
        rri_samples.append(rri_score)
        scenario_details.append({
            "rri": rri_score,
            "conditions": perturbed_conditions,
            "scenario_type": scenario_type,
            "contributors": contributors
        })
    
    if include_extremes:
        extreme_scenarios = scenario_generator.generate_extreme_scenarios(base_conditions)
        for extreme in extreme_scenarios:
            extreme_metar = metar_data.copy()
            extreme_metar.update(extreme["conditions"])
            
            head, cross, is_head = wind_components(
                rwy_heading, extreme["conditions"]["wind_dir"], extreme["conditions"]["wind_speed"]
            )
            gust_head, gust_cross, gust_is_head = gust_components(
                rwy_heading, extreme["conditions"]["wind_dir"], extreme["conditions"].get("wind_gust", 0)
            )
            
            extreme_rri, _ = calculate_rri(
                head, cross, gust_head, gust_cross,
                extreme["conditions"]["wind_speed"], extreme["conditions"].get("wind_gust", 0),
                is_head, gust_is_head, da_diff, extreme_metar,
                lat, lon, rwy_heading, None
            )
            
            rri_samples.append(extreme_rri)
    
    temporal_evolution = None
    if include_temporal:
        temporal_scenarios = scenario_generator.generate_temporal_scenarios(base_conditions)
        temporal_evolution = []
        
        for temporal in temporal_scenarios:
            temp_metar = metar_data.copy()
            temp_metar.update(temporal["conditions"])
            
            head, cross, is_head = wind_components(
                rwy_heading, temporal["conditions"]["wind_dir"], temporal["conditions"]["wind_speed"]
            )
            gust_head, gust_cross, gust_is_head = gust_components(
                rwy_heading, temporal["conditions"]["wind_dir"], temporal["conditions"].get("wind_gust", 0)
            )
            
            temporal_rri, _ = calculate_rri(
                head, cross, gust_head, gust_cross,
                temporal["conditions"]["wind_speed"], temporal["conditions"].get("wind_gust", 0),
                is_head, gust_is_head, da_diff, temp_metar,
                lat, lon, rwy_heading, None
            )
            
            temporal_evolution.append({
                "time_offset": temporal["time_offset"],
                "rri": temporal_rri,
                "confidence": temporal["confidence"],
                "conditions": temporal["conditions"]
            })
    
    percentiles = statistical_analyzer.calculate_percentiles(rri_samples)
    statistics = statistical_analyzer.calculate_comprehensive_statistics(rri_samples)
    risk_distribution = statistical_analyzer.analyze_risk_distribution(rri_samples)
    
    extreme_scenarios_analysis = [
        scenario for scenario in scenario_details 
        if scenario["rri"] >= float(np.percentile(rri_samples, 95))
    ][:10]
    
    sensitivity_analysis = sensitivity_analyzer.calculate_parameter_sensitivity(
        base_conditions, rwy_heading, da_diff, metar_data, lat, lon
    )
    
    confidence_intervals = {
        "90_percent": (percentiles["p05"], percentiles["p95"]),
        "80_percent": (percentiles["p10"], percentiles["p90"]),
        "50_percent": (percentiles["p25"], percentiles["p75"])
    }
    
    scenario_clusters = {
        "normal": [s for s in scenario_details if s["scenario_type"] == "normal"],
        "deteriorating": [s for s in scenario_details if s["scenario_type"] == "deteriorating"],
        "improving": [s for s in scenario_details if s["scenario_type"] == "improving"]
    }
    
    result = ProbabilisticResult(
        percentiles=convert_numpy_types(percentiles),
        statistics=convert_numpy_types(statistics),
        risk_distribution=convert_numpy_types(risk_distribution),
        extreme_scenarios=convert_numpy_types(extreme_scenarios_analysis),
        sensitivity_analysis=convert_numpy_types(sensitivity_analysis),
        confidence_intervals=convert_numpy_types(confidence_intervals),
        scenario_clusters=convert_numpy_types(scenario_clusters),
        temporal_evolution=convert_numpy_types(temporal_evolution)
    )
    
    return result

def calculate_probabilistic_rri_monte_carlo(
    rwy_heading: float,
    original_wind_dir: int,
    original_wind_speed: int,
    original_wind_gust: int,
    da_diff: float,
    metar_data: dict,
    lat: float,
    lon: float,
    num_draws: int = 500
) -> Dict[str, float]:
    """
    Legacy function maintained for backward compatibility
    For new implementations, use calculate_advanced_probabilistic_rri()
    """
    
    base_conditions = {
        "wind_dir": original_wind_dir,
        "wind_speed": original_wind_speed,
        "wind_gust": original_wind_gust if original_wind_gust > 0 else 0,
        "temp_c": metar_data.get("temp_c", 15)
    }
    
    result = calculate_advanced_probabilistic_rri(
        rwy_heading, base_conditions, da_diff, metar_data, lat, lon, num_draws
    )
    
    return {
        "rri_p05": convert_numpy_types(result.percentiles["p05"]),
        "rri_p95": convert_numpy_types(result.percentiles["p95"])
    } 