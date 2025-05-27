# RunwayGuard ARRI
## Advanced Runway Risk Intelligence

**Professional runway safety assessment for pilots and flight operations**

*A product of [OpenTurf.org](https://openturf.org) - Copyright © awade12*

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.8+](https://img.shields.io/badge/python-3.8+-blue.svg)](https://www.python.org/downloads/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.68+-00a393.svg)](https://fastapi.tiangolo.com)

---

## What is RunwayGuard?

RunwayGuard transforms complex weather data into clear runway risk assessments. Used by flight schools, charter operators, and professional pilots for enhanced safety decision-making.

**Key Features:**
- Real-time weather analysis from multiple sources (METAR, TAF, NOTAMs, PIREPs)
- Aircraft-specific performance calculations (C172 to Citation jets)
- Experience-based risk thresholds (student to ATP)
- Monte Carlo simulation for confidence intervals
- Plain English summaries with actionable recommendations

## Quick Start

```bash
# Setup
git clone https://github.com/andrewwade/runwayguard.git
cd runwayguard
pip install -r requirements.txt
cp .env.example .env  # Add your API keys

# Run
uvicorn main:app --reload

# Test
curl -X POST "http://localhost:8000/v1/brief" \
     -H "Content-Type: application/json" \
     -d '{"icao": "KDFW", "aircraft_type": "c172", "pilot_experience": "commercial"}'
```

## Risk Assessment Engine

### Weather Analysis
- **Atmospheric modeling** - thermal gradients, stability indices, temperature inversions
- **Precipitation analysis** - 12 types with intensity and contamination effects
- **Wind analysis** - crosswind, gusts, shear detection
- **Visibility assessment** - fog, haze, precipitation impacts

### Performance Calculations
- **Runway adequacy** - length vs aircraft requirements with contamination factors
- **Density altitude effects** - temperature and pressure altitude corrections
- **Weight considerations** - performance degradation modeling
- **Seasonal adjustments** - time-based atmospheric effects

### Risk Scoring

| Level | Score | Status | Description |
|-------|-------|--------|-------------|
| 🟢 LOW | 0-25 | GO | Excellent conditions |
| 🟡 MODERATE | 26-50 | CAUTION | Manageable challenges |
| 🟠 HIGH | 51-75 | CAUTION | Significant challenges |
| 🔴 EXTREME | 76-100 | NO-GO | Dangerous conditions |

## Aircraft & Pilot Profiles

**Aircraft Types:**
- `c172` - Cessna 172 (2000ft runway requirement)
- `pa34` - Piper Seneca (2500ft runway requirement)
- `tbm` - TBM Series (3000ft runway requirement)
- `citation` - Citation Jets (3500ft runway requirement)

**Experience Levels:**
- `student` - Conservative thresholds (0.8x)
- `private` - Standard thresholds (1.0x)
- `commercial` - Standard thresholds (1.0x)
- `atp` - Aggressive thresholds (1.2x)

## Example Output

```json
{
  "runway_risk_index": 32,
  "risk_category": "MODERATE",
  "status": "CAUTION",
  "plain_summary": "Moderate crosswind conditions with good visibility. Runway performance adequate with 500ft margin.",
  "weather_summary": {
    "wind": "240° at 12kt, gusting 18kt",
    "visibility": "10+ miles",
    "ceiling": "Few clouds at 3000ft"
  },
  "risk_factors": {
    "crosswind_component": 8,
    "runway_performance": 15,
    "atmospheric_conditions": 9
  },
  "recommendations": [
    "Monitor wind conditions - gusts approaching limits",
    "Consider runway 24L for better wind alignment"
  ]
}
```

## SMS Integration

Get briefings via text message:

```
Text: KDFW C172 PRIVATE
Reply: KDFW RWY18R: GO
       RRI: 25/100 (LOW)
       Wind: 180°@8kt, X: +8kt
       RunwayGuard.com
```

**Supported formats:**
- Aircraft: `C172`, `TWIN`, `TURBO`, `JET`
- Experience: `STUDENT`, `PRIVATE`, `COMMERCIAL`, `ATP`

## API Reference

### POST /v1/brief
```json
{
  "icao": "KDFW",
  "aircraft_type": "c172",
  "pilot_experience": "commercial"
}
```

### GET /v1/brief/help
Complete API documentation and examples.

**Rate limits:**
- Brief endpoint: 20 requests/minute
- Help endpoint: 60 requests/minute

## Technical Details

**Architecture:**
- Python 3.8+ with FastAPI
- Async processing for concurrent weather data retrieval
- Redis caching for performance
- Comprehensive input validation

**Data Sources:**
- METAR (hourly observations)
- TAF (terminal forecasts)
- NOTAMs (real-time notices)
- PIREPs (pilot reports)
- SIGMETs/AIRMETs (significant weather)

**Performance:**
- Response time: <500ms average
- Coverage: 5,000+ airports worldwide
- Uptime target: 99.9%

## Documentation

- [Algorithm Details](docs/algorithm.md)
- [Advanced Risk Analysis](docs/advanced_risk_analysis.md)
- [API Enhancement Guide](docs/api_enhancement_summary.md)
- [Usage Examples](docs/example/)

## Development

```bash
# Development setup
git clone https://github.com/andrewwade/runwayguard.git
cd runwayguard
pip install -r requirements.txt
pip install -r requirements-dev.txt

# Run tests
pytest tests/

# Submit improvements
git checkout -b feature/improvement
# Make changes...
git commit -m "Description of changes"
git push origin feature/improvement
```

## Safety Notice

⚠️ **RunwayGuard is an advisory tool only**

- Always consult official weather briefings and NOTAMs
- Follow your aircraft's operating limitations
- Use proper flight planning procedures
- Not a replacement for pilot judgment
- Not certified for operational decision-making

## Support

- **Issues:** [GitHub Issues](https://github.com/andrewwade/runwayguard/issues)
- **Features:** [GitHub Discussions](https://github.com/andrewwade/runwayguard/discussions)
- **Commercial:** andrew@openturf.org
- **Documentation:** [docs/](docs/)

## License

MIT License - see [LICENSE.md](LICENSE.md)

---

**RunwayGuard ARRI** - Professional runway risk assessment for safer aviation operations.

*Built by pilots, for pilots. A product of [OpenTurf.org](https://openturf.org)*
