import os
import asyncio
import logging
from datetime import datetime
from typing import Dict, Any, Optional
import asyncpg
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.ext.asyncio import async_sessionmaker
from sqlalchemy.orm import declarative_base
from sqlalchemy import Column, Integer, String, DateTime, Text, JSON, select, desc, text
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

Base = declarative_base()

class APIResponse(Base):
    __tablename__ = "api_responses" # should change later
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    endpoint = Column(String(50), nullable=False, index=True)
    request_data = Column(JSON, nullable=False)
    response_data = Column(JSON, nullable=False)
    processing_time_seconds = Column(String(10))
    icao_codes = Column(String(200), index=True)
    aircraft_type = Column(String(50), index=True)
    pilot_experience = Column(String(50), index=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    client_ip = Column(String(45))
    error_message = Column(Text, nullable=True)

class DatabaseManager:
    def __init__(self):
        self.database_url = os.getenv("DATABASE_URL")
        if not self.database_url:
            logger.warning("DATABASE_URL not found in environment variables")
            self.database_url = "postgresql+asyncpg://user:password@localhost:5432/runwayguard"
        else:
            if self.database_url.startswith("postgresql://"):
                self.database_url = self.database_url.replace("postgresql://", "postgresql+asyncpg://", 1)
                logger.info("Converted DATABASE_URL to use asyncpg driver")
            elif not self.database_url.startswith("postgresql+asyncpg://"):
                logger.warning(f"DATABASE_URL format may be incorrect. Expected postgresql+asyncpg:// but got: {self.database_url[:20]}...")
        
        self.engine = None
        self.async_session = None
        
    async def initialize(self):
        if not self.database_url or self.database_url == "postgresql+asyncpg://user:password@localhost:5432/runwayguard":
            logger.warning("Using default database URL - database functionality may not work without proper configuration")
            return False
            
        try:
            self.engine = create_async_engine(
                self.database_url,
                echo=False,
                pool_size=10,
                max_overflow=20,
                pool_pre_ping=True,
                pool_recycle=3600
            )
            
            self.async_session = async_sessionmaker(
                self.engine,
                class_=AsyncSession,
                expire_on_commit=False
            )
            
            logger.info("Database connection initialized successfully")
            return True
            
        except Exception as e:
            logger.error(f"Failed to initialize database connection: {str(e)}")
            return False
    
    async def create_tables(self):
        try:
            async with self.engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
            logger.info("Database tables created successfully")
            return True
        except Exception as e:
            logger.error(f"Failed to create database tables: {str(e)}")
            return False
    
    async def store_api_response(
        self,
        endpoint: str,
        request_data: Dict[str, Any],
        response_data: Dict[str, Any],
        processing_time: Optional[float] = None,
        client_ip: Optional[str] = None,
        error_message: Optional[str] = None
    ) -> bool:
        try:
            icao_codes = self._extract_icao_codes(request_data, endpoint)
            aircraft_type = request_data.get("aircraft_type", "light")
            pilot_experience = request_data.get("pilot_experience", "standard")
            
            api_response = APIResponse(
                endpoint=endpoint,
                request_data=request_data,
                response_data=response_data,
                processing_time_seconds=str(processing_time) if processing_time else None,
                icao_codes=icao_codes,
                aircraft_type=aircraft_type,
                pilot_experience=pilot_experience,
                client_ip=client_ip,
                error_message=error_message
            )
            
            async with self.async_session() as session:
                session.add(api_response)
                await session.commit()
                
            logger.debug(f"Stored API response for endpoint {endpoint} with ICAO codes: {icao_codes}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to store API response: {str(e)}")
            return False
    
    def _extract_icao_codes(self, request_data: Dict[str, Any], endpoint: str) -> str:
        if endpoint == "brief":
            return request_data.get("icao", "").upper()
        elif endpoint == "route":
            airports = request_data.get("airports", [])
            return " -> ".join([airport.upper() for airport in airports])
        return ""
    
    async def get_recent_responses(
        self,
        endpoint: Optional[str] = None,
        icao_code: Optional[str] = None,
        limit: int = 100
    ) -> list:
        try:
            async with self.async_session() as session:
                query = select(APIResponse)
                
                if endpoint:
                    query = query.where(APIResponse.endpoint == endpoint)
                
                if icao_code:
                    query = query.where(APIResponse.icao_codes.ilike(f"%{icao_code.upper()}%"))
                
                query = query.order_by(desc(APIResponse.created_at)).limit(limit)
                
                result = await session.execute(query)
                rows = result.scalars().all()
                
                return [{
                    "id": row.id,
                    "endpoint": row.endpoint,
                    "request_data": row.request_data,
                    "response_data": row.response_data,
                    "processing_time_seconds": row.processing_time_seconds,
                    "icao_codes": row.icao_codes,
                    "aircraft_type": row.aircraft_type,
                    "pilot_experience": row.pilot_experience,
                    "created_at": row.created_at.isoformat() if row.created_at else None,
                    "client_ip": row.client_ip,
                    "error_message": row.error_message
                } for row in rows]
                
        except Exception as e:
            logger.error(f"Failed to retrieve API responses: {str(e)}")
            return []
    
    async def get_usage_stats(self, days: int = 30) -> Dict[str, Any]:
        try:
            async with self.async_session() as session:
                query = text("""
                    SELECT 
                        endpoint,
                        COUNT(*) as total_requests,
                        COUNT(DISTINCT icao_codes) as unique_airports,
                        AVG(CAST(processing_time_seconds AS FLOAT)) as avg_processing_time,
                        COUNT(CASE WHEN error_message IS NOT NULL THEN 1 END) as error_count
                    FROM api_responses 
                    WHERE created_at >= NOW() - INTERVAL '%s days'
                    GROUP BY endpoint
                """ % days)
                
                result = await session.execute(query)
                rows = result.fetchall()
                
                stats = []
                for row in rows:
                    stats.append({
                        "endpoint": row[0],
                        "total_requests": row[1],
                        "unique_airports": row[2],
                        "avg_processing_time": float(row[3]) if row[3] else 0.0,
                        "error_count": row[4],
                        "error_rate_percent": round((row[4] / row[1]) * 100, 2) if row[1] > 0 else 0
                    })
                
                return {
                    "period_days": days,
                    "stats": stats
                }
                
        except Exception as e:
            logger.error(f"Failed to get usage stats: {str(e)}")
            return {"error": str(e), "period_days": days, "stats": []}
    
    async def close(self):
        if self.engine:
            await self.engine.dispose()
            logger.info("Database connection closed")

db_manager = DatabaseManager()

async def get_database():
    if not db_manager.engine:
        await db_manager.initialize()
    return db_manager

async def initialize_database():
    await db_manager.initialize()
    await db_manager.create_tables()
    return db_manager 