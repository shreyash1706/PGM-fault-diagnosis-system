import json
import time
import random
from confluent_kafka import Producer

def generate_mock_telemetry():
    """Generates a fake telemetry payload matching the new Bayesian Network DAG."""
    
    # 1. Pick a scenario based on realistic base rates
    faults = ['Healthy', 'Compute_Overload', 'Memory_Leak', 'Network_Partition', 'App_Crash']
    fault_weights = [0.60, 0.10, 0.10, 0.10, 0.10]
    true_state = random.choices(faults, weights=fault_weights)[0]

    # 2. Baseline Healthy Metrics
    cpu = 'Normal'
    ram = 'Normal'
    latency = 'Normal'
    error = 'Zero'
    
    # 3. Inject the overlapping symptoms (The DAG Physics)
    if true_state == 'Healthy':
        if random.random() < 0.05: cpu = 'High'
        if random.random() < 0.05: ram = 'High'
    elif true_state == 'Compute_Overload':
        cpu = random.choices(['High', 'Critical'], weights=[0.3, 0.7])[0]
        latency = random.choices(['Elevated', 'Timeout'], weights=[0.8, 0.2])[0]
    elif true_state == 'Memory_Leak':
        ram = random.choices(['High', 'Critical'], weights=[0.2, 0.8])[0]
        latency = random.choices(['Elevated', 'Timeout'], weights=[0.8, 0.2])[0]
    elif true_state == 'Network_Partition':
        latency = 'Timeout'
        error = random.choices(['Zero', 'Spiking'], weights=[0.2, 0.8])[0]
    elif true_state == 'App_Crash':
        error = 'Spiking'
        if random.random() < 0.3: latency = 'Elevated'

    # 4. Construct the exact JSON FastAPI expects
    return {
        "timestamp": int(time.time()),
        "CPU_Usage": cpu,
        "RAM_Usage": ram,
        "API_Latency": latency,
        "Error_Rate": error,
        "Root_Cause": true_state # Passed for consumer validation, API ignores this
    }

# --- Kafka Producer Setup ---
conf = {'bootstrap.servers': 'localhost:9092'}
producer = Producer(conf)

def delivery_report(err, msg):
    if err is not None:
        print(f"Message delivery failed: {err}")

print("Starting Updated Telemetry Producer... (Press Ctrl+C to stop)")

try:
    while True:
        payload = generate_mock_telemetry()
        producer.produce(
            'telemetry_stream', 
            key=str(payload['timestamp']), 
            value=json.dumps(payload), 
            callback=delivery_report
        )
        producer.poll(0)
        
        # Print what we just sent so you can watch it flow
        print(f"Produced: {payload['Root_Cause']} -> CPU:{payload['CPU_Usage']} RAM:{payload['RAM_Usage']} Latency:{payload['API_Latency']}")
        
        time.sleep(2) # Send a metric every 2 seconds
        
except KeyboardInterrupt:
    print("\nShutting down producer.")
finally:
    producer.flush()
