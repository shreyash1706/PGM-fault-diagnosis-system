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
- Single fault mode with buffer period for PGM training

PGM NODE MAPPING (matches nodes.md):
- Compute_Overload  ←→  Compute_Overload fault  (was: cpu_spike)
- Memory_Leak       ←→  Memory_Leak fault        (was: memory_leak)
- Network_Partition ←→  Network_Partition fault  (was: api_latency)
- App_Crash         ←→  App_Crash fault          (was: error_rate)

Observable Nodes (discrete states):
- CPU_Usage:    Normal (<40%), High (40-80%), Critical (>80%)
- RAM_Usage:    Normal (<40%), High (40-70%), Critical (>70%)
- API_Latency:  Normal (<200ms), Elevated (200-1000ms), Timeout (>1000ms)
- Error_Rate:   Zero (<5%), Spiking (>5%)

Causal latency effects (matches DAG):
- Compute_Overload  → mild latency    (0.5-2.0s)
- Memory_Leak       → moderate latency (0.5-2.5s)
- Network_Partition → severe latency  (3.0-8.0s)
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
from typing import Dict, List
import math
from collections import deque
import os

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
logger = logging.getLogger(__name__)


# ============================================================================
# GLOBAL VARIABLES
# ============================================================================

# Fault states - PGM Latent Nodes (keys now match PGM node names exactly)
fault_active: Dict[str, bool] = {
    "Compute_Overload": False,   # PGM: Compute_Overload  (was: cpu_spike)
    "Memory_Leak": False,        # PGM: Memory_Leak       (was: memory_leak)
    "Network_Partition": False,  # PGM: Network_Partition (was: api_latency)
    "App_Crash": False           # PGM: App_Crash         (was: error_rate)
}

# Canonical fault list for schedulers
FAULT_LIST = ["Compute_Overload", "Memory_Leak", "Network_Partition", "App_Crash"]

# Auto-fault system enabled/disabled
auto_fault_enabled: bool = True

# Single fault mode with buffer (for PGM training)
single_fault_mode: bool = False

# Memory leak storage - grows when Memory_Leak fault is active
memory_leak_data: List[bytearray] = []

# Metrics tracking - sliding window with deques
request_times = deque(maxlen=100)  # Response times for last 100 requests (ms)
error_flags = deque(maxlen=100)    # Error flags for last 100 requests (1=error, 0=success)
total_requests: int = 0

# Redis connection
redis_client = None


# ============================================================================
# CONFIGURATION
# ============================================================================

class Config:
    """Configuration for fault injection and noise"""

    AUTO_COMPUTE_PROB: float = 0.25      # 25% chance for Compute_Overload
    AUTO_MEMORY_PROB: float = 0.25       # 25% chance for Memory_Leak
    AUTO_NETWORK_PROB: float = 0.25      # 25% chance for Network_Partition
    AUTO_CRASH_PROB: float = 0.25        # 25% chance for App_Crash

    FAULT_DURATION: tuple = (20, 40)     # Faults last 20-40 seconds

    # Natural noise (false positives)
    CPU_NOISE_PROB: float = 0.15
    CPU_NOISE_RANGE: tuple = (2, 8)
    LATENCY_NOISE_PROB: float = 0.15
    LATENCY_NOISE_RANGE: tuple = (0.1, 0.4)

    # PGM training mode configuration
    PGM_FAULT_DURATION: float = 30.0
    PGM_HEALTH_PROBABILITY: float = 0.7
    PGM_BUFFER_MIN: float = 15.0
    PGM_BUFFER_MAX: float = 45.0


# Track when each fault will automatically stop
fault_end_times: Dict[str, float] = {}
fault_tasks: Dict[str, asyncio.Task] = {}
buffer_active: bool = False
buffer_end_time: float = 0


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def get_container_cpu():
    """Get container CPU usage using load average"""
    try:
        load = os.getloadavg()[0]
        cpu_count = os.cpu_count() or 1
        return (load / cpu_count) * 100
    except:
        return 0


def get_cpu_state(cpu_percent: float) -> str:
    """Convert CPU percentage to PGM discrete state"""
    if cpu_percent >= 80:
        return "Critical"
    elif cpu_percent >= 40:
        return "High"
    return "Normal"


def get_ram_state(ram_percent: float) -> str:
    """Convert RAM percentage to PGM discrete state"""
    if ram_percent >= 70:
        return "Critical"
    elif ram_percent >= 40:
        return "High"
    return "Normal"


def get_latency_state(latency_ms: float) -> str:
    """Convert latency to PGM discrete state"""
    if latency_ms > 1000:
        return "Timeout"
    elif latency_ms > 200:
        return "Elevated"
    return "Normal"


def get_error_state(error_rate: float) -> str:
    """Convert error rate to PGM discrete state"""
    if error_rate > 5:
        return "Spiking"
    return "Zero"


# ============================================================================
# BACKGROUND TASKS (Fault Implementation)
# ============================================================================

async def cpu_hog():
    """PGM: Compute_Overload - CPU spike to 80-95%"""
    logger.warning("🔥 Compute_Overload (CPU Spike) STARTED")
    while fault_active["Compute_Overload"]:
        for i in range(20_000_000):
            _ = math.sqrt(i) * math.sin(i) * math.cos(i) ** 3
            _ = math.pow(i, 1.5) * math.log(i + 1)
            _ = math.exp(math.sin(i)) * math.cos(math.tan(i))
        await asyncio.sleep(0.01)
    logger.warning("✅ Compute_Overload (CPU Spike) STOPPED")


async def memory_hog():
    """PGM: Memory_Leak - RAM exhaustion simulation"""
    global memory_leak_data
    chunk_size = 50 * 1024 * 1024
    logger.warning("💾 Memory_Leak (RAM leak) STARTED")

    while fault_active["Memory_Leak"]:
        memory_leak_data.append(bytearray(chunk_size))
        total_mb = len(memory_leak_data) * 50
        logger.warning(f"Memory_Leak: {total_mb}MB total")
        for chunk in memory_leak_data:
            chunk[0] = 1
        await asyncio.sleep(2)
    logger.warning("✅ Memory_Leak STOPPED")


async def pgm_fault_scheduler():
    """Single fault mode scheduler for PGM training"""
    global fault_active, fault_end_times, fault_tasks, buffer_active, buffer_end_time, memory_leak_data

    while True:
        try:
            current_time = time.time()
            active_faults = [f for f, v in fault_active.items() if v]

            if active_faults:
                fault_name = active_faults[0]
                if current_time >= fault_end_times.get(fault_name, 0):
                    fault_active[fault_name] = False
                    logger.info(f"PGM FAULT ENDED: {fault_name}")

                    if fault_name in fault_tasks:
                        fault_tasks[fault_name].cancel()
                        del fault_tasks[fault_name]

                    if fault_name == "Memory_Leak":
                        memory_leak_data.clear()

                    buffer_duration = random.uniform(Config.PGM_BUFFER_MIN, Config.PGM_BUFFER_MAX)
                    buffer_end_time = current_time + buffer_duration
                    buffer_active = True
                    logger.info(f"BUFFER: {buffer_duration:.1f}s (no faults)")

                    if fault_name in fault_end_times:
                        del fault_end_times[fault_name]

            elif buffer_active:
                if current_time >= buffer_end_time:
                    buffer_active = False
                    logger.info("BUFFER ENDED - Ready for next fault")

            elif not buffer_active and not any(fault_active.values()):
                # Make ONE decision per cycle

                decision = random.random()

                if decision < Config.PGM_HEALTH_PROBABILITY:
                    # Stay healthy for a fixed duration (like RL environment step)
                    healthy_duration = random.uniform(20, 40)

                    buffer_active = True
                    buffer_end_time = current_time + healthy_duration

                    logger.info(f"PGM: HEALTHY PERIOD for {healthy_duration:.1f}s")

                else:
                    # Trigger exactly ONE fault
                    fault_name = random.choice(FAULT_LIST)

                    fault_active[fault_name] = True
                    fault_end_times[fault_name] = current_time + Config.PGM_FAULT_DURATION

                    # Start fault-specific background tasks
                    if fault_name == "Compute_Overload":
                        task = asyncio.create_task(cpu_hog())
                        fault_tasks[fault_name] = task

                    elif fault_name == "Memory_Leak":
                        task = asyncio.create_task(memory_hog())
                        fault_tasks[fault_name] = task

                    logger.warning(f"PGM FAULT: {fault_name} ({Config.PGM_FAULT_DURATION}s)")

            await asyncio.sleep(1)

        except Exception as e:
            logger.error(f"PGM scheduler error: {e}")
            await asyncio.sleep(5)


async def auto_fault_manager():
    """Automatic fault manager - supports both multi-fault and single-fault mode"""
    global fault_end_times, memory_leak_data, fault_tasks, auto_fault_enabled

    if single_fault_mode:
        logger.info("Single Fault Mode ENABLED - PGM training active")
        asyncio.create_task(pgm_fault_scheduler())
        return

    while True:
        try:
            current_time = time.time()

            # Clean up expired faults
            expired = []
            for fault, end_time in list(fault_end_times.items()):
                if current_time > end_time and fault_active.get(fault, False):
                    fault_active[fault] = False
                    expired.append(fault)
                    logger.info(f"AUTO FAULT ENDED: {fault}")

                    if fault in fault_tasks:
                        fault_tasks[fault].cancel()
                        del fault_tasks[fault]

                    if fault == "Memory_Leak":
                        memory_leak_data.clear()

            for fault in expired:
                if fault in fault_end_times:
                    del fault_end_times[fault]

            # Trigger new faults
            if auto_fault_enabled:
                if not fault_active["Compute_Overload"] and random.random() < Config.AUTO_COMPUTE_PROB:
                    duration = random.uniform(*Config.FAULT_DURATION)
                    fault_active["Compute_Overload"] = True
                    fault_end_times["Compute_Overload"] = current_time + duration
                    task = asyncio.create_task(cpu_hog())
                    fault_tasks["Compute_Overload"] = task
                    logger.warning(f"Compute_Overload for {duration:.1f}s")

                if not fault_active["Memory_Leak"] and random.random() < Config.AUTO_MEMORY_PROB:
                    duration = random.uniform(*Config.FAULT_DURATION)
                    fault_active["Memory_Leak"] = True
                    fault_end_times["Memory_Leak"] = current_time + duration
                    task = asyncio.create_task(memory_hog())
                    fault_tasks["Memory_Leak"] = task
                    logger.warning(f"Memory_Leak for {duration:.1f}s")

                if not fault_active["Network_Partition"] and random.random() < Config.AUTO_NETWORK_PROB:
                    duration = random.uniform(*Config.FAULT_DURATION)
                    fault_active["Network_Partition"] = True
                    fault_end_times["Network_Partition"] = current_time + duration
                    logger.warning(f"Network_Partition for {duration:.1f}s")

                if not fault_active["App_Crash"] and random.random() < Config.AUTO_CRASH_PROB:
                    duration = random.uniform(*Config.FAULT_DURATION)
                    fault_active["App_Crash"] = True
                    fault_end_times["App_Crash"] = current_time + duration
                    logger.warning(f"App_Crash for {duration:.1f}s")

            active = [f for f, v in fault_active.items() if v]
            if len(active) > 1:
                logger.warning(f"MULTIPLE FAULTS: {active}")

            await asyncio.sleep(10)

        except Exception as e:
            logger.error(f"Auto fault error: {e}")
            await asyncio.sleep(5)


# ============================================================================
# LIFESPAN MANAGEMENT
# ============================================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    global redis_client

    try:
        redis_client = await redis.from_url("redis://redis:6379", decode_responses=True)
        await redis_client.ping()
        await redis_client.set("products", '{"laptop": 999, "mouse": 25}')
        logger.info("Connected to Redis")
    except Exception as e:
        logger.warning(f"Redis not available: {e}")

    asyncio.create_task(auto_fault_manager())
    logger.info("Victim Server Started")
    logger.info("  Compute_Overload : 80-95% CPU + mild latency (0.5-2s)")
    logger.info("  Memory_Leak      : +50MB/2sec + moderate latency (0.5-2.5s)")
    logger.info("  Network_Partition: severe latency (3-8s)")
    logger.info("  App_Crash        : 30% error rate")

    yield

    for task in fault_tasks.values():
        task.cancel()
    if redis_client:
        await redis_client.close()


# Create FastAPI application
app = FastAPI(
    title="Victim Server - PGM Fault Injection",
    description="Fault injection system for PGM training",
    version="2.0.0",
    lifespan=lifespan
)


# ============================================================================
# MIDDLEWARE
# ============================================================================

@app.middleware("http")
async def track_requests(request: Request, call_next):
    global total_requests, request_times, error_flags

    total_requests += 1
    start = time.time()

    try:
        # Natural baseline noise (only when no network fault active)
        if not fault_active["Network_Partition"] and random.random() < Config.LATENCY_NOISE_PROB:
            delay = random.uniform(*Config.LATENCY_NOISE_RANGE)
            await asyncio.sleep(delay)

        response = await call_next(request)
        process_time = (time.time() - start) * 1000
        request_times.append(process_time)
        error_flags.append(0)

        return response
    except Exception:
        error_flags.append(1)
        raise


# ============================================================================
# BUSINESS ENDPOINTS
# ============================================================================

@app.get("/api/products")
async def get_products():
    # --- Compute_Overload: CPU burn + mild latency ---
    if fault_active["Compute_Overload"]:
        for i in range(8_000_000):
            _ = math.sqrt(i) * math.sin(i) * math.cos(i) ** 3
            _ = math.pow(i, 1.7) * math.log(i + 1)
        # Mild latency side-effect (DAG: Compute_Overload → API_Latency)
        await asyncio.sleep(random.uniform(0.5, 2.0))

    # --- Memory_Leak: moderate latency side-effect ---
    if fault_active["Memory_Leak"]:
        # Moderate latency side-effect (DAG: Memory_Leak → API_Latency)
        await asyncio.sleep(random.uniform(0.5, 2.5))

    # --- Network_Partition: severe latency ---
    if fault_active["Network_Partition"]:
        await asyncio.sleep(random.uniform(3.0, 8.0))

    # --- App_Crash: 30% random errors ---
    if fault_active["App_Crash"]:
        if random.random() < 0.3:
            raise HTTPException(status_code=500, detail="Random error injected")

    return {
        "products": "laptop: $999, mouse: $25",
        "timestamp": datetime.now().isoformat()
    }


@app.get("/api/users")
async def get_users():
    # --- Compute_Overload: CPU burn + mild latency ---
    if fault_active["Compute_Overload"]:
        for i in range(5_000_000):
            _ = math.sqrt(i) * math.pow(i, 1.5)
        # Mild latency side-effect (DAG: Compute_Overload → API_Latency)
        await asyncio.sleep(random.uniform(0.5, 2.0))

    # --- Memory_Leak: moderate latency side-effect ---
    if fault_active["Memory_Leak"]:
        # Moderate latency side-effect (DAG: Memory_Leak → API_Latency)
        await asyncio.sleep(random.uniform(0.5, 2.5))

    # --- Network_Partition: severe latency ---
    if fault_active["Network_Partition"]:
        await asyncio.sleep(random.uniform(3.0, 8.0))

    # --- App_Crash: 30% random errors ---
    if fault_active["App_Crash"] and random.random() < 0.3:
        raise HTTPException(status_code=500, detail="Random error")

    return {"users": 1500, "active": 423}


# ============================================================================
# METRICS ENDPOINTS
# ============================================================================

@app.get("/health")
async def health():
    global total_requests, request_times, error_flags, memory_leak_data

    system_cpu = psutil.cpu_percent(interval=0.5)
    container_cpu = get_container_cpu()
    mem = psutil.virtual_memory().percent

    avg_lat = sum(request_times) / len(request_times) if request_times else 0
    err_rate = (sum(error_flags) / len(error_flags) * 100) if error_flags else 0

    # CPU noise (only when no fault active)
    if not fault_active["Compute_Overload"] and random.random() < Config.CPU_NOISE_PROB:
        container_cpu += random.uniform(*Config.CPU_NOISE_RANGE)
        container_cpu = min(container_cpu, 100)

    return {
        "timestamp": datetime.now().isoformat(),
        "metrics": {
            "system_cpu_percent": round(system_cpu, 2),
            "container_cpu_percent": round(container_cpu, 2),
            "memory_percent": round(mem, 2),
            "avg_latency_ms": round(avg_lat, 2),
            "error_rate_percent": round(err_rate, 2),
            "total_requests": total_requests,
            "memory_leak_mb": len(memory_leak_data) * 50
        },
        "faults_active": fault_active,
        "multiple_faults": sum(fault_active.values()) > 1,
        "auto_fault_enabled": auto_fault_enabled,
        "single_fault_mode": single_fault_mode,
        "buffer_active": buffer_active if single_fault_mode else None
    }


@app.get("/api/metrics")
async def get_metrics():
    """
    PGM-ready metrics - discrete states for Bayesian Network

    Observables:
    - CPU_Usage:   Normal / High / Critical
    - RAM_Usage:   Normal / High / Critical
    - API_Latency: Normal / Elevated / Timeout
    - Error_Rate:  Zero / Spiking

    Latent nodes (ground truth for training):
    - Compute_Overload, Memory_Leak, Network_Partition, App_Crash

    Matches nodes.md exactly.
    """
    health_data = await health()
    m = health_data["metrics"]

    # Use CONTAINER CPU for PGM (not system CPU)
    cpu_state = get_cpu_state(m["container_cpu_percent"])
    ram_state = get_ram_state(m["memory_percent"])
    latency_state = get_latency_state(m["avg_latency_ms"])
    error_state = get_error_state(m["error_rate_percent"])

    return {
        "timestamp": health_data["timestamp"],
        "faults_active": fault_active,               # ground truth latent nodes
        "auto_fault_enabled": auto_fault_enabled,
        "single_fault_mode": single_fault_mode,
        "observable_nodes": {
            "CPU_Usage": cpu_state,
            "RAM_Usage": ram_state,
            "API_Latency": latency_state,
            "Error_Rate": error_state
        }
    }


@app.get("/metrics", response_class=PlainTextResponse)
async def get_prometheus_format():
    """Prometheus metrics endpoint"""
    health_data = await health()
    m = health_data["metrics"]

    lines = [
        "# HELP victim_container_cpu_percent Container CPU usage",
        "# TYPE victim_container_cpu_percent gauge",
        f'victim_container_cpu_percent {m["container_cpu_percent"]}',

        "# HELP victim_memory_percent Memory utilization",
        "# TYPE victim_memory_percent gauge",
        f'victim_memory_percent {m["memory_percent"]}',

        "# HELP victim_avg_latency_ms Average API Latency in ms",
        "# TYPE victim_avg_latency_ms gauge",
        f'victim_avg_latency_ms {m["avg_latency_ms"]}',

        "# HELP victim_error_rate_percent Percentage of HTTP errors",
        "# TYPE victim_error_rate_percent gauge",
        f'victim_error_rate_percent {m["error_rate_percent"]}',

        "# HELP victim_total_requests Total requests served",
        "# TYPE victim_total_requests counter",
        f'victim_total_requests {m["total_requests"]}',

        "# HELP victim_memory_leak_mb Memory leaked so far",
        "# TYPE victim_memory_leak_mb gauge",
        f'victim_memory_leak_mb {m["memory_leak_mb"]}',

        "# HELP victim_fault_compute_overload Compute_Overload active",
        "# TYPE victim_fault_compute_overload gauge",
        f'victim_fault_compute_overload {1 if fault_active["Compute_Overload"] else 0}',

        "# HELP victim_fault_memory_leak Memory_Leak active",
        "# TYPE victim_fault_memory_leak gauge",
        f'victim_fault_memory_leak {1 if fault_active["Memory_Leak"] else 0}',

        "# HELP victim_fault_network_partition Network_Partition active",
        "# TYPE victim_fault_network_partition gauge",
        f'victim_fault_network_partition {1 if fault_active["Network_Partition"] else 0}',

        "# HELP victim_fault_app_crash App_Crash active",
        "# TYPE victim_fault_app_crash gauge",
        f'victim_fault_app_crash {1 if fault_active["App_Crash"] else 0}',
    ]
    return "\n".join(lines) + "\n"


@app.get("/api/debug")
async def debug():
    return {
        "faults": fault_active,
        "auto_fault_enabled": auto_fault_enabled,
        "single_fault_mode": single_fault_mode,
        "buffer_active": buffer_active if single_fault_mode else None,
        "stats": {
            "total_requests": total_requests,
            "error_flags_recent": list(error_flags)[-10:] if error_flags else [],
            "request_times_recent": list(request_times)[-10:] if request_times else [],
            "memory_leak_mb": len(memory_leak_data) * 50
        }
    }


# ============================================================================
# CONTROL ENDPOINTS
# ============================================================================

@app.post("/auto-fault/stop")
async def stop_auto_faults():
    global auto_fault_enabled
    auto_fault_enabled = False
    logger.warning("Auto-fault system DISABLED")
    return {"status": "success", "auto_fault_enabled": auto_fault_enabled}


@app.post("/auto-fault/start")
async def start_auto_faults():
    global auto_fault_enabled
    auto_fault_enabled = True
    logger.info("Auto-fault system ENABLED")
    return {"status": "success", "auto_fault_enabled": auto_fault_enabled}


@app.post("/single-fault-mode/enable")
async def enable_single_fault_mode():
    global single_fault_mode, fault_active, fault_tasks, memory_leak_data, buffer_active

    if single_fault_mode:
        return {"status": "warning", "message": "Already enabled"}

    for fault in fault_active:
        fault_active[fault] = False
    for task in fault_tasks.values():
        task.cancel()
    fault_tasks.clear()
    memory_leak_data.clear()
    buffer_active = False
    single_fault_mode = True

    logger.warning("SINGLE FAULT MODE ENABLED - PGM training active")
    return {
        "status": "success",
        "single_fault_mode": single_fault_mode,
        "configuration": {
            "fault_duration": "30s",
            "buffer_range": "15-45s",
            "health_probability": "70%"
        }
    }


@app.post("/single-fault-mode/disable")
async def disable_single_fault_mode():
    global single_fault_mode, fault_active, fault_tasks, memory_leak_data, buffer_active

    if not single_fault_mode:
        return {"status": "warning", "message": "Already disabled"}

    for fault in fault_active:
        fault_active[fault] = False
    for task in fault_tasks.values():
        task.cancel()
    fault_tasks.clear()
    memory_leak_data.clear()
    buffer_active = False
    single_fault_mode = False

    logger.warning("SINGLE FAULT MODE DISABLED")
    return {"status": "success", "single_fault_mode": single_fault_mode}


# ============================================================================
# MANUAL FAULT CONTROL ENDPOINTS
# ============================================================================

@app.post("/fault/cpu/{action}")
async def cpu_control(action: str):
    """Manual control for Compute_Overload fault"""
    global fault_tasks

    if single_fault_mode and action == "start":
        if any(fault_active.values()):
            active_faults = [f for f, v in fault_active.items() if v]
            raise HTTPException(409, f"Fault '{active_faults[0]}' already active")

    if action == "start":
        fault_active["Compute_Overload"] = True
        if "Compute_Overload" in fault_tasks:
            fault_tasks["Compute_Overload"].cancel()
        fault_tasks["Compute_Overload"] = asyncio.create_task(cpu_hog())
        return {"message": "Compute_Overload STARTED"}
    elif action == "stop":
        fault_active["Compute_Overload"] = False
        if "Compute_Overload" in fault_tasks:
            fault_tasks["Compute_Overload"].cancel()
            del fault_tasks["Compute_Overload"]
        return {"message": "Compute_Overload STOPPED"}
    raise HTTPException(400, "Invalid action. Use 'start' or 'stop'.")


@app.post("/fault/memory/{action}")
async def memory_control(action: str):
    """Manual control for Memory_Leak fault"""
    global memory_leak_data, fault_tasks

    if single_fault_mode and action == "start":
        if any(fault_active.values()):
            active_faults = [f for f, v in fault_active.items() if v]
            raise HTTPException(409, f"Fault '{active_faults[0]}' already active")

    if action == "start":
        fault_active["Memory_Leak"] = True
        if "Memory_Leak" in fault_tasks:
            fault_tasks["Memory_Leak"].cancel()
        fault_tasks["Memory_Leak"] = asyncio.create_task(memory_hog())
        return {"message": "Memory_Leak STARTED"}
    elif action == "stop":
        fault_active["Memory_Leak"] = False
        if "Memory_Leak" in fault_tasks:
            fault_tasks["Memory_Leak"].cancel()
            del fault_tasks["Memory_Leak"]
        memory_leak_data.clear()
        return {"message": "Memory_Leak STOPPED"}
    raise HTTPException(400, "Invalid action. Use 'start' or 'stop'.")


@app.post("/fault/latency/{action}")
async def latency_control(action: str):
    """Manual control for Network_Partition fault"""
    if single_fault_mode and action == "start":
        if any(fault_active.values()):
            active_faults = [f for f, v in fault_active.items() if v]
            raise HTTPException(409, f"Fault '{active_faults[0]}' already active")

    if action == "start":
        fault_active["Network_Partition"] = True
        return {"message": "Network_Partition STARTED"}
    elif action == "stop":
        fault_active["Network_Partition"] = False
        return {"message": "Network_Partition STOPPED"}
    raise HTTPException(400, "Invalid action. Use 'start' or 'stop'.")


@app.post("/fault/errors/{action}")
async def errors_control(action: str):
    """Manual control for App_Crash fault"""
    if single_fault_mode and action == "start":
        if any(fault_active.values()):
            active_faults = [f for f, v in fault_active.items() if v]
            raise HTTPException(409, f"Fault '{active_faults[0]}' already active")

    if action == "start":
        fault_active["App_Crash"] = True
        return {"message": "App_Crash STARTED"}
    elif action == "stop":
        fault_active["App_Crash"] = False
        return {"message": "App_Crash STOPPED"}
    raise HTTPException(400, "Invalid action. Use 'start' or 'stop'.")


@app.post("/fault/stop-all")
async def stop_all_faults():
    global fault_active, memory_leak_data, fault_tasks, fault_end_times, buffer_active

    for fault in fault_active:
        fault_active[fault] = False
    for task in fault_tasks.values():
        task.cancel()
    fault_tasks.clear()
    memory_leak_data.clear()
    fault_end_times.clear()
    if single_fault_mode:
        buffer_active = False

    logger.warning("ALL FAULTS STOPPED")
    return {"status": "success", "faults_active": fault_active}


# ============================================================================
# ROOT
# ============================================================================

@app.get("/")
async def root():
    return {
        "server": "Victim Server - PGM Fault Injection",
        "status": "running",
        "version": "2.0.0",
        "faults_active": fault_active,
        "auto_fault_enabled": auto_fault_enabled,
        "single_fault_mode": single_fault_mode,
        "causal_model": {
            "Compute_Overload":  "→ CPU_Usage=Critical, API_Latency=Elevated (mild)",
            "Memory_Leak":       "→ RAM_Usage=Critical, API_Latency=Elevated (moderate)",
            "Network_Partition": "→ API_Latency=Timeout (severe)",
            "App_Crash":         "→ Error_Rate=Spiking"
        },
        "controls": {
            "faults": {
                "Compute_Overload":  "POST /fault/cpu/{start|stop}",
                "Memory_Leak":       "POST /fault/memory/{start|stop}",
                "Network_Partition": "POST /fault/latency/{start|stop}",
                "App_Crash":         "POST /fault/errors/{start|stop}",
                "stop_all":          "POST /fault/stop-all"
            },
            "metrics": {
                "pgm_metrics": "GET /api/metrics",
                "health":      "GET /health",
                "prometheus":  "GET /metrics",
                "debug":       "GET /api/debug"
            },
            "modes": {
                "auto_fault_stop":         "POST /auto-fault/stop",
                "auto_fault_start":        "POST /auto-fault/start",
                "single_fault_mode_on":    "POST /single-fault-mode/enable",
                "single_fault_mode_off":   "POST /single-fault-mode/disable"
            }
        }
    }


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)