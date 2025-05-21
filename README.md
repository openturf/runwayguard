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

RunwayGuard employs several sophisticated algorithms:

1. **Wind Component Analysis**
   ```python
   headwind = wind_speed * cos(θ)
   crosswind = wind_speed * sin(θ)
   ```

2. **Density Altitude Computation**
   ```python
   pressure_altitude = field_elevation + (29.92 - altimeter) * 1000
   density_altitude = pressure_altitude + 120 * (temp - isa_temp)
   ```

3. **Probabilistic Risk Assessment**
   - Monte Carlo simulation with 500 iterations
   - Confidence intervals (5th to 95th percentile)
   - Natural variability modeling

For detailed algorithm documentation, see [Algorithm Documentation](docs/algorithm.md).

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
