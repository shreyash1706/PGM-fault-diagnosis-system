from fastapi import FastAPI,HTTPException
from pydantic import BaseModel, Field
import pandas as pd 
import pickle 

app = FastAPI(title="Server Fault Diagnosis API")

try:
    with open("bayesian_fault_model.pkl","rb") as f:
        model = pickle.load(f)
    print("model loaded successfully into memory.")

except FileNotFoundError:
    print("model file not found. Please ensure 'bayesian_fault_model.pkl' is in the same directory as this script.")
    model = None
    
class TelemetryData(BaseModel):
    CPU_Usage: str = Field(... , pattern = "^(Normal|High|Critical)$")
    RAM_Usage: str = Field(... , pattern = "^(Normal|High|Critical)$")
    API_Latency: str = Field(... , pattern = "^(Normal|Elevated|Timeout)$")
    Error_Rate: str = Field(... , pattern = "^(Zero|Spiking)$")


@app.post("/diagnose")
async def diagnose_server(data: TelemetryData):
    try:
        input_data = pd.DataFrame([{
            "CPU_Usage": data.CPU_Usage,
            "RAM_Usage": data.RAM_Usage,
            "API_Latency": data.API_Latency,
            "Error_Rate": data.Error_Rate 
        }])
        
        prediction_df = model.predict(input_data)
        result = prediction_df.iloc[0].to_dict()
        
        return {
            "status": "success",
            "input_evidence": data.model_dump(),
            "diagnosis": result

        }
        
    except Exception as e:
        raise HTTPException(status_code= 500, details= str(e))
    
    
@app.get("/")
async def root():
    return {"message": "Fault Diagnosis API is running."}