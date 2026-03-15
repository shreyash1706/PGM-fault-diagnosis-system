"""
Victim Server - Python 3.12 compatible version
"""
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
import redis.asyncio as redis  # Updated import for async Redis
import psutil
import time
import random
import asyncio
import logging
from datetime import datetime, timezone
from contextlib import asynccontextmanager
import uvicorn
import socket
import platform
from typing import Dict, Any, Optional
from pydantic import BaseModel

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Pydantic models for request/response
class DataUpdate(BaseModel):
    data: str

class FaultResponse(BaseModel):
    message: str
    fault: str
    timestamp: datetime

class StatusResponse(BaseModel):
    status: str
    service: str
    timestamp: datetime
    faults_active: Dict[str, bool]
    system: str

# Global variables for fault injection
fault_active: Dict[str, bool] = {
    "cpu_spike": False,
    "memory_leak": False,
    "network_delay": False,
    "database_slow": False,
    "random_crash": False
}

# Redis connection
redis_client: Optional[redis.Redis] = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    global redis_client
    try:
        redis_client = await redis.from_url(
            "redis://redis:6379",
            decode_responses=True,
            health_check_interval=30
        )
        await redis_client.ping()
        logger.info("✅ Connected to Redis")
        
        # Initialize some data
        await redis_client.set("important_data", "This is important data")
        await redis_client.set("counter", "0")
        await redis_client.set("start_time", str(time.time()))
    except Exception as e:
        logger.warning(f"⚠️ Redis not available: {e}")
        redis_client = None
    
    # Get system info
    system_info = {
        "platform": platform.platform(),
        "processor": platform.processor(),
        "python_version": platform.python_version(),
        "hostname": socket.gethostname()
    }
    logger.info(f"🚀 Victim server started on {system_info['hostname']}")
    logger.info(f"Python: {system_info['python_version']}")
    logger.info(f"System: {system_info['platform']}")
    
    yield
    
    # Shutdown
    if redis_client:
        await redis_client.close()
    logger.info("👋 Victim server shutting down")

# Create FastAPI app
app = FastAPI(
    title="Victim Server",
    description="A deliberately breakable server for fault diagnosis",
    version="2.0.0",
    lifespan=lifespan
)

# ============= HEALTHY ENDPOINTS =============

@app.get("/", response_model=StatusResponse)
async def root():
    """Healthy root endpoint"""
    return StatusResponse(
        status="alive",
        service="Victim Server",
        timestamp=datetime.now(timezone.utc),
        faults_active=fault_active,
        system=platform.platform()
    )

@app.get("/health")
async def health():
    """Health check endpoint for monitoring"""
    redis_status = "disconnected"
    if redis_client:
        try:
            await redis_client.ping()
            redis_status = "connected"
        except:
            redis_status = "error"
    
    return {
        "status": "healthy",
        "cpu_percent": psutil.cpu_percent(interval=0.5),
        "memory_percent": psutil.virtual_memory().percent,
        "disk_percent": psutil.disk_usage('/').percent,
        "redis_status": redis_status,
        "timestamp": datetime.now(timezone.utc).isoformat()
    }

@app.get("/api/data")
async def get_data():
    """Normal API endpoint with slight delay"""
    # Check for database fault
    if fault_active["database_slow"]:
        await asyncio.sleep(5)  # Artificial slowdown
    
    if redis_client:
        try:
            await redis_client.ping()
            data = await redis_client.get("important_data")
            counter = await redis_client.incr("counter")
            return {
                "data": data,
                "counter": counter,
                "from_cache": False,
                "timestamp": datetime.now(timezone.utc).isoformat()
            }
        except Exception as e:
            logger.error(f"Redis error: {e}")
            return {
                "data": "Error connecting to Redis",
                "counter": 0,
                "from_cache": True,
                "error": str(e)
            }
    
    # Fallback if Redis is down
    return {
        "data": "Fallback data (Redis unavailable)",
        "counter": 0,
        "from_cache": True
    }

@app.post("/api/data")
async def update_data(new_data: DataUpdate):
    """Update data in database"""
    if not redis_client:
        raise HTTPException(status_code=503, detail="Database unavailable")
    
    try:
        await redis_client.set("important_data", new_data.data)
        return {
            "message": "Data updated",
            "success": True,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")

# ============= FAULT INJECTION ENDPOINTS =============

@app.post("/fault/cpu/{action}", response_model=FaultResponse)
async def cpu_fault(action: str):
    """Inject CPU spike fault"""
    if action == "start":
        fault_active["cpu_spike"] = True
        # Start CPU spike in background task
        asyncio.create_task(_cpu_spike())
        return FaultResponse(
            message="CPU spike started",
            fault="cpu_spike",
            timestamp=datetime.now(timezone.utc)
        )
    elif action == "stop":
        fault_active["cpu_spike"] = False
        return FaultResponse(
            message="CPU spike stopped",
            fault="cpu_spike",
            timestamp=datetime.now(timezone.utc)
        )
    raise HTTPException(status_code=400, detail="Invalid action")

async def _cpu_spike():
    """Background CPU spike - more aggressive version"""
    while fault_active["cpu_spike"]:
        # Continuous heavy computation without sleeping
        start = time.time()
        while time.time() - start < 0.5:  # Run for 0.5 seconds continuously
            for i in range(100000):
                _ = i ** 2 + i ** 3 + i ** 4
        # Very tiny sleep just to yield control
        await asyncio.sleep(0.01)
        logger.info("CPU spike running...")

@app.post("/fault/memory/{action}", response_model=FaultResponse)
async def memory_fault(action: str):
    """Inject memory leak fault"""
    if action == "start":
        fault_active["memory_leak"] = True
        asyncio.create_task(_memory_leak())
        return FaultResponse(
            message="Memory leak started",
            fault="memory_leak",
            timestamp=datetime.now(timezone.utc)
        )
    elif action == "stop":
        fault_active["memory_leak"] = False
        return FaultResponse(
            message="Memory leak stopped",
            fault="memory_leak",
            timestamp=datetime.now(timezone.utc)
        )

async def _memory_leak():
    """Background memory leak - async version"""
    leaky_list = []
    while fault_active["memory_leak"]:
        # Add 10MB every second
        leaky_list.append(' ' * 10 * 1024 * 1024)
        logger.info(f"Memory leak: added 10MB, total: {len(leaky_list) * 10}MB")
        await asyncio.sleep(1)

@app.post("/fault/network/{action}", response_model=FaultResponse)
async def network_fault(action: str):
    """Inject network delay"""
    if action == "start":
        fault_active["network_delay"] = True
        return FaultResponse(
            message="Network delay started",
            fault="network_delay",
            timestamp=datetime.now(timezone.utc)
        )
    elif action == "stop":
        fault_active["network_delay"] = False
        return FaultResponse(
            message="Network delay stopped",
            fault="network_delay",
            timestamp=datetime.now(timezone.utc)
        )

@app.post("/fault/database/{action}", response_model=FaultResponse)
async def database_fault(action: str):
    """Inject database slowdown"""
    if action == "start":
        fault_active["database_slow"] = True
        return FaultResponse(
            message="Database slowdown started",
            fault="database_slow",
            timestamp=datetime.now(timezone.utc)
        )
    elif action == "stop":
        fault_active["database_slow"] = False
        return FaultResponse(
            message="Database slowdown stopped",
            fault="database_slow",
            timestamp=datetime.now(timezone.utc)
        )

@app.get("/api/slow")
async def slow_endpoint():
    """Endpoint that can be slow"""
    if fault_active["network_delay"]:
        await asyncio.sleep(random.uniform(2, 5))
    
    if fault_active["random_crash"] and random.random() < 0.3:
        raise HTTPException(status_code=500, detail="Random crash triggered")
    
    return {
        "message": "This might be slow",
        "delay_applied": fault_active["network_delay"],
        "timestamp": datetime.now(timezone.utc).isoformat()
    }

@app.get("/api/status")
async def full_status():
    """Get complete system status"""
    redis_connected = False
    start_time_val = time.time()
    
    if redis_client:
        try:
            await redis_client.ping()
            redis_connected = True
            stored_start = await redis_client.get("start_time")
            if stored_start:
                start_time_val = float(stored_start)
        except Exception as e:
            logger.error(f"Redis status check failed: {e}")
    
    return {
        "app": {
            "uptime": time.time() - start_time_val,
            "faults": fault_active,
            "platform": platform.platform(),
            "python_version": platform.python_version()
        },
        "system": {
            "cpu": psutil.cpu_percent(interval=0.5),
            "memory": psutil.virtual_memory().percent,
            "disk": psutil.disk_usage('/').percent,
            "cpu_count": psutil.cpu_count(),
            "memory_total": psutil.virtual_memory().total / (1024**3)  # GB
        },
        "database": {
            "connected": redis_connected
        }
    }

@app.get("/api/metrics")
async def get_metrics():
    """Get detailed metrics for monitoring"""
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "cpu": {
            "percent": psutil.cpu_percent(interval=0.5, percpu=True),
            "frequency": psutil.cpu_freq()._asdict() if psutil.cpu_freq() else None,
            "stats": psutil.cpu_stats()._asdict()
        },
        "memory": {
            "virtual": psutil.virtual_memory()._asdict(),
            "swap": psutil.swap_memory()._asdict()
        },
        "disk": {
            "usage": psutil.disk_usage('/')._asdict(),
            "io": psutil.disk_io_counters()._asdict() if psutil.disk_io_counters() else None
        },
        "network": {
            "connections": len(psutil.net_connections()),
            "io": psutil.net_io_counters()._asdict()
        },
        "process": {
            "pid": psutil.Process().pid,
            "memory_percent": psutil.Process().memory_percent(),
            "cpu_percent": psutil.Process().cpu_percent(),
            "threads": len(psutil.Process().threads())
        }
    }

if __name__ == "__main__":
    uvicorn.run(
        "app:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info"
    )