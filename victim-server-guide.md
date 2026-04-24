# 🚀 PGM Fault Diagnosis System (Victim Server)

A **fault injection + observability system** designed to generate **causal training data** for a **Probabilistic Graphical Model (PGM)**.

---

# 🧠 System Overview

This system simulates real-world failures where:

> **Faults (latent variables) → Metrics (observable variables)**

Your model learns:

> **P(Fault | Observations)**

---

## 🔹 Latent Nodes (Hidden Faults)

| Fault             | Description                       |
| ----------------- | --------------------------------- |
| Compute_Overload  | CPU spike + mild latency          |
| Memory_Leak       | RAM exhaustion + moderate latency |
| Network_Partition | High latency (timeouts)           |
| App_Crash         | Random HTTP errors                |

---

## 🔹 Observable Nodes (PGM Inputs)

| Metric      | States                      |
| ----------- | --------------------------- |
| CPU_Usage   | Normal / High / Critical    |
| RAM_Usage   | Normal / High / Critical    |
| API_Latency | Normal / Elevated / Timeout |
| Error_Rate  | Zero / Spiking              |

---

## 🔗 Causal Mapping

| Fault             | Effects           |
| ----------------- | ----------------- |
| Compute_Overload  | CPU ↑ + Latency ↑ |
| Memory_Leak       | RAM ↑ + Latency ↑ |
| Network_Partition | Latency ↑↑        |
| App_Crash         | Errors ↑          |

---

# 🚀 Quick Start

## 1️⃣ Start the system

```bash
docker-compose down -v
docker-compose up -d --build
docker-compose ps
```

---

## 2️⃣ Verify services

```bash
curl http://localhost:8000/health
```

---

## 3️⃣ Open dashboards

| Service       | URL                        |
| ------------- | -------------------------- |
| API Docs      | http://localhost:8000/docs |
| Prometheus    | http://localhost:9090      |
| Grafana       | http://localhost:3000      |
| Kafka UI      | http://localhost:8080      |
| MLflow        | http://localhost:5000      |
| Redis Insight | http://localhost:5540      |

---

# 🎮 Modes

---

## 🔹 PGM Mode (IMPORTANT)

```bash
curl -X POST http://localhost:8000/single-fault-mode/enable
```

### Behavior:

* One fault at a time
* Clean causal data
* RL-style cycle:

```
Healthy → Decision → Fault → Buffer → Repeat
```

---

## 🔹 Disable PGM Mode

```bash
curl -X POST http://localhost:8000/single-fault-mode/disable
```

---

## 🔹 Auto Fault Control

```bash
curl -X POST http://localhost:8000/auto-fault/start
curl -X POST http://localhost:8000/auto-fault/stop
```

---

# 🔧 Manual Fault Control

---

## Compute_Overload

```bash
curl -X POST http://localhost:8000/fault/cpu/start
curl -X POST http://localhost:8000/fault/cpu/stop
```

---

## Memory_Leak

```bash
curl -X POST http://localhost:8000/fault/memory/start
curl -X POST http://localhost:8000/fault/memory/stop
```

---

## Network_Partition

```bash
curl -X POST http://localhost:8000/fault/latency/start
curl -X POST http://localhost:8000/fault/latency/stop
```

---

## App_Crash

```bash
curl -X POST http://localhost:8000/fault/errors/start
curl -X POST http://localhost:8000/fault/errors/stop
```

---

## Stop All Faults

```bash
curl -X POST http://localhost:8000/fault/stop-all
```

---

# 📊 Metrics

---

## 🔹 Raw Metrics

```bash
curl http://localhost:8000/health
```

Includes:

* container_cpu_percent ✅
* memory_percent
* avg_latency_ms
* error_rate_percent

---

## 🔹 PGM Metrics (MAIN)

```bash
curl http://localhost:8000/api/metrics
```

Example:

```json
{
  "observable_nodes": {
    "CPU_Usage": "High",
    "RAM_Usage": "Normal",
    "API_Latency": "Elevated",
    "Error_Rate": "Zero"
  },
  "faults_active": {
    "Compute_Overload": true
  }
}
```

---

## 🔹 Prometheus

```bash
curl http://localhost:8000/metrics
```

---

# 🧪 Monitoring

Run live monitor:

```bash
python monitor.py
```

Shows:

* CPU / RAM / Latency / Errors
* Active faults
* PGM observable states

---

# 🧠 PGM Inference Logic

| Observations      | Likely Fault      |
| ----------------- | ----------------- |
| CPU ↑ + Latency ↑ | Compute_Overload  |
| RAM ↑ + Latency ↑ | Memory_Leak       |
| Latency Timeout   | Network_Partition |
| Errors ↑ only     | App_Crash         |

---

# 🛠 Troubleshooting

---

## Check logs

```bash
docker-compose logs -f victim-app
```

---

## Restart service

```bash
docker-compose restart victim-app
```

---

## Full reset

```bash
docker-compose down -v
docker-compose up -d --build
```

---

# ✅ Success Criteria

✔ Containers are healthy
✔ `/health` returns data
✔ `/api/metrics` shows correct states
✔ Faults change metrics correctly
✔ Prometheus scrapes metrics
✔ Grafana shows data

---

# 🎯 Summary

This system provides:

* ✔ Clean causal data generation
* ✔ Single-fault training mode
* ✔ Real-time observability (Prometheus + Grafana)
* ✔ Kafka + ML pipeline ready

---

# 🚀 Next Steps

* Train Bayesian Network using `/api/metrics`
* Stream data to Kafka
* Build real-time fault inference

---

**Version:** 6.0
**Status:** Production-ready PGM simulation system
