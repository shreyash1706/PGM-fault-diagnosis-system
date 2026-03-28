"""
Victim Server - Complete Fault Injection System with Auto/Manual Control
CPU Spike (80%+), Memory Leak (RAM rises), API Latency (3-8s), Error Rate (30%)

This server simulates real-world server failures for training ML models.
Features:
- Automatic faults (configurable on/off, 25% chance each, 20-40s duration)
- Manual fault triggers (POST endpoints)
- Multiple simultaneous faults
- Natural noise and false positives
- PGM-ready metrics (discrete states)
- Auto-fault system can be disabled/enabled via API
"""

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import PlainTextResponse
import redis.asyncio as redis
import psutil
import time
import random
import asyncio
import logging
from datetime import datetime
from contextlib import asynccontextmanager
import uvicorn
import socket
from typing import Dict, List
import statistics
import math

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
logger = logging.getLogger(__name__)


# ============================================================================
# GLOBAL VARIABLES
# ============================================================================

# Fault states - True if fault is currently active
fault_active: Dict[str, bool] = {
    "cpu_spike": False,      # CPU overload fault
    "memory_leak": False,    # Memory exhaustion fault
    "api_latency": False,    # Slow API responses fault
    "error_rate": False      # Random 500 errors fault
}

# Auto-fault system enabled/disabled
auto_fault_enabled: bool = True

# Memory leak storage - grows when memory leak fault is active
memory_leak_data: List[bytearray] = []

# Metrics tracking
request_times: List[float] = []      # Response times for last 100 requests (ms)
error_count: int = 0                  # Total number of 500 errors
total_requests: int = 0               # Total requests processed

# Redis connection
redis_client = None


# ============================================================================
# CONFIGURATION
# ============================================================================

class Config:
    """Configuration for fault injection and noise"""
    
    # Automatic fault probabilities (checked every 10 seconds)
    # Each fault type is independent - multiple can trigger simultaneously
    AUTO_CPU_PROB: float = 0.25      # 25% chance for CPU spike
    AUTO_MEMORY_PROB: float = 0.25   # 25% chance for memory leak
    AUTO_LATENCY_PROB: float = 0.25  # 25% chance for API latency
    AUTO_ERROR_PROB: float = 0.25    # 25% chance for error rate
    
    # Fault duration range (seconds)
    FAULT_DURATION: tuple = (20, 40)  # Faults last 20-40 seconds
    
    # Natural noise (false positives)
    CPU_NOISE_PROB: float = 0.15      # 15% chance of random CPU spike
    CPU_NOISE_RANGE: tuple = (2, 8)   # 2-8% extra CPU when noise occurs
    LATENCY_NOISE_PROB: float = 0.15  # 15% chance of random latency
    LATENCY_NOISE_RANGE: tuple = (0.1, 0.4)  # 0.1-0.4s delay when noise occurs


# Track when each fault will automatically stop
fault_end_times: Dict[str, float] = {}

# Track background tasks for each fault
fault_tasks: Dict[str, asyncio.Task] = {}


# ============================================================================
# UNDERSTANDING CPU METRICS
# ============================================================================
#
# There are two ways to measure CPU usage, and both are CORRECT:
#
# 1. Docker Container CPU (visible in Docker Desktop)
#    - Shows: 100.40% / 400% (4 CPUs available)
#    - Meaning: Container is using 100.40% of ONE CPU core
#    - Calculation: 100.40% of 1 core = 1 core fully utilized
#    - Interpretation: CPU spike fault is ACTIVE and working
#
# 2. psutil.cpu_percent() (from /health endpoint)
#    - Shows: 2.6% (percentage of TOTAL system)
#    - Meaning: 2.6% of ALL 4 CPU cores combined
#    - Calculation: 2.6% × 4 cores = 10.4% of one core
#    - Interpretation: System-wide average CPU usage
#
# RELATIONSHIP:
# Docker 100% (1 core) = psutil 25% (4 cores)
# If Docker shows 100% on one core, psutil will show ~25% total
# This is NOT a bug - it's measuring different things!
#
# ============================================================================


# ============================================================================
# BACKGROUND TASKS (Fault Implementation)
# ============================================================================

async def cpu_hog():
    """
    CPU spike fault - consumes CPU cycles to spike usage to 80-95%
    
    This function runs a loop of heavy mathematical computations that
    consume significant CPU resources. When active, Docker will show
    high CPU usage (80-100% of one core).
    """
    logger.warning("CPU HOG STARTED - CPU will spike to 80-95%")
    while fault_active["cpu_spike"]:
        # Heavy computation loop - 5 million iterations
        for i in range(5_000_000):
            # Complex math operations that stress CPU
            _ = math.sqrt(i) * math.sin(i) * math.cos(i) ** 3
            _ = math.pow(i, 1.5) * math.log(i + 1)
            _ = math.exp(math.sin(i)) * math.cos(math.tan(i))
        # Tiny break to prevent blocking the event loop completely
        await asyncio.sleep(0.01)
    logger.warning("CPU HOG STOPPED")


async def memory_hog():
    """
    Memory leak fault - consumes RAM to simulate memory exhaustion
    
    This function adds 50MB chunks of memory every 2 seconds when active.
    Memory usage will visibly increase in Docker Desktop.
    """
    global memory_leak_data
    chunk_size = 50 * 1024 * 1024  # 50MB chunks
    logger.warning("MEMORY HOG STARTED - RAM will increase")
    
    while fault_active["memory_leak"]:
        # Add a large chunk of memory
        memory_leak_data.append(bytearray(chunk_size))
        total_mb = len(memory_leak_data) * 50
        logger.warning(f"MEMORY LEAK: {total_mb}MB total")
        
        # Touch memory to ensure it's actually allocated
        for chunk in memory_leak_data:
            chunk[0] = 1
        await asyncio.sleep(2)  # Add chunk every 2 seconds
    logger.warning("MEMORY HOG STOPPED")


async def auto_fault_manager():
    """
    Automatic fault manager - randomly triggers and stops faults
    
    This background task runs every 10 seconds and:
    1. Checks for expired faults and stops them
    2. Randomly triggers new faults based on probabilities (if enabled)
    3. Logs multiple fault conditions
    """
    global fault_end_times, memory_leak_data, fault_tasks, auto_fault_enabled
    
    while True:
        try:
            current_time = time.time()
            
            # ----- Step 1: Clean up expired faults -----
            expired = []
            for fault, end_time in list(fault_end_times.items()):
                if current_time > end_time and fault_active.get(fault, False):
                    fault_active[fault] = False
                    expired.append(fault)
                    logger.info(f"AUTO FAULT ENDED: {fault}")
                    
                    # Cancel background task if it exists
                    if fault in fault_tasks:
                        fault_tasks[fault].cancel()
                        del fault_tasks[fault]
                    
                    # Clear memory leak data when fault ends
                    if fault == "memory_leak":
                        memory_leak_data.clear()
            
            # Remove expired faults from tracking
            for fault in expired:
                if fault in fault_end_times:
                    del fault_end_times[fault]
            
            # ----- Step 2: Trigger new faults (only if auto-fault is enabled) -----
            if auto_fault_enabled:
                # CPU Fault
                if not fault_active["cpu_spike"] and random.random() < Config.AUTO_CPU_PROB:
                    duration = random.uniform(*Config.FAULT_DURATION)
                    fault_active["cpu_spike"] = True
                    fault_end_times["cpu_spike"] = current_time + duration
                    task = asyncio.create_task(cpu_hog())
                    fault_tasks["cpu_spike"] = task
                    logger.warning(f"AUTO CPU FAULT for {duration:.1f}s")
                
                # Memory Fault
                if not fault_active["memory_leak"] and random.random() < Config.AUTO_MEMORY_PROB:
                    duration = random.uniform(*Config.FAULT_DURATION)
                    fault_active["memory_leak"] = True
                    fault_end_times["memory_leak"] = current_time + duration
                    task = asyncio.create_task(memory_hog())
                    fault_tasks["memory_leak"] = task
                    logger.warning(f"AUTO MEMORY FAULT for {duration:.1f}s")
                
                # Latency Fault
                if not fault_active["api_latency"] and random.random() < Config.AUTO_LATENCY_PROB:
                    duration = random.uniform(*Config.FAULT_DURATION)
                    fault_active["api_latency"] = True
                    fault_end_times["api_latency"] = current_time + duration
                    logger.warning(f"AUTO LATENCY FAULT for {duration:.1f}s")
                
                # Error Fault
                if not fault_active["error_rate"] and random.random() < Config.AUTO_ERROR_PROB:
                    duration = random.uniform(*Config.FAULT_DURATION)
                    fault_active["error_rate"] = True
                    fault_end_times["error_rate"] = current_time + duration
                    logger.warning(f"AUTO ERROR FAULT for {duration:.1f}s")
            
            # Log multiple faults if they occur together
            active = [f for f, v in fault_active.items() if v]
            if len(active) > 1:
                logger.warning(f"MULTIPLE FAULTS: {active}")
            
            await asyncio.sleep(10)  # Check every 10 seconds
            
        except Exception as e:
            logger.error(f"Auto fault error: {e}")
            await asyncio.sleep(5)


# ============================================================================
# LIFESPAN MANAGEMENT
# ============================================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan - startup and shutdown tasks"""
    global redis_client
    
    # ----- Startup -----
    try:
        redis_client = await redis.from_url("redis://redis:6379", decode_responses=True)
        await redis_client.ping()  # type: ignore
        await redis_client.set("products", '{"laptop": 999, "mouse": 25}')
        logger.info("Connected to Redis")
    except Exception as e:
        logger.warning(f"Redis not available: {e}")
    
    # Start automatic fault manager background task
    asyncio.create_task(auto_fault_manager())
    logger.info("Server started - AUTO FAULTS ENABLED (use /auto-fault/stop to disable)")
    logger.info("  CPU Spike: 80-95% CPU")
    logger.info("  Memory Leak: +50MB/2sec (visible RAM increase)")
    logger.info("  API Latency: 3-8 second delay")
    logger.info("  Error Rate: 30% failures")
    
    yield  # Server runs here
    
    # ----- Shutdown -----
    # Cancel all running fault tasks
    for task in fault_tasks.values():
        task.cancel()
    if redis_client:
        await redis_client.close()


# Create FastAPI application
app = FastAPI(
    title="Victim Server",
    description="Fault injection system for ML training",
    version="9.0.0",
    lifespan=lifespan
)


# ============================================================================
# MIDDLEWARE
# ============================================================================

@app.middleware("http")
async def track_requests(request: Request, call_next):
    """Middleware to track request times and errors"""
    global total_requests, error_count, request_times
    
    total_requests += 1
    start = time.time()
    
    try:
        # Add natural latency noise (false positives)
        if not fault_active["api_latency"] and random.random() < 0.15:
            delay = random.uniform(0.1, 0.4)
            await asyncio.sleep(delay)
        
        response = await call_next(request)
        process_time = (time.time() - start) * 1000  # Convert to ms
        request_times.append(process_time)
        if len(request_times) > 100:
            request_times.pop(0)
        return response
    except Exception:
        error_count += 1
        raise


# ============================================================================
# BUSINESS ENDPOINTS
# ============================================================================

@app.get("/api/products")
async def get_products():
    """
    Get products endpoint
    Affected by: CPU spike, API latency, Error rate faults
    """
    global error_count
    
    # CPU Spike Fault - heavy computation
    if fault_active["cpu_spike"]:
        for i in range(8_000_000):  # 8 million iterations
            _ = math.sqrt(i) * math.sin(i) * math.cos(i) ** 3
            _ = math.pow(i, 1.7) * math.log(i + 1)
    
    # API Latency Fault - artificial delay
    if fault_active["api_latency"]:
        delay = random.uniform(3.0, 8.0)
        await asyncio.sleep(delay)
    
    # Error Rate Fault - random failures
    if fault_active["error_rate"]:
        if random.random() < 0.3:  # 30% failure rate
            error_count += 1
            raise HTTPException(status_code=500, detail="Random error injected")
    
    return {
        "products": "laptop: $999, mouse: $25",
        "timestamp": datetime.now().isoformat()
    }


@app.get("/api/users")
async def get_users():
    """
    Get users endpoint
    Affected by: CPU spike, API latency, Error rate faults
    """
    if fault_active["cpu_spike"]:
        for i in range(5_000_000):
            _ = math.sqrt(i) * math.pow(i, 1.5)
    
    if fault_active["api_latency"]:
        await asyncio.sleep(random.uniform(3.0, 8.0))
    
    if fault_active["error_rate"] and random.random() < 0.3:
        raise HTTPException(status_code=500, detail="Random error")
    
    return {"users": 1500, "active": 423}


# ============================================================================
# METRICS ENDPOINTS
# ============================================================================

@app.get("/health")
async def health():
    """
    Health check endpoint - real-time system metrics
    
    CPU NOTE: psutil.cpu_percent() measures TOTAL system CPU (all cores combined).
    If container uses 100% of 1 core on a 4-core system, this shows ~25%.
    This is NOT a bug - Docker and psutil measure different things:
    - Docker: Container's CPU relative to allocated cores (1 core = 100%)
    - psutil: Percentage of TOTAL system CPU (4 cores = 100%)
    """
    global error_count, total_requests, request_times, memory_leak_data
    
    # Get REAL system metrics with interval=None for non-blocking accurate async reading
    cpu = psutil.cpu_percent(interval=None)
    mem = psutil.virtual_memory().percent
    avg_lat = statistics.mean(request_times) if request_times else 0
    err_rate = (error_count / total_requests * 100) if total_requests > 0 else 0
    
    # Natural CPU noise (false positives) - only when fault not active
    if not fault_active["cpu_spike"] and random.random() < 0.15:
        cpu += random.uniform(2, 8)
        cpu = min(cpu, 100)
    
    return {
        "timestamp": datetime.now().isoformat(),
        "metrics": {
            "cpu_percent": round(cpu, 2),
            "memory_percent": round(mem, 2),
            "avg_latency_ms": round(avg_lat, 2),
            "error_rate_percent": round(err_rate, 2),
            "total_requests": total_requests,
            "memory_leak_mb": len(memory_leak_data) * 50
        },
        "faults_active": fault_active,
        "multiple_faults": sum(fault_active.values()) > 1,
        "auto_fault_enabled": auto_fault_enabled
    }


@app.get("/api/metrics")
async def get_metrics():
    """
    PGM-ready metrics - discrete states for machine learning models
    
    Converts continuous metrics into categorical states:
    - CPU: Normal (<20), High (20-50), Critical (>50)
    - RAM: Normal (<40), High (40-70), Critical (>70)
    - Latency: Normal (<200), Elevated (200-1000), Timeout (>1000)
    - Errors: Zero (<5), Spiking (>5)
    """
    health_data = await health()
    m = health_data["metrics"]
    
    return {
        "timestamp": health_data["timestamp"],
        "faults_active": fault_active,
        "auto_fault_enabled": auto_fault_enabled,
        "observable_nodes": {
            "cpu_usage": "Critical" if m["cpu_percent"] >= 30 else "High" if m["cpu_percent"] >= 10 else "Normal",
            "ram_usage": "Critical" if m["memory_percent"] >= 70 else "High" if m["memory_percent"] >= 20 else "Normal",
            "api_latency": "Timeout" if m["avg_latency_ms"] > 1000 else "Elevated" if m["avg_latency_ms"] > 200 else "Normal",
            "error_rate": "Spiking" if m["error_rate_percent"] > 5 else "Zero"
        }
    }

@app.get("/metrics", response_class=PlainTextResponse)
async def get_prometheus_format():
    """Endpoint scraped strictly by Prometheus."""
    health_data = await health()
    m = health_data["metrics"]
    
    lines = [
        "# HELP victim_cpu_percent CPU utilization.",
        "# TYPE victim_cpu_percent gauge",
        f'victim_cpu_percent {m["cpu_percent"]}',
        "# HELP victim_memory_percent Memory utilization.",
        "# TYPE victim_memory_percent gauge",
        f'victim_memory_percent {m["memory_percent"]}',
        "# HELP victim_avg_latency_ms Average API Latency in ms.",
        "# TYPE victim_avg_latency_ms gauge",
        f'victim_avg_latency_ms {m["avg_latency_ms"]}',
        "# HELP victim_error_rate_percent Percentage of HTTP errors.",
        "# TYPE victim_error_rate_percent gauge",
        f'victim_error_rate_percent {m["error_rate_percent"]}',
        "# HELP victim_total_requests Total requests served.",
        "# TYPE victim_total_requests counter",
        f'victim_total_requests {m["total_requests"]}',
        "# HELP victim_memory_leak_mb Memory leaked so far.",
        "# TYPE victim_memory_leak_mb gauge",
        f'victim_memory_leak_mb {m["memory_leak_mb"]}',
    ]
    return "\n".join(lines) + "\n"

@app.get("/api/debug")
async def debug():
    """
    Debug endpoint - internal state inspection
    Shows fault states and request statistics
    """
    return {
        "faults": fault_active,
        "auto_fault_enabled": auto_fault_enabled,
        "stats": {
            "total_requests": total_requests,
            "error_count": error_count,
            "error_rate_percent": (error_count / total_requests * 100) if total_requests > 0 else 0,
            "recent_latencies_ms": request_times[-10:] if request_times else [],
            "memory_leak_mb": len(memory_leak_data) * 50
        }
    }


# ============================================================================
# AUTO-FAULT CONTROL ENDPOINTS (NEW)
# ============================================================================

@app.post("/auto-fault/stop")
async def stop_auto_faults():
    """
    Stop automatic fault generation.
    This will not affect manually triggered faults.
    """
    global auto_fault_enabled
    auto_fault_enabled = False
    logger.warning("AUTO-FAULT SYSTEM DISABLED (manual triggers only)")
    return {
        "status": "success",
        "message": "Automatic fault generation stopped",
        "auto_fault_enabled": auto_fault_enabled,
        "note": "Manual fault triggers still work. Use /auto-fault/start to re-enable."
    }


@app.post("/auto-fault/start")
async def start_auto_faults():
    """
    Start automatic fault generation.
    """
    global auto_fault_enabled
    auto_fault_enabled = True
    logger.info("AUTO-FAULT SYSTEM ENABLED")
    return {
        "status": "success",
        "message": "Automatic fault generation started",
        "auto_fault_enabled": auto_fault_enabled,
        "probabilities": {
            "cpu": f"{Config.AUTO_CPU_PROB * 100}%",
            "memory": f"{Config.AUTO_MEMORY_PROB * 100}%",
            "latency": f"{Config.AUTO_LATENCY_PROB * 100}%",
            "errors": f"{Config.AUTO_ERROR_PROB * 100}%"
        }
    }


@app.get("/auto-fault/status")
async def get_auto_fault_status():
    """
    Get current status of automatic fault system.
    """
    return {
        "auto_fault_enabled": auto_fault_enabled,
        "active_faults": [f for f, v in fault_active.items() if v],
        "multiple_faults": sum(fault_active.values()) > 1,
        "probabilities": {
            "cpu": f"{Config.AUTO_CPU_PROB * 100}%",
            "memory": f"{Config.AUTO_MEMORY_PROB * 100}%",
            "latency": f"{Config.AUTO_LATENCY_PROB * 100}%",
            "errors": f"{Config.AUTO_ERROR_PROB * 100}%"
        },
        "fault_duration": f"{Config.FAULT_DURATION[0]}-{Config.FAULT_DURATION[1]} seconds"
    }


# ============================================================================
# MANUAL FAULT CONTROL ENDPOINTS
# ============================================================================
@app.post("/fault/cpu/{action}")
async def cpu_control(action: str):
    """Manually control CPU spike fault"""
    global fault_tasks
    if action == "start":
        fault_active["cpu_spike"] = True
        if "cpu_spike" in fault_tasks:
            fault_tasks["cpu_spike"].cancel()
        fault_tasks["cpu_spike"] = asyncio.create_task(cpu_hog())
        return {"message": "CPU spike STARTED - CPU will go to 80-95%"}
    elif action == "stop":
        fault_active["cpu_spike"] = False
        if "cpu_spike" in fault_tasks:
            fault_tasks["cpu_spike"].cancel()
            del fault_tasks["cpu_spike"]
        return {"message": "CPU spike STOPPED"}
    raise HTTPException(status_code=400, detail="Invalid action. Use 'start' or 'stop'")


@app.post("/fault/memory/{action}")
async def memory_control(action: str):
    """Manually control memory leak fault"""
    global memory_leak_data, fault_tasks
    if action == "start":
        fault_active["memory_leak"] = True
        if "memory_leak" in fault_tasks:
            fault_tasks["memory_leak"].cancel()
        fault_tasks["memory_leak"] = asyncio.create_task(memory_hog())
        return {"message": "Memory leak STARTED - RAM will increase"}
    elif action == "stop":
        fault_active["memory_leak"] = False
        if "memory_leak" in fault_tasks:
            fault_tasks["memory_leak"].cancel()
            del fault_tasks["memory_leak"]
        memory_leak_data.clear()
        return {"message": "Memory leak STOPPED"}
    raise HTTPException(status_code=400, detail="Invalid action. Use 'start' or 'stop'")


@app.post("/fault/latency/{action}")
async def latency_control(action: str):
    """Manually control API latency fault"""
    if action == "start":
        fault_active["api_latency"] = True
        return {"message": "Latency STARTED - 3-8s delay"}
    elif action == "stop":
        fault_active["api_latency"] = False
        return {"message": "Latency STOPPED"}
    raise HTTPException(status_code=400, detail="Invalid action. Use 'start' or 'stop'")


@app.post("/fault/errors/{action}")
async def errors_control(action: str):
    """Manually control error rate fault"""
    if action == "start":
        fault_active["error_rate"] = True
        return {"message": "Error rate STARTED - 30% failures"}
    elif action == "stop":
        fault_active["error_rate"] = False
        return {"message": "Error rate STOPPED"}
    raise HTTPException(status_code=400, detail="Invalid action. Use 'start' or 'stop'")


@app.post("/fault/stop-all")
async def stop_all_faults():
    """
    Stop ALL faults (both automatic and manual)
    """
    global fault_active, memory_leak_data, fault_tasks, fault_end_times
    
    # Stop all fault states
    for fault in fault_active:
        fault_active[fault] = False
    
    # Cancel all background tasks
    for task in fault_tasks.values():
        task.cancel()
    fault_tasks.clear()
    
    # Clear memory leak data
    memory_leak_data.clear()
    
    # Clear fault end times
    fault_end_times.clear()
    
    logger.warning("ALL FAULTS STOPPED (manual and auto)")
    return {
        "status": "success",
        "message": "All faults stopped",
        "faults_active": fault_active
    }


# ============================================================================
# ROOT ENDPOINT
# ============================================================================

@app.get("/")
async def root():
    """Root endpoint - server information"""
    return {
        "server": "Victim Server",
        "status": "running",
        "version": "9.0.0",
        "faults_active": fault_active,
        "auto_fault_enabled": auto_fault_enabled,
        "memory_leak_mb": len(memory_leak_data) * 50,
        "controls": {
            "auto_fault": {
                "enable": "POST /auto-fault/start",
                "disable": "POST /auto-fault/stop",
                "status": "GET /auto-fault/status"
            },
            "manual_faults": {
                "cpu": "POST /fault/cpu/{start/stop}",
                "memory": "POST /fault/memory/{start/stop}",
                "latency": "POST /fault/latency/{start/stop}",
                "errors": "POST /fault/errors/{start/stop}",
                "stop_all": "POST /fault/stop-all"
            },
            "metrics": {
                "health": "GET /health",
                "pgm_metrics": "GET /api/metrics",
                "debug": "GET /api/debug"
            }
        }
    }


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)