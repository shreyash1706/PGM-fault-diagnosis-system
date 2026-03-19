"""
Victim Server - Complete with all 4 fault types + Natural Randomness + Automatic Faults
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
import math

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

# ============= AUTOMATIC FAULTS CONFIGURATION =============
# Yeh faults apne aap honge - real world ki tarah!

class AutomaticFaults:
    """Faults that happen automatically without manual trigger"""
    
    # Probability of automatic faults (checked every 30 seconds)
    AUTO_CPU_FAULT_PROBABILITY = 0.45   # 15% chance of CPU fault
    AUTO_MEMORY_FAULT_PROBABILITY = 0.45 # 12% chance of memory leak
    AUTO_LATENCY_FAULT_PROBABILITY = 0.40 # 18% chance of latency
    AUTO_ERROR_FAULT_PROBABILITY = 0.40  # 10% chance of error rate
    
    # Duration of automatic faults (seconds)
    FAULT_DURATION_RANGE = (10, 30)  # Fault lasts 10-30 seconds
    
    # Cooldown period between faults (seconds)
    COOLDOWN_PERIOD = 45  # Minimum 45 seconds between faults
    
    # Probability of multiple faults occurring together
    MULTI_FAULT_PROBABILITY = 0.20  # 20% chance of two faults together

# Track automatic faults
last_fault_time = 0
current_auto_faults = []  # Multiple faults can be active
fault_end_times = {}  # Track end time for each fault

# ============= NATURAL RANDOMNESS CONFIGURATION =============
# Yeh settings random fluctuations add karengi realistic behavior ke liye

class NaturalNoise:
    """Adds natural randomness to simulate real-world conditions"""
    
    # Random CPU spikes (false positives) - kabhi kabhi bina fault ke CPU up/down ho jayega
    CPU_NOISE_PROBABILITY = 0.40  # 20% chance of random CPU fluctuation
    CPU_NOISE_RANGE = (5, 25)     # 5-25% extra CPU usage randomly
    
    # Random latency spikes
    LATENCY_NOISE_PROBABILITY = 0.40  # 25% chance of random latency
    LATENCY_NOISE_RANGE = (0.5, 3.0)  # 0.5-3.0 second random delay
    
    # Random memory fluctuations
    MEMORY_NOISE_PROBABILITY = 0.45   # 15% chance of memory fluctuation
    MEMORY_NOISE_RANGE = (3, 12)      # 3-12% memory usage variation
    
    # Background noise - continuous small variations
    BACKGROUND_CPU_VARIATION = 45.0    # ±5% continuous CPU variation
    BACKGROUND_LATENCY_VARIATION = 300 # ±300ms continuous latency variation
    
    # False positive/negative rates for categorization
    FALSE_POSITIVE_RATE = 0.4   # 8% chance of false positive
    FALSE_NEGATIVE_RATE = 0.2    # 8% chance of false negative

# For tracking baseline noise
baseline_cpu = 5.0
baseline_memory = 20.0

# ============= AUTOMATIC FAULT TASKS =============

async def check_and_trigger_automatic_faults():
    """Background task that randomly triggers faults automatically"""
    global last_fault_time, current_auto_faults, fault_end_times
    
    while True:
        try:
            current_time = time.time()
            
            # Clean up expired faults
            expired_faults = []
            for fault, end_time in fault_end_times.items():
                if current_time > end_time:
                    if fault in fault_active:
                        fault_active[fault] = False
                        expired_faults.append(fault)
                        logger.info(f"🤖 AUTO-FAULT ENDED: {fault} finished automatically")
            
            for fault in expired_faults:
                if fault in fault_end_times:
                    del fault_end_times[fault]
                if fault in current_auto_faults:
                    current_auto_faults.remove(fault)
            
            # Check if cooldown period has passed
            if current_time - last_fault_time > AutomaticFaults.COOLDOWN_PERIOD:
                
                # Don't trigger if too many manual faults are active
                manual_active = sum(1 for f in fault_active.values() if f)
                if manual_active < 2:  # Allow up to 2 manual faults
                    
                    # Randomly decide to trigger a fault
                    rand = random.random()
                    triggered_faults = []
                    
                    # Check each fault type
                    if rand < AutomaticFaults.AUTO_CPU_FAULT_PROBABILITY:
                        triggered_faults.append("cpu_spike")
                    
                    # Check for memory fault (cumulative probability)
                    elif rand < AutomaticFaults.AUTO_CPU_FAULT_PROBABILITY + AutomaticFaults.AUTO_MEMORY_FAULT_PROBABILITY:
                        triggered_faults.append("memory_leak")
                    
                    # Check for latency fault
                    elif rand < AutomaticFaults.AUTO_CPU_FAULT_PROBABILITY + AutomaticFaults.AUTO_MEMORY_FAULT_PROBABILITY + AutomaticFaults.AUTO_LATENCY_FAULT_PROBABILITY:
                        triggered_faults.append("api_latency")
                    
                    # Check for error fault
                    elif rand < AutomaticFaults.AUTO_CPU_FAULT_PROBABILITY + AutomaticFaults.AUTO_MEMORY_FAULT_PROBABILITY + AutomaticFaults.AUTO_LATENCY_FAULT_PROBABILITY + AutomaticFaults.AUTO_ERROR_FAULT_PROBABILITY:
                        triggered_faults.append("error_rate")
                    
                    # Possibly add a second fault (multi-fault scenario)
                    if triggered_faults and random.random() < AutomaticFaults.MULTI_FAULT_PROBABILITY:
                        second_fault = random.choice(["cpu_spike", "memory_leak", "api_latency", "error_rate"])
                        if second_fault not in triggered_faults:
                            triggered_faults.append(second_fault)
                            logger.info(f"🤖 MULTI-FAULT: Adding {second_fault} to the mix")
                    
                    # Trigger the faults
                    for fault in triggered_faults:
                        if not fault_active[fault]:  # Don't override manual faults
                            duration = random.uniform(*AutomaticFaults.FAULT_DURATION_RANGE)
                            fault_active[fault] = True
                            fault_end_times[fault] = current_time + duration
                            current_auto_faults.append(fault)
                            logger.warning(f"🤖 AUTO-FAULT STARTED: {fault} for {duration:.1f} seconds")
                    
                    if triggered_faults:
                        last_fault_time = current_time
            
            await asyncio.sleep(5)  # Check every 5 seconds
            
        except Exception as e:
            logger.error(f"Error in auto-fault system: {e}")
            await asyncio.sleep(10)

# For tracking baseline noise
baseline_cpu = 5.0
baseline_memory = 20.0

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    global redis_client, baseline_cpu, baseline_memory
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
    
    # Set baseline metrics
    baseline_cpu = psutil.cpu_percent(interval=1.0)
    baseline_memory = psutil.virtual_memory().percent
    
    # START AUTOMATIC FAULT SYSTEM
    asyncio.create_task(check_and_trigger_automatic_faults())
    logger.info("🤖 Automatic fault system started - faults will occur randomly!")
    
    logger.info(f"🚀 Victim server started on {socket.gethostname()}")
    logger.info(f"📊 Baseline CPU: {baseline_cpu:.1f}%, Baseline Memory: {baseline_memory:.1f}%")
    yield
    
    # Shutdown
    if redis_client:
        await redis_client.close()
    logger.info("👋 Victim server shutting down")

# Create FastAPI app
app = FastAPI(
    title="Victim Server",
    description="Complete fault diagnosis testbed with 4 fault types + natural randomness + automatic faults",
    version="5.0.0",
    lifespan=lifespan
)

# ============= HELPER FUNCTIONS FOR NATURAL RANDOMNESS =============

def add_natural_cpu_noise(base_cpu: float) -> float:
    """Add natural random fluctuations to CPU"""
    global baseline_cpu
    
    # Continuous background noise (sinusoidal variation throughout day)
    time_factor = math.sin(time.time() / 100) * NaturalNoise.BACKGROUND_CPU_VARIATION
    
    # Random spikes (false positives)
    if random.random() < NaturalNoise.CPU_NOISE_PROBABILITY:
        spike = random.uniform(*NaturalNoise.CPU_NOISE_RANGE)
        logger.debug(f"🌊 Natural CPU spike: +{spike:.1f}%")
        return base_cpu + spike + time_factor
    
    return base_cpu + time_factor

def add_natural_memory_noise(base_memory: float) -> float:
    """Add natural random fluctuations to memory"""
    global baseline_memory
    
    # Random memory fluctuations
    if random.random() < NaturalNoise.MEMORY_NOISE_PROBABILITY:
        fluctuation = random.uniform(*NaturalNoise.MEMORY_NOISE_RANGE)
        logger.debug(f"🌊 Natural memory fluctuation: {fluctuation:+.1f}%")
        return base_memory + fluctuation
    
    return base_memory

async def add_natural_latency_noise():
    """Add natural random latency spikes"""
    if random.random() < NaturalNoise.LATENCY_NOISE_PROBABILITY:
        delay = random.uniform(*NaturalNoise.LATENCY_NOISE_RANGE)
        logger.debug(f"🌊 Natural latency spike: +{delay:.2f}s")
        await asyncio.sleep(delay)

def get_noisy_cpu() -> float:
    """Get CPU with natural randomness"""
    actual_cpu = psutil.cpu_percent(interval=0.3)
    
    # Agar fault active hai toh actual CPU do, otherwise add noise
    if fault_active["cpu_spike"]:
        return actual_cpu
    else:
        return add_natural_cpu_noise(actual_cpu)

def get_noisy_memory() -> float:
    """Get memory with natural randomness"""
    actual_memory = psutil.virtual_memory().percent
    
    if fault_active["memory_leak"]:
        return actual_memory
    else:
        return add_natural_memory_noise(actual_memory)

# ============= MIDDLEWARE for Tracking =============
@app.middleware("http")
async def track_requests(request: Request, call_next):
    """Track request times and error rates"""
    global total_requests, error_count, request_times
    
    total_requests += 1
    start_time = time.time()
    
    try:
        # Add natural latency noise (false positives)
        await add_natural_latency_noise()
        
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
    # Count active automatic faults
    auto_faults_active = [f for f in fault_active if fault_active[f]]
    
    return {
        "server": "Victim Server",
        "status": "running",
        "version": "5.0.0",
        "faults_active": fault_active,
        "auto_faults_active": len(auto_faults_active) > 0,
        "natural_randomness": {
            "cpu_noise": f"{NaturalNoise.CPU_NOISE_PROBABILITY*100}% chance",
            "latency_noise": f"{NaturalNoise.LATENCY_NOISE_PROBABILITY*100}% chance",
            "memory_noise": f"{NaturalNoise.MEMORY_NOISE_PROBABILITY*100}% chance"
        },
        "automatic_faults": {
            "enabled": True,
            "check_interval": "5 seconds",
            "fault_probabilities": {
                "cpu": f"{AutomaticFaults.AUTO_CPU_FAULT_PROBABILITY*100}%",
                "memory": f"{AutomaticFaults.AUTO_MEMORY_FAULT_PROBABILITY*100}%",
                "latency": f"{AutomaticFaults.AUTO_LATENCY_FAULT_PROBABILITY*100}%",
                "errors": f"{AutomaticFaults.AUTO_ERROR_FAULT_PROBABILITY*100}%"
            }
        },
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

# ============= FAULT INJECTION ENDPOINTS (Manual) =============

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
    """Enhanced health check with more metrics + natural randomness"""
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
    
    # Add natural randomness to metrics
    noisy_cpu = get_noisy_cpu()
    noisy_memory = get_noisy_memory()
    
    return {
        "status": "healthy",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "metrics": {
            "cpu_percent": round(noisy_cpu, 2),
            "memory_percent": round(noisy_memory, 2),
            "avg_latency_ms": round(avg_latency, 2),
            "error_rate_percent": round(error_rate_pct, 2),
            "total_requests": total_requests
        },
        "faults_active": fault_active,
        "redis_status": redis_status,
        "auto_faults_enabled": True
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
        },
        "auto_faults": {
            "enabled": True,
            "last_fault_time": last_fault_time,
            "active_auto_faults": current_auto_faults
        }
    }

@app.get("/api/metrics")
async def get_metrics():
    """Detailed metrics for ML model + natural randomness"""
    global error_count, total_requests, request_times
    
    avg_latency = statistics.mean(request_times) if request_times else 0
    error_rate_pct = (error_count / total_requests * 100) if total_requests > 0 else 0
    
    # Add natural randomness to metrics
    noisy_cpu = get_noisy_cpu()
    noisy_memory = get_noisy_memory()
    
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "faults_active": fault_active,
        "observable_nodes": {
            "cpu_usage": _categorize_cpu(noisy_cpu),
            "ram_usage": _categorize_ram(noisy_memory),
            "api_latency": _categorize_latency(avg_latency + random.uniform(-20, 20)),  # Small variation
            "error_rate": _categorize_errors(error_rate_pct)
        },
        "raw_values": {
            "cpu_percent": round(noisy_cpu, 2),
            "memory_percent": round(noisy_memory, 2),
            "avg_latency_ms": round(avg_latency, 2),
            "error_rate_percent": round(error_rate_pct, 2)
        },
        "natural_noise_applied": {
            "cpu_noise": round(noisy_cpu - psutil.cpu_percent(interval=0.1), 2),
            "memory_noise": round(noisy_memory - psutil.virtual_memory().percent, 2)
        }
    }

def _categorize_cpu(cpu_percent):
    """Convert CPU to discrete states with fuzzy boundaries"""
    # False positive: Normal ko High dikhana
    if cpu_percent < 30:
        if random.random() < NaturalNoise.FALSE_POSITIVE_RATE and not fault_active["cpu_spike"]:
            return "High"  # False positive
        return "Normal"
    
    # False negative: High ko Normal dikhana
    elif cpu_percent < 70:
        if random.random() < NaturalNoise.FALSE_NEGATIVE_RATE and fault_active["cpu_spike"]:
            return "Normal"  # False negative
        return "High"
    
    # Critical zone - kam chances of misclassification
    else:
        # 2% chance of false negative in critical zone
        if random.random() < 0.02 and fault_active["cpu_spike"]:
            return "High"
        return "Critical"

def _categorize_ram(ram_percent):
    """Convert RAM to discrete states with fuzzy boundaries"""
    if ram_percent < 40:
        if random.random() < NaturalNoise.FALSE_POSITIVE_RATE and not fault_active["memory_leak"]:
            return "High"
        return "Normal"
    elif ram_percent < 70:
        if random.random() < NaturalNoise.FALSE_NEGATIVE_RATE and fault_active["memory_leak"]:
            return "Normal"
        return "High"
    else:
        return "Critical"

def _categorize_latency(latency_ms):
    """Convert latency to discrete states with fuzzy boundaries"""
    if latency_ms < 100:
        if random.random() < NaturalNoise.FALSE_POSITIVE_RATE and not fault_active["api_latency"]:
            return "Elevated"
        return "Normal"
    elif latency_ms < 500:
        if random.random() < NaturalNoise.FALSE_NEGATIVE_RATE and fault_active["api_latency"]:
            return "Normal"
        return "Elevated"
    else:
        return "Timeout"

def _categorize_errors(error_pct):
    """Convert error rate to discrete states with fuzzy boundaries"""
    is_spiking = error_pct > 5
    
    if is_spiking:
        # 5% chance of false negative (spiking ko Zero dikhana)
        if random.random() < 0.05 and fault_active["error_rate"]:
            return "Zero"
        return "Spiking"
    else:
        # 5% chance of false positive (Zero ko Spiking dikhana)
        if random.random() < 0.05 and not fault_active["error_rate"]:
            return "Spiking"
        return "Zero"

if __name__ == "__main__":
    uvicorn.run(
        "app:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info"
    )