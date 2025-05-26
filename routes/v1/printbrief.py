"""
PDF Brief Generation Endpoint for RunwayGuard

This endpoint provides the same comprehensive runway risk analysis as /brief
but generates a professional PDF report suitable for printing or archiving.
The PDF includes all weather data, risk analysis, charts, and recommendations
in a pilot-friendly format.

Supports the same aircraft types and pilot experience levels as the main brief
endpoint, with identical risk calculations and thresholds. Rate limited to
10 requests per minute due to PDF generation overhead.

Copyright by awade12(openturf.org)
"""

import os
import io
import math
import time
import re
import logging
import html
from datetime import datetime
from typing import Optional, Dict, Any, List
from pydantic import BaseModel, validator
from fastapi import Request, status, HTTPException
from fastapi.responses import StreamingResponse
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter, A4
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, PageBreak
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.graphics.shapes import Drawing
from reportlab.graphics.charts.linecharts import HorizontalLineChart
from reportlab.graphics.charts.barcharts import VerticalBarChart
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT

from fastapi import APIRouter
from slowapi import Limiter
from slowapi.util import get_remote_address
from functions.core.time_factors import calculate_time_risk_factor
from functions.core.core_calculations import pressure_alt, density_alt, wind_components, gust_components, calculate_rri, calculate_advanced_rri, get_rri_category, get_status_from_rri
from functions.core.probabilistic_rri import calculate_probabilistic_rri_monte_carlo, calculate_advanced_probabilistic_rri
from functions.data_sources.weather_fetcher import fetch_metar, fetch_taf, fetch_notams, fetch_stationinfo, fetch_gairmet, fetch_sigmet, fetch_isigmet, fetch_pirep, fetch_cwa, fetch_windtemp, fetch_areafcst, fetch_fcstdisc, fetch_mis
from functions.data_sources.getairportinfo import fetch_airport_info
from functions.core.route_analysis import analyze_route
from dotenv import load_dotenv
from functions.config.advanced_config import ConfigurationManager
from functions.infrastructure.database import get_database

load_dotenv()

logger = logging.getLogger(__name__)

router = APIRouter()

limiter = Limiter(key_func=get_remote_address)

def get_client_ip(request: Request) -> str:
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"

def clean_html_for_pdf(text: str) -> str:
    """Clean HTML content for safe use in PDF generation"""
    if not text or text.strip() == "":
        return "None"
    
    # Convert to string if not already
    text = str(text)
    
    # Remove HTML tags completely
    clean_text = re.sub(r'<[^>]+>', '', text)
    
    # Decode HTML entities
    try:
        clean_text = html.unescape(clean_text)
    except Exception:
        pass  # If unescape fails, continue with original text
    
    # Remove extra whitespace and newlines
    clean_text = re.sub(r'\s+', ' ', clean_text).strip()
    
    # Remove non-printable characters
    clean_text = re.sub(r'[^\x20-\x7E]', '', clean_text)
    
    # Escape special characters for ReportLab
    clean_text = clean_text.replace('&', '&amp;')
    clean_text = clean_text.replace('<', '&lt;')
    clean_text = clean_text.replace('>', '&gt;')
    
    # Handle specific problematic patterns
    clean_text = re.sub(r'rel\s*=\s*["\'][^"\']*["\']', '', clean_text)
    clean_text = re.sub(r'href\s*=\s*["\'][^"\']*["\']', '', clean_text)
    
    # Truncate if too long for PDF display
    if len(clean_text) > 1000:
        clean_text = clean_text[:997] + "..."
    
    return clean_text if clean_text and clean_text.strip() else "No data available"

class APIError(Exception):
    def __init__(self, message: str, status_code: int = 500, details: Optional[Dict[str, Any]] = None):
        self.message = message
        self.status_code = status_code
        self.details = details or {}
        super().__init__(self.message)

class BriefRequest(BaseModel):
    icao: str
    aircraft_type: Optional[str] = "light"
    pilot_experience: Optional[str] = "standard"
    
    @validator('icao')
    def validate_icao(cls, v):
        v = v.upper()
        if not re.match(r'^[A-Z0-9]{3,4}$', v):
            raise ValueError('ICAO code must be 3-4 alphanumeric characters')
        return v

class RouteRequest(BaseModel):
    airports: List[str]
    aircraft_type: Optional[str] = "light"
    pilot_experience: Optional[str] = "standard"
    route_distances: Optional[List[float]] = None
    
    @validator('airports')
    def validate_airports(cls, v):
        if len(v) < 2:
            raise ValueError('Route must include at least departure and destination airports')
        if len(v) > 10:
            raise ValueError('Route analysis limited to 10 airports maximum')
        
        validated_airports = []
        for airport in v:
            airport = airport.upper()
            if not re.match(r'^[A-Z0-9]{3,4}$', airport):
                raise ValueError(f'Invalid ICAO code: {airport}')
            validated_airports.append(airport)
        return validated_airports
    
    @validator('route_distances')
    def validate_distances(cls, v, values):
        if v is not None:
            airports = values.get('airports', [])
            if len(v) != len(airports) - 1:
                raise ValueError('Route distances must have one less entry than airports')
            if any(d <= 0 for d in v):
                raise ValueError('All distances must be positive')
        return v

class PDFGenerator:
    def __init__(self):
        self.styles = getSampleStyleSheet()
        self.title_style = ParagraphStyle(
            'CustomTitle',
            parent=self.styles['Heading1'],
            fontSize=20,
            spaceAfter=20,
            spaceBefore=10,
            alignment=TA_CENTER,
            textColor=colors.darkblue,
            fontName='Helvetica-Bold'
        )
        self.heading_style = ParagraphStyle(
            'CustomHeading',
            parent=self.styles['Heading2'],
            fontSize=14,
            spaceAfter=8,
            spaceBefore=15,
            textColor=colors.darkblue,
            fontName='Helvetica-Bold'
        )
        self.subheading_style = ParagraphStyle(
            'SubHeading',
            parent=self.styles['Heading3'],
            fontSize=12,
            spaceAfter=6,
            spaceBefore=10,
            textColor=colors.darkgreen,
            fontName='Helvetica-Bold'
        )
        self.warning_style = ParagraphStyle(
            'Warning',
            parent=self.styles['Normal'],
            fontSize=10,
            textColor=colors.red,
            backColor=colors.mistyrose,
            borderColor=colors.red,
            borderWidth=1,
            leftIndent=10,
            rightIndent=10,
            topPadding=5,
            bottomPadding=5,
            spaceAfter=6
        )
        self.good_style = ParagraphStyle(
            'Good',
            parent=self.styles['Normal'],
            fontSize=10,
            textColor=colors.darkgreen,
            backColor=colors.lightgreen,
            borderColor=colors.green,
            borderWidth=1,
            leftIndent=10,
            rightIndent=10,
            topPadding=5,
            bottomPadding=5,
            spaceAfter=6
        )
        self.caution_style = ParagraphStyle(
            'Caution',
            parent=self.styles['Normal'],
            fontSize=10,
            textColor=colors.darkorange,
            backColor=colors.lightyellow,
            borderColor=colors.orange,
            borderWidth=1,
            leftIndent=10,
            rightIndent=10,
            topPadding=5,
            bottomPadding=5,
            spaceAfter=6
        )
        self.data_style = ParagraphStyle(
            'DataStyle',
            parent=self.styles['Normal'],
            fontSize=9,
            textColor=colors.black,
            fontName='Courier',
            leftIndent=5,
            spaceAfter=3
        )
        self.summary_style = ParagraphStyle(
            'Summary',
            parent=self.styles['Normal'],
            fontSize=11,
            textColor=colors.darkblue,
            backColor=colors.aliceblue,
            borderColor=colors.blue,
            borderWidth=1,
            leftIndent=10,
            rightIndent=10,
            topPadding=8,
            bottomPadding=8,
            spaceAfter=10
        )
        
    def create_brief_pdf(self, brief_data: Dict, icao: str) -> io.BytesIO:
        buffer = io.BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=letter, rightMargin=50, leftMargin=50, topMargin=50, bottomMargin=50)
        
        story = []
        
        # Header with logo-style title
        story.append(Paragraph("🛫 RUNWAYGUARD", self.title_style))
        story.append(Paragraph(f"Professional Aviation Risk Assessment - {icao}", self.styles['Normal']))
        story.append(Paragraph(f"Generated: {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}", self.styles['Normal']))
        story.append(Spacer(1, 20))
        
        # Executive Summary Box
        runway_briefs = brief_data.get('runway_briefs', [])
        if runway_briefs:
            best_runway = min(runway_briefs, key=lambda x: x.get('runway_risk_index', 100))
            worst_runway = max(runway_briefs, key=lambda x: x.get('runway_risk_index', 0))
            
            summary_text = f"""
            <b>EXECUTIVE SUMMARY:</b><br/>
            Best Runway: {best_runway.get('runway', 'N/A')} (RRI: {best_runway.get('runway_risk_index', 'N/A')}/100 - {best_runway.get('status', 'N/A')})<br/>
            Worst Runway: {worst_runway.get('runway', 'N/A')} (RRI: {worst_runway.get('runway_risk_index', 'N/A')}/100 - {worst_runway.get('status', 'N/A')})<br/>
            Total Runways Analyzed: {len(runway_briefs)}<br/>
            Processing Time: {brief_data.get('processing_time_seconds', 'N/A')} seconds
            """
            story.append(Paragraph(summary_text, self.summary_style))
            story.append(Spacer(1, 15))
        
        # Airport Information Section
        airport_info = brief_data.get('airport_info', {})
        if airport_info:
            story.append(Paragraph("🏢 AIRPORT INFORMATION", self.heading_style))
            
            # Enhanced airport table with more data
            airport_table_data = [
                ['Airport Name:', airport_info.get('name', 'N/A')],
                ['ICAO Code:', icao],
                ['IATA Code:', airport_info.get('iata', 'N/A')],
                ['Elevation:', f"{airport_info.get('elevation', 'N/A')} ft MSL"],
                ['Magnetic Declination:', f"{airport_info.get('mag_dec', 'N/A')}°"],
                ['City:', airport_info.get('city', 'N/A')],
                ['State/Country:', airport_info.get('state', 'N/A')],
                ['Latitude:', f"{airport_info.get('latitude', 'N/A')}°"],
                ['Longitude:', f"{airport_info.get('longitude', 'N/A')}°"]
            ]
            
            # Add runway information
            runways = airport_info.get('runways', [])
            if runways:
                runway_info = []
                for rwy in runways:
                    rwy_text = f"{rwy.get('id', 'N/A')} ({rwy.get('heading', 'N/A')}°"
                    if rwy.get('length'):
                        rwy_text += f", {rwy.get('length')}ft"
                    if rwy.get('surface'):
                        rwy_text += f", {rwy.get('surface')}"
                    rwy_text += ")"
                    runway_info.append(rwy_text)
                airport_table_data.append(['Runways:', '; '.join(runway_info)])
            
            airport_table = Table(airport_table_data, colWidths=[2*inch, 4*inch])
            airport_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (0, -1), colors.lightsteelblue),
                ('TEXTCOLOR', (0, 0), (-1, -1), colors.black),
                ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
                ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
                ('FONTSIZE', (0, 0), (-1, -1), 9),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
                ('TOPPADDING', (0, 0), (-1, -1), 8),
                ('BACKGROUND', (1, 0), (1, -1), colors.white),
                ('GRID', (0, 0), (-1, -1), 1, colors.darkblue),
                ('VALIGN', (0, 0), (-1, -1), 'TOP')
            ]))
            story.append(airport_table)
            story.append(Spacer(1, 20))
        
        # Current Weather Section
        metar = brief_data.get('metar', {})
        if metar:
            story.append(Paragraph("🌤️ CURRENT WEATHER (METAR)", self.heading_style))
            clean_metar_text = clean_html_for_pdf(metar.get('raw', ''))
            story.append(Paragraph(f"<b>Raw METAR:</b>", self.subheading_style))
            story.append(Paragraph(clean_metar_text, self.data_style))
            story.append(Spacer(1, 10))
            
            # Enhanced weather table
            weather_table_data = [
                ['Wind Direction:', f"{metar.get('wind_dir', 'N/A')}° {self._get_wind_direction_text(metar.get('wind_dir', 0))}"],
                ['Wind Speed:', f"{metar.get('wind_speed', 'N/A')} kt"],
                ['Wind Gusts:', f"{metar.get('wind_gust', 'None')} kt" if metar.get('wind_gust', 0) > 0 else "None"],
                ['Visibility:', f"{metar.get('visibility', 'N/A')} SM"],
                ['Ceiling:', f"{metar.get('ceiling', 'Unlimited')} ft AGL" if metar.get('ceiling') else "Unlimited"],
                ['Temperature:', f"{metar.get('temp_c', 'N/A')}°C ({metar.get('temp_f', 'N/A')}°F)"],
                ['Dewpoint:', f"{metar.get('dewpoint_c', 'N/A')}°C ({metar.get('dewpoint_f', 'N/A')}°F)"],
                ['Dewpoint Spread:', f"{metar.get('temp_c', 0) - metar.get('dewpoint_c', 0):.1f}°C" if metar.get('temp_c') and metar.get('dewpoint_c') else 'N/A'],
                ['Altimeter:', f"{metar.get('altim_in_hg', 'N/A')} inHg"],
                ['Weather Phenomena:', ', '.join(metar.get('weather', [])) if metar.get('weather') else 'None reported'],
                ['Flight Category:', self._get_flight_category(metar.get('visibility'), metar.get('ceiling'))]
            ]
            
            weather_table = Table(weather_table_data, colWidths=[2*inch, 4*inch])
            weather_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (0, -1), colors.lightgreen),
                ('TEXTCOLOR', (0, 0), (-1, -1), colors.black),
                ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
                ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
                ('FONTSIZE', (0, 0), (-1, -1), 9),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
                ('TOPPADDING', (0, 0), (-1, -1), 8),
                ('BACKGROUND', (1, 0), (1, -1), colors.white),
                ('GRID', (0, 0), (-1, -1), 1, colors.darkgreen)
            ]))
            story.append(weather_table)
            story.append(Spacer(1, 20))
        
        # Aircraft Configuration Section
        aircraft_config = brief_data.get('aircraft_config', {})
        if aircraft_config:
            story.append(Paragraph("✈️ AIRCRAFT CONFIGURATION", self.heading_style))
            config_table_data = [
                ['Aircraft Type:', aircraft_config.get('type', 'N/A').title()],
                ['Aircraft Category:', aircraft_config.get('category', 'N/A').title()],
                ['Pilot Experience:', aircraft_config.get('experience_level', 'N/A').title()],
                ['Risk Profile:', aircraft_config.get('risk_profile', 'N/A').title()],
                ['Runway Requirement:', f"{aircraft_config.get('runway_requirement_ft', 'N/A')} ft minimum"],
                ['Risk Threshold Multiplier:', f"{aircraft_config.get('threshold_multiplier', 'N/A')}x standard thresholds"]
            ]
            config_table = Table(config_table_data, colWidths=[2.5*inch, 3.5*inch])
            config_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (0, -1), colors.lightyellow),
                ('TEXTCOLOR', (0, 0), (-1, -1), colors.black),
                ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
                ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
                ('FONTSIZE', (0, 0), (-1, -1), 9),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
                ('TOPPADDING', (0, 0), (-1, -1), 8),
                ('BACKGROUND', (1, 0), (1, -1), colors.white),
                ('GRID', (0, 0), (-1, -1), 1, colors.orange)
            ]))
            story.append(config_table)
            story.append(Spacer(1, 20))
        
        # Detailed Runway Analysis
        for i, runway in enumerate(runway_briefs):
            if i > 0:
                story.append(PageBreak())
            
            rwy_id = runway.get('runway', 'N/A')
            rri = runway.get('runway_risk_index', 0)
            risk_category = runway.get('risk_category', 'UNKNOWN')
            status = runway.get('status', 'UNKNOWN')
            
            story.append(Paragraph(f"🛬 RUNWAY {rwy_id} DETAILED ANALYSIS", self.title_style))
            
            # Status indicator with color coding
            if status == "GOOD":
                status_style = self.good_style
                status_icon = "✅"
            elif status == "CAUTION":
                status_style = self.caution_style
                status_icon = "⚠️"
            else:
                status_style = self.warning_style
                status_icon = "🚫"
            
            story.append(Paragraph(f"{status_icon} <b>RUNWAY RISK INDEX: {rri}/100</b> - {risk_category} RISK - <b>{status}</b>", status_style))
            story.append(Spacer(1, 15))
            
            # Basic runway data
            story.append(Paragraph("📊 RUNWAY SPECIFICATIONS", self.subheading_style))
            runway_specs_data = [
                ['Runway Identifier:', rwy_id],
                ['Magnetic Heading:', f"{runway.get('heading', 'N/A')}°"],
                ['Runway Length:', f"{runway.get('length', 'Unknown')} ft" if runway.get('length') else 'Unknown'],
                ['Surface Type:', runway.get('surface', 'Unknown')],
                ['Terrain Factor:', f"{runway.get('terrain_factor', 1.0):.1f}x"]
            ]
            
            runway_specs_table = Table(runway_specs_data, colWidths=[2*inch, 4*inch])
            runway_specs_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (0, -1), colors.lightcyan),
                ('TEXTCOLOR', (0, 0), (-1, -1), colors.black),
                ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
                ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
                ('FONTSIZE', (0, 0), (-1, -1), 9),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
                ('TOPPADDING', (0, 0), (-1, -1), 8),
                ('BACKGROUND', (1, 0), (1, -1), colors.white),
                ('GRID', (0, 0), (-1, -1), 1, colors.darkcyan)
            ]))
            story.append(runway_specs_table)
            story.append(Spacer(1, 15))
            
            # Wind analysis
            story.append(Paragraph("💨 WIND ANALYSIS", self.subheading_style))
            wind_data = [
                ['Headwind Component:', f"{runway.get('headwind_kt', 'N/A')} kt"],
                ['Crosswind Component:', f"{runway.get('crosswind_kt', 'N/A')} kt"],
                ['Tailwind Condition:', 'YES - CAUTION' if runway.get('tailwind') else 'No'],
                ['Gust Headwind:', f"{runway.get('gust_headwind_kt', 'N/A')} kt"],
                ['Gust Crosswind:', f"{runway.get('gust_crosswind_kt', 'N/A')} kt"],
                ['Gust Tailwind:', 'YES - CAUTION' if runway.get('gust_tailwind') else 'No']
            ]
            
            wind_table = Table(wind_data, colWidths=[2*inch, 4*inch])
            wind_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (0, -1), colors.lightblue),
                ('TEXTCOLOR', (0, 0), (-1, -1), colors.black),
                ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
                ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
                ('FONTSIZE', (0, 0), (-1, -1), 9),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
                ('TOPPADDING', (0, 0), (-1, -1), 8),
                ('BACKGROUND', (1, 0), (1, -1), colors.white),
                ('GRID', (0, 0), (-1, -1), 1, colors.darkblue)
            ]))
            story.append(wind_table)
            story.append(Spacer(1, 15))
            
            # Performance factors
            story.append(Paragraph("📈 PERFORMANCE FACTORS", self.subheading_style))
            perf_data = [
                ['Density Altitude:', f"{runway.get('density_altitude_ft', 'N/A')} ft"],
                ['DA Difference:', f"{runway.get('density_altitude_diff_ft', 'N/A')} ft above field elevation"],
                ['Temperature Effect:', self._get_temperature_effect(runway.get('density_altitude_diff_ft', 0))],
                ['Ceiling:', f"{runway.get('ceiling', 'Unlimited')} ft AGL" if runway.get('ceiling') else 'Unlimited'],
                ['Visibility:', f"{runway.get('visibility', 'N/A')} SM"],
                ['Weather Conditions:', ', '.join(runway.get('weather', [])) if runway.get('weather') else 'None']
            ]
            
            perf_table = Table(perf_data, colWidths=[2*inch, 4*inch])
            perf_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (0, -1), colors.lightgoldenrodyellow),
                ('TEXTCOLOR', (0, 0), (-1, -1), colors.black),
                ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
                ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
                ('FONTSIZE', (0, 0), (-1, -1), 9),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
                ('TOPPADDING', (0, 0), (-1, -1), 8),
                ('BACKGROUND', (1, 0), (1, -1), colors.white),
                ('GRID', (0, 0), (-1, -1), 1, colors.darkgoldenrod)
            ]))
            story.append(perf_table)
            story.append(Spacer(1, 15))
            
            # Risk contributors breakdown
            rri_contributors = runway.get('runway_risk_contributors', {})
            if rri_contributors:
                story.append(Paragraph("🎯 RISK FACTOR BREAKDOWN", self.subheading_style))
                
                risk_breakdown = []
                for factor, data in rri_contributors.items():
                    if isinstance(data, dict) and data.get('score', 0) > 0:
                        factor_name = factor.replace('_', ' ').title()
                        score = data.get('score', 0)
                        description = data.get('description', 'No description available')
                        risk_breakdown.append([factor_name, f"{score} points", description])
                
                if risk_breakdown:
                    risk_table = Table(risk_breakdown, colWidths=[1.5*inch, 1*inch, 3.5*inch])
                    risk_table.setStyle(TableStyle([
                        ('BACKGROUND', (0, 0), (-1, 0), colors.lightcoral),
                        ('TEXTCOLOR', (0, 0), (-1, -1), colors.black),
                        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
                        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                        ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
                        ('FONTSIZE', (0, 0), (-1, -1), 8),
                        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
                        ('TOPPADDING', (0, 0), (-1, -1), 6),
                        ('BACKGROUND', (0, 1), (-1, -1), colors.white),
                        ('GRID', (0, 0), (-1, -1), 1, colors.darkred),
                        ('VALIGN', (0, 0), (-1, -1), 'TOP')
                    ]))
                    story.append(risk_table)
                    story.append(Spacer(1, 15))
            
            # Warnings and advisories
            warnings = runway.get('warnings', [])
            if warnings:
                story.append(Paragraph("⚠️ WARNINGS AND ADVISORIES", self.subheading_style))
                for warning in warnings:
                    clean_warning = clean_html_for_pdf(warning)
                    story.append(Paragraph(f"• {clean_warning}", self.warning_style))
                story.append(Spacer(1, 15))
            
            # Uncertainty analysis
            probabilistic_analysis = runway.get('probabilistic_analysis', {})
            if probabilistic_analysis and 'percentiles' in probabilistic_analysis:
                story.append(Paragraph("📊 RISK UNCERTAINTY ANALYSIS", self.subheading_style))
                percentiles = probabilistic_analysis['percentiles']
                
                uncertainty_data = [
                    ['Risk Metric', 'Value', 'Interpretation'],
                    ['5th Percentile (Best Case):', f"{percentiles.get('p05', 'N/A'):.1f}", 'Optimistic scenario'],
                    ['25th Percentile:', f"{percentiles.get('p25', 'N/A'):.1f}", 'Better than average'],
                    ['50th Percentile (Median):', f"{percentiles.get('p50', 'N/A'):.1f}", 'Most likely scenario'],
                    ['75th Percentile:', f"{percentiles.get('p75', 'N/A'):.1f}", 'Worse than average'],
                    ['95th Percentile (Worst Case):', f"{percentiles.get('p95', 'N/A'):.1f}", 'Pessimistic scenario']
                ]
                
                uncertainty_table = Table(uncertainty_data, colWidths=[2.5*inch, 1*inch, 2.5*inch])
                uncertainty_table.setStyle(TableStyle([
                    ('BACKGROUND', (0, 0), (-1, 0), colors.lightpink),
                    ('TEXTCOLOR', (0, 0), (-1, -1), colors.black),
                    ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
                    ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                    ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
                    ('FONTSIZE', (0, 0), (-1, -1), 8),
                    ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
                    ('TOPPADDING', (0, 0), (-1, -1), 6),
                    ('BACKGROUND', (0, 1), (-1, -1), colors.white),
                    ('GRID', (0, 0), (-1, -1), 1, colors.darkred)
                ]))
                story.append(uncertainty_table)
                story.append(Spacer(1, 15))
                
                # Risk distribution
                risk_dist = probabilistic_analysis.get('risk_distribution', {})
                if risk_dist:
                    story.append(Paragraph("📈 RISK PROBABILITY DISTRIBUTION", self.subheading_style))
                    dist_data = [
                        ['Risk Level', 'Probability', 'Description'],
                        ['Low Risk (≤25):', f"{risk_dist.get('low_risk', 0):.1%}", 'Excellent conditions'],
                        ['Moderate Risk (26-50):', f"{risk_dist.get('moderate_risk', 0):.1%}", 'Manageable conditions'],
                        ['High Risk (51-75):', f"{risk_dist.get('high_risk', 0):.1%}", 'Challenging conditions'],
                        ['Extreme Risk (>75):', f"{risk_dist.get('extreme_risk', 0):.1%}", 'Dangerous conditions'],
                        ['NO-GO Probability:', f"{risk_dist.get('no_go_probability', 0):.1%}", 'Conditions exceed limits']
                    ]
                    
                    dist_table = Table(dist_data, colWidths=[2*inch, 1.5*inch, 2.5*inch])
                    dist_table.setStyle(TableStyle([
                        ('BACKGROUND', (0, 0), (-1, 0), colors.lightsteelblue),
                        ('TEXTCOLOR', (0, 0), (-1, -1), colors.black),
                        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
                        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                        ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
                        ('FONTSIZE', (0, 0), (-1, -1), 8),
                        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
                        ('TOPPADDING', (0, 0), (-1, -1), 6),
                        ('BACKGROUND', (0, 1), (-1, -1), colors.white),
                        ('GRID', (0, 0), (-1, -1), 1, colors.darkblue)
                    ]))
                    story.append(dist_table)
                    story.append(Spacer(1, 15))
            
            # Advanced analysis
            advanced_analysis = runway.get('advanced_analysis', {})
            if advanced_analysis:
                story.append(Paragraph("🔬 ADVANCED ANALYSIS", self.subheading_style))
                
                for analysis_type, analysis_data in advanced_analysis.items():
                    if analysis_data and analysis_type != 'diagnostic_info':
                        analysis_name = analysis_type.replace('_', ' ').title()
                        story.append(Paragraph(f"<b>{analysis_name}:</b>", self.styles['Normal']))
                        
                        if isinstance(analysis_data, list):
                            for item in analysis_data:
                                clean_item = clean_html_for_pdf(str(item))
                                story.append(Paragraph(f"• {clean_item}", self.styles['Normal']))
                        else:
                            clean_data = clean_html_for_pdf(str(analysis_data))
                            story.append(Paragraph(clean_data, self.styles['Normal']))
                        story.append(Spacer(1, 5))
                
                story.append(Spacer(1, 10))
            
            # AI Summary
            plain_summary = runway.get('plain_summary')
            if plain_summary:
                story.append(Paragraph("🤖 AI PILOT ADVISORY", self.subheading_style))
                clean_summary = clean_html_for_pdf(plain_summary)
                story.append(Paragraph(clean_summary, self.summary_style))
                story.append(Spacer(1, 15))
            
            # Time factors
            time_factors = runway.get('time_factors')
            if time_factors:
                story.append(Paragraph("🕐 TIME-BASED RISK FACTORS", self.subheading_style))
                time_data = [
                    ['Current Time Risk:', f"{time_factors.get('risk_score', 'N/A')} points"],
                    ['Risk Category:', time_factors.get('risk_category', 'N/A')],
                    ['Primary Factors:', '; '.join(time_factors.get('risk_reasons', []))]
                ]
                
                time_table = Table(time_data, colWidths=[2*inch, 4*inch])
                time_table.setStyle(TableStyle([
                    ('BACKGROUND', (0, 0), (0, -1), colors.lightgrey),
                    ('TEXTCOLOR', (0, 0), (-1, -1), colors.black),
                    ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
                    ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
                    ('FONTSIZE', (0, 0), (-1, -1), 9),
                    ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
                                         ('TOPPADDING', (0, 0), (-1, -1), 8),
                     ('BACKGROUND', (1, 0), (1, -1), colors.white),
                     ('GRID', (0, 0), (-1, -1), 1, colors.grey),
                     ('VALIGN', (0, 0), (-1, -1), 'TOP')
                ]))
                story.append(time_table)
                story.append(Spacer(1, 15))
        
        # Additional weather data
        story.append(PageBreak())
        story.append(Paragraph("📋 ADDITIONAL WEATHER DATA", self.heading_style))
        
        # TAF
        taf = brief_data.get('taf', {})
        if taf and taf.get('raw'):
            story.append(Paragraph("Terminal Area Forecast (TAF)", self.subheading_style))
            clean_taf_text = clean_html_for_pdf(taf.get('raw', ''))
            story.append(Paragraph(clean_taf_text, self.data_style))
            story.append(Spacer(1, 10))
        
        # NOTAMs
        notams = brief_data.get('notams', {})
        if notams and (notams.get('closed_runways') or notams.get('raw_text')):
            story.append(Paragraph("NOTAMs (Notice to Airmen)", self.subheading_style))
            if notams.get('closed_runways'):
                story.append(Paragraph(f"<b>🚫 CLOSED RUNWAYS:</b> {', '.join(notams['closed_runways'])}", self.warning_style))
            if notams.get('raw_text'):
                clean_notam_text = clean_html_for_pdf(notams.get('raw_text', ''))
                if clean_notam_text != "No data available":
                    story.append(Paragraph(clean_notam_text, self.data_style))
            story.append(Spacer(1, 15))
        
        # Additional weather products
        weather_products = [
            ('gairmet', 'G-AIRMETs'),
            ('sigmet', 'SIGMETs'),
            ('isigmet', 'International SIGMETs'),
            ('pirep', 'Pilot Reports'),
            ('cwa', 'Center Weather Advisories'),
            ('windtemp', 'Winds and Temperature Aloft'),
            ('areafcst', 'Area Forecasts'),
            ('fcstdisc', 'Forecast Discussion'),
            ('mis', 'Meteorological Impact Statements')
        ]
        
        for product_key, product_name in weather_products:
            product_data = brief_data.get(product_key, {})
            if product_data and product_data.get('raw'):
                story.append(Paragraph(product_name, self.subheading_style))
                clean_product_text = clean_html_for_pdf(product_data.get('raw', ''))
                if clean_product_text != "No data available":
                    story.append(Paragraph(clean_product_text, self.data_style))
                story.append(Spacer(1, 10))
        
        # Station information
        stationinfo = brief_data.get('stationinfo', {})
        if stationinfo and (stationinfo.get('latitude') or stationinfo.get('longitude')):
            story.append(Paragraph("Station Information", self.subheading_style))
            station_data = [
                ['Latitude:', f"{stationinfo.get('latitude', 'N/A')}°"],
                ['Longitude:', f"{stationinfo.get('longitude', 'N/A')}°"],
                ['Station ID:', stationinfo.get('station_id', 'N/A')]
            ]
            
            station_table = Table(station_data, colWidths=[2*inch, 4*inch])
            station_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (0, -1), colors.lightgrey),
                ('TEXTCOLOR', (0, 0), (-1, -1), colors.black),
                ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
                ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
                ('FONTSIZE', (0, 0), (-1, -1), 9),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
                                 ('TOPPADDING', (0, 0), (-1, -1), 8),
                 ('BACKGROUND', (1, 0), (1, -1), colors.white),
                 ('GRID', (0, 0), (-1, -1), 1, colors.grey)
            ]))
            story.append(station_table)
            story.append(Spacer(1, 15))
        
        # Footer and disclaimer
        story.append(PageBreak())
        story.append(Paragraph("⚖️ LEGAL DISCLAIMER", self.heading_style))
        disclaimer_text = """
        <b>IMPORTANT SAFETY NOTICE:</b><br/><br/>
        This RunwayGuard brief is provided for informational purposes only and should NOT be used as the sole source 
        for flight planning decisions. This system is NOT certified for operational use and should be used 
        in conjunction with official aviation weather services.<br/><br/>
        
        <b>PILOT RESPONSIBILITIES:</b><br/>
        • Always consult official weather briefings and NOTAMs<br/>
        • Follow proper flight planning procedures<br/>
        • Make go/no-go decisions based on your training, experience, and aircraft limitations<br/>
        • Verify all data with official sources<br/>
        • Consider factors not captured in this analysis<br/><br/>
        
        <b>LIMITATIONS:</b><br/>
        • Risk calculations are estimates based on available data<br/>
        • Weather conditions can change rapidly<br/>
        • Local conditions may differ from reported data<br/>
        • System may not capture all relevant risk factors<br/><br/>
        
        <b>COPYRIGHT:</b> RunwayGuard © awade12(openturf.org) - Professional Aviation Risk Assessment System
        """
        story.append(Paragraph(disclaimer_text, self.styles['Normal']))
        
        doc.build(story)
        buffer.seek(0)
        return buffer
    
    def _get_wind_direction_text(self, wind_dir):
        """Convert wind direction to cardinal direction"""
        if wind_dir is None:
            return ""
        
        directions = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE", 
                     "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"]
        index = round(wind_dir / 22.5) % 16
        return f"({directions[index]})"
    
    def _get_flight_category(self, visibility, ceiling):
        """Determine flight category based on visibility and ceiling"""
        if visibility is None and ceiling is None:
            return "Unknown"
        
        vis = visibility if visibility is not None else 10
        ceil = ceiling if ceiling is not None else 10000
        
        if vis >= 5 and ceil >= 3000:
            return "VFR (Visual Flight Rules)"
        elif vis >= 3 and ceil >= 1000:
            return "MVFR (Marginal VFR)"
        elif vis >= 1 and ceil >= 500:
            return "IFR (Instrument Flight Rules)"
        else:
            return "LIFR (Low IFR)"
    
    def _get_temperature_effect(self, da_diff):
        """Get temperature effect description"""
        if da_diff is None:
            return "Unknown"
        elif da_diff < 500:
            return "Minimal impact on performance"
        elif da_diff < 1000:
            return "Slight performance degradation"
        elif da_diff < 2000:
            return "Noticeable performance impact"
        elif da_diff < 3000:
            return "Significant performance degradation"
        else:
            return "Severe performance impact - use caution"
    
    def create_route_pdf(self, route_data: Dict) -> io.BytesIO:
        buffer = io.BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=letter, rightMargin=72, leftMargin=72, topMargin=72, bottomMargin=18)
        
        story = []
        
        airports = route_data.get('route_summary', {}).get('airports', [])
        route_string = ' → '.join(airports) if airports else 'Route Analysis'
        
        story.append(Paragraph(f"RunwayGuard Route Analysis", self.title_style))
        story.append(Paragraph(f"Route: {route_string}", self.styles['Normal']))
        story.append(Paragraph(f"Generated: {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}", self.styles['Normal']))
        story.append(Spacer(1, 20))
        
        route_summary = route_data.get('route_summary', {})
        if route_summary:
            story.append(Paragraph("Route Summary", self.heading_style))
            summary_table_data = [
                ['Total Distance:', f"{route_summary.get('total_distance_nm', 'N/A')} nm"],
                ['Number of Airports:', str(len(airports))],
                ['Overall Status:', route_summary.get('overall_status', 'N/A')],
                ['Average RRI:', f"{route_summary.get('average_rri', 'N/A'):.1f}" if route_summary.get('average_rri') else 'N/A'],
                ['Highest RRI:', f"{route_summary.get('highest_rri', 'N/A'):.1f}" if route_summary.get('highest_rri') else 'N/A']
            ]
            summary_table = Table(summary_table_data, colWidths=[2*inch, 3*inch])
            summary_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (0, -1), colors.lightblue),
                ('TEXTCOLOR', (0, 0), (-1, -1), colors.black),
                ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
                ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
                ('FONTSIZE', (0, 0), (-1, -1), 10),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 12),
                ('BACKGROUND', (1, 0), (1, -1), colors.beige),
                ('GRID', (0, 0), (-1, -1), 1, colors.black)
            ]))
            story.append(summary_table)
            story.append(Spacer(1, 20))
        
        waypoints = route_data.get('waypoints', [])
        for i, waypoint in enumerate(waypoints):
            if i > 0:
                story.append(PageBreak())
            
            icao = waypoint.get('icao', 'N/A')
            story.append(Paragraph(f"Airport: {icao}", self.title_style))
            
            best_runway = waypoint.get('best_runway_analysis', {}).get('best_runway', {})
            if best_runway:
                rri = best_runway.get('rri', 0)
                risk_category = best_runway.get('risk_category', 'UNKNOWN')
                status = best_runway.get('status', 'UNKNOWN')
                
                status_color = colors.green if status == "GOOD" else colors.orange if status == "CAUTION" else colors.red
                story.append(Paragraph(f"<b>Best Runway:</b> {best_runway.get('runway', 'N/A')} - RRI: {rri}/100 ({risk_category}) - <font color='{status_color.hexval()}'>{status}</font>", self.styles['Normal']))
                story.append(Spacer(1, 15))
        
        recommendations = route_data.get('strategic_recommendations', [])
        if recommendations:
            story.append(Paragraph("Strategic Recommendations", self.heading_style))
            for rec in recommendations:
                story.append(Paragraph(f"• {rec}", self.styles['Normal']))
            story.append(Spacer(1, 15))
        
        story.append(PageBreak())
        story.append(Paragraph("Disclaimer", self.heading_style))
        disclaimer_text = """
        This RunwayGuard route analysis is provided for informational purposes only and should not be used as the sole source 
        for flight planning decisions. Always consult official weather briefings, NOTAMs, and follow proper flight 
        planning procedures. Pilots are responsible for making their own go/no-go decisions based on their training, 
        experience, and aircraft limitations. RunwayGuard is not certified for operational use and should be used 
        in conjunction with official aviation weather services.
        """
        story.append(Paragraph(disclaimer_text, self.styles['Normal']))
        
        doc.build(story)
        buffer.seek(0)
        return buffer

@router.post("/printbrief")
@limiter.limit("10/minute")
async def print_brief(request: Request, req: BriefRequest):
    start_time = time.time()
    icao = req.icao.upper()
    logger.info(f"Processing PDF brief request for ICAO: {icao}, Aircraft: {req.aircraft_type}, Experience: {req.pilot_experience}")
    
    config = ConfigurationManager.get_config_for_aircraft(req.aircraft_type, req.pilot_experience)
    
    try:
        airport = await fetch_airport_info(icao)
        if not airport or not airport.get("elevation"):
            logger.warning(f"Airport data not found or incomplete for ICAO: {icao}")
            raise APIError(
                message="Airport not found or data incomplete",
                status_code=status.HTTP_404_NOT_FOUND,
                details={
                    "icao": icao, 
                    "airport_data": airport,
                    "help": "For API usage guidance, visit /v1/help",
                    "suggestions": [
                        "Verify ICAO code is correct (e.g., KDFW, KGGG, KCNW)",
                        "Use 4-letter ICAO codes, not 3-letter IATA codes",
                        "Check if airport has published weather data"
                    ]
                }
            )
        
        logger.debug(f"Airport info retrieved for {icao}: {airport}")
        
        try:
            metar = await fetch_metar(icao)
            if not metar or not metar.get("raw"):
                logger.warning(f"No METAR data available for ICAO: {icao}")
                raise APIError(
                    message="No current weather data available",
                    status_code=status.HTTP_404_NOT_FOUND,
                    details={
                        "icao": icao, 
                        "metar_data": metar,
                        "help": "For API usage guidance, visit /v1/help",
                        "suggestions": [
                            "Airport may not report weather conditions",
                            "Try a nearby airport with weather reporting",
                            "Verify airport is active and operational"
                        ]
                    }
                )
        except Exception as e:
            logger.error(f"Error fetching METAR for {icao}: {str(e)}")
            raise APIError(
                message="Failed to fetch current weather data",
                status_code=status.HTTP_502_BAD_GATEWAY,
                details={"icao": icao, "error": str(e)}
            )
        
        taf = {"raw": "", "start_time": None, "end_time": None}
        stationinfo = {"latitude": None, "longitude": None}
        notams = {"closed_runways": [], "raw_text": ""}
        gairmet = []
        sigmet = []
        isigmet = []
        pirep = []
        cwa = []
        windtemp = {"raw": ""}
        areafcst = {"raw": ""}
        fcstdisc = {"raw": ""}
        mis = {"raw": ""}
        
        try:
            taf = await fetch_taf(icao)
            stationinfo = await fetch_stationinfo(icao)
            notams = await fetch_notams(icao)
            gairmet = await fetch_gairmet(icao)
            sigmet = await fetch_sigmet(icao)
            isigmet = await fetch_isigmet(icao)
            pirep = await fetch_pirep(icao)
            cwa = await fetch_cwa(icao)
            windtemp = await fetch_windtemp()
            areafcst = await fetch_areafcst()
            fcstdisc = await fetch_fcstdisc()
            mis = await fetch_mis()
        except Exception as e:
            logger.error(f"Error fetching supplementary data for {icao}: {str(e)}")
            
        field_elev = airport.get("elevation")
        runways = airport.get("runways", [])
        mag_dec = airport.get("mag_dec")
        wind_dir = metar.get("wind_dir", 0)
        wind_speed = metar.get("wind_speed", 0)
        wind_gust = metar.get("wind_gust", 0)
        altim_in_hg = metar.get("altim_in_hg", 29.92)
        temp_c = metar.get("temp_c", 15)
        closed_runways = notams.get("closed_runways", [])
        
        if not runways:
            logger.warning(f"No runway data available for ICAO: {icao}")
            raise APIError(
                message="No runway data available",
                status_code=status.HTTP_404_NOT_FOUND,
                details={"icao": icao}
            )
            
        runway_results = []
        for rwy in runways:
            rwy_id = rwy.get("id")
            rwy_heading = rwy.get("heading")
            
            if rwy_id is None or rwy_heading is None:
                logger.warning(f"Invalid runway data for {icao}: {rwy}")
                continue
                
            is_closed = any(rwy_id.startswith(crwy) or rwy_id.endswith(crwy) for crwy in closed_runways)
            if is_closed:
                runway_results.append({
                    "runway": rwy_id,
                    "heading": rwy_heading,
                    "headwind_kt": 0,
                    "crosswind_kt": 0,
                    "gust_headwind_kt": 0,
                    "gust_crosswind_kt": 0,
                    "tailwind": False,
                    "gust_tailwind": False,
                    "density_altitude_ft": density_alt(field_elev, temp_c, altim_in_hg),
                    "runway_risk_index": 100,
                    "risk_category": "EXTREME",
                    "status": "NO-GO",
                    "warnings": [f"Runway {rwy_id} CLOSED per NOTAM"],
                    "plain_summary": None
                })
                continue
                
            lat = stationinfo.get("latitude")
            lon = stationinfo.get("longitude")
            
            try:
                da = density_alt(field_elev, temp_c, altim_in_hg)
                da_diff = da - field_elev
                head, cross, is_head = wind_components(rwy_heading, wind_dir, wind_speed)
                
                gust_head, gust_cross, gust_is_head = (0, 0, True)
                if wind_gust > 0:
                    gust_head, gust_cross, gust_is_head = gust_components(rwy_heading, wind_dir, wind_gust)
                
                runway_length = rwy.get("length")
                
                terrain_factor = 1.0
                if field_elev > 5000:
                    terrain_factor = 1.2
                elif field_elev > 3000:
                    terrain_factor = 1.1
                
                rri, rri_contributors = calculate_advanced_rri(
                    head=head, 
                    cross=cross, 
                    gust_head=gust_head, 
                    gust_cross=gust_cross, 
                    wind_speed=wind_speed, 
                    wind_gust=wind_gust,
                    is_head=is_head, 
                    gust_is_head=gust_is_head, 
                    da_diff=da_diff, 
                    metar_data=metar, 
                    lat=lat, 
                    lon=lon, 
                    rwy_heading=rwy_heading, 
                    notam_data=notams,
                    runway_length=runway_length,
                    airport_elevation=field_elev,
                    terrain_factor=terrain_factor,
                    historical_trend=None,
                    aircraft_category=req.aircraft_type
                )
                
                time_factors = calculate_time_risk_factor(datetime.utcnow(), lat, lon, rwy_heading) if lat and lon else None
                
                weather = metar.get("weather", [])
                ceiling = metar.get("ceiling")
                visibility = metar.get("visibility")
                
                probabilistic_analysis = None
                if lat is not None and lon is not None:
                    base_conditions = {
                        "wind_dir": wind_dir,
                        "wind_speed": wind_speed,
                        "wind_gust": wind_gust if wind_gust > 0 else 0,
                        "temp_c": temp_c,
                        "altim_in_hg": altim_in_hg
                    }
                    
                    if visibility is not None:
                        base_conditions["visibility"] = visibility
                    if ceiling is not None:
                        base_conditions["ceiling"] = ceiling
                    
                    try:
                        probabilistic_result = calculate_advanced_probabilistic_rri(
                            rwy_heading=rwy_heading,
                            base_conditions=base_conditions,
                            da_diff=da_diff,
                            metar_data=metar,
                            lat=lat,
                            lon=lon,
                            num_draws=1000,
                            include_temporal=True,
                            include_extremes=True,
                            runway_length=runway_length,
                            airport_elevation=field_elev,
                            aircraft_category=req.aircraft_type
                        )
                        
                        probabilistic_analysis = {
                            "percentiles": probabilistic_result.percentiles,
                            "statistics": probabilistic_result.statistics,
                            "risk_distribution": probabilistic_result.risk_distribution,
                            "confidence_intervals": probabilistic_result.confidence_intervals,
                            "sensitivity_analysis": probabilistic_result.sensitivity_analysis,
                            "extreme_scenarios": probabilistic_result.extreme_scenarios[:5],
                            "temporal_forecast": probabilistic_result.temporal_evolution,
                            "scenario_summary": {
                                "total_scenarios": len(probabilistic_result.scenario_clusters["normal"]) + 
                                                 len(probabilistic_result.scenario_clusters["deteriorating"]) + 
                                                 len(probabilistic_result.scenario_clusters["improving"]),
                                "deteriorating_scenarios": len(probabilistic_result.scenario_clusters["deteriorating"]),
                                "improving_scenarios": len(probabilistic_result.scenario_clusters["improving"])
                            }
                        }
                        
                        legacy_format = {
                            "rri_p05": probabilistic_result.percentiles["p05"],
                            "rri_p95": probabilistic_result.percentiles["p95"]
                        }
                        
                    except Exception as prob_error:
                        logger.warning(f"Advanced probabilistic analysis failed for {icao} runway {rwy_id}: {str(prob_error)}")
                        legacy_format = calculate_probabilistic_rri_monte_carlo(
                            rwy_heading=rwy_heading,
                            original_wind_dir=wind_dir,
                            original_wind_speed=wind_speed,
                            original_wind_gust=wind_gust,
                            da_diff=da_diff,
                            metar_data=metar,
                            lat=lat,
                            lon=lon
                        )
                        probabilistic_analysis = {
                            "error": "Advanced analysis unavailable - using legacy calculation",
                            "legacy_percentiles": legacy_format
                        }
                else:
                    legacy_format = {"rri_p05": None, "rri_p95": None}
            except Exception as e:
                logger.error(f"Error calculating runway data for {icao} runway {rwy_id}: {str(e)}")
                continue

            warnings = []
            if time_factors:
                warnings.extend(time_factors["risk_reasons"])
            
            advanced_warning_contributors = [
                "icing_conditions", "temperature_performance", "wind_shear_risk", 
                "enhanced_weather", "notam_risks", "thermal_gradient", 
                "atmospheric_stability", "runway_performance", "precipitation_intensity",
                "turbulence_risk", "trend_analysis", "risk_amplification"
            ]
            
            for contributor in advanced_warning_contributors:
                if contributor in rri_contributors and isinstance(rri_contributors[contributor]["value"], list):
                    warnings.extend(rri_contributors[contributor]["value"])
            
            if any("TS" in weather_condition for weather_condition in weather):
                warnings.append("Active thunderstorm in vicinity - NO-GO condition.")
            if any("LTG" in weather_condition for weather_condition in weather):
                if any(all(condition in weather_condition for condition in ["DSNT", "ALQDS"]) for weather_condition in weather):
                    warnings.append("Lightning observed in all quadrants.")
                else:
                    warnings.append("Lightning observed in vicinity.")
            if ceiling is not None and ceiling < 3000:
                warnings.append(f"Low ceiling: {ceiling} ft AGL.")
            if visibility is not None and visibility < 5:
                warnings.append(f"Reduced visibility: {visibility} SM.")
            if any("GR" in weather_condition for weather_condition in weather):
                warnings.append("Hail reported.")
            if any("FC" in weather_condition for weather_condition in weather):
                warnings.append("Funnel cloud reported - NO-GO condition.")
            if any("FZ" in weather_condition for weather_condition in weather):
                warnings.append("Freezing precipitation reported.")
            if any("+" in weather_condition for weather_condition in weather):
                warnings.append("Heavy precipitation reported.")
                    
            if da_diff > 2000:
                warnings.append(f"Density altitude {da} ft is > 2000 ft above field elevation.")
            
            if runway_length and da_diff > 1000:
                performance_factor = 1 + (da_diff / 10000)
                effective_length = int(runway_length / performance_factor)
                if effective_length < 2500:
                    warnings.append(f"Performance-adjusted runway length: {effective_length}ft - monitor closely.")
                elif runway_length is None and da_diff > 500:
                    warnings.append(f"Runway length unknown - verify performance calculations for {da_diff}ft density altitude difference.")
            
            summary = None
            if os.getenv("OPENAI_API_KEY"):
                try:
                    import openai
                    import textwrap
                    openai.api_key = os.environ["OPENAI_API_KEY"]
                    gust_info = f", gusting {wind_gust} kt" if wind_gust > 0 else ""
                    weather_info = ", ".join(weather) if weather else "No significant weather"
                    
                    advanced_risks = []
                    for risk_type in ["thermal_gradient", "atmospheric_stability", "runway_performance", "precipitation_intensity", "turbulence_risk"]:
                        if risk_type in rri_contributors:
                            advanced_risks.append(f"{risk_type.replace('_', ' ').title()}: {rri_contributors[risk_type]['score']}")
                    
                    advanced_info = "; ".join(advanced_risks) if advanced_risks else "No advanced risk factors detected"
                    
                    uncertainty_info = "No uncertainty analysis available"
                    if probabilistic_analysis and "confidence_intervals" in probabilistic_analysis:
                        ci_90 = probabilistic_analysis["confidence_intervals"]["90_percent"]
                        uncertainty_info = f"90% confidence interval: {ci_90[0]:.0f}-{ci_90[1]:.0f} RRI"
                        
                        if "risk_distribution" in probabilistic_analysis:
                            risk_dist = probabilistic_analysis["risk_distribution"]
                            no_go_prob = risk_dist.get("no_go_probability", 0)
                            if no_go_prob > 0.05:
                                uncertainty_info += f"; {no_go_prob:.1%} chance NO-GO conditions"
                    
                    prompt = textwrap.dedent(
                        f"""
                        Generate a single-sentence advisory for a GA pilot based on these data.
                        Airport: {icao}, Runway {rwy_id} ({rwy_heading}°).
                        Wind: {wind_speed} kt{gust_info} from {wind_dir}°.
                        Weather: {weather_info}
                        Ceiling: {ceiling if ceiling is not None else "unlimited"} ft
                        Visibility: {visibility if visibility is not None else "unlimited"} SM
                        Headwind: {head} kt {'(tailwind)' if not is_head else ''}.
                        Crosswind: {cross} kt.
                        Gust headwind: {gust_head} kt {'(tailwind)' if not gust_is_head else ''}.
                        Gust crosswind: {gust_cross} kt.
                        Density altitude: {da} ft.
                        Advanced Risk Analysis: {advanced_info}
                        Uncertainty Analysis: {uncertainty_info}
                        Runway Risk Index: {rri}/100 ({get_rri_category(rri)} RISK)
                        Status: {get_status_from_rri(rri)}.
                        """
                    )
                    chat = openai.chat.completions.create(
                        model="gpt-3.5-turbo",
                        messages=[{"role": "user", "content": prompt}],
                        temperature=0.3,
                        max_tokens=50,
                    )
                    summary = chat.choices[0].message.content.strip()
                except Exception as e:
                    logger.error(f"Error generating OpenAI summary for {icao} runway {rwy_id}: {str(e)}")
                    summary = None
            
            runway_results.append({
                "runway": rwy_id,
                "heading": rwy_heading,
                "length": runway_length,
                "headwind_kt": head,
                "crosswind_kt": cross,
                "gust_headwind_kt": gust_head,
                "gust_crosswind_kt": gust_cross,
                "tailwind": not is_head,
                "gust_tailwind": not gust_is_head,
                "density_altitude_ft": da,
                "density_altitude_diff_ft": da_diff,
                "terrain_factor": terrain_factor,
                "runway_risk_contributors": rri_contributors,
                "runway_risk_index": rri,
                "risk_category": get_rri_category(rri),
                "status": get_status_from_rri(rri),
                "rri_p05": legacy_format.get("rri_p05"),
                "rri_p95": legacy_format.get("rri_p95"),
                "probabilistic_analysis": probabilistic_analysis,
                "weather": weather,
                "ceiling": ceiling,
                "visibility": visibility,
                "warnings": warnings,
                "time_factors": time_factors,
                "plain_summary": summary
            })
            
        if not runway_results:
            logger.error(f"No valid runway data could be processed for {icao}")
            raise APIError(
                message="Failed to process runway data",
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                details={"icao": icao}
            )
            
        processing_time = round(time.time() - start_time, 3)
        
        brief_data = {
            "icao": icao,
            "processing_time_seconds": processing_time,
            "aircraft_config": {
                "type": req.aircraft_type,
                "experience_level": req.pilot_experience,
                "category": config.aircraft_category.value,
                "risk_profile": config.risk_profile.value,
                "runway_requirement_ft": config.runway_length_requirement,
                "threshold_multiplier": config.threshold_multiplier
            },
            "airport_info": airport,
            "metar": metar,
            "taf": taf,
            "stationinfo": stationinfo,
            "notams": notams,
            "gairmet": gairmet,
            "sigmet": sigmet,
            "isigmet": isigmet,
            "pirep": pirep,
            "cwa": cwa,
            "windtemp": windtemp,
            "areafcst": areafcst,
            "fcstdisc": fcstdisc,
            "mis": mis,
            "runway_briefs": runway_results
        }
        
        try:
            db = await get_database()
            if db.engine:
                await db.store_api_response(
                    endpoint="printbrief",
                    request_data=req.dict(),
                    response_data={"pdf_generated": True, "icao": icao},
                    processing_time=processing_time,
                    client_ip=get_client_ip(request)
                )
            else:
                logger.info("Database not configured - skipping response storage")
        except Exception as e:
            logger.error(f"Failed to store response to database: {str(e)}")
        
        try:
            pdf_generator = PDFGenerator()
            pdf_buffer = pdf_generator.create_brief_pdf(brief_data, icao)
            
            logger.info(f"Successfully generated PDF brief for {icao} in {processing_time}s")
            
            return StreamingResponse(
                io.BytesIO(pdf_buffer.read()),
                media_type="application/pdf",
                headers={"Content-Disposition": f"attachment; filename=RunwayGuard_Brief_{icao}_{datetime.utcnow().strftime('%Y%m%d_%H%M')}.pdf"}
            )
        except Exception as pdf_error:
            logger.error(f"PDF generation failed for {icao}: {str(pdf_error)}")
            raise APIError(
                message="PDF generation failed",
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                details={
                    "icao": icao,
                    "pdf_error": str(pdf_error),
                    "suggestion": "Try the regular /brief endpoint for JSON data"
                }
            )
            
    except APIError as api_error:
        try:
            db = await get_database()
            if db.engine:
                await db.store_api_response(
                    endpoint="printbrief",
                    request_data=req.dict(),
                    response_data={},
                    processing_time=round(time.time() - start_time, 3),
                    client_ip=get_client_ip(request),
                    error_message=api_error.message
                )
        except Exception as e:
            logger.error(f"Failed to store error to database: {str(e)}")
        raise
    except Exception as e:
        processing_time = round(time.time() - start_time, 3)
        error_message = f"Internal server error: {str(e)}"
        
        try:
            db = await get_database()
            if db.engine:
                await db.store_api_response(
                    endpoint="printbrief",
                    request_data=req.dict(),
                    response_data={},
                    processing_time=processing_time,
                    client_ip=get_client_ip(request),
                    error_message=error_message
                )
        except Exception as db_error:
            logger.error(f"Failed to store error to database: {str(db_error)}")
        
        logger.exception(f"Unexpected error processing PDF brief for {icao}")
        raise APIError(
            message="Internal server error",
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            details={
                "icao": icao,
                "error": str(e)
            }
        )

@router.post("/printroute")
@limiter.limit("5/minute")
async def print_route(request: Request, req: RouteRequest):
    route_airports = req.airports
    logger.info(f"Processing PDF route analysis for {len(route_airports)} airports: {' -> '.join(route_airports)}")
    
    try:
        route_data = await analyze_route(
            airports=route_airports,
            aircraft_type=req.aircraft_type,
            pilot_experience=req.pilot_experience,
            route_distances=req.route_distances
        )
        
        try:
            db = await get_database()
            if db.engine:
                await db.store_api_response(
                    endpoint="printroute",
                    request_data=req.dict(),
                    response_data={"pdf_generated": True, "airports": route_airports},
                    client_ip=get_client_ip(request)
                )
            else:
                logger.info("Database not configured - skipping route response storage")
        except Exception as e:
            logger.error(f"Failed to store route response to database: {str(e)}")
        
        try:
            pdf_generator = PDFGenerator()
            pdf_buffer = pdf_generator.create_route_pdf(route_data)
            
            route_string = '_'.join(route_airports)
            logger.info(f"Successfully generated PDF route analysis for {' -> '.join(route_airports)}")
            
            return StreamingResponse(
                io.BytesIO(pdf_buffer.read()),
                media_type="application/pdf",
                headers={"Content-Disposition": f"attachment; filename=RunwayGuard_Route_{route_string}_{datetime.utcnow().strftime('%Y%m%d_%H%M')}.pdf"}
            )
        except Exception as pdf_error:
            logger.error(f"PDF generation failed for route {' -> '.join(route_airports)}: {str(pdf_error)}")
            raise APIError(
                message="PDF generation failed",
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                details={
                    "airports": route_airports,
                    "pdf_error": str(pdf_error),
                    "suggestion": "Try the regular /route endpoint for JSON data"
                }
            )
        
    except ValueError as e:
        error_message = f"Invalid route configuration: {str(e)}"
        
        try:
            db = await get_database()
            if db.engine:
                await db.store_api_response(
                    endpoint="printroute",
                    request_data=req.dict(),
                    response_data={},
                    client_ip=get_client_ip(request),
                    error_message=error_message
                )
        except Exception as db_error:
            logger.error(f"Failed to store route error to database: {str(db_error)}")
        
        logger.warning(f"Invalid route request: {str(e)}")
        raise APIError(
            message=error_message,
            status_code=status.HTTP_400_BAD_REQUEST,
            details={
                "airports": route_airports,
                "help": "For API usage guidance, visit /v1/help"
            }
        )
    except Exception as e:
        error_message = f"Internal server error during route analysis: {str(e)}"
        
        try:
            db = await get_database()
            if db.engine:
                await db.store_api_response(
                    endpoint="printroute",
                    request_data=req.dict(),
                    response_data={},
                    client_ip=get_client_ip(request),
                    error_message=error_message
                )
        except Exception as db_error:
            logger.error(f"Failed to store route error to database: {str(db_error)}")
        
        logger.exception(f"Unexpected error processing PDF route analysis for {' -> '.join(route_airports)}")
        raise APIError(
            message="Internal server error during route analysis",
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            details={
                "airports": route_airports,
                "error": str(e)
            }
        )
