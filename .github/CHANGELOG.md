# Changelog

All notable changes to **RunwayGuard** will be documented in this file.

This project follows [Semantic Versioning](https://semver.org/).

---

## [0.5.0] – 2025-01-27

### Added
- **Enhanced RRI Algorithm** with comprehensive new risk factors
  * **Icing Risk Assessment** (max 30 points)
    - Freezing precipitation detection (30 points)
    - Prime icing conditions analysis (0°C to +2°C with clouds, 25 points)
    - Temperature range icing risk (-10°C to 0°C with clouds, 20 points)
    - High humidity icing risk using dewpoint spread (15 points)
    - Ice pellet detection (20 points)
  * **Temperature Performance Risk** (max 25 points)
    - High temperature performance degradation (>35°C, 15 points)
    - Elevated temperature effects (>30°C, 10 points)
    - Very cold weather system impacts (<-20°C, 15 points)
    - Cold weather risks (<-10°C, 10 points)
    - Combined high density altitude and temperature risk (10 points)
  * **Wind Shear Risk Assessment** (max 25 points)
    - Thunderstorm-related wind shear detection (25 points)
    - Shower activity wind shear indicators (15 points)
  * **Enhanced Weather Condition Parsing**
    - Volcanic ash detection (100 points, automatic EXTREME)
    - Squall line activity (30 points)
    - Dust/sand storm conditions (20 points)
    - Fog condition analysis (15 points)
    - Mist/haze visibility reduction (5 points)
  * **NOTAM Risk Integration** (max 25 points)
    - Runway contamination detection (snow/ice/slush/wet, 20 points)
    - Construction and obstacle warnings (15 points)
    - Navigation equipment outage alerts (10 points)

### Enhanced
- **METAR Data Parsing**
  * Added dewpoint temperature extraction for improved icing analysis
  * Enhanced weather phenomenon detection accuracy
  * Improved temperature/dewpoint validation and error handling
- **NOTAM Processing**
  * Added raw NOTAM text parsing for contamination detection
  * Enhanced closed runway detection with additional risk factors
- **Risk Warning System**
  * Integrated all new risk factors into pilot warning messages
  * Enhanced advisory generation with detailed risk explanations
  * Improved risk contributor tracking and reporting

### Technical
- Updated `calculate_rri()` function signature to accept NOTAM data
- Enhanced probabilistic RRI calculations with new risk factors
- Improved modular risk assessment with dedicated calculation functions
- Enhanced data validation and error handling throughout risk pipeline

---

## [0.4.2] – 2025-05-26

### Added
- Example outputs section in README.md
  * Added visual example output for KDFW
  * Enhanced documentation with real-world use case
  * Improved user understanding with visual aids

---

## [0.4.1] – 2025-05-26

### Added
- Enhanced `/v1/info` endpoint with comprehensive API information
  * System version and status details
  * Detailed feature documentation
  * Weather integration capabilities
  * Risk assessment descriptions
  * Real-time operational status

### Changed
- Updated main router configuration to include info endpoints
- Improved API documentation with proper GitHub repository links

---

## [0.4.0] – 2025-05-25

### Added
- `CODE_OF_CONDUCT.md` establishing community guidelines and standards
- `CONTRIBUTING.md` with comprehensive contribution workflows and project structure
- Detailed documentation for developers, pilots, and educators

---

## [0.3.0] – 2025-05-20

### Added
- `CONTRIBUTING.md` with clear dev and educator guidance
- `CODE_OF_CONDUCT.md` for community standards
- Expanded algorithm documentation (density altitude, crosswind penalty details)
- Realistic sample scenarios and static METAR inputs (in `samples/`)

### Changed
- Modularized FastAPI routes into separate files
- Improved docstrings for calculation functions
- Refactored RRI scoring logic for better readability

---

## [0.2.0] – 2025-05-12

### Added
- `/brief` endpoint for real-time runway risk analysis
- RRI scoring system with multi-factor scoring model
- Density altitude, solar angle, and Monte Carlo simulation logic
- GPT integration for advisory generation
- Initial README and deployment instructions

---

## [0.1.0] – 2025-05-01

### Initial Release
- FastAPI scaffold with core runway safety logic
- METAR/TAF fetch functions
- Wind and risk factor calculations (non-ML)
