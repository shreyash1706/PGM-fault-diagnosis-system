import time
import json
import requests
import logging
from confluent_kafka import Producer

# ================= Configure Logging =================
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# ================= Configuration =================
# If running locally vs docker: Prometheus is usually on 9090
PROMETHEUS_URL = "http://localhost:9090"  
KAFKA_BROKER = "localhost:9092"
KAFKA_TOPIC = "telemetry_stream"

def get_prometheus_metric(query: str, default_value=0.0) -> float:
    """Fetch realtime metric value from Prometheus."""
    try:
        response = requests.get(f"{PROMETHEUS_URL}/api/v1/query", params={"query": query}, timeout=3)
        response.raise_for_status()
        results = response.json().get('data', {}).get('result', [])
        if results:
            value = results[0]['value'][1]
            return float(value)
        return default_value
    except Exception as e:
        logger.error(f"Failed fetching metric {query}: {e}")
        return default_value

# ================= Discrete Logic (The Bayesian Node Mapping) =================
# We categorize raw technical metrics into the semantic states expected by
# the Probabilistic Graphical Model defined in nodes.md
# ✅ FIXED: Exact thresholds matching training data and victim server
def discretize_cpu(cpu_percent: float) -> str:
    if cpu_percent >= 80: return "Critical"
    if cpu_percent >= 40: return "High"
    return "Normal"

def discretize_ram(ram_percent: float) -> str:
    if ram_percent >= 70: return "Critical"
    if ram_percent >= 50: return "High"
    return "Normal"

def discretize_latency(latency_ms: float) -> str:
    if latency_ms > 1000: return "Timeout"
    if latency_ms > 200: return "Elevated"
    return "Normal"

def discretize_error_rate(error_rate: float) -> str:
    if error_rate > 15: return "Spiking"
    return "Zero"

# ✅ FIXED: Correct Prometheus metric names matching victim server
def get_active_fault() -> str:
    """Determine active fault from Prometheus metrics - single fault only"""
    if get_prometheus_metric("victim_fault_compute_overload") == 1:
        return "Compute_Overload"
    elif get_prometheus_metric("victim_fault_memory_leak") == 1:
        return "Memory_Leak"
    elif get_prometheus_metric("victim_fault_network_partition") == 1:
        return "Network_Partition"
    elif get_prometheus_metric("victim_fault_app_crash") == 1:
        return "App_Crash"
    else:
        return "Healthy"

def build_pgm_payload() -> dict:
    """Build the final payload containing structured observations for the Bayesian Net"""
    cpu_percent = get_prometheus_metric("victim_container_cpu_percent")
    ram_percent = get_prometheus_metric("victim_memory_percent")
    latency_ms = get_prometheus_metric("victim_avg_latency_ms")
    error_rate = get_prometheus_metric("victim_error_rate_percent")

    return {
        "timestamp": int(time.time() * 1000),
        "observable_nodes": {
            "CPU_Usage": discretize_cpu(cpu_percent),
            "RAM_Usage": discretize_ram(ram_percent),
            "API_Latency": discretize_latency(latency_ms),
            "Error_Rate": discretize_error_rate(error_rate)
        },
        "raw_metrics": {
            "cpu_percent": round(cpu_percent, 2),
            "ram_percent": round(ram_percent, 2),
            "latency_ms": round(latency_ms, 2),
            "error_rate": round(error_rate, 2)
        },
        "active_fault": get_active_fault()
    }

def main():
    logger.info("Initializing Bridge Pipeline: Prometheus -> Bridge -> Kafka")
    
    # Standard Kafka producer setup
    try:
        producer = Producer({
            'bootstrap.servers': KAFKA_BROKER,
            'message.timeout.ms': 5000
        })
        logger.info("✅ Connected to Kafka")
    except Exception as e:
        logger.warning(f"⚠️ Could not connect to Kafka broker at {KAFKA_BROKER}. Running in dry-run mode. Error: {e}")
        producer = None

    # Processing Loop
    while True:
        payload = build_pgm_payload()
        
        if producer:
            try:
                payload_bytes = json.dumps(payload).encode('utf-8')
                producer.produce(KAFKA_TOPIC, value=payload_bytes)
                producer.poll(0)
                producer.flush()
                logger.info(f"active fault: {payload['active_fault']}")
                logger.info(f"📤 Pushed to Kafka: {payload['observable_nodes']}")
            except Exception as e:
                logger.error(f"❌ Error publishing to Kafka: {e}")
        else:
            logger.info(f"DRY RUN (Kafka offline) payload: {payload['observable_nodes']}")
        
        # Pull interval synchronized roughly with Prometheus scrape interval
        time.sleep(5)

if __name__ == "__main__":
    main()