# 🚀 Complete Victim Server Test Guide

**FastAPI + Redis Fault Injection System**

---

## 📦 Setup Commands

```bash
# Rebuild with new code
docker-compose down
docker-compose up -d --build

# Check it's running
curl http://localhost:8000/
```

**Expected response:**

```json
{
  "server": "Victim Server",
  "status": "running",
  "version": "3.0.0",
  "faults_active": {
    "cpu_spike": false,
    "memory_leak": false,
    "api_latency": false,
    "error_rate": false
  }
}
```

---

## 🔥 FAULT 1: CPU Spike

### What it simulates:

* **Type:** Compute overload / CPU exhaustion
* **Scenario:** A background process or infinite loop consuming all CPU cores
* **Real-world equivalent:** Cryptominer, unoptimized algorithm, fork bomb

### APIs Affected:

* `/api/products` — Gets slower due to CPU contention
* `/api/users` — Also slower
* All endpoints experience delay

### Test Commands:

```bash
# Start CPU spike
curl -X POST http://localhost:8000/fault/cpu/start

# Watch CPU and latency increase
for i in {1..5}; do
    sleep 2
    curl -s http://localhost:8000/health | grep -E "cpu_percent|avg_latency"
done

# Stop CPU spike
curl -X POST http://localhost:8000/fault/cpu/stop
```

### Expected Behavior:

* CPU usage jumps from `<5%` to `>50%`
* API latency increases from `<100ms` to `>500ms`
* Memory remains normal

---

## 🧠 FAULT 2: Memory Leak

### What it simulates:

* **Type:** RAM exhaustion / memory leak
* **Scenario:** Application holding onto references, not freeing memory
* **Real-world equivalent:** Caching without limits, image processing, session memory leak

### APIs Affected:

* `/api/products` — Gets progressively slower as memory fills
* `/api/users` — Same behavior
* System may eventually OOM (Out of Memory) if not stopped

### Test Commands:

```bash
# Check current memory
curl -s http://localhost:8000/health | grep memory_percent

# Start memory leak
curl -X POST http://localhost:8000/fault/memory/start

# Watch memory grow over 30 seconds
for i in {1..6}; do
    sleep 5
    curl -s http://localhost:8000/health | grep memory_percent
done

# Stop memory leak
curl -X POST http://localhost:8000/fault/memory/stop
```

### Expected Behavior:

* Memory usage steadily increases (adds ~10MB every 2 seconds)
* API latency gradually increases as memory fills
* CPU remains normal
* After ~100MB, system shows warning logs

---

## 🐌 FAULT 3: API Latency

### What it simulates:

* **Type:** Network latency / slow database queries
* **Scenario:** High network congestion, slow external API calls, database connection pool exhaustion
* **Real-world equivalent:** Slow third-party service, network packet loss, throttled database

### APIs Affected:

* `/api/products` — Artificial 1–3 second delay added
* `/api/users` — Same delay applied
* CPU and memory remain normal

### Test Commands:

```bash
# Test normal response time
time curl -s http://localhost:8000/api/products > /dev/null

# Start API latency
curl -X POST http://localhost:8000/fault/latency/start

# Test slow responses (1–3 second delays)
time curl -s http://localhost:8000/api/products > /dev/null
time curl -s http://localhost:8000/api/users > /dev/null

# Check metrics
curl -s http://localhost:8000/health | grep avg_latency

# Stop latency
curl -X POST http://localhost:8000/fault/latency/stop
```

### Expected Behavior:

* Response time jumps from `<0.5s` to `1–3s`
* CPU and memory remain normal
* Only latency metric increases

---

## 💥 FAULT 4: Error Rate

### What it simulates:

* **Type:** Application errors / 500 Internal Server Errors
* **Scenario:** Bug in code, database connection failure, unhandled exceptions
* **Real-world equivalent:** Null pointer exceptions, validation errors, service degradation

### APIs Affected:

* `/api/products` — 30% chance of returning 500 error
* `/api/users` — Same error rate
* `/api/data` — Also affected
* System resources remain normal

### Test Commands:

```bash
# Test normal (0% errors)
for i in {1..5}; do
    curl -s http://localhost:8000/api/products | grep -o "products\|error" || echo "Failed"
done

# Start error rate (30% failures)
curl -X POST http://localhost:8000/fault/errors/start

# Watch errors happen
for i in {1..10}; do
    curl -s http://localhost:8000/api/products 2>&1 || echo "💥 Request failed"
    sleep 1
done

# Check error rate metric
curl -s http://localhost:8000/health | grep error_rate

# Stop errors
curl -X POST http://localhost:8000/fault/errors/stop
```

### Expected Behavior:

* About 30% of requests fail with 500 error
* Error rate metric increases
* CPU, memory, latency remain normal
* Successful requests still return valid data

---

## 📊 Monitoring Endpoints Examples

### 1. `/health` — Real-time System Metrics

This endpoint provides real-time system health.

```bash
curl http://localhost:8000/health
```

**Example (Normal State):**

```json
{
  "status": "healthy",
  "timestamp": "2026-03-18T17:28:29.578965+00:00",
  "metrics": {
    "cpu_percent": 5.0,
    "memory_percent": 23.7,
    "avg_latency_ms": 98.5,
    "error_rate_percent": 0.0,
    "total_requests": 145
  },
  "faults_active": {
    "cpu_spike": false,
    "memory_leak": false,
    "api_latency": false,
    "error_rate": false
  },
  "redis_status": "connected"
}
```

**Example (During CPU Spike):**

```json
{
  "status": "healthy",
  "timestamp": "2026-03-18T17:30:24.157601+00:00",
  "metrics": {
    "cpu_percent": 85.5,
    "memory_percent": 24.1,
    "avg_latency_ms": 1250.75,
    "error_rate_percent": 0.0,
    "total_requests": 178
  },
  "faults_active": {
    "cpu_spike": true,
    "memory_leak": false,
    "api_latency": false,
    "error_rate": false
  },
  "redis_status": "connected"
}
```

---

### 2. `/api/metrics` — Formatted for PGM Consumption

This endpoint provides structured data for Probabilistic Graphical Models.

```bash
curl http://localhost:8000/api/metrics
```

**Example (Normal State):**

```json
{
  "timestamp": "2026-03-18T17:35:07.342875Z",
  "faults_active": {
    "cpu_spike": false,
    "memory_leak": false,
    "api_latency": false,
    "error_rate": false
  },
  "observable_nodes": {
    "cpu_usage": "Normal",
    "ram_usage": "Normal",
    "api_latency": "Normal",
    "error_rate": "Zero"
  },
  "raw_values": {
    "cpu_percent": 5.0,
    "memory_percent": 23.7,
    "avg_latency_ms": 98.5,
    "error_rate_percent": 0.0
  }
}
```

**Example (During CPU Spike):**

```json
{
  "timestamp": "2026-03-18T17:32:42.507853Z",
  "faults_active": {
    "cpu_spike": true,
    "memory_leak": false,
    "api_latency": false,
    "error_rate": false
  },
  "observable_nodes": {
    "cpu_usage": "High",
    "ram_usage": "Normal",
    "api_latency": "Elevated",
    "error_rate": "Zero"
  },
  "raw_values": {
    "cpu_percent": 85.5,
    "memory_percent": 24.1,
    "avg_latency_ms": 1250.75,
    "error_rate_percent": 0.0
  }
}
```

**Example (During Memory Leak):**

```json
{
  "observable_nodes": {
    "cpu_usage": "Normal",
    "ram_usage": "High",
    "api_latency": "Elevated",
    "error_rate": "Zero"
  }
}
```

**Example (During API Latency):**

```json
{
  "observable_nodes": {
    "cpu_usage": "Normal",
    "ram_usage": "Normal",
    "api_latency": "Timeout",
    "error_rate": "Zero"
  }
}
```

**Example (During Error Rate):**

```json
{
  "observable_nodes": {
    "cpu_usage": "Normal",
    "ram_usage": "Normal",
    "api_latency": "Normal",
    "error_rate": "Spiking"
  }
}
```

---

### 3. `/api/debug` — Internal State Inspection

This endpoint shows internal statistics.

```bash
curl http://localhost:8000/api/debug
```

**Example (Normal State):**

```json
{
  "faults": {
    "cpu_spike": false,
    "memory_leak": false,
    "api_latency": false,
    "error_rate": false
  },
  "stats": {
    "total_requests": 145,
    "error_count": 2,
    "recent_latencies": [98.5, 102.3, 95.7, 99.2, 101.5, 97.8, 103.1, 98.9, 100.2, 96.4]
  }
}
```

**Example (After Many Errors):**

```json
{
  "faults": {
    "error_rate": true
  },
  "stats": {
    "total_requests": 178,
    "error_count": 42,
    "recent_latencies": [101.2, 98.7, 456.2, 99.1, 102.8, 97.5, 489.1]
  }
}
```

---

## 📝 Checking All Endpoints Together

```bash
# Terminal 1 - Health check
curl http://localhost:8000/health | jq .

# Terminal 2 - PGM Metrics
curl http://localhost:8000/api/metrics | jq .

# Terminal 3 - Debug info
curl http://localhost:8000/api/debug | jq .
```

---

## 🎯 When to Use Each Endpoint

| Endpoint       | Use Case             | What to Observe                         |
| -------------- | -------------------- | --------------------------------------- |
| `/health`      | Real-time monitoring | CPU, Memory, Latency, Errors            |
| `/api/metrics` | PGM / ML model input | Discrete states (Normal, High, etc.)    |
| `/api/debug`   | Troubleshooting      | Request counts, errors, latency history |

---

## 📊 API Endpoints Summary

| Endpoint               | Method | Description             | Affected By                  |
| ---------------------- | ------ | ----------------------- | ---------------------------- |
| `/`                    | GET    | Server status           | None                         |
| `/health`              | GET    | System metrics          | All faults                   |
| `/api/metrics`         | GET    | Detailed PGM metrics    | All faults                   |
| `/api/debug`           | GET    | Debug info              | None                         |
| `/api/products`        | GET    | Get products from Redis | CPU, Memory, Latency, Errors |
| `/api/users`           | GET    | Get user count          | CPU, Memory, Latency, Errors |
| `/fault/cpu/start`     | POST   | Start CPU spike         | -                            |
| `/fault/cpu/stop`      | POST   | Stop CPU spike          | -                            |
| `/fault/memory/start`  | POST   | Start memory leak       | -                            |
| `/fault/memory/stop`   | POST   | Stop memory leak        | -                            |
| `/fault/latency/start` | POST   | Start API latency       | -                            |
| `/fault/latency/stop`  | POST   | Stop API latency        | -                            |
| `/fault/errors/start`  | POST   | Start error rate        | -                            |
| `/fault/errors/stop`   | POST   | Stop error rate         | -                            |

---

## 🎯 PGM Observable Nodes Mapping

| Fault       | CPU_Usage        | RAM_Usage        | API_Latency         | Error_Rate |
| ----------- | ---------------- | ---------------- | ------------------- | ---------- |
| CPU Spike   | 🔴 High/Critical | 🟢 Normal        | 🔴 Elevated         | 🟢 Zero    |
| Memory Leak | 🟢 Normal        | 🔴 High/Critical | 🟡 Slight Elevation | 🟢 Zero    |
| API Latency | 🟢 Normal        | 🟢 Normal        | 🔴 Elevated/Timeout | 🟢 Zero    |
| Error Rate  | 🟢 Normal        | 🟢 Normal        | 🟢 Normal           | 🔴 Spiking |

---
