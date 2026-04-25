from fastapi import FastAPI, HTTPException, Response
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field
import pandas as pd 
import pickle 
from prometheus_client import Gauge, generate_latest

app = FastAPI(title="Server Fault Diagnosis API")

# ML output metrics
ml_compute_overload = Gauge("ml_compute_overload", "ML predicted Compute Overload")
ml_memory_leak = Gauge("ml_memory_leak", "ML predicted Memory Leak")
ml_network_partition = Gauge("ml_network_partition", "ML predicted Network Partition")
ml_app_crash = Gauge("ml_app_crash", "ML predicted App Crash")

# ✅ FIX: Initialize metrics to 0 (so Grafana always sees data)
ml_compute_overload.set(0)
ml_memory_leak.set(0)
ml_network_partition.set(0)
ml_app_crash.set(0)

try:
    with open("bayesian_fault_model.pkl", "rb") as f:
        model = pickle.load(f)
    print("model loaded successfully into memory.")

except FileNotFoundError:
    print("model file not found. Please ensure 'bayesian_fault_model.pkl' is in the same directory as this script.")
    model = None
    
class TelemetryData(BaseModel):
    CPU_Usage: str = Field(..., pattern="^(Normal|High|Critical)$")
    RAM_Usage: str = Field(..., pattern="^(Normal|High|Critical)$")
    API_Latency: str = Field(..., pattern="^(Normal|Elevated|Timeout)$")
    Error_Rate: str = Field(..., pattern="^(Zero|Spiking)$")


@app.post("/diagnose")
async def diagnose_server(data: TelemetryData):
    # ✅ FIX: Check if model loaded successfully
    if model is None:
        raise HTTPException(status_code=500, detail="Model not loaded")
    
    try:
        input_data = pd.DataFrame([{
            "CPU_Usage": data.CPU_Usage,
            "RAM_Usage": data.RAM_Usage,
            "API_Latency": data.API_Latency,
            "Error_Rate": data.Error_Rate 
        }])
        
        prediction_df = model.predict(input_data)
        result = prediction_df.iloc[0].to_dict()
        
        # Update Prometheus metrics
        ml_compute_overload.set(result.get("Compute_Overload", 0))
        ml_memory_leak.set(result.get("Memory_Leak", 0))
        ml_network_partition.set(result.get("Network_Partition", 0))
        ml_app_crash.set(result.get("App_Crash", 0))
        
        return {
            "status": "success",
            "input_evidence": data.model_dump(),
            "diagnoses": result
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    

@app.get("/metrics")
async def metrics():
    # ✅ FIX: Explicit content type
    return Response(generate_latest(), media_type="text/plain")
    

@app.get("/")
async def root():
    return {"message": "Fault Diagnosis API is running."}