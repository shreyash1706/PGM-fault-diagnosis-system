# Real-Time Probabilistic Fault Diagnosis Pipeline

This project builds a live, end-to-end telemetry and diagnosis pipeline using FastAPI, Prometheus, Apache Kafka, and a probabilistic Bayesian Network graphical model. 

It perfectly demonstrates how distributed infrastructure can automatically detect, stream, and probabilistically infer the root causes of server-degradation incidents (such as memory leaks and compute overloads) in real-time.

## Project Structure Overview
- **`victim-server/app.py`**: A simulated FastAPI web server that artificially injects random system faults (CPU hogs, memory leaks, latency, and HTTP 500 errors) and exports the raw hardware metrics via `psutil`.
- **`monitoring/prometheus.yml`**: Configures Prometheus to actively scrape the victim server metrics.
- **`bridge.py`**: A continuous Python loop that pulls raw data from Prometheus, discretizes the continuous metrics (e.g., `90% CPU` -> `"Critical"`), and pushes them to Apache Kafka.
- **`consumer.py`**: Subscribes to the Kafka `telemetry_stream` topic, isolating the discrete evidence and POSTing it to the Diagnostic API.
- **`main.py`**: Hosts the `bayesian_fault_model.pkl` probabilistic model using FastAPI to provide a `/diagnose` endpoint.

---

## 🚀 How to Run the Full Pipeline

### Requirements
You will need Docker Desktop and Python 3.10+ installed.

### Step 1: Start the Infrastructure
Fire up the backend data components (Prometheus, Zookeeper, Apache Kafka, Redis, and MLFlow) in your initial terminal:
```bash
docker compose up -d
```

### Step 2: Start the Victim Server
In a **second terminal**, start the victim server where the faults will be generated:
```bash
python victim-server/app.py
```

### Step 3: Start the Telemetry Bridge
In a **third terminal**, run the bridge script to pick up Promethus metrics and stream them to Kafka:
```bash
python bridge.py
```

### Step 4: Host the Diagnostic Engine
In a **fourth terminal**, host the Bayesian Network Inference model API. Note that it must be run on Port `8001` to avoid conflicting with the Victim Server!
```bash
uvicorn main:app --port 8001
```

### Step 5: Start the Diagnosis Consumer
In a **fifth terminal**, start the final script which parses the Kafka stream and prints the active diagnoses:
```bash
python consumer.py
```

### 🚨 Forcing a System Failure
To witness the pipeline reacting in real time, simply wait for the `victim-server/app.py` to auto-trigger a massive fault (like a Memory Hog), or trigger one yourself! As soon as it occurs, watch the `bridge.py` terminal change from `"Normal"` to `"Critical"`, and watch the `consumer.py` terminal output a `🚨 FAULT DETECTED 🚨` alert!
