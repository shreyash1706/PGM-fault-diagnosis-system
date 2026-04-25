"""
Victim Server - Complete Fault Injection System with Auto/Manual Control
CPU Spike (80%+), Memory Leak (RAM rises), API Latency (3-8s), Error Rate (30%)

PGM NODE MAPPING:
- Compute_Overload  ←→  Compute_Overload fault
- Memory_Leak       ←→  Memory_Leak fault
- Network_Partition ←→  Network_Partition fault
- App_Crash         ←→  App_Crash fault

Observable Nodes (discrete states):
- CPU_Usage:    Normal (<40%), High (40-80%), Critical (>80%)
- RAM_Usage:    Normal (<40%), High (40-70%), Critical (>70%)
- API_Latency:  Normal (<200ms), Elevated (200-1000ms), Timeout (>1000ms)
- Error_Rate:   Zero (<5%), Spiking (>5%)
"""

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import PlainTextResponse
import redis.asyncio as redis
import psutil
import time
import random
import asyncio
import logging
import threading
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

# Fault states - PGM Latent Nodes
fault_active: Dict[str, bool] = {
    "Compute_Overload": False,
    "Memory_Leak": False,
    "Network_Partition": False,
    "App_Crash": False
}

# Canonical fault list for schedulers
FAULT_LIST = ["Compute_Overload", "Memory_Leak", "Network_Partition", "App_Crash"]

# Auto-fault system enabled/disabled
auto_fault_enabled: bool = True

# Single fault mode with buffer (for PGM training)
single_fault_mode: bool = False

# Memory leak storage
memory_leak_data: List[bytearray] = []

# Metrics tracking
request_times = deque(maxlen=100)
error_flags = deque(maxlen=100)
total_requests: int = 0

# Redis connection
redis_client = None

# CPU thread reference
cpu_thread = None

# ✅ FIXED: CPU delta tracking variables
_prev_cpu = None
_prev_system = None


# ============================================================================
# CONFIGURATION
# ============================================================================

class Config:
    AUTO_COMPUTE_PROB: float = 0.25
    AUTO_MEMORY_PROB: float = 0.25
    AUTO_NETWORK_PROB: float = 0.25
    AUTO_CRASH_PROB: float = 0.25
    FAULT_DURATION: tuple = (20, 40)
    
    # Natural noise (disabled - use only for testing, not for production metrics)
    CPU_NOISE_PROB: float = 0.0  # ✅ DISABLED - was corrupting metrics
    CPU_NOISE_RANGE: tuple = (2, 8)
    LATENCY_NOISE_PROB: float = 0.15
    LATENCY_NOISE_RANGE: tuple = (0.1, 0.4)
    
    # PGM training mode
    PGM_FAULT_DURATION: float = 30.0
    PGM_HEALTH_PROBABILITY: float = 0.7
    PGM_BUFFER_MIN: float = 15.0
    PGM_BUFFER_MAX: float = 45.0
    
    # Error rates
    NETWORK_PARTITION_ERROR_RATE: float = 0.5
    APP_CRASH_ERROR_RATE: float = 0.3


# Track fault timers
fault_end_times: Dict[str, float] = {}
fault_tasks: Dict[str, asyncio.Task] = {}
buffer_active: bool = False
buffer_end_time: float = 0


# ============================================================================
# ✅ FIXED: DELTA-BASED CPU CALCULATION (MATCHES DOCKER)
# ============================================================================

def get_container_cpu():
    """
    Calculate container CPU usage using delta between readings.
    This matches exactly how Docker calculates CPU %.
    """
    global _prev_cpu, _prev_system
    
    try:
        # Get container CPU time from cgroup
        with open("/sys/fs/cgroup/cpuacct/cpuacct.usage", "r") as f:
            cpu_usage = int(f.read().strip())
        
        # Get total system CPU time from /proc/stat
        with open("/proc/stat", "r") as f:
            parts = f.readline().split()[1:]
            system_usage = sum(int(p) for p in parts)
        
        if _prev_cpu is not None and _prev_system is not None:
            cpu_delta = cpu_usage - _prev_cpu
            system_delta = system_usage - _prev_system
            
            if system_delta > 0:
                # CPU percent = (container_delta / system_delta) * CPU_COUNT * 100
                cpu_count = os.cpu_count() or 1
                cpu_percent = (cpu_delta / system_delta) * cpu_count * 100
                cpu_percent = max(0.0, min(cpu_percent, 100.0))
            else:
                cpu_percent = 0.0
        else:
            cpu_percent = 0.0
        
        # Store for next calculation
        _prev_cpu = cpu_usage
        _prev_system = system_usage
        
        return cpu_percent
        
    except Exception as e:
        # Fallback to psutil if cgroup not available
        try:
            process = psutil.Process()
            return process.cpu_percent(interval=0.1)
        except:
            return 0.0


# ============================================================================
# STRONG CPU LOAD USING THREAD
# ============================================================================

def run_cpu_hog():
    """STRONG CPU load - runs in separate thread, blocks CPU fully"""
    logger.warning("🔥 Compute_Overload (CPU Spike) STARTED - Thread mode")
    while fault_active["Compute_Overload"]:
        # Heavy CPU computation - 100 million iterations
        for _ in range(100_000_000):
            _ = math.sqrt(_) * math.sin(_) * math.cos(_)
        # Tiny sleep to prevent complete system freeze
        time.sleep(0.001)
    logger.warning("✅ Compute_Overload (CPU Spike) STOPPED")


def start_cpu_hog():
    """Start CPU hog in a background thread"""
    global cpu_thread
    if cpu_thread and cpu_thread.is_alive():
        return
    cpu_thread = threading.Thread(target=run_cpu_hog, daemon=True)
    cpu_thread.start()


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def get_cpu_state(cpu_percent: float) -> str:
    if cpu_percent >= 80:
        return "Critical"
    elif cpu_percent >= 40:
        return "High"
    return "Normal"


def get_ram_state(ram_percent: float) -> str:
    if ram_percent >= 70:
        return "Critical"
    elif ram_percent >= 40:
        return "High"
    return "Normal"


def get_latency_state(latency_ms: float) -> str:
    if latency_ms > 1000:
        return "Timeout"
    elif latency_ms > 200:
        return "Elevated"
    return "Normal"


def get_error_state(error_rate: float) -> str:
    if error_rate > 5:
        return "Spiking"
    return "Zero"


# ============================================================================
# FAULT IMPLEMENTATIONS
# ============================================================================

async def memory_hog():
    """PGM: Memory_Leak - RAM exhaustion simulation"""
    global memory_leak_data
    chunk_size = 50 * 1024 * 1024
    logger.warning("💾 Memory_Leak (RAM leak) STARTED")

    while fault_active["Memory_Leak"]:
        memory_leak_data.append(bytearray(chunk_size))
        total_mb = len(memory_leak_data) * 50
        logger.info(f"Memory_Leak: {total_mb}MB allocated")
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
                decision = random.random()

                if decision < Config.PGM_HEALTH_PROBABILITY:
                    healthy_duration = random.uniform(20, 40)
                    buffer_active = True
                    buffer_end_time = current_time + healthy_duration
                    logger.info(f"PGM: HEALTHY PERIOD for {healthy_duration:.1f}s")

                else:
                    fault_name = random.choice(FAULT_LIST)
                    fault_active[fault_name] = True
                    fault_end_times[fault_name] = current_time + Config.PGM_FAULT_DURATION

                    if fault_name == "Compute_Overload":
                        start_cpu_hog()
                    elif fault_name == "Memory_Leak":
                        task = asyncio.create_task(memory_hog())
                        fault_tasks[fault_name] = task

                    logger.warning(f"PGM FAULT: {fault_name} ({Config.PGM_FAULT_DURATION}s)")

            await asyncio.sleep(1)

        except Exception as e:
            logger.error(f"PGM scheduler error: {e}")
            await asyncio.sleep(5)


async def auto_fault_manager():
    """Automatic fault manager"""
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
                    start_cpu_hog()
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
    logger.info("=" * 60)
    logger.info("Victim Server Started - PGM Fault Injection")
    logger.info("  Compute_Overload : 80-95% CPU + mild latency (THREAD MODE)")
    logger.info("  Memory_Leak      : +50MB/2sec + moderate latency")
    logger.info("  Network_Partition: severe latency (3-8s) + 50% errors")
    logger.info("  App_Crash        : 30% error rate")
    logger.info("=" * 60)

    yield

    for task in fault_tasks.values():
        task.cancel()
    if redis_client:
        await redis_client.close()


# Create FastAPI application
app = FastAPI(
    title="Victim Server - PGM Fault Injection",
    description="Fault injection system for PGM training",
    version="3.0.0",
    lifespan=lifespan
)


# ============================================================================
# MIDDLEWARE
# ============================================================================

@app.middleware("http")
async def apply_fault_effects(request: Request, call_next):
    """Apply latency and error effects based on active faults"""
    global total_requests, request_times, error_flags

    total_requests += 1
    start = time.time()
    error_occurred = False

    try:
        # Apply latency effects
        if fault_active["Compute_Overload"]:
            await asyncio.sleep(random.uniform(0.5, 2.0))
        elif fault_active["Memory_Leak"]:
            await asyncio.sleep(random.uniform(0.5, 2.5))
        elif fault_active["Network_Partition"]:
            await asyncio.sleep(random.uniform(3.0, 8.0))

        response = await call_next(request)
        process_time = (time.time() - start) * 1000
        request_times.append(process_time)
        
        # Error injection
        if fault_active["Network_Partition"] and random.random() < Config.NETWORK_PARTITION_ERROR_RATE:
            error_occurred = True
        if fault_active["App_Crash"] and random.random() < Config.APP_CRASH_ERROR_RATE:
            error_occurred = True
        
        error_flags.append(1 if error_occurred else 0)
        
        if error_occurred:
            raise HTTPException(status_code=504, detail="Gateway Timeout")
        
        return response
        
    except HTTPException:
        error_flags.append(1)
        raise
    except Exception:
        error_flags.append(1)
        raise


# ============================================================================
# BUSINESS ENDPOINTS
# ============================================================================

@app.get("/api/products")
async def get_products():
    return {
        "products": "laptop: $999, mouse: $25",
        "timestamp": datetime.now().isoformat()
    }


@app.get("/api/users")
async def get_users():
    return {"users": 1500, "active": 423}


# ============================================================================
# METRICS ENDPOINTS
# ============================================================================

@app.get("/health")
async def health():
    global total_requests, request_times, error_flags, memory_leak_data, _prev_cpu, _prev_system

    # ✅ FIXED: Double sampling for proper delta calculation
    container_cpu = get_container_cpu()
    time.sleep(0.1)  # Small delay to get meaningful delta
    container_cpu = get_container_cpu()
    
    system_cpu = psutil.cpu_percent(interval=0.1)
    mem = psutil.virtual_memory().percent

    avg_lat = sum(request_times) / len(request_times) if request_times else 0
    err_rate = (sum(error_flags) / len(error_flags) * 100) if error_flags else 0

    # ✅ REMOVED: Fake CPU noise that was corrupting metrics
    # No random CPU addition anymore

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
    """PGM-ready metrics - discrete states for Bayesian Network"""
    health_data = await health()
    m = health_data["metrics"]

    cpu_state = get_cpu_state(m["container_cpu_percent"])
    ram_state = get_ram_state(m["memory_percent"])
    latency_state = get_latency_state(m["avg_latency_ms"])
    error_state = get_error_state(m["error_rate_percent"])

    return {
        "timestamp": health_data["timestamp"],
        "faults_active": fault_active,
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

    return "\n".join([
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
    ])


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
    return {"status": "success", "single_fault_mode": single_fault_mode}


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


@app.post("/fault/compute-overload/{action}")
async def compute_overload_control(action: str):
    if single_fault_mode and action == "start":
        if any(fault_active.values()):
            active_faults = [f for f, v in fault_active.items() if v]
            raise HTTPException(409, f"Fault '{active_faults[0]}' already active")

    if action == "start":
        fault_active["Compute_Overload"] = True
        start_cpu_hog()
        return {"message": "Compute_Overload STARTED"}
    elif action == "stop":
        fault_active["Compute_Overload"] = False
        return {"message": "Compute_Overload STOPPED"}
    raise HTTPException(400, "Invalid action. Use 'start' or 'stop'.")


@app.post("/fault/memory-leak/{action}")
async def memory_leak_control(action: str):
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


@app.post("/fault/network-partition/{action}")
async def network_partition_control(action: str):
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


@app.post("/fault/app-crash/{action}")
async def app_crash_control(action: str):
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


@app.get("/")
async def root():
    return {
        "server": "Victim Server - PGM Fault Injection",
        "version": "3.0.0",
        "faults_active": fault_active,
        "auto_fault_enabled": auto_fault_enabled,
        "single_fault_mode": single_fault_mode,
        "causal_model": {
            "Compute_Overload": "→ CPU_Usage ↑, API_Latency ↑",
            "Memory_Leak": "→ RAM_Usage ↑, API_Latency ↑",
            "Network_Partition": "→ API_Latency Timeout, Error_Rate ↑",
            "App_Crash": "→ Error_Rate ↑"
        }
    }


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)