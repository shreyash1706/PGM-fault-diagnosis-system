# 🚀 PGP Victim Server: Complete Operation Guide

This guide provides a comprehensive walkthrough for managing, monitoring, and testing the **PGM Fault Diagnosis System**. It covers everything from initial container deployment to manual fault injection and multi-fault stress testing.

---

## 📋 Phase 1: Environment Orchestration

### Step 1: Build and Start Containers
Ensure your environment is clean and all services are running based on the latest configurations.

```bash
# Navigate to your project folder
cd D:\PGP

# Stop any existing containers (clean start)
docker-compose down

# Build and start all services in detached mode
docker-compose up -d --build

# Check if containers are running
docker-compose ps
```

**What these commands do:**
- `docker-compose down`: Stops and removes containers, networks, and images defined in the compose file. This ensures you start from a clean state.
- `docker-compose up -d --build`: 
    - `-d`: Runs containers in the background (**detached mode**).
    - `--build`: Forces a rebuild of images even if they already exist, ensuring your latest code changes are included.
- `docker-compose ps`: Lists the status of your containers to verify services are `Up (healthy)`.

---

## 📋 Phase 2: Core Connectivity Verification

### Step 2: Check Basic Endpoints
Before running any tests, verify that the server is responding correctly.

```bash
# Check root endpoint
curl http://localhost:8000/

# Check health endpoint
curl http://localhost:8000/health

# Check auto-fault status (should be enabled by default)
curl http://localhost:8000/auto-fault/status
```

**What these commands do:**
- `/`: Confirms the web server is alive and reachable.
- `/health`: Provides real-time metrics for the server. This is the primary endpoint used for monitoring.
- `/auto-fault/status`: Queries the internal scheduler to see if the system will automatically generate faults for testing.

---

## 📋 Phase 3: Real-Time Monitoring

### Step 3: Run the Visual Monitor
Open a **new terminal** window and run the monitoring script to watch the system's behavior in real-time.

```bash
cd D:\PGP
python monitor.py
```

**What this script does:**
- Continuously polls the `/health` endpoint.
- Displays a visual dashboard showing **CPU Usage**, **Memory Usage**, **Latency**, and **Error Rates**.
- Highlights active faults and displays notifications for multiple fault detection.
- Useful for visually confirming that your manual triggers are working as expected.

---

## 📋 Phase 4: Auto-Fault System Control

### Step 4: Manage Scheduled Faults
The system has an "Auto-Fault" mode where it randomly injects problems. You can control this for testing stability.

```bash
# CHECK AUTO-FAULT STATUS
curl http://localhost:8000/auto-fault/status

# DISABLE AUTO-FAULTS (Switch to manual testing only)
curl -X POST http://localhost:8000/auto-fault/stop

# ENABLE AUTO-FAULTS (Let the server manage fault cycles)
curl -X POST http://localhost:8000/auto-fault/start

# Verify auto-faults are enabled
curl http://localhost:8000/auto-fault/status
```

**Why manage this?**
- When performing manual tests (Phase 5), it is recommended to **Stop** auto-faults first so they don't interfere with your specific test results.

---

## 📋 Phase 5: Manual Fault Injection Testing

### Step 5: Test Each Fault Type Individually
You can manually trigger specific failure modes to observe how the monitoring and PGM system reacts.

#### 1. CPU SPIKE
```bash
# Start CPU spike
curl -X POST http://localhost:8000/fault/cpu/start

# Check current status (should show CPU spike active)
curl http://localhost:8000/health | grep faults_active

# Wait 10 seconds, then check CPU
curl http://localhost:8000/health | grep cpu_percent

# Stop CPU spike
curl -X POST http://localhost:8000/fault/cpu/stop
```
- **Effect**: Spawns multiple threads to perform heavy mathematical calculations, pushing CPU usage toward 100%.

#### 2. MEMORY LEAK
```bash
# Start memory leak
curl -X POST http://localhost:8000/fault/memory/start

# Watch memory grow (run multiple times)
curl http://localhost:8000/health | grep memory_leak_mb
sleep 3
curl http://localhost:8000/health | grep memory_leak_mb
sleep 3
curl http://localhost:8000/health | grep memory_leak_mb

# Stop memory leak
curl -X POST http://localhost:8000/fault/memory/stop
```
- **Effect**: Continuously allocates memory in a background list. Use `curl http://localhost:8000/health | grep memory_leak_mb` to watch the leak grow.

#### 3. API LATENCY
```bash
# Test normal response time
time curl -s http://localhost:8000/api/products > /dev/null

# Start latency fault
curl -X POST http://localhost:8000/fault/latency/start

# Test slow response time (3-8 seconds)
time curl -s http://localhost:8000/api/products > /dev/null

# Stop latency fault
curl -X POST http://localhost:8000/fault/latency/stop
```
- **Effect**: Introduces a random sleep (3-8 seconds) into API calls like `/api/products`. Expect request times to spike significantly.

#### 4. ERROR RATE
```bash
# Start error rate fault
curl -X POST http://localhost:8000/fault/errors/start

# Watch errors happen (30% will fail)
for i in {1..10}; do
    echo -n "Request $i: "
    curl -s http://localhost:8000/api/products | grep -o "products\|error" || echo "ERROR"
done

# Stop error rate fault
curl -X POST http://localhost:8000/fault/errors/stop
```
- **Effect**: Forces roughly 30% of API requests to fail with a `500 Internal Server Error`.

---

## 📋 Phase 6: Multi-Fault Stress Testing

### Step 6: Test Combined Failure Scenarios
In real-world environments, faults rarely happen in isolation. Test how the system handles multiple simultaneous issues.

```bash
# START ALL FAULTS SIMULTANEOUSLY
curl -X POST http://localhost:8000/fault/cpu/start
curl -X POST http://localhost:8000/fault/memory/start
curl -X POST http://localhost:8000/fault/latency/start
curl -X POST http://localhost:8000/fault/errors/start

# VERIFY STATUS (Should list all 4 active faults)
curl http://localhost:8000/health | grep faults_active

# STOP ALL FAULTS (Emergency Stop for all injected issues)
curl -X POST http://localhost:8000/fault/stop-all
```

**Why test this?**
- Confirms the monitor's ability to handle overlapping telemetry signals.
- Validates the "Stop All" fail-safe mechanism.

---

## 📋 Phase 7: Advanced Data Inspection

### Step 7: Examine Metrics for ML & Debugging
These endpoints provide the raw data used by the PGM model and for developer debugging.

```bash
# HEALTH ENDPOINT: Real-time system state
curl http://localhost:8000/health | python -m json.tool

# PGM METRICS: Structured data optimized for the Probabilistic Graphical Model
curl http://localhost:8000/api/metrics | python -m json.tool

# DEBUG ENDPOINT: Internal scheduler and detailed fault state
curl http://localhost:8000/api/debug | python -m json.tool
```

**Command Note:**
- `| python -m json.tool`: Piped into Python to "pretty-print" the JSON response, making it easier to read in the terminal.
