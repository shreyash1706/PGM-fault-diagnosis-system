How to actually run + test everything step-by-step with terminals

So I’m giving you a FULL upgraded README (ready to paste) — with:

terminal setup ✅
exact commands ✅
testing flow ✅
expected outputs ✅
debugging clarity ✅
📄 🔥 FINAL COMPLETE README (PASTE THIS)
# 🚀 PGM Fault Diagnosis System (FULL TESTING GUIDE)

This guide explains:

✔ How to run the system  
✔ What to run in each terminal  
✔ How to test ALL modes  
✔ How to test ALL faults  
✔ What results to expect  

---

# 🧠 SYSTEM ARCHITECTURE


Victim Server → Prometheus → Grafana
↓
Kafka → ML → Predictions


---

# 🚀 STEP 1 — START SYSTEM

```bash
docker-compose down -v
docker-compose up -d --build

Check:

docker-compose ps
🌐 STEP 2 — VERIFY SYSTEM
curl http://localhost:8000/health
🖥️ STEP 3 — TERMINAL SETUP (VERY IMPORTANT)

You NEED 4 terminals.

🟢 Terminal 1 — Docker Stats
docker stats

👉 Shows real container CPU & memory

🟢 Terminal 2 — Health Monitor
while true; do curl -s http://localhost:8000/health; echo ""; sleep 1; done

👉 Shows live system metrics

🟢 Terminal 3 — Traffic Generator (MANDATORY)
while true; do curl -s http://localhost:8000/api/products > /dev/null; done

👉 Required for:

latency
error rate
🔴 Terminal 4 — CONTROL PANEL

👉 ALL curl commands run here

🎮 MODES
🔹 1. MANUAL MODE

👉 You control faults manually

curl -X POST http://localhost:8000/auto-fault/stop
curl -X POST http://localhost:8000/fault/stop-all
🔹 2. AUTO MODE
curl -X POST http://localhost:8000/auto-fault/start

👉 System randomly triggers faults

Stop:

curl -X POST http://localhost:8000/auto-fault/stop
🔹 3. SINGLE FAULT MODE (PGM MODE)
curl -X POST http://localhost:8000/single-fault-mode/enable

👉 Only ONE fault active at a time

Disable:

curl -X POST http://localhost:8000/single-fault-mode/disable
🔥 MANUAL FAULT TESTING (STEP-BY-STEP)
🟥 1. Compute Overload (CPU Spike)
curl -X POST http://localhost:8000/fault/compute-overload/start
EXPECT:
CPU → 80–95%
latency ↑

Stop:

curl -X POST http://localhost:8000/fault/compute-overload/stop
🟦 2. Memory Leak
curl -X POST http://localhost:8000/fault/memory-leak/start
EXPECT:
memory_leak_mb ↑
RAM ↑

Stop:

curl -X POST http://localhost:8000/fault/memory-leak/stop
🟨 3. Network Partition
curl -X POST http://localhost:8000/fault/network-partition/start
EXPECT:
latency → 3000–8000 ms
error_rate ↑

Stop:

curl -X POST http://localhost:8000/fault/network-partition/stop
🟥 4. App Crash
curl -X POST http://localhost:8000/fault/app-crash/start
EXPECT:
error_rate → ~30–60%
latency normal

Stop:

curl -X POST http://localhost:8000/fault/app-crash/stop
🧨 STOP ALL FAULTS
curl -X POST http://localhost:8000/fault/stop-all
🧠 IMPORTANT RULES
❗ Rule 1 — Always run traffic
while true; do curl -s http://localhost:8000/api/products > /dev/null; done
❗ Rule 2 — One fault at a time (for testing)
start → observe → stop → next
❗ Rule 3 — Metrics lag is NORMAL

👉 CPU may stay high even after fault OFF
👉 Error rate decreases slowly

📊 METRICS EXPLANATION
/health
{
  "container_cpu_percent": 85,
  "memory_percent": 60,
  "avg_latency_ms": 1500,
  "error_rate_percent": 30,
  "total_requests": 1000
}
Meaning:
Metric	Meaning
CPU	container CPU usage
Latency	request delay
Error rate	failed requests %
total_requests	total API calls
🧠 PGM LOGIC
Observation	Fault
CPU ↑ + latency ↑	Compute Overload
RAM ↑ + latency ↑	Memory Leak
Latency ↑↑	Network Partition
Errors ↑	App Crash