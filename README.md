# RunwayGuard 🛫

> Real-time runway risk assessment powered by advanced meteorological analysis and machine learning

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.8+](https://img.shields.io/badge/python-3.8+-blue.svg)](https://www.python.org/downloads/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.68+-00a393.svg)](https://fastapi.tiangolo.com)

RunwayGuard is a next-generation aviation safety system that provides real-time runway risk assessment through sophisticated multi-factor analysis. It helps pilots and aviation professionals make informed decisions about runway operations by analyzing weather conditions, calculating density altitude, and providing plain-English advisories.

## 🎯 Key Features

- **Real-time Risk Assessment**: Instant calculation of Runway Risk Index (RRI) based on current conditions
- **Comprehensive Weather Analysis**: Integration with aviation weather services for METAR, TAF, and NOTAMs
- **Smart Wind Components**: Advanced calculations of headwind, crosswind, and gust factors
- **Density Altitude**: Precise computation considering temperature, pressure, and elevation
- **AI-Powered Advisories**: Plain-English summaries powered by OpenAI (optional)
- **Probabilistic Risk Modeling**: Monte Carlo simulation for confidence intervals
- **Time-Based Risk Factors**: Solar position and visibility considerations
- **REST API**: Easy integration with existing aviation systems

## 🚀 Quick Start

1. Clone the repository:
```bash
git clone https://github.com/yourusername/runwayguard.git
cd runwayguard
```

2. Install dependencies:
```bash
pip install -r requirements.txt
```

3. Set up environment variables:
```bash
cp .env.example .env
# Edit .env with your API keys and settings
```

4. Run the server:
```bash
uvicorn runwayguard:app --reload
```

5. Make a test request:
```bash
curl -X POST "http://localhost:8000/brief" \
     -H "Content-Type: application/json" \
     -d '{"icao": "KABI"}'
```

## 💡 How It Works

RunwayGuard uses a sophisticated algorithm to calculate a Runway Risk Index (RRI) from 0-100:

- **LOW Risk (0-25)**: Favorable conditions
- **MODERATE Risk (26-50)**: Exercise normal caution
- **HIGH Risk (51-75)**: Enhanced vigilance required
- **EXTREME Risk (76-100)**: Operations not recommended

### Risk Factors Include:

- Wind components (headwind/crosswind)
- Gust factors
- Density altitude
- Ceiling and visibility
- Time of day considerations
- Weather phenomena (TS, LTG, etc.)
- NOTAMs and runway closures

### Sample Response:

```json
{
  "runway": "17",
  "headwind_kt": 8,
  "crosswind_kt": 12,
  "density_altitude_ft": 2500,
  "runway_risk_index": 45,
  "status": "CAUTION",
  "plain_summary": "Moderate crosswind conditions with elevated density altitude..."
}
```

## 🎯 Use Cases

### For Pilots
- Pre-flight runway selection
- Real-time risk assessment
- Training and familiarization
- Weather trend monitoring

### For Flight Schools
- Student pilot guidance
- Training scenario development
- Risk management education
- Standard operating procedures

### For Airport Operations
- Runway assignment optimization
- Safety management systems
- Operational risk monitoring
- Historical trend analysis

## 🔬 Technical Details

RunwayGuard employs several sophisticated algorithms and real-time data processing techniques:

### Core Algorithms

1. **Wind Component Analysis**
   ```python
   # Vector decomposition for precise wind effects
   rad_diff = math.radians((wind_dir_deg - rwy_heading_deg) % 360)
   headwind = wind_speed_kt * math.cos(rad_diff)
   crosswind = wind_speed_kt * math.sin(rad_diff)
   ```
   - Handles variable wind directions
   - Processes gust components separately
   - Accounts for runway magnetic variation

2. **Density Altitude Computation**
   ```python
   pressure_altitude = field_elevation + (29.92 - altimeter) * 1000
   isa_temp = 15 - 2 * (field_elevation / 1000)
   density_altitude = pressure_altitude + 120 * (temp - isa_temp)
   ```
   - Temperature range validation (-60°C to +50°C)
   - Altitude range checks (-1000 to 20000 ft)
   - ISA deviation calculations

3. **Probabilistic Risk Assessment**
   - Monte Carlo simulation (500 iterations)
   - Wind variations:
     * Direction: ±5 degrees
     * Speed: ±2 knots
   - Preserves gust differentials
   - Confidence intervals (5th to 95th percentile)

4. **Solar Position Analysis**
   ```python
   # Complex solar calculations for time-based risk
   zenith_angle = acos(sin(lat) * sin(decl) + 
                      cos(lat) * cos(decl) * cos(hour_angle))
   ```
   - Day/Night/Twilight determination
   - Runway-specific glare analysis
   - Seasonal variation handling

### Risk Scoring System

#### Wind-Based Risk Factors
- **Tailwind**: 6 points/kt (max 30)
- **Crosswind**: 2 points/kt (max 30)
- **Gust Differential**: 2 points/kt (max 20)
- **Gust Effects**:
  * Tailwind: 1 point/kt (max 10)
  * Crosswind: 0.5 points/kt (max 10)

#### Environmental Risk Factors
- **Density Altitude**: 0.015 points/ft above field (max 30)
- **Time of Day**: Up to 30 points based on:
  * Night operations: +20
  * Twilight conditions: +15
  * Sun glare: Up to +25

#### Weather Phenomena Scoring
| Condition | Risk Points | Notes |
|-----------|-------------|-------|
| Thunderstorm (TS) | 100 | Automatic EXTREME |
| Lightning (LTG) | +25 | Cumulative |
| Funnel Cloud (FC) | 100 | Automatic EXTREME |
| Hail (GR) | +40 | Cumulative |
| Freezing Precip (FZ) | +30 | Cumulative |
| Heavy Precip (+) | +20 | Cumulative |

#### Ceiling & Visibility Points
| Ceiling (ft) | Points | Visibility (SM) | Points |
|--------------|--------|-----------------|--------|
| < 500 | +40 | < 1 | +40 |
| < 1000 | +30 | < 2 | +30 |
| < 2000 | +20 | < 3 | +20 |
| < 3000 | +10 | < 5 | +10 |

### Data Integration

1. **Weather Data Sources**
   - METAR parsing and validation
   - TAF trend analysis
   - NOTAM integration
   - Station information correlation

2. **Caching System**
   ```python
   BUCKET_SECONDS = 60  # Cache lifetime
   _cached = {}  # In-memory cache
   ```
   - Efficient data retrieval
   - Automatic cache invalidation
   - Request rate optimization

3. **Error Handling**
   - Input validation
   - Data consistency checks
   - Graceful fallbacks
   - Detailed error reporting

## 🎯 Extended Use Cases

### For Pilots

#### Pre-flight Planning
- Runway selection optimization
- Density altitude trend analysis
- Crosswind component visualization
- Go/No-Go decision support

#### In-flight Updates
- Real-time risk trend monitoring
- Diversion planning assistance
- Alternative runway assessment
- Weather trend analysis

#### Training Scenarios
- Risk assessment practice
- Weather interpretation skills
- Decision-making exercises
- Performance planning

### For Flight Schools

#### Student Training
- Progressive risk introduction
- Scenario-based training
- Weather minimums compliance
- Performance calculations

#### Instructor Tools
- Demonstration scenarios
- Risk management teaching
- Student progress tracking
- Standardized assessments

### For Airport Operations

#### Safety Management
- Real-time risk monitoring
- Trend analysis and reporting
- Incident prevention
- Resource allocation

#### Efficiency Optimization
- Runway usage patterns
- Traffic flow management
- Maintenance planning
- Capacity optimization

### For Developers

#### API Integration
- RESTful endpoints
- JSON response format
- Rate limiting controls
- Error handling patterns

#### Custom Applications
- Mobile app development
- Flight planning software
- Training simulators
- Safety management systems

## 🔧 Advanced Features

### Probabilistic Analysis
- Confidence interval reporting
- Risk trend prediction
- Uncertainty quantification
- Variable sensitivity analysis

### Time-Based Risk Factors
- Solar position calculations
- Circadian considerations
- Seasonal adjustments
- Local conditions

### Weather Pattern Analysis
- Trend identification
- Severity assessment
- Pattern recognition
- Impact prediction

### Performance Optimization
- Async API calls
- Efficient caching
- Request batching
- Response compression

## ⚠️ Important Notes

- RunwayGuard is an advisory tool only
- Always follow official weather briefings
- Consult your aircraft's operating handbook
- Use in conjunction with proper flight planning
- Not a replacement for pilot judgment

## 🤝 Contributing

We welcome contributions! Please see our [Contributing Guide](CONTRIBUTING.md) for details.

1. Fork the repository
2. Create your feature branch
3. Commit your changes
4. Push to the branch
5. Create a Pull Request

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## 🙏 Acknowledgments

- Aviation Weather Center for weather data
- OpenAI for natural language processing
- FastAPI team for the web framework
- Aviation community for feedback and support

## 📚 Further Reading

<!-- - [Technical Documentation](docs/technical.md)
- [API Reference](docs/api.md) -->
- [Algorithm Details](docs/algorithm.md)
- [Deployment Guide](docs/deployment.md)

---

*RunwayGuard is not certified for use in operational decision-making. Always follow official weather sources and aircraft limitations.*
