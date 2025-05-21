"""
Caching functions for RunwayGuard.
Handles all caching of external API calls using Redis.
"""

import httpx
import asyncio
import json
import os
from redis import asyncio as aioredis
from dotenv import load_dotenv

load_dotenv()

REDIS_URL = os.getenv('REDIS_URL')
BUCKET_SECONDS = 60

redis = aioredis.from_url(REDIS_URL, decode_responses=True)

async def cached_fetch(key, url, parser=None):
    try:
        cached_data = await redis.get(key)
        if cached_data:
            return json.loads(cached_data)
            
        async with httpx.AsyncClient() as client:
            r = await client.get(url, timeout=10.0)
            r.raise_for_status()
            
        data = await parser(r) if parser and asyncio.iscoroutinefunction(parser) else parser(r) if parser else r.json() if r.headers.get("content-type","").startswith("application/json") else r.text
        
        await redis.setex(key, BUCKET_SECONDS, json.dumps(data))
        return data
        
    except httpx.RequestError as exc:
        raise RuntimeError(f"Fetch failed: {exc}") from exc