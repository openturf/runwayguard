"""
Probabilistic Risk Analysis

This handles uncertainty in runway risk calculations using Monte Carlo simulation.
Weather conditions aren't perfectly predictable, so this runs hundreds of slightly
different scenarios to give you confidence intervals.

The main function takes your current conditions and wiggles the wind direction,
speed, and gusts within realistic ranges. Then it calculates RRI for each scenario
and gives you the 5th and 95th percentile results.

This helps answer: "What's the worst-case scenario if conditions shift slightly?"
versus "What's the best case if things improve a bit?"
"""

import random
import math
from .core_calculations import calculate_rri, wind_components, gust_components

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
):
    rri_samples = []

    original_gust_differential = 0
    if original_wind_gust > 0 and original_wind_speed >= 0:
        original_gust_differential = original_wind_gust - original_wind_speed

    for _ in range(num_draws):
        perturbed_wind_dir = original_wind_dir + random.uniform(-5, 5)
        
        perturbed_wind_speed = original_wind_speed + random.uniform(-2, 2)
        perturbed_wind_speed = max(0, perturbed_wind_speed)

        perturbed_wind_gust = 0
        if original_wind_gust > 0:
            perturbed_wind_gust_candidate = perturbed_wind_speed + original_gust_differential
            perturbed_wind_gust = max(perturbed_wind_speed, perturbed_wind_gust_candidate)
            perturbed_wind_gust = max(0, perturbed_wind_gust)
        
        p_head, p_cross, p_is_head = wind_components(
            rwy_heading, perturbed_wind_dir, perturbed_wind_speed
        )

        p_gust_head, p_gust_cross, p_gust_is_head = (0, 0, True)
        if perturbed_wind_gust > 0:
            p_gust_head, p_gust_cross, p_gust_is_head = gust_components(
                rwy_heading, perturbed_wind_dir, perturbed_wind_gust
            )
        
        current_rri_score, _ = calculate_rri(
            p_head, p_cross, 
            p_gust_head, p_gust_cross,
            perturbed_wind_speed, 
            perturbed_wind_gust, 
            p_is_head, p_gust_is_head, 
            da_diff, metar_data, lat, lon, rwy_heading, None
        )
        rri_samples.append(current_rri_score)

    if not rri_samples:
        return {"rri_p05": None, "rri_p95": None}

    rri_samples.sort()
    
    p05_index = math.floor((num_draws - 1) * 0.05)
    p95_index = math.floor((num_draws - 1) * 0.95)
    
    p05_index = max(0, min(num_draws - 1, p05_index))
    p95_index = max(0, min(num_draws - 1, p95_index))

    rri_p05 = rri_samples[p05_index]
    rri_p95 = rri_samples[p95_index]
    
    return {"rri_p05": rri_p05, "rri_p95": rri_p95} 