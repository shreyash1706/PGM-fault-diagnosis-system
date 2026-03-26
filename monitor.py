import requests
import time
import os
from datetime import datetime

def clear_screen():
    os.system('cls' if os.name == 'nt' else 'clear')

def get_color(value, thresholds):
    if value > thresholds[1]:
        return '\033[91m'  # Red
    elif value > thresholds[0]:
        return '\033[93m'  # Yellow
    else:
        return '\033[92m'  # Green

def print_colored(text, color_code):
    print(f"{color_code}{text}\033[0m")

while True:
    try:
        clear_screen()
        print("\033[96m╔════════════════════════════════════════════════════════════╗\033[0m")
        print("\033[96m║         VICTIM SERVER - REAL-TIME FAULT MONITOR            ║\033[0m")
        print("\033[96m╚════════════════════════════════════════════════════════════╝\033[0m")
        print(f"Time: {datetime.now().strftime('%H:%M:%S')}")
        print("")
        
        # Get health data
        health = requests.get("http://localhost:8000/health", timeout=2).json()
        m = health['metrics']
        
        # System Metrics
        print("\033[93m📊 SYSTEM METRICS\033[0m")
        print("────────────────────────────────────────────────")
        
        cpu_color = get_color(m['cpu_percent'], (20, 50))
        print(f"🔥 CPU:     {cpu_color}{m['cpu_percent']}%\033[0m")
        
        mem_color = get_color(m['memory_percent'], (40, 70))
        print(f"📀 Memory:  {mem_color}{m['memory_percent']}%\033[0m")
        print(f"   Leak:    \033[95m{m['memory_leak_mb']}MB\033[0m")
        
        lat_color = get_color(m['avg_latency_ms'], (200, 1000))
        print(f"⏱️ Latency: {lat_color}{m['avg_latency_ms']}ms\033[0m")
        
        err_color = get_color(m['error_rate_percent'], (2, 5))
        print(f"❌ Errors:  {err_color}{m['error_rate_percent']}%\033[0m")
        
        print(f"📝 Requests: \033[96m{m['total_requests']}\033[0m")
        
        # Active Faults
        print("")
        print("\033[93m⚠️ ACTIVE FAULTS\033[0m")
        print("────────────────────────────────────────────────")
        
        faults = health['faults_active']
        active = []
        
        if faults['cpu_spike']:
            print("  \033[91m🔥 CPU SPIKE\033[0m")
            active.append('CPU')
        if faults['memory_leak']:
            print("  \033[91m🧠 MEMORY LEAK\033[0m")
            active.append('MEM')
        if faults['api_latency']:
            print("  \033[91m🐌 API LATENCY\033[0m")
            active.append('LAT')
        if faults['error_rate']:
            print("  \033[91m💥 ERROR RATE\033[0m")
            active.append('ERR')
        
        if not active:
            print("  \033[92mNo active faults\033[0m")
        elif len(active) > 1:
            print("")
            print(f"  \033[95m🎯 MULTIPLE FAULTS DETECTED: {len(active)} active\033[0m")
        
        # PGM Metrics
        try:
            metrics = requests.get("http://localhost:8000/api/metrics", timeout=2).json()
            print("")
            print("\033[93m🎯 PGM OBSERVABLE NODES\033[0m")
            print("────────────────────────────────────────────────")
            obs = metrics['observable_nodes']
            print(f"  CPU_Usage:    {obs['cpu_usage']}")
            print(f"  RAM_Usage:    {obs['ram_usage']}")
            print(f"  API_Latency:  {obs['api_latency']}")
            print(f"  Error_Rate:   {obs['error_rate']}")
        except:
            pass
        
        # False Positives
        print("")
        print("\033[93m⚠️ FALSE POSITIVE CHECK\033[0m")
        print("────────────────────────────────────────────────")
        
        if not faults['cpu_spike'] and m['cpu_percent'] > 20:
            print(f"  \033[91m🌊 NATURAL CPU SPIKE: {m['cpu_percent']}% without fault\033[0m")
        if not faults['api_latency'] and m['avg_latency_ms'] > 300:
            print(f"  \033[91m🌊 NATURAL LATENCY: {m['avg_latency_ms']}ms without fault\033[0m")
        
        print("")
        print("────────────────────────────────────────────────")
        print("Press Ctrl+C to stop | Refreshing in 3 seconds...")
        
    except Exception as e:
        print("\033[91m❌ Error: Server not responding!\033[0m")
        print("   Make sure server is running at http://localhost:8000")
    
    time.sleep(3)