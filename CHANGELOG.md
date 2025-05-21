# Changelog

All notable changes to **RunwayGuard** will be documented in this file.

This project follows [Semantic Versioning](https://semver.org/).

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
