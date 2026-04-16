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
- NEW: Single fault mode with buffer period for PGM training
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

# NEW: Single fault mode with buffer (for PGM training)
single_fault_mode: bool = False  # Toggle for single-fault-with-buffer mode

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
    
    # NEW: PGM training mode configuration
    PGM_FAULT_DURATION: float = 30.0  # Fixed 30 second fault duration
    PGM_HEALTH_PROBABILITY: float = 0.7  # 70% chance to stay healthy
    PGM_BUFFER_MIN: float = 15.0  # Minimum buffer between faults (seconds)
    PGM_BUFFER_MAX: float = 45.0  # Maximum buffer between faults (seconds)


# Track when each fault will automatically stop
fault_end_times: Dict[str, float] = {}

# Track background tasks for each fault
fault_tasks: Dict[str, asyncio.Task] = {}

# NEW: Track if buffer period is active (no faults during this time)
buffer_active: bool = False
buffer_end_time: float = 0


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


async def pgm_fault_scheduler():
    """
    NEW: PGM-specific fault scheduler for training data collection.
    
    This implements:
    1. Single fault at a time (no multiple simultaneous faults)
    2. Faults last exactly 30 seconds
    3. Buffer period between faults (15-45 seconds)
    4. Exploration/Exploitation: 70% chance to stay healthy, 30% chance to trigger fault
    5. Random timing (not fixed intervals) - faults occur at irregular intervals
    """
    global fault_active, fault_end_times, fault_tasks, buffer_active, buffer_end_time, memory_leak_data
    
    fault_list = ["cpu_spike", "memory_leak", "api_latency", "error_rate"]
    
    while True:
        try:
            current_time = time.time()
            
            # Check if any fault is currently active
            active_faults = [f for f, v in fault_active.items() if v]
            
            # If a fault is active, check if it's time to stop it
            if active_faults:
                fault_name = active_faults[0]  # Only one fault should be active
                if current_time >= fault_end_times.get(fault_name, 0):
                    # Stop the fault
                    fault_active[fault_name] = False
                    logger.info(f"PGM FAULT ENDED: {fault_name} (lasted 30 seconds)")
                    
                    # Cancel background task if it exists
                    if fault_name in fault_tasks:
                        fault_tasks[fault_name].cancel()
                        del fault_tasks[fault_name]
                    
                    # Clear memory leak data
                    if fault_name == "memory_leak":
                        memory_leak_data.clear()
                    
                    # Start buffer period (no faults)
                    buffer_duration = random.uniform(Config.PGM_BUFFER_MIN, Config.PGM_BUFFER_MAX)
                    buffer_end_time = current_time + buffer_duration
                    buffer_active = True
                    logger.info(f"BUFFER PERIOD STARTED: {buffer_duration:.1f}s (no faults during this time)")
                    
                    # Remove from end times
                    if fault_name in fault_end_times:
                        del fault_end_times[fault_name]
            
            # If in buffer period, check if it's over
            elif buffer_active:
                if current_time >= buffer_end_time:
                    buffer_active = False
                    logger.info("BUFFER PERIOD ENDED - Ready for next fault")
            
            # If no fault active and not in buffer period, decide whether to trigger a fault
            elif not buffer_active and not any(fault_active.values()):
                # Exploration vs Exploitation: 70% chance to stay healthy, 30% to trigger fault
                if random.random() < Config.PGM_HEALTH_PROBABILITY:
                    # Stay healthy (no fault)
                    logger.debug("PGM: Staying healthy (70% chance)")
                else:
                    # Trigger a random fault (30% chance)
                    fault_name = random.choice(fault_list)
                    fault_active[fault_name] = True
                    fault_end_times[fault_name] = current_time + Config.PGM_FAULT_DURATION
                    
                    # Start the appropriate background task
                    if fault_name == "cpu_spike":
                        task = asyncio.create_task(cpu_hog())
                        fault_tasks[fault_name] = task
                    elif fault_name == "memory_leak":
                        task = asyncio.create_task(memory_hog())
                        fault_tasks[fault_name] = task
                    
                    logger.warning(f"PGM FAULT TRIGGERED: {fault_name} (will last 30 seconds)")
            
            # Sleep for 1 second and check again
            await asyncio.sleep(1)
            
        except Exception as e:
            logger.error(f"PGM fault scheduler error: {e}")
            await asyncio.sleep(5)


async def auto_fault_manager():
    """
    Automatic fault manager - randomly triggers and stops faults
    
    This background task runs every 10 seconds and:
    1. Checks for expired faults and stops them
    2. Randomly triggers new faults based on probabilities (if enabled)
    3. Logs multiple fault conditions
    
    MODIFIED: Now respects single_fault_mode - if enabled, uses PGM scheduler instead
    """
    global fault_end_times, memory_leak_data, fault_tasks, auto_fault_enabled
    
    # If single fault mode is enabled, start the PGM scheduler and exit this function
    if single_fault_mode:
        logger.info("Single fault mode ENABLED - Using PGM scheduler (30s faults, buffer period, 70/30 split)")
        asyncio.create_task(pgm_fault_scheduler())
        return  # Exit - PGM scheduler handles everything
    
    # Original auto fault manager logic (for multiple simultaneous faults)
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
    version="10.0.0",
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
        "auto_fault_enabled": auto_fault_enabled,
        "single_fault_mode": single_fault_mode,  # NEW: Show current mode
        "buffer_active": buffer_active if single_fault_mode else None  # NEW: Show buffer status
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
        "single_fault_mode": single_fault_mode,  # NEW
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
        
        "# HELP victim_fault_cpu_spike CPU spike fault active (1=Yes, 0=No).",
        "# TYPE victim_fault_cpu_spike gauge",
        f'victim_fault_cpu_spike {1 if fault_active["cpu_spike"] else 0}',
        
        "# HELP victim_fault_memory_leak Memory leak fault active (1=Yes, 0=No).",
        "# TYPE victim_fault_memory_leak gauge",
        f'victim_fault_memory_leak {1 if fault_active["memory_leak"] else 0}',
        
        "# HELP victim_fault_api_latency API latency fault active (1=Yes, 0=No).",
        "# TYPE victim_fault_api_latency gauge",
        f'victim_fault_api_latency {1 if fault_active["api_latency"] else 0}',
        
        "# HELP victim_fault_error_rate Error rate fault active (1=Yes, 0=No).",
        "# TYPE victim_fault_error_rate gauge",
        f'victim_fault_error_rate {1 if fault_active["error_rate"] else 0}',
        
        "# HELP victim_multiple_faults Multiple faults active (1=Yes, 0=No).",
        "# TYPE victim_multiple_faults gauge",
        f'victim_multiple_faults {1 if sum(fault_active.values()) > 1 else 0}',
        
        "# HELP victim_auto_fault_enabled Auto-fault system enabled (1=Yes, 0=No).",
        "# TYPE victim_auto_fault_enabled gauge",
        f'victim_auto_fault_enabled {1 if auto_fault_enabled else 0}',
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
        "single_fault_mode": single_fault_mode,  # NEW
        "buffer_active": buffer_active if single_fault_mode else None,
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
        "single_fault_mode": single_fault_mode,  # NEW
        "active_faults": [f for f, v in fault_active.items() if v],
        "multiple_faults": sum(fault_active.values()) > 1,
        "buffer_active": buffer_active if single_fault_mode else None,
        "probabilities": {
            "cpu": f"{Config.AUTO_CPU_PROB * 100}%",
            "memory": f"{Config.AUTO_MEMORY_PROB * 100}%",
            "latency": f"{Config.AUTO_LATENCY_PROB * 100}%",
            "errors": f"{Config.AUTO_ERROR_PROB * 100}%"
        },
        "fault_duration": f"{Config.FAULT_DURATION[0]}-{Config.FAULT_DURATION[1]} seconds"
    }


# ============================================================================
# NEW: SINGLE FAULT MODE CONTROL ENDPOINTS (for PGM training)
# ============================================================================

@app.post("/single-fault-mode/enable")
async def enable_single_fault_mode():
    """
    Enable single fault mode with buffer period for PGM training.
    
    Features:
    - Only ONE fault at a time
    - Faults last exactly 30 seconds
    - Buffer period between faults (15-45 seconds, random)
    - 70% chance to stay healthy, 30% chance to trigger a fault
    - Random timing (not fixed intervals)
    """
    global single_fault_mode, fault_active, fault_tasks, memory_leak_data, buffer_active
    
    if single_fault_mode:
        return {
            "status": "warning",
            "message": "Single fault mode is already enabled",
            "single_fault_mode": single_fault_mode
        }
    
    # Stop all currently active faults
    for fault in fault_active:
        fault_active[fault] = False
    
    # Cancel all background tasks
    for task in fault_tasks.values():
        task.cancel()
    fault_tasks.clear()
    
    # Clear memory leak data
    memory_leak_data.clear()
    
    # Reset buffer
    buffer_active = False
    
    # Enable single fault mode
    single_fault_mode = True
    
    # The PGM scheduler will start automatically in auto_fault_manager
    
    logger.warning("SINGLE FAULT MODE ENABLED - PGM training mode active")
    return {
        "status": "success",
        "message": "Single fault mode enabled (PGM training mode)",
        "single_fault_mode": single_fault_mode,
        "configuration": {
            "fault_duration": f"{Config.PGM_FAULT_DURATION} seconds",
            "buffer_range": f"{Config.PGM_BUFFER_MIN}-{Config.PGM_BUFFER_MAX} seconds",
            "health_probability": f"{Config.PGM_HEALTH_PROBABILITY * 100}% (stay healthy)",
            "fault_probability": f"{(1 - Config.PGM_HEALTH_PROBABILITY) * 100}% (trigger fault)",
            "max_concurrent_faults": 1
        }
    }


@app.post("/single-fault-mode/disable")
async def disable_single_fault_mode():
    """
    Disable single fault mode and revert to original auto-fault behavior.
    """
    global single_fault_mode, fault_active, fault_tasks, memory_leak_data, buffer_active
    
    if not single_fault_mode:
        return {
            "status": "warning",
            "message": "Single fault mode is already disabled",
            "single_fault_mode": single_fault_mode
        }
    
    # Stop all currently active faults
    for fault in fault_active:
        fault_active[fault] = False
    
    # Cancel all background tasks
    for task in fault_tasks.values():
        task.cancel()
    fault_tasks.clear()
    
    # Clear memory leak data
    memory_leak_data.clear()
    
    # Reset buffer
    buffer_active = False
    
    # Disable single fault mode
    single_fault_mode = False
    
    logger.warning("SINGLE FAULT MODE DISABLED - Reverting to original auto-fault behavior")
    return {
        "status": "success",
        "message": "Single fault mode disabled (reverted to original auto-fault behavior)",
        "single_fault_mode": single_fault_mode,
        "note": "Auto-fault system is still active with original probabilities"
    }


@app.get("/single-fault-mode/status")
async def get_single_fault_mode_status():
    """
    Get current status of single fault mode.
    """
    active_faults = [f for f, v in fault_active.items() if v]
    
    return {
        "single_fault_mode": single_fault_mode,
        "is_active": single_fault_mode,
        "current_fault": active_faults[0] if active_faults else None,
        "buffer_active": buffer_active if single_fault_mode else None,
        "buffer_remaining_seconds": round(buffer_end_time - time.time(), 1) if buffer_active and single_fault_mode else 0,
        "configuration": {
            "fault_duration": f"{Config.PGM_FAULT_DURATION} seconds",
            "buffer_range": f"{Config.PGM_BUFFER_MIN}-{Config.PGM_BUFFER_MAX} seconds",
            "health_probability": f"{Config.PGM_HEALTH_PROBABILITY * 100}%",
            "fault_probability": f"{(1 - Config.PGM_HEALTH_PROBABILITY) * 100}%"
        } if single_fault_mode else None
    }


# ============================================================================
# MANUAL FAULT CONTROL ENDPOINTS
# ============================================================================
@app.post("/fault/cpu/{action}")
async def cpu_control(action: str):
    """Manually control CPU spike fault"""
    global fault_tasks
    
    # Check if in single fault mode and trying to start a fault
    if single_fault_mode and action == "start":
        # Check if any fault is already active
        if any(fault_active.values()):
            active_faults = [f for f, v in fault_active.items() if v]
            raise HTTPException(
                status_code=409,
                detail=f"Cannot start CPU fault. Single fault mode is active and fault '{active_faults[0]}' is already running. Stop it first or disable single fault mode."
            )
    
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
    
    # Check if in single fault mode and trying to start a fault
    if single_fault_mode and action == "start":
        if any(fault_active.values()):
            active_faults = [f for f, v in fault_active.items() if v]
            raise HTTPException(
                status_code=409,
                detail=f"Cannot start memory fault. Single fault mode is active and fault '{active_faults[0]}' is already running. Stop it first or disable single fault mode."
            )
    
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
    
    # Check if in single fault mode and trying to start a fault
    if single_fault_mode and action == "start":
        if any(fault_active.values()):
            active_faults = [f for f, v in fault_active.items() if v]
            raise HTTPException(
                status_code=409,
                detail=f"Cannot start latency fault. Single fault mode is active and fault '{active_faults[0]}' is already running. Stop it first or disable single fault mode."
            )
    
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
    
    # Check if in single fault mode and trying to start a fault
    if single_fault_mode and action == "start":
        if any(fault_active.values()):
            active_faults = [f for f, v in fault_active.items() if v]
            raise HTTPException(
                status_code=409,
                detail=f"Cannot start error fault. Single fault mode is active and fault '{active_faults[0]}' is already running. Stop it first or disable single fault mode."
            )
    
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
    global fault_active, memory_leak_data, fault_tasks, fault_end_times, buffer_active
    
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
    
    # Reset buffer if in single fault mode
    if single_fault_mode:
        buffer_active = False
    
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
        "version": "10.0.0",
        "faults_active": fault_active,
        "auto_fault_enabled": auto_fault_enabled,
        "single_fault_mode": single_fault_mode,  # NEW
        "memory_leak_mb": len(memory_leak_data) * 50,
        "controls": {
            "auto_fault": {
                "enable": "POST /auto-fault/start",
                "disable": "POST /auto-fault/stop",
                "status": "GET /auto-fault/status"
            },
            "single_fault_mode_pgm_training": {  # NEW
                "enable": "POST /single-fault-mode/enable",
                "disable": "POST /single-fault-mode/disable",
                "status": "GET /single-fault-mode/status",
                "description": "30s faults, buffer period, 70/30 health/fault split"
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