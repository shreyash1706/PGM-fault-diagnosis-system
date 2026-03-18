import json 
from confluent_kafka import Consumer,KafkaError,KafkaException

KAFKA_TOPIC = "telemetry_stream"
conf = {
        'bootstrap.servers':'localhost:9092',
        'group.id':'ml-inference-group',
        'auto.offset.reset':'latest'
        }

consumer = Consumer(conf)
consumer.subscribe([KAFKA_TOPIC])

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

        print(f"\n[RECEIVED] State: {telemetry['true_fault_label']}")
        print(f"  --> CPU: {telemetry['cpu_state']}")
        print(f"  --> RAM: {telemetry['ram_state']}")
        print(f"  --> LAT: {telemetry['latency_state']}")

except KeyboardInterrupt:
    print("\nShutting down consumer...")
finally:
    # Close down consumer to commit final offsets.
    consumer.close()
    print("Consumer closed.")
