"""
Victim Server Monitor - PGM Correct Version

✔ Uses correct fault names
✔ Uses container CPU (not system CPU)
✔ Shows true observable nodes (NO overrides)
✔ Matches PGM architecture (Fault → Metrics → Inference later)
"""

import requests
import time
import os
import sys
from datetime import datetime

# CONFIG
SERVER_URL = "http://localhost:8000"
REFRESH_INTERVAL = 2
HEALTH_TIMEOUT = 10
METRICS_TIMEOUT = 5


# UTILS
def clear_screen():
    os.system('cls' if os.name == 'nt' else 'clear')


def get_color(value, thresholds):
    if value > thresholds[1]:
        return '\033[91m'
    elif value > thresholds[0]:
        return '\033[93m'
    return '\033[92m'


def print_header(text, color='\033[96m'):
    print(f"{color}{text}\033[0m")


def print_colored(text, color='\033[0m'):
    print(f"{color}{text}\033[0m")


def draw_bar(val, width=30):
    filled = int(width * val / 100)
    return '█' * filled + '░' * (width - filled)


# MAIN LOOP
def main():
    previous_fault = None

    while True:
        try:
            clear_screen()

            print_header("════════════════════════════════════════════════════════════════════")
            print_header("        PGM VICTIM SERVER MONITOR (FINAL CORRECT VERSION)")
            print_header("════════════════════════════════════════════════════════════════════")
            print(f"Time: {datetime.now().strftime('%H:%M:%S')}\n")

            # ---------------- HEALTH ----------------
            health = requests.get(f"{SERVER_URL}/health", timeout=HEALTH_TIMEOUT).json()
            m = health["metrics"]

            faults = health.get("faults_active", {})
            active_faults = [f for f, v in faults.items() if v]
            single_mode = health.get("single_fault_mode", False)
            buffer_active = health.get("buffer_active", False)

            # ---------------- MODE ----------------
            print_header("MODE", '\033[95m')
            if single_mode:
                print_colored("Single Fault Mode (PGM Training)", '\033[92m')
                if buffer_active:
                    print_colored("Buffer (healthy period)", '\033[93m')
            else:
                print_colored("Multi Fault Mode", '\033[96m')
            print()

            # ---------------- METRICS ----------------
            print_header("SYSTEM METRICS", '\033[93m')

            cpu = float(m.get("container_cpu_percent", 0))
            mem = float(m.get("memory_percent", 0))
            lat = float(m.get("avg_latency_ms", 0))
            err = float(m.get("error_rate_percent", 0))

            print(f"CPU:     {get_color(cpu,(40,80))}{cpu:5.1f}% {draw_bar(cpu)}\033[0m")
            print(f"Memory:  {get_color(mem,(40,70))}{mem:5.1f}% {draw_bar(mem)}\033[0m")
            print(f"Latency: {get_color(lat,(200,1000))}{lat:7.1f} ms\033[0m")
            print(f"Errors:  {get_color(err,(2,5))}{err:5.1f}%\033[0m")

            print()

            # ---------------- ACTIVE FAULTS ----------------
            print_header("ACTIVE FAULTS", '\033[93m')

            if faults.get("Compute_Overload"):
                print_colored("Compute_Overload (CPU + Latency)", '\033[91m')

            if faults.get("Memory_Leak"):
                print_colored("Memory_Leak (RAM + Latency)", '\033[91m')

            if faults.get("Network_Partition"):
                print_colored("Network_Partition (High Latency)", '\033[91m')

            if faults.get("App_Crash"):
                print_colored("App_Crash (Errors)", '\033[91m')

            if not active_faults:
                print_colored("No active faults (Healthy)", '\033[92m')

            print()

            # ---------------- PGM OBSERVABLES ----------------
            try:
                metrics = requests.get(f"{SERVER_URL}/api/metrics", timeout=METRICS_TIMEOUT).json()
                obs = metrics.get("observable_nodes", {})

                print_header("PGM OBSERVABLE NODES", '\033[93m')

                print(f"CPU_Usage:    {obs.get('CPU_Usage')}")
                print(f"RAM_Usage:    {obs.get('RAM_Usage')}")
                print(f"API_Latency:  {obs.get('API_Latency')}")
                print(f"Error_Rate:   {obs.get('Error_Rate')}")

            except:
                print("PGM metrics unavailable")

            print()

            # ---------------- FAULT TRANSITION ----------------
            if active_faults:
                current = active_faults[0]
                if current != previous_fault:
                    print_colored(f"Transition: {previous_fault} → {current}", '\033[96m')
                    previous_fault = current
            else:
                previous_fault = None

            print("\n────────────────────────────────────────────────────────────")
            print("Ctrl+C to stop | Refreshing...\n")

        except Exception as e:
            print(f"Error: {e}")

        time.sleep(REFRESH_INTERVAL)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nStopped.")
        sys.exit(0)

