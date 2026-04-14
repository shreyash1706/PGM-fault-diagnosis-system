import time
import requests
import json
from sklearn.metrics import accuracy_score, precision_score, recall_score, f1_score

VICTIM_METRICS_URL = "http://localhost:8000/api/metrics"
DIAGNOSIS_API_URL = "http://localhost:8001/diagnose"

# Map the raw boolean flags from app.py to the string outputs of main.py's ML model
FAULT_MAPPING = {
    "cpu_spike": "Compute_Overload",
    "memory_leak": "Memory_Leak", 
    "api_latency": "Network_Partition", 
    "error_rate": "App_Crash"
}

def evaluate_system(iterations=20, sleep_delay=3):
    print(f"Starting System Accuracy Evaluation ({iterations} iterations)...\nThis will take {iterations * sleep_delay} seconds. Please wait...\n")
    
    y_true = []
    y_pred = []

    for i in range(iterations):
        try:
            # 1. Grab Ground Truth & Symptoms from Victim Server
            resp = requests.get(VICTIM_METRICS_URL)
            if resp.status_code != 200:
                print("Failed to reach Victim Server.")
                continue
                
            payload = resp.json()
            ground_truth_dict = payload.get("faults_active", {})
            symptoms = payload.get("observable_nodes", {})
            
            # Format ground truth: Which faults are actually True right now?
            true_faults = {FAULT_MAPPING[k]: 1 for k, v in ground_truth_dict.items() if v}
            
            # Map lowercase `/api/metrics` symptom keys to Capitalized Pydantic models
            formatted_symptoms = {
                "CPU_Usage": symptoms.get("cpu_usage", "Normal").capitalize(),
                "RAM_Usage": symptoms.get("ram_usage", "Normal").capitalize(),
                "API_Latency": symptoms.get("api_latency", "Normal").capitalize(),
                "Error_Rate": symptoms.get("error_rate", "Zero").capitalize()
            }
            
            # 2. Get Bayesian Network Prediction
            diag_resp = requests.post(DIAGNOSIS_API_URL, json=formatted_symptoms)
            if diag_resp.status_code != 200:
                print(f"Diagnostic API returned error {diag_resp.status_code}: {diag_resp.text}")
                continue
                
            predicted_faults = diag_resp.json().get("diagnoses", {})
            
            # Filter the ML predictions: Keep only the actual root-cause faults that are > 0.5
            latent_nodes = {"Compute_Overload", "Memory_Leak", "Network_Partition", "App_Crash"}
            active_predictions = [k for k, v in predicted_faults.items() if k in latent_nodes and v > 0.5]
            
            # We want to measure exact-match accuracy. 
            true_str = str(sorted(true_faults.keys()))
            pred_str = str(sorted(active_predictions))
            
            y_true.append(true_str)
            y_pred.append(pred_str)
            
            # Status emoji
            match = "✅" if true_str == pred_str else "❌"
            print(f"[{i+1}/{iterations}] {match} | TRUE: {true_str:<40} | ML_PREDICTED: {pred_str}")
            if match == "❌":
                print(f"      ↳ SYMPTOMS VISIBLE TO ML: {formatted_symptoms}")
            time.sleep(sleep_delay)
            
        except Exception as e:
            print(f"Error during eval: {e}")
            time.sleep(sleep_delay)

    # Calculate metrics
    if len(y_true) > 0:
        print("\n" + "="*60)
        print("          📊 FINAL DIAGNOSIS ACCURACY REPORT")
        print("="*60)
        
        acc = accuracy_score(y_true, y_pred)
        # Using macro precision/recall because classification classes are combinations of strings
        prec = precision_score(y_true, y_pred, average='macro', zero_division=0)
        rec = recall_score(y_true, y_pred, average='macro', zero_division=0)
        
        print(f"Global Accuracy:  {acc*100:6.2f}%")
        print(f"Macro Precision:  {prec*100:6.2f}%")
        print(f"Macro Recall:     {rec*100:6.2f}%")
        print("="*60)
        print("\nNote: Accuracy measures how often the Bayesian graph perfectly deduced\nthe exact underlying fault combination based only on the vague telemetry symptoms.")

if __name__ == "__main__":
    import warnings
    warnings.filterwarnings('ignore') # Suppress sklearn zero_division warnings
    evaluate_system()
