"""
Victim Server - Complete with all 4 fault types
CPU Spike, Memory Leak, API Latency, and Error Rate
"""
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
import redis.asyncio as redis
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
import statistics

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Pydantic models
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
    "cpu_spike": False,        # FAULT 1: CPU overload
    "memory_leak": False,       # FAULT 2: Memory exhaustion
    "api_latency": False,       # FAULT 3: Slow API responses
    "error_rate": False         # FAULT 4: Random 500 errors
}

# For tracking metrics
request_times = []
error_count = 0
total_requests = 0

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
        
        # Initialize realistic data
        await redis_client.set("products", '{"laptop": 999, "mouse": 25, "keyboard": 75}')
        await redis_client.set("users", "1500")
        await redis_client.set("orders_today", "42")
        await redis_client.set("start_time", str(time.time()))
    except Exception as e:
        logger.warning(f"⚠️ Redis not available: {e}")
        redis_client = None
    
    logger.info(f"🚀 Victim server started on {socket.gethostname()}")
    yield
    
    # Shutdown
    if redis_client:
        await redis_client.close()
    logger.info("👋 Victim server shutting down")

# Create FastAPI app
app = FastAPI(
    title="Victim Server",
    description="Complete fault diagnosis testbed with 4 fault types",
    version="3.0.0",
    lifespan=lifespan
)

# ============= MIDDLEWARE for Tracking =============
@app.middleware("http")
async def track_requests(request: Request, call_next):
    """Track request times and error rates"""
    global total_requests, error_count, request_times
    
    total_requests += 1
    start_time = time.time()
    
    try:
        response = await call_next(request)
        process_time = time.time() - start_time
        
        # Keep last 100 request times for latency calculation
        request_times.append(process_time * 1000)  # Convert to ms
        if len(request_times) > 100:
            request_times.pop(0)
        
        return response
    except Exception as e:
        error_count += 1
        raise

# ============= ROOT ENDPOINT =============
@app.get("/")
async def root():
    """Root endpoint - shows server status"""
    return {
        "server": "Victim Server",
        "status": "running",
        "version": "3.0.0",
        "faults_active": fault_active,
        "endpoints": {
            "health": "/health",
            "products": "/api/products",
            "users": "/api/users",
            "metrics": "/api/metrics",
            "debug": "/api/debug",
            "faults": {
                "cpu": "/fault/cpu/{start/stop}",
                "memory": "/fault/memory/{start/stop}",
                "latency": "/fault/latency/{start/stop}",
                "errors": "/fault/errors/{start/stop}"
            }
        },
        "timestamp": datetime.now(timezone.utc).isoformat()
    }    

# ============= MAIN BUSINESS ENDPOINT =============
@app.get("/api/products")
async def get_products():
    """Main business endpoint - gets product data from Redis"""
    global error_count
    
    # FAULT 1: CPU Spike affects response time
    if fault_active["cpu_spike"]:
        # Simulate CPU contention - do heavy computation
        for _ in range(1000000):
            _ = random.random() ** 2
    
    # FAULT 3: API Latency - artificial delay
    if fault_active["api_latency"]:
        delay = random.uniform(1.0, 3.0)
        await asyncio.sleep(delay)
    
    # FAULT 4: Error Rate - random failures
    if fault_active["error_rate"] and random.random() < 0.3:  # 30% error rate
        error_count += 1
        logger.warning("⚠️ Random 500 error injected")
        raise HTTPException(
            status_code=500, 
            detail="Internal Server Error (Fault injected)"
        )
    
    # Normal operation - get from Redis
    if redis_client:
        try:
            products = await redis_client.get("products")
            return {
                "products": products,
                "source": "redis",
                "timestamp": datetime.now(timezone.utc).isoformat()
            }
        except Exception as e:
            logger.error(f"Redis error: {e}")
    
    # Fallback data
    return {
        "products": '{"laptop": 999, "mouse": 25, "keyboard": 75}',
        "source": "fallback",
        "timestamp": datetime.now(timezone.utc).isoformat()
    }

@app.get("/api/users")
async def get_users():
    """Another business endpoint"""
    if fault_active["cpu_spike"]:
        for _ in range(500000):
            _ = random.random() ** 3
    
    if fault_active["api_latency"]:
        await asyncio.sleep(random.uniform(0.5, 2.0))
    
    if fault_active["error_rate"] and random.random() < 0.3:
        raise HTTPException(status_code=500, detail="Random error")
    
    users = await redis_client.get("users") if redis_client else "1500"
    return {"active_users": users}

# ============= FAULT INJECTION ENDPOINTS =============

# FAULT 1: CPU SPIKE
@app.post("/fault/cpu/{action}", response_model=FaultResponse)
async def cpu_fault(action: str):
    """FAULT 1: CPU Spike - makes the container compute-intensive"""
    if action == "start":
        fault_active["cpu_spike"] = True
        asyncio.create_task(_cpu_spike())
        return FaultResponse(
            message="🔥 CPU spike started - API will be slow",
            fault="cpu_spike",
            timestamp=datetime.now(timezone.utc)
        )
    elif action == "stop":
        fault_active["cpu_spike"] = False
        return FaultResponse(
            message="✅ CPU spike stopped",
            fault="cpu_spike",
            timestamp=datetime.now(timezone.utc)
        )
    raise HTTPException(status_code=400, detail="Invalid action")

async def _cpu_spike():
    """Background CPU spike - affects all endpoints"""
    while fault_active["cpu_spike"]:
        # Heavy computation that impacts everything
        start = time.time()
        while time.time() - start < 1.0:  # 1 second of continuous CPU work
            [i ** 2 for i in range(100000)]
        await asyncio.sleep(0.1)

# FAULT 2: MEMORY LEAK
@app.post("/fault/memory/{action}", response_model=FaultResponse)
async def memory_fault(action: str):
    """FAULT 2: Memory Leak - gradually consumes RAM"""
    if action == "start":
        fault_active["memory_leak"] = True
        asyncio.create_task(_memory_leak())
        return FaultResponse(
            message="🧠 Memory leak started - RAM will fill up",
            fault="memory_leak",
            timestamp=datetime.now(timezone.utc)
        )
    elif action == "stop":
        fault_active["memory_leak"] = False
        return FaultResponse(
            message="✅ Memory leak stopped",
            fault="memory_leak",
            timestamp=datetime.now(timezone.utc)
        )

async def _memory_leak():
    """Background memory leak - eats RAM over time"""
    leaky_list = []
    chunk_size = 10 * 1024 * 1024  # 10MB chunks
    
    while fault_active["memory_leak"]:
        # Add memory chunk
        leaky_list.append('X' * chunk_size)
        current_mb = len(leaky_list) * 10
        
        logger.info(f"🧠 Memory leak: {current_mb}MB used")
        
        # When memory gets high, system slows down naturally
        if current_mb > 100:  # After 100MB, API gets slower
            logger.warning(f"⚠️ High memory ({current_mb}MB) - API slowing down")
        
        await asyncio.sleep(2)

# FAULT 3: API LATENCY
@app.post("/fault/latency/{action}", response_model=FaultResponse)
async def latency_fault(action: str):
    """FAULT 3: API Latency - adds delay to all responses"""
    if action == "start":
        fault_active["api_latency"] = True
        return FaultResponse(
            message="🐌 API latency started - responses will be slow",
            fault="api_latency",
            timestamp=datetime.now(timezone.utc)
        )
    elif action == "stop":
        fault_active["api_latency"] = False
        return FaultResponse(
            message="✅ API latency stopped",
            fault="api_latency",
            timestamp=datetime.now(timezone.utc)
        )

# FAULT 4: ERROR RATE
@app.post("/fault/errors/{action}", response_model=FaultResponse)
async def errors_fault(action: str):
    """FAULT 4: Error Rate - injects random 500 errors"""
    if action == "start":
        fault_active["error_rate"] = True
        return FaultResponse(
            message="💥 Error rate started - 30% of requests will fail",
            fault="error_rate",
            timestamp=datetime.now(timezone.utc)
        )
    elif action == "stop":
        fault_active["error_rate"] = False
        return FaultResponse(
            message="✅ Error rate stopped",
            fault="error_rate",
            timestamp=datetime.now(timezone.utc)
        )

# ============= METRICS ENDPOINTS =============

@app.get("/health")
async def health():
    """Enhanced health check with more metrics"""
    global error_count, total_requests, request_times
    
    # Calculate average latency
    avg_latency = statistics.mean(request_times) if request_times else 0
    
    # Calculate error rate
    error_rate_pct = (error_count / total_requests * 100) if total_requests > 0 else 0
    
    redis_status = "disconnected"
    if redis_client:
        try:
            await redis_client.ping()
            redis_status = "connected"
        except:
            redis_status = "error"
    
    return {
        "status": "healthy",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "metrics": {
            "cpu_percent": psutil.cpu_percent(interval=0.5),
            "memory_percent": psutil.virtual_memory().percent,
            "avg_latency_ms": round(avg_latency, 2),
            "error_rate_percent": round(error_rate_pct, 2),
            "total_requests": total_requests
        },
        "faults_active": fault_active,
        "redis_status": redis_status
    }

@app.get("/api/debug")
async def debug():
    """Debug endpoint showing current fault states"""
    return {
        "faults": fault_active,
        "stats": {
            "total_requests": total_requests,
            "error_count": error_count,
            "recent_latencies": request_times[-10:] if request_times else []
        }
    }

@app.get("/api/metrics")
async def get_metrics():
    """Detailed metrics for ML model"""
    global error_count, total_requests, request_times
    
    avg_latency = statistics.mean(request_times) if request_times else 0
    error_rate_pct = (error_count / total_requests * 100) if total_requests > 0 else 0
    
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "faults_active": fault_active,
        "observable_nodes": {
            "cpu_usage": _categorize_cpu(psutil.cpu_percent(interval=0.5)),
            "ram_usage": _categorize_ram(psutil.virtual_memory().percent),
            "api_latency": _categorize_latency(avg_latency),
            "error_rate": _categorize_errors(error_rate_pct)
        },
        "raw_values": {
            "cpu_percent": psutil.cpu_percent(interval=0.5),
            "memory_percent": psutil.virtual_memory().percent,
            "avg_latency_ms": avg_latency,
            "error_rate_percent": error_rate_pct
        }
    }

def _categorize_cpu(cpu_percent):
    """Convert CPU to discrete states"""
    if cpu_percent < 30:
        return "Normal"
    elif cpu_percent < 70:
        return "High"
    else:
        return "Critical"

def _categorize_ram(ram_percent):
    """Convert RAM to discrete states"""
    if ram_percent < 40:
        return "Normal"
    elif ram_percent < 70:
        return "High"
    else:
        return "Critical"

def _categorize_latency(latency_ms):
    """Convert latency to discrete states"""
    if latency_ms < 100:
        return "Normal"
    elif latency_ms < 500:
        return "Elevated"
    else:
        return "Timeout"

def _categorize_errors(error_pct):
    """Convert error rate to discrete states"""
    return "Spiking" if error_pct > 5 else "Zero"

if __name__ == "__main__":
    uvicorn.run(
        "app:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info"
    )