import json 
from confluent_kafka import Consumer,KafkaError,KafkaException
import requests

KAFKA_TOPIC = "telemetry_stream"
conf = {
        'bootstrap.servers':'localhost:9092',
        'group.id':'ml-inference-group',
        'auto.offset.reset':'latest'
        }

consumer = Consumer(conf)
consumer.subscribe(["telemetry_stream"])

API_URL = "http://127.0.0.1:8001/diagnose"

print("Starting Telemetry Consumer... Waiting for data... (Press Ctrl+C to stop)")

try:
    while True:
        msg = consumer.poll(timeout=1.0)

        if msg is None:
            continue

        if msg.error():
            if msg.error().code()==KafkaError._PARTITION_EOF:
                continue
            else:
                raise KafkaException(msg.error())

        raw_data = msg.value().decode('utf-8')

        telemetry = json.loads(raw_data)

        # bridge.py nests the actual evidence inside "observable_nodes"
        evidence_payload = telemetry.get("observable_nodes", telemetry)

        try:
            response = requests.post(API_URL, json=evidence_payload)
            response.raise_for_status() # Raises an error for bad HTTP codes
            
            diagnosis = response.json().get('diagnoses', {})
            
            # 4. Filter out the 0s to only show the actual faults
            active_faults = {k: v for k, v in diagnosis.items() if v == 1}
            
            if active_faults:
                print(f"🚨 FAULT DETECTED: {active_faults} 🚨")
            else:
                print("✅ System Healthy")
                
        except requests.exceptions.RequestException as e:
            print(f"API Connection Error: Is FastAPI running? ({e})")

except KeyboardInterrupt:
    print("\nShutting down consumer...")
finally:
    # Close down consumer to commit final offsets.
    consumer.close()
    print("Consumer closed.")
