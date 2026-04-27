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

CAUSAL CONSTRAINTS (STRICTLY ENFORCED):
- Compute_Overload: ONLY affects CPU_Usage ↑, API_Latency ↑
- Memory_Leak: ONLY affects RAM_Usage ↑, API_Latency ↑
- Network_Partition: ONLY affects API_Latency Timeout, Error_Rate ↑
- App_Crash: ONLY affects Error_Rate ↑
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

# Fault states - PGM Latent Nodes (ONLY ONE CAN BE TRUE AT A TIME)
fault_active: Dict[str, bool] = {
    "Compute_Overload": False,
    "Memory_Leak": False,
    "Network_Partition": False,
    "App_Crash": False
}

# Canonical fault list for schedulers
FAULT_LIST = ["Compute_Overload", "Memory_Leak", "Network_Partition", "App_Crash"]

# Auto-fault system enabled/disabled (OFF BY DEFAULT for PGM compliance)
auto_fault_enabled: bool = False

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

# CPU delta tracking variables
_prev_cpu = None
_prev_system = None


# ============================================================================
# CONFIGURATION
# ============================================================================

class Config:
    # Fault durations
    FAULT_DURATION: tuple = (20, 40)
    
    # PGM training mode
    PGM_FAULT_DURATION: float = 30.0
    PGM_HEALTH_PROBABILITY: float = 0.7
    PGM_BUFFER_MIN: float = 15.0
    PGM_BUFFER_MAX: float = 45.0
    
    # Memory leak allocation (ensures >70% RAM)
    MEMORY_CHUNK_MB: int = 100  # 100MB chunks to guarantee CRITICAL
    
    # Deterministic effects (NO PROBABILITY)
    COMPUTE_LATENCY_MS: float = 600.0  # 1.5 seconds -> Elevated
    MEMORY_LATENCY_MS: float = 600.0   # 2.0 seconds -> Elevated
    NETWORK_LATENCY_MS: float = 5000.0  # 5.0 seconds -> Timeout


# Track fault timers
fault_end_times: Dict[str, float] = {}
fault_tasks: Dict[str, asyncio.Task] = {}
buffer_active: bool = False
buffer_end_time: float = 0


# ============================================================================
# FAULT ISOLATION (CRITICAL: ENFORCES SINGLE FAULT)
# ============================================================================

def activate_only(fault_name: str):
    """
    Ensure ONLY ONE fault is active at any time.
    This is CRITICAL for PGM causal model.
    """
    global fault_active, fault_tasks, memory_leak_data, cpu_thread
    
    # Deactivate all faults
    for f in fault_active:
        fault_active[f] = False
    
    # Cancel all fault tasks
    for task in fault_tasks.values():
        task.cancel()
    fault_tasks.clear()
    
    # Clean up memory leak data
    #memory_leak_data.clear()
    
    # Stop CPU thread if running
    if cpu_thread and cpu_thread.is_alive():
        # Thread will stop when fault_active["Compute_Overload"] becomes False
        cpu_thread = None
    
    # Activate the requested fault only
    fault_active[fault_name] = True
    logger.warning(f"🔄 SINGLE FAULT ACTIVATED: {fault_name}")


# ============================================================================
# DELTA-BASED CPU CALCULATION (MATCHES DOCKER)
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
# STRONG CPU LOAD USING THREAD (Compute_Overload)
# ============================================================================

def run_cpu_hog():
    """STRONG CPU load - ensures CPU reaches Critical (>80%)"""
    logger.warning("🔥 Compute_Overload (CPU Spike) STARTED - Target: Critical CPU")
    while fault_active["Compute_Overload"]:
        # Heavy CPU computation - ensures sustained high CPU
        for _ in range(100_000_000):
            _ = math.sqrt(_) * math.sin(_) * math.cos(_)
        # Tiny sleep to prevent complete system freeze but maintain high CPU
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
# MEMORY HOG (Memory_Leak) - Ensures RAM >70%
# ============================================================================

async def memory_hog():
    global memory_leak_data
    chunk_size = Config.MEMORY_CHUNK_MB * 1024 * 1024

    logger.warning("💾 Memory_Leak STARTED")

    try:
        while fault_active["Memory_Leak"]:
            memory_leak_data.append(bytearray(chunk_size))

            # force allocation
            for chunk in memory_leak_data:
                chunk[0] = 1

            logger.info(f"Memory_Leak: {len(memory_leak_data) * Config.MEMORY_CHUNK_MB}MB")

            await asyncio.sleep(1)

    except asyncio.CancelledError:
        logger.warning("Memory_Leak task cancelled")
        raise

    except Exception as e:
        logger.error(f"Memory_Leak crashed: {e}")

    finally:
        logger.warning("💾 Memory_Leak LOOP EXITED")


# ============================================================================
# PGM FAULT SCHEDULER (Single fault mode for training)
# ============================================================================

async def pgm_fault_scheduler():
    """Single fault mode scheduler for PGM training - ensures ONE FAULT at a time"""
    global fault_active, fault_end_times, fault_tasks, buffer_active, buffer_end_time, memory_leak_data

    while True:
        try:
            current_time = time.time()
            active_faults = [f for f, v in fault_active.items() if v]

            if active_faults:
                fault_name = active_faults[0]
                if current_time >= fault_end_times.get(fault_name, 0):
                    # Fault expired - deactivate it
                    fault_active[fault_name] = False
                    logger.info(f"PGM FAULT ENDED: {fault_name}")

                    if fault_name in fault_tasks:
                        fault_tasks[fault_name].cancel()
                        del fault_tasks[fault_name]

                    if fault_name == "Memory_Leak":
                        memory_leak_data.clear()

                    # Start buffer period (healthy state)
                    buffer_duration = random.uniform(Config.PGM_BUFFER_MIN, Config.PGM_BUFFER_MAX)
                    buffer_end_time = current_time + buffer_duration
                    buffer_active = True
                    logger.info(f"BUFFER PERIOD: {buffer_duration:.1f}s (Healthy state)")

                    if fault_name in fault_end_times:
                        del fault_end_times[fault_name]

            elif buffer_active:
                if current_time >= buffer_end_time:
                    buffer_active = False
                    logger.info("BUFFER PERIOD ENDED - Ready for next fault")

            elif not buffer_active and not any(fault_active.values()):
                # Decide next action
                decision = random.random()

                if decision < Config.PGM_HEALTH_PROBABILITY:
                    # Healthy period
                    healthy_duration = random.uniform(20, 40)
                    buffer_active = True
                    buffer_end_time = current_time + healthy_duration
                    logger.info(f"PGM: HEALTHY PERIOD for {healthy_duration:.1f}s")
                else:
                    # Inject single fault
                    fault_name = random.choice(FAULT_LIST)
                    
                    # Ensure no other faults are active
                    for f in fault_active:
                        fault_active[f] = False
                    
                    fault_active[fault_name] = True
                    fault_end_times[fault_name] = current_time + Config.PGM_FAULT_DURATION

                    # Start fault-specific background tasks
                    if fault_name == "Compute_Overload":
                        start_cpu_hog()
                    elif fault_name == "Memory_Leak":
                        task = asyncio.create_task(memory_hog())
                        fault_tasks[fault_name] = task

                    logger.warning(f"PGM FAULT INJECTED: {fault_name} ({Config.PGM_FAULT_DURATION}s)")

            await asyncio.sleep(1)

        except Exception as e:
            logger.error(f"PGM scheduler error: {e}")
            await asyncio.sleep(5)


# ============================================================================
# AUTO FAULT MANAGER (DISABLED BY DEFAULT for PGM compliance)
# ============================================================================

async def auto_fault_manager():
    """Automatic fault manager - DISABLED by default to prevent multi-faults"""
    global fault_end_times, memory_leak_data, fault_tasks, auto_fault_enabled

    if single_fault_mode:
        logger.info("Single Fault Mode ENABLED - PGM training active")
        asyncio.create_task(pgm_fault_scheduler())
        return

    # Auto fault is OFF by default - do nothing unless manually enabled
    if not auto_fault_enabled:
        logger.info("Auto-fault system DISABLED (PGM compliance mode)")
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
    logger.info("Victim Server Started - PGM Fault Injection (STRICT MODE)")
    logger.info("  ✅ Single fault enforced (ONLY ONE fault at a time)")
    logger.info("  ✅ Deterministic causal effects")
    logger.info("  ✅ Auto-fault: OFF by default")
    logger.info("")
    logger.info("CAUSAL MODEL:")
    logger.info("  Compute_Overload  → CPU_Usage ↑, API_Latency ↑")
    logger.info("  Memory_Leak       → RAM_Usage ↑, API_Latency ↑")
    logger.info("  Network_Partition → API_Latency Timeout, Error_Rate ↑")
    logger.info("  App_Crash         → Error_Rate ↑")
    logger.info("=" * 60)

    yield

    for task in fault_tasks.values():
        task.cancel()
    if redis_client:
        await redis_client.close()


# Create FastAPI application
app = FastAPI(
    title="Victim Server - PGM Fault Injection",
    description="Fault injection system for PGM training - Strict causal enforcement",
    version="4.0.0",
    lifespan=lifespan
)


# ============================================================================
# MIDDLEWARE - DETERMINISTIC FAULT EFFECTS
# ============================================================================

from fastapi.responses import JSONResponse

@app.middleware("http")
async def apply_fault_effects(request: Request, call_next):

    # 🚨 FIX 1: Skip control + metrics endpoints
    if (
        request.url.path.startswith("/fault")
        or request.url.path.startswith("/auto-fault")
        or request.url.path.startswith("/single-fault-mode")
        or request.url.path.startswith("/health")
        or request.url.path.startswith("/metrics")
        or request.url.path.startswith("/api/metrics")
    ):
        return await call_next(request)

    global total_requests, request_times, error_flags

    total_requests += 1
    start = time.time()

    try:
        # ================= LATENCY =================
        if fault_active["Compute_Overload"]:
            await asyncio.sleep(Config.COMPUTE_LATENCY_MS / 1000.0)

        elif fault_active["Memory_Leak"]:
            await asyncio.sleep(Config.MEMORY_LATENCY_MS / 1000.0)

        elif fault_active["Network_Partition"]:
            await asyncio.sleep(Config.NETWORK_LATENCY_MS / 1000.0)

        # ================= CALL API =================
        response = await call_next(request)

        process_time = (time.time() - start) * 1000
        request_times.append(process_time)

        # ================= ERROR =================
        error_occurred = False

        if fault_active["Network_Partition"]:
            error_occurred = True

        elif fault_active["App_Crash"]:
            error_occurred = True

        error_flags.append(1 if error_occurred else 0)

        # 🚨 FIX 2: RETURN response instead of raising exception
        if error_occurred:
            return JSONResponse(
                status_code=504,
                content={"error": "Simulated Failure"}
            )

        return response

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
    """Health endpoint with comprehensive metrics"""
    global total_requests, request_times, error_flags, memory_leak_data, _prev_cpu, _prev_system

    # Get CPU with proper delta calculation
    # ================= FIXED CPU =================
    process = psutil.Process()
    container_cpu = process.cpu_percent(interval=0.5)
    # ============================================
    
    system_cpu = psutil.cpu_percent(interval=0.1)
    # ================= FIXED MEMORY =================
    try:
        with open("/sys/fs/cgroup/memory/memory.usage_in_bytes", "r") as f:
            usage = int(f.read().strip())
        with open("/sys/fs/cgroup/memory/memory.limit_in_bytes", "r") as f:
            limit = int(f.read().strip())
        
        mem = (usage / limit) * 100 if limit > 0 else 0.0
    except:
        mem = psutil.virtual_memory().percent
        # ==============================================

    avg_lat = request_times[-1] if request_times else 0
    err_rate = (sum(error_flags) / len(error_flags) * 100) if error_flags else 0

    # Count active faults (should be 0 or 1 in PGM mode)
    active_faults = [f for f, v in fault_active.items() if v]
    multiple_faults = len(active_faults) > 1

    if multiple_faults:
        logger.error(f"⚠️ MULTIPLE FAULTS DETECTED: {active_faults} - PGM constraint violated!")

    return {
        "timestamp": datetime.now().isoformat(),
        "metrics": {
            "system_cpu_percent": round(system_cpu, 2),
            "container_cpu_percent": round(container_cpu, 2),
            "memory_percent": round(mem, 2),
            "avg_latency_ms": round(avg_lat, 2),
            "error_rate_percent": round(err_rate, 2),
            "total_requests": total_requests,
            "memory_leak_mb": len(memory_leak_data) * Config.MEMORY_CHUNK_MB
        },
        "faults_active": fault_active,
        "active_fault_count": len(active_faults),
        "multiple_faults": multiple_faults,
        "auto_fault_enabled": auto_fault_enabled,
        "single_fault_mode": single_fault_mode,
        "buffer_active": buffer_active if single_fault_mode else None
    }


@app.get("/api/metrics")
async def get_metrics():
    """PGM-ready metrics - discrete states for Bayesian Network"""
    health_data = await health()
    m = health_data["metrics"]

    # EXACT DISCRETIZATION THRESHOLDS (match training data)
    # CPU: Normal <40%, High 40-80%, Critical >80%
    if m["container_cpu_percent"] >= 80:
        cpu_state = "Critical"
    elif m["container_cpu_percent"] >= 40:
        cpu_state = "High"
    else:
        cpu_state = "Normal"
    
    # RAM: Normal <40%, High 40-70%, Critical >70%
    if m["memory_percent"] >= 70:
        ram_state = "Critical"
    elif m["memory_percent"] >= 40:
        ram_state = "High"
    else:
        ram_state = "Normal"
    
    # Latency: Normal <200ms, Elevated 200-1000ms, Timeout >1000ms
    if m["avg_latency_ms"] > 1000:
        latency_state = "Timeout"
    elif m["avg_latency_ms"] > 200:
        latency_state = "Elevated"
    else:
        latency_state = "Normal"
    
    # Error: Zero <5%, Spiking >5%
    if m["error_rate_percent"] > 5:
        error_state = "Spiking"
    else:
        error_state = "Zero"

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

    # Determine active fault for Prometheus (should be only ONE)
    active_fault_name = "None"
    for fault_name, is_active in fault_active.items():
        if is_active:
            active_fault_name = fault_name
            break

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
        "# HELP victim_active_fault Currently active fault",
        "# TYPE victim_active_fault gauge",
        f'victim_active_fault {1 if active_fault_name != "None" else 0}',
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
    logger.warning("⚠️ Auto-fault system ENABLED - May violate PGM constraints if multiple faults occur")
    return {"status": "success", "auto_fault_enabled": auto_fault_enabled}


@app.post("/single-fault-mode/enable")
async def enable_single_fault_mode():
    """Enable PGM training mode - strictly enforces single fault"""
    global single_fault_mode, fault_active, fault_tasks, memory_leak_data, buffer_active, auto_fault_enabled

    if single_fault_mode:
        return {"status": "warning", "message": "Already enabled"}

    # Clear all active faults
    for fault in fault_active:
        fault_active[fault] = False
    for task in fault_tasks.values():
        task.cancel()
    fault_tasks.clear()
    memory_leak_data.clear()
    buffer_active = False
    
    # Disable auto-fault in single fault mode
    auto_fault_enabled = False
    single_fault_mode = True

    logger.warning("=" * 60)
    logger.warning("SINGLE FAULT MODE ENABLED - PGM training active")
    logger.warning("✅ Only ONE fault will be active at a time")
    logger.warning("✅ Deterministic causal effects enforced")
    logger.warning("=" * 60)
    
    return {"status": "success", "single_fault_mode": single_fault_mode}


@app.post("/single-fault-mode/disable")
async def disable_single_fault_mode():
    """Disable PGM training mode"""
    global single_fault_mode, fault_active, fault_tasks, memory_leak_data, buffer_active

    if not single_fault_mode:
        return {"status": "warning", "message": "Already disabled"}

    # Clear all active faults
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
    """Control Compute_Overload fault - STRICTLY enforces single fault"""
    if action == "start":
        # Enforce single fault constraint
        if single_fault_mode and any(fault_active.values()):
            active_faults = [f for f, v in fault_active.items() if v]
            raise HTTPException(409, f"Cannot start Compute_Overload: Fault '{active_faults[0]}' already active (PGM single fault constraint)")
        
        activate_only("Compute_Overload")
        start_cpu_hog()
        logger.warning("🚀 Compute_Overload STARTED - CPU will spike to Critical")
        return {"message": "Compute_Overload STARTED", "active_fault": "Compute_Overload"}
        
    elif action == "stop":
        fault_active["Compute_Overload"] = False
        logger.info("Compute_Overload STOPPED")
        return {"message": "Compute_Overload STOPPED"}
        
    raise HTTPException(400, "Invalid action. Use 'start' or 'stop'.")


@app.post("/fault/memory-leak/{action}")
async def memory_leak_control(action: str):
    """Control Memory_Leak fault - STRICTLY enforces single fault"""
    global memory_leak_data, fault_tasks

    if action == "start":
        # Enforce single fault constraint
        if single_fault_mode and any(fault_active.values()):
            active_faults = [f for f, v in fault_active.items() if v]
            raise HTTPException(409, f"Cannot start Memory_Leak: Fault '{active_faults[0]}' already active (PGM single fault constraint)")
        
        activate_only("Memory_Leak")
        
        if "Memory_Leak" in fault_tasks:
            fault_tasks["Memory_Leak"].cancel()
        fault_tasks["Memory_Leak"] = asyncio.create_task(memory_hog())
        
        logger.warning("💾 Memory_Leak STARTED - RAM will rise to Critical")
        return {"message": "Memory_Leak STARTED", "active_fault": "Memory_Leak"}
        
    elif action == "stop":
        fault_active["Memory_Leak"] = False
        if "Memory_Leak" in fault_tasks:
            fault_tasks["Memory_Leak"].cancel()
            del fault_tasks["Memory_Leak"]
        memory_leak_data.clear()
        logger.info("Memory_Leak STOPPED")
        return {"message": "Memory_Leak STOPPED"}
        
    raise HTTPException(400, "Invalid action. Use 'start' or 'stop'.")


@app.post("/fault/network-partition/{action}")
async def network_partition_control(action: str):
    """Control Network_Partition fault - STRICTLY enforces single fault"""
    if action == "start":
        # Enforce single fault constraint
        if single_fault_mode and any(fault_active.values()):
            active_faults = [f for f, v in fault_active.items() if v]
            raise HTTPException(409, f"Cannot start Network_Partition: Fault '{active_faults[0]}' already active (PGM single fault constraint)")
        
        activate_only("Network_Partition")
        logger.warning("🌐 Network_Partition STARTED - Latency will spike to Timeout, errors will spike")
        return {"message": "Network_Partition STARTED", "active_fault": "Network_Partition"}
        
    elif action == "stop":
        fault_active["Network_Partition"] = False
        logger.info("Network_Partition STOPPED")
        return {"message": "Network_Partition STOPPED"}
        
    raise HTTPException(400, "Invalid action. Use 'start' or 'stop'.")


@app.post("/fault/app-crash/{action}")
async def app_crash_control(action: str):
    """Control App_Crash fault - STRICTLY enforces single fault"""
    if action == "start":
        # Enforce single fault constraint
        if single_fault_mode and any(fault_active.values()):
            active_faults = [f for f, v in fault_active.items() if v]
            raise HTTPException(409, f"Cannot start App_Crash: Fault '{active_faults[0]}' already active (PGM single fault constraint)")
        
        activate_only("App_Crash")
        logger.warning("💥 App_Crash STARTED - Error rate will spike to Spiking")
        return {"message": "App_Crash STARTED", "active_fault": "App_Crash"}
        
    elif action == "stop":
        fault_active["App_Crash"] = False
        logger.info("App_Crash STOPPED")
        return {"message": "App_Crash STOPPED"}
        
    raise HTTPException(400, "Invalid action. Use 'start' or 'stop'.")


@app.post("/fault/stop-all")
async def stop_all_faults():
    """Emergency stop - deactivates all faults"""
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

    logger.warning("🛑 ALL FAULTS STOPPED - System returning to Healthy state")
    return {"status": "success", "faults_active": fault_active, "system_state": "Healthy"}


@app.get("/")
async def root():
    """Root endpoint with PGM model information"""
    active_faults = [f for f, v in fault_active.items() if v]
    
    return {
        "server": "Victim Server - PGM Fault Injection",
        "version": "4.0.0",
        "pgm_compliance": {
            "single_fault_enforced": single_fault_mode or len(active_faults) <= 1,
            "active_faults": active_faults,
            "auto_fault_enabled": auto_fault_enabled,
            "single_fault_mode": single_fault_mode
        },
        "causal_model": {
            "Compute_Overload": {
                "effects": ["CPU_Usage → Critical/High", "API_Latency → Elevated"],
                "no_effects": ["RAM_Usage", "Error_Rate"]
            },
            "Memory_Leak": {
                "effects": ["RAM_Usage → Critical/High", "API_Latency → Elevated"],
                "no_effects": ["CPU_Usage", "Error_Rate"]
            },
            "Network_Partition": {
                "effects": ["API_Latency → Timeout", "Error_Rate → Spiking"],
                "no_effects": ["CPU_Usage", "RAM_Usage"]
            },
            "App_Crash": {
                "effects": ["Error_Rate → Spiking"],
                "no_effects": ["CPU_Usage", "RAM_Usage", "API_Latency"]
            }
        },
        "discretization_thresholds": {
            "CPU_Usage": {"Normal": "<40%", "High": "40-80%", "Critical": ">80%"},
            "RAM_Usage": {"Normal": "<40%", "High": "40-70%", "Critical": ">70%"},
            "API_Latency": {"Normal": "<200ms", "Elevated": "200-1000ms", "Timeout": ">1000ms"},
            "Error_Rate": {"Zero": "<5%", "Spiking": ">5%"}
        }
    }


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)