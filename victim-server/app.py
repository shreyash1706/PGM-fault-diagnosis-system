"""
Victim Server - ULTIMATE FIXED VERSION with GUARANTEED Symptoms
CPU Spike (80%+), Memory Leak (RAM rises), API Latency (3-8s), Error Rate (30%)
"""
from fastapi import FastAPI, HTTPException, Request
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

# ============= GLOBAL VARIABLES =============
fault_active: Dict[str, bool] = {
    "cpu_spike": False,
    "memory_leak": False,
    "api_latency": False,
    "error_rate": False
}

# For memory leak - ACTUAL memory consumption
memory_leak_data: List[bytearray] = []  # Using bytearray for better memory representation

# For tracking metrics
request_times: List[float] = []
error_count = 0
total_requests = 0

# Redis connection
redis_client = None

# ============= CONFIGURATION =============
class Config:
    # Automatic fault probabilities
    AUTO_CPU_PROB = 0.25      # 25% chance
    AUTO_MEMORY_PROB = 0.25   # 25% chance
    AUTO_LATENCY_PROB = 0.25  # 25% chance
    AUTO_ERROR_PROB = 0.25    # 25% chance
    
    # Fault duration (seconds)
    FAULT_DURATION = (20, 40)  # 20-40 seconds
    
    # Natural noise
    CPU_NOISE_PROB = 0.15      # 15% chance
    CPU_NOISE_RANGE = (2, 8)   # 2-8% natural variation
    LATENCY_NOISE_PROB = 0.15  # 15% chance
    LATENCY_NOISE_RANGE = (0.1, 0.4)  # 0.1-0.4s natural delay

# Track fault end times
fault_end_times: Dict[str, float] = {}
fault_tasks: Dict[str, asyncio.Task] = {}

# ============= BACKGROUND TASKS =============

async def cpu_hog():
    """🔥 REAL CPU spike - makes CPU 80-95%"""
    logger.warning("🔥 CPU HOG STARTED - CPU will spike to 80-95%")
    while fault_active["cpu_spike"]:
        # Heavy computation that actually spikes CPU
        for i in range(5_000_000):
            # Complex math operations
            _ = math.sqrt(i) * math.sin(i) * math.cos(i) ** 3
            _ = math.pow(i, 1.5) * math.log(i + 1)
            _ = math.exp(math.sin(i)) * math.cos(math.tan(i))
        await asyncio.sleep(0.01)  # Very tiny break
    logger.warning("🔥 CPU HOG STOPPED")

async def memory_hog():
    """🧠 REAL memory leak - RAM will increase visibly"""
    global memory_leak_data
    chunk_size = 50 * 1024 * 1024  # 50MB chunks - BIGGER for visible effect
    logger.warning("🧠 MEMORY HOG STARTED - RAM will increase")
    
    while fault_active["memory_leak"]:
        # Add large chunk of memory
        memory_leak_data.append(bytearray(chunk_size))
        total_mb = len(memory_leak_data) * 50
        logger.warning(f"🧠 MEMORY LEAK: {total_mb}MB total")
        
        # Force memory to be used
        for chunk in memory_leak_data:
            chunk[0] = 1  # Touch memory to keep it
        await asyncio.sleep(2)  # Add every 2 seconds
    logger.warning("🧠 MEMORY HOG STOPPED")

async def auto_fault_manager():
    """Automatically triggers and manages faults"""
    global fault_end_times, memory_leak_data, fault_tasks
    
    while True:
        try:
            current_time = time.time()
            
            # ===== CHECK EXPIRED FAULTS =====
            expired = []
            for fault, end_time in list(fault_end_times.items()):
                if current_time > end_time and fault_active.get(fault, False):
                    fault_active[fault] = False
                    expired.append(fault)
                    logger.info(f"✅ AUTO FAULT ENDED: {fault}")
                    
                    # Cancel background task if exists
                    if fault in fault_tasks:
                        fault_tasks[fault].cancel()
                        del fault_tasks[fault]
                    
                    # Clear memory leak data
                    if fault == "memory_leak":
                        memory_leak_data.clear()
            
            # ===== TRIGGER NEW FAULTS =====
            # CPU FAULT
            if not fault_active["cpu_spike"] and random.random() < Config.AUTO_CPU_PROB:
                duration = random.uniform(*Config.FAULT_DURATION)
                fault_active["cpu_spike"] = True
                fault_end_times["cpu_spike"] = current_time + duration
                task = asyncio.create_task(cpu_hog())
                fault_tasks["cpu_spike"] = task
                logger.warning(f"🔥 AUTO CPU FAULT for {duration:.1f}s")
            
            # MEMORY FAULT
            if not fault_active["memory_leak"] and random.random() < Config.AUTO_MEMORY_PROB:
                duration = random.uniform(*Config.FAULT_DURATION)
                fault_active["memory_leak"] = True
                fault_end_times["memory_leak"] = current_time + duration
                task = asyncio.create_task(memory_hog())
                fault_tasks["memory_leak"] = task
                logger.warning(f"🧠 AUTO MEMORY FAULT for {duration:.1f}s")
            
            # LATENCY FAULT
            if not fault_active["api_latency"] and random.random() < Config.AUTO_LATENCY_PROB:
                duration = random.uniform(*Config.FAULT_DURATION)
                fault_active["api_latency"] = True
                fault_end_times["api_latency"] = current_time + duration
                logger.warning(f"🐌 AUTO LATENCY FAULT for {duration:.1f}s")
            
            # ERROR FAULT
            if not fault_active["error_rate"] and random.random() < Config.AUTO_ERROR_PROB:
                duration = random.uniform(*Config.FAULT_DURATION)
                fault_active["error_rate"] = True
                fault_end_times["error_rate"] = current_time + duration
                logger.warning(f"💥 AUTO ERROR FAULT for {duration:.1f}s")
            
            # Log multiple faults
            active = [f for f, v in fault_active.items() if v]
            if len(active) > 1:
                logger.warning(f"🎯 MULTIPLE FAULTS: {active}")
            
            await asyncio.sleep(10)  # Check every 10 seconds
            
        except Exception as e:
            logger.error(f"Auto fault error: {e}")
            await asyncio.sleep(5)

# ============= LIFESPAN =============
@asynccontextmanager
async def lifespan(app: FastAPI):
    global redis_client
    try:
        redis_client = await redis.from_url("redis://redis:6379", decode_responses=True)
        await redis_client.ping()
        await redis_client.set("products", '{"laptop": 999, "mouse": 25}')
        logger.info("✅ Connected to Redis")
    except Exception as e:
        logger.warning(f"⚠️ Redis not available: {e}")
    
    # Start auto fault manager
    asyncio.create_task(auto_fault_manager())
    logger.info("🚀 Server started - AUTO FAULTS ENABLED")
    logger.info("   • CPU Spike: 80-95% CPU")
    logger.info("   • Memory Leak: +50MB/2sec (visible RAM increase)")
    logger.info("   • API Latency: 3-8 second delay")
    logger.info("   • Error Rate: 30% failures")
    yield
    
    # Cleanup
    for task in fault_tasks.values():
        task.cancel()
    if redis_client:
        await redis_client.close()

app = FastAPI(title="Victim Server", version="9.0.0", lifespan=lifespan)

# ============= MIDDLEWARE =============
@app.middleware("http")
async def track_requests(request: Request, call_next):
    global total_requests, error_count, request_times
    total_requests += 1
    start = time.time()
    
    try:
        # Natural latency noise
        if not fault_active["api_latency"] and random.random() < 0.15:
            delay = random.uniform(0.1, 0.4)
            await asyncio.sleep(delay)
        
        response = await call_next(request)
        process_time = time.time() - start
        request_times.append(process_time * 1000)
        if len(request_times) > 100:
            request_times.pop(0)
        return response
    except Exception:
        error_count += 1
        raise

# ============= BUSINESS ENDPOINTS =============
@app.get("/api/products")
async def get_products():
    global error_count
    
    # 🔥 CPU SPIKE - EXTREME heavy computation
    if fault_active["cpu_spike"]:
        for i in range(8_000_000):  # 8 million iterations
            _ = math.sqrt(i) * math.sin(i) * math.cos(i) ** 3
            _ = math.pow(i, 1.7) * math.log(i + 1)
    
    # 🐌 API LATENCY - Significant delay
    if fault_active["api_latency"]:
        delay = random.uniform(3.0, 8.0)
        await asyncio.sleep(delay)
    
    # 💥 ERROR RATE - Guaranteed failures
    if fault_active["error_rate"]:
        if random.random() < 0.3:  # 30% chance
            error_count += 1
            raise HTTPException(status_code=500, detail="Random error injected")
    
    return {"products": "laptop: $999, mouse: $25", "timestamp": datetime.now().isoformat()}

@app.get("/api/users")
async def get_users():
    if fault_active["cpu_spike"]:
        for i in range(5_000_000):
            _ = math.sqrt(i) * math.pow(i, 1.5)
    
    if fault_active["api_latency"]:
        await asyncio.sleep(random.uniform(3.0, 8.0))
    
    if fault_active["error_rate"] and random.random() < 0.3:
        raise HTTPException(status_code=500, detail="Random error")
    
    return {"users": 1500, "active": 423}

# ============= METRICS ENDPOINTS =============
@app.get("/health")
async def health():
    global error_count, total_requests, request_times, memory_leak_data
    
    # Get REAL system metrics with longer interval for accuracy
    cpu = psutil.cpu_percent(interval=2.0)  # 2 second interval for better reading
    mem = psutil.virtual_memory().percent
    avg_lat = statistics.mean(request_times) if request_times else 0
    err_rate = (error_count / total_requests * 100) if total_requests > 0 else 0
    
    # Natural CPU noise only when fault not active
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
            "memory_leak_mb": len(memory_leak_data) * 50  # 50MB per chunk
        },
        "faults_active": fault_active,
        "multiple_faults": sum(fault_active.values()) > 1
    }

@app.get("/api/metrics")
async def get_metrics():
    """PGM-ready metrics"""
    health_data = await health()
    m = health_data["metrics"]
    
    return {
        "timestamp": health_data["timestamp"],
        "faults_active": fault_active,
        "observable_nodes": {
            "cpu_usage": "Critical" if m["cpu_percent"] > 50 else "High" if m["cpu_percent"] > 20 else "Normal",
            "ram_usage": "Critical" if m["memory_percent"] > 70 else "High" if m["memory_percent"] > 40 else "Normal",
            "api_latency": "Timeout" if m["avg_latency_ms"] > 1000 else "Elevated" if m["avg_latency_ms"] > 200 else "Normal",
            "error_rate": "Spiking" if m["error_rate_percent"] > 5 else "Zero"
        }
    }

# ============= MANUAL FAULT CONTROL =============
@app.post("/fault/cpu/{action}")
async def cpu_control(action: str):
    global fault_tasks
    if action == "start":
        fault_active["cpu_spike"] = True
        if "cpu_spike" in fault_tasks:
            fault_tasks["cpu_spike"].cancel()
        fault_tasks["cpu_spike"] = asyncio.create_task(cpu_hog())
        return {"message": "🔥 CPU spike STARTED - CPU will go to 80-95%"}
    fault_active["cpu_spike"] = False
    if "cpu_spike" in fault_tasks:
        fault_tasks["cpu_spike"].cancel()
        del fault_tasks["cpu_spike"]
    return {"message": "✅ CPU spike STOPPED"}

@app.post("/fault/memory/{action}")
async def memory_control(action: str):
    global memory_leak_data, fault_tasks
    if action == "start":
        fault_active["memory_leak"] = True
        if "memory_leak" in fault_tasks:
            fault_tasks["memory_leak"].cancel()
        fault_tasks["memory_leak"] = asyncio.create_task(memory_hog())
        return {"message": "🧠 Memory leak STARTED - RAM will increase"}
    fault_active["memory_leak"] = False
    if "memory_leak" in fault_tasks:
        fault_tasks["memory_leak"].cancel()
        del fault_tasks["memory_leak"]
    memory_leak_data.clear()
    return {"message": "✅ Memory leak STOPPED"}

@app.post("/fault/latency/{action}")
async def latency_control(action: str):
    fault_active["api_latency"] = (action == "start")
    return {"message": f"🐌 Latency {action}ed - {'3-8s delay' if action=='start' else 'normal'}"}

@app.post("/fault/errors/{action}")
async def errors_control(action: str):
    fault_active["error_rate"] = (action == "start")
    return {"message": f"💥 Error rate {action}ed - {'30% failures' if action=='start' else 'normal'}"}

@app.get("/")
async def root():
    return {
        "server": "Victim Server",
        "status": "running",
        "version": "9.0.0",
        "faults_active": fault_active,
        "memory_leak_mb": len(memory_leak_data) * 50
    }

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)