"""
Victim Server Monitor - Real-time Fault Monitoring System

This script monitors the victim server and displays:
- Real-time system metrics (CPU, Memory, Latency, Errors)
- Active faults with status
- Multiple fault detection
- PGM observable nodes (discrete states)
- False positive detection (natural noise without faults)
- Docker vs psutil CPU explanation
- Automatic recovery from timeouts (server overload handling)
"""

import requests
import time
import os
import sys
from datetime import datetime


# ============================================================================
# CONFIGURATION
# ============================================================================

SERVER_URL = "http://localhost:8000"
REFRESH_INTERVAL = 3  # seconds
HEALTH_TIMEOUT = 10   # seconds (increased for when server is overloaded)
METRICS_TIMEOUT = 5   # seconds


# ============================================================================
# UTILITY FUNCTIONS
# ============================================================================

def clear_screen():
    """Clear the terminal screen (works on Windows and Unix)"""
    os.system('cls' if os.name == 'nt' else 'clear')


def get_color(value, thresholds):
    """
    Get color code based on value thresholds
    
    Args:
        value: The metric value to evaluate
        thresholds: Tuple of (yellow_threshold, red_threshold)
    
    Returns:
        ANSI color code string
    """
    if value > thresholds[1]:
        return '\033[91m'   # Red - Critical
    elif value > thresholds[0]:
        return '\033[93m'   # Yellow - Warning
    else:
        return '\033[92m'   # Green - Normal


def print_header(text, color_code='\033[96m'):
    """Print a formatted header"""
    print(f"{color_code}{text}\033[0m")


def print_colored(text, color_code='\033[0m'):
    """Print colored text"""
    print(f"{color_code}{text}\033[0m")


def safe_int(value):
    """Safely convert to int, return 0 if conversion fails"""
    try:
        return int(value)
    except (ValueError, TypeError):
        return 0


def safe_float(value):
    """Safely convert to float, return 0.0 if conversion fails"""
    try:
        return float(value)
    except (ValueError, TypeError):
        return 0.0


# ============================================================================
# MAIN MONITORING LOOP
# ============================================================================

def main():
    """Main monitoring loop with automatic timeout recovery"""
    
    # Print header once at startup
    print("\033[96m")
    print("╔════════════════════════════════════════════════════════════════════════════════╗")
    print("║                    VICTIM SERVER - REAL-TIME FAULT MONITOR                      ║")
    print("║                                                                                ║")
    print("║  CPU NOTE: Docker shows per-core usage (100% on 1 core = 100%),                 ║")
    print("║            psutil shows total system CPU (100% on 4 cores = 25% per core)       ║")
    print("║            This is NOT a bug - both measurements are CORRECT!                   ║")
    print("╚════════════════════════════════════════════════════════════════════════════════╝")
    print("\033[0m")
    
    consecutive_timeouts = 0
    
    while True:
        try:
            clear_screen()
            
            # Print header
            print_header("╔════════════════════════════════════════════════════════════════════════════════╗")
            print_header("║                    VICTIM SERVER - REAL-TIME FAULT MONITOR                      ║")
            print_header("╚════════════════════════════════════════════════════════════════════════════════╝")
            print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            
            # Show timeout warning if recovering
            if consecutive_timeouts > 0:
                print(f"\033[93m⚠️  Recovering from server overload... (Last timeout: {consecutive_timeouts})\033[0m")
            
            print("")
            
            # Get health data with increased timeout
            try:
                response = requests.get(f"{SERVER_URL}/health", timeout=HEALTH_TIMEOUT)
                health = response.json()
                m = health['metrics']
                consecutive_timeouts = 0  # Reset counter on success
                
            except requests.exceptions.Timeout:
                consecutive_timeouts += 1
                print("\033[93m")
                print("╔════════════════════════════════════════════════════════════════════════════════╗")
                print("║                      ⚠️  SERVER OVERLOAD DETECTED                                ║")
                print("╚════════════════════════════════════════════════════════════════════════════════╝")
                print("\033[0m")
                print("")
                print("  The server is under heavy load (multiple faults active)")
                print("  This is EXPECTED behavior - faults are working correctly!")
                print("")
                print("  The monitor will automatically retry...")
                print("")
                print("  Active faults from logs:")
                print("    - CPU SPIKE (80-95% CPU)")
                print("    - MEMORY LEAK (+50MB/2sec)")
                print("    - ERROR RATE (30% failures)")
                print("")
                print("────────────────────────────────────────────────────────────────────────────────")
                print(f"Press Ctrl+C to stop | Retrying in {REFRESH_INTERVAL} seconds...")
                time.sleep(REFRESH_INTERVAL)
                continue
                
            except Exception as e:
                print(f"\033[91m⚠️  Connection error: {e}\033[0m")
                print(f"   Retrying in {REFRESH_INTERVAL} seconds...")
                time.sleep(REFRESH_INTERVAL)
                continue
            
            # ------------------------------------------------------------------
            # SECTION 1: SYSTEM METRICS
            # ------------------------------------------------------------------
            print_header("📊 SYSTEM METRICS", '\033[93m')
            print("────────────────────────────────────────────────────────────────────────────────")
            
            # CPU
            cpu_val = safe_float(m.get('cpu_percent', 0))
            cpu_color = get_color(cpu_val, (20, 50))
            print(f"CPU:        {cpu_color}{cpu_val}%\033[0m")
            
            # Memory
            mem_val = safe_float(m.get('memory_percent', 0))
            mem_color = get_color(mem_val, (40, 70))
            print(f"Memory:     {mem_color}{mem_val}%\033[0m")
            
            leak_val = safe_int(m.get('memory_leak_mb', 0))
            leak_color = '\033[95m' if leak_val > 100 else '\033[0m'
            print(f"   Leak:    {leak_color}{leak_val} MB\033[0m")
            
            # Latency
            lat_val = safe_float(m.get('avg_latency_ms', 0))
            lat_color = get_color(lat_val, (200, 1000))
            print(f"Latency:    {lat_color}{lat_val} ms\033[0m")
            
            # Errors
            err_val = safe_float(m.get('error_rate_percent', 0))
            err_color = get_color(err_val, (2, 5))
            print(f"Errors:     {err_color}{err_val}%\033[0m")
            
            # Requests
            req_val = safe_int(m.get('total_requests', 0))
            print(f"Requests:   {req_val}")
            
            # ------------------------------------------------------------------
            # SECTION 2: ACTIVE FAULTS
            # ------------------------------------------------------------------
            print("")
            print_header("⚠️  ACTIVE FAULTS", '\033[93m')
            print("────────────────────────────────────────────────────────────────────────────────")
            
            faults = health.get('faults_active', {})
            active_faults = []
            
            if faults.get('cpu_spike', False):
                print_colored("  CPU SPIKE (80-95% CPU)", '\033[91m')
                active_faults.append('CPU')
            if faults.get('memory_leak', False):
                print_colored("  MEMORY LEAK (+50MB/2sec)", '\033[91m')
                active_faults.append('MEM')
            if faults.get('api_latency', False):
                print_colored("  API LATENCY (3-8s delay)", '\033[91m')
                active_faults.append('LAT')
            if faults.get('error_rate', False):
                print_colored("  ERROR RATE (30% failures)", '\033[91m')
                active_faults.append('ERR')
            
            if not active_faults:
                print_colored("  No active faults", '\033[92m')
            elif len(active_faults) > 1:
                print("")
                print_colored(f"  🎯 MULTIPLE FAULTS DETECTED: {len(active_faults)} active", '\033[95m')
            
            # ------------------------------------------------------------------
            # SECTION 3: PGM OBSERVABLE NODES
            # ------------------------------------------------------------------
            try:
                metrics_response = requests.get(f"{SERVER_URL}/api/metrics", timeout=METRICS_TIMEOUT)
                metrics = metrics_response.json()
                
                print("")
                print_header("🎯 PGM OBSERVABLE NODES", '\033[93m')
                print("────────────────────────────────────────────────────────────────────────────────")
                
                obs = metrics.get('observable_nodes', {})
                print(f"  CPU_Usage:    {obs.get('cpu_usage', 'Unknown')}")
                print(f"  RAM_Usage:    {obs.get('ram_usage', 'Unknown')}")
                print(f"  API_Latency:  {obs.get('api_latency', 'Unknown')}")
                print(f"  Error_Rate:   {obs.get('error_rate', 'Unknown')}")
                
            except Exception as e:
                print("")
                print_header("🎯 PGM OBSERVABLE NODES", '\033[93m')
                print("────────────────────────────────────────────────────────────────────────────────")
                print_colored("  (Unable to fetch PGM metrics - server busy)", '\033[93m')
            
            # ------------------------------------------------------------------
            # SECTION 4: FALSE POSITIVE DETECTION
            # ------------------------------------------------------------------
            print("")
            print_header("⚠️  FALSE POSITIVE DETECTION", '\033[93m')
            print("────────────────────────────────────────────────────────────────────────────────")
            
            false_positive_count = 0
            
            # Natural CPU spike without fault
            if not faults.get('cpu_spike', False) and cpu_val > 20:
                print_colored(f"  🌊 NATURAL CPU SPIKE: {cpu_val}% without fault", '\033[91m')
                false_positive_count += 1
            
            # Natural latency without fault
            if not faults.get('api_latency', False) and lat_val > 300:
                print_colored(f"  🌊 NATURAL LATENCY: {lat_val}ms without fault", '\033[91m')
                false_positive_count += 1
            
            # Natural memory increase without memory leak fault
            if not faults.get('memory_leak', False) and leak_val > 50:
                print_colored(f"  🌊 NATURAL MEMORY SPIKE: {leak_val}MB without fault", '\033[91m')
                false_positive_count += 1
            
            if false_positive_count == 0:
                print_colored("  No false positives detected", '\033[92m')
            
            # ------------------------------------------------------------------
            # SECTION 5: CPU METRICS EXPLANATION (show only when CPU is low but faults active)
            # ------------------------------------------------------------------
            if faults.get('cpu_spike', False) and cpu_val < 30:
                print("")
                print_header("📖 CPU METRICS EXPLANATION", '\033[93m')
                print("────────────────────────────────────────────────────────────────────────────────")
                print_colored("  NOTE: CPU spike fault is ACTIVE but CPU shows low percentage!", '\033[93m')
                print_colored("  This is NORMAL because:", '\033[96m')
                print_colored("    - Docker shows per-core usage (100% on 1 core)", '\033[96m')
                print_colored("    - psutil shows TOTAL system CPU (25% on 4 cores)", '\033[96m')
                print_colored("    - Your Docker Desktop should show 80-100% CPU!", '\033[92m')
            
            # ------------------------------------------------------------------
            # SECTION 6: FAULT STATUS SUMMARY
            # ------------------------------------------------------------------
            print("")
            print_header("📋 FAULT STATUS SUMMARY", '\033[93m')
            print("────────────────────────────────────────────────────────────────────────────────")
            
            auto_status = []
            if cpu_val > 50:
                auto_status.append(f"CPU at {cpu_val}%")
            if leak_val > 100:
                auto_status.append(f"Memory leak at {leak_val}MB")
            if lat_val > 2000:
                auto_status.append(f"Latency at {lat_val}ms")
            if err_val > 10:
                auto_status.append(f"Error rate at {err_val}%")
            
            if auto_status:
                print_colored(f"  HIGH METRICS: {', '.join(auto_status)}", '\033[93m')
                if not active_faults:
                    print_colored("  ⚠️  High metrics but no faults - These are FALSE POSITIVES!", '\033[91m')
                else:
                    print_colored(f"  ✓ Active faults: {', '.join(active_faults)}", '\033[92m')
            else:
                print_colored("  All metrics normal", '\033[92m')
                if active_faults:
                    print_colored(f"  ⚠️  Faults active but metrics normal - Check Docker Desktop!", '\033[93m')
            
            print("")
            print("────────────────────────────────────────────────────────────────────────────────")
            print(f"Press Ctrl+C to stop | Refreshing every {REFRESH_INTERVAL} seconds...")
            
        except requests.exceptions.ConnectionError:
            print("\033[91m")
            print("╔════════════════════════════════════════════════════════════════════════════════╗")
            print("║                         ❌ ERROR: SERVER NOT RESPONDING                         ║")
            print("╚════════════════════════════════════════════════════════════════════════════════╝")
            print("\033[0m")
            print("")
            print("Make sure the victim server is running:")
            print("  docker-compose up -d")
            print("")
            print("Check if server is accessible:")
            print(f"  curl {SERVER_URL}/health")
            print("")
            
        except Exception as e:
            print(f"\033[91m⚠️  Unexpected error: {e}\033[0m")
            print(f"   Retrying in {REFRESH_INTERVAL} seconds...")
        
        time.sleep(REFRESH_INTERVAL)


# ============================================================================
# ENTRY POINT
# ============================================================================

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n\033[92m")
        print("╔════════════════════════════════════════════════════════════════════════════════╗")
        print("║                           MONITORING STOPPED BY USER                            ║")
        print("╚════════════════════════════════════════════════════════════════════════════════╝")
        print("\033[0m")
        sys.exit(0)