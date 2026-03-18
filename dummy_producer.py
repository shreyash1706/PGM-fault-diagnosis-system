import json
import time
import random
from confluent_kafka import Producer

# Kafka Configuration
KAFKA_TOPIC = "telemetry_stream"
conf = {
    'bootstrap.servers': 'localhost:9092',
    'client.id': 'dummy-telemetry-producer'
}

producer = Producer(conf)

def delivery_report(err, msg):
    """Callback triggered upon successful or failed message delivery."""
    if err is not None:
        print(f"Message delivery failed: {err}")
    else:
        print(f"Delivered to topic [{msg.topic()}] - Data: {msg.value().decode('utf-8')}")

def generate_mock_telemetry():
    """Generates a fake telemetry payload with randomized faults."""
    
    # Define possible system states
    scenarios = ["Healthy", "Healthy", "Healthy", "Healthy", "CPU_Spike", "Memory_Leak", "Network_Lag"]
    current_state = random.choice(scenarios)

    # Base healthy metrics
    payload = {
        "timestamp": int(time.time()),
        "cpu_state": "Normal",
        "ram_state": "Normal",
        "latency_state": "Normal",
        "true_fault_label": current_state # Passed so the ML guy can verify accuracy
    }

    # Injecting the overlapping symptoms based on the chosen scenario
    if current_state == "CPU_Spike":
        payload["cpu_state"] = "Critical"
        payload["latency_state"] = "Elevated"
        
    elif current_state == "Memory_Leak":
        payload["ram_state"] = "Critical"
        payload["latency_state"] = "Elevated"
        
    elif current_state == "Network_Lag":
        payload["latency_state"] = "Timeout"
        # Notice CPU and RAM stay Normal, which is the key differentiator
        
    # Adding a bit of noise (sometimes a healthy server has a brief CPU blip)
    if current_state == "Healthy" and random.random() > 0.9:
        payload["cpu_state"] = "Elevated"

    return payload

print("Starting Dummy Telemetry Producer... (Press Ctrl+C to stop)")

try:
    while True:
        # 1. Generate the fake data
        data = generate_mock_telemetry()
        
        # 2. Convert to JSON byte string
        json_payload = json.dumps(data).encode('utf-8')
        
        # 3. Push to Kafka Topic
        producer.produce(topic=KAFKA_TOPIC, value=json_payload, callback=delivery_report)
        
        # 4. Flush to ensure it sends immediately
        producer.poll(0) 
        
        # Simulate a 1-second metric scraping interval
        time.sleep(1)

except KeyboardInterrupt:
    print("\nStopping producer...")
finally:
    # Wait for any outstanding messages to be delivered
    producer.flush()
    print("Producer safely shut down.")
