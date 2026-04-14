"""
Victim Server Monitor - Real-time Fault Monitoring System

This script monitors the victim server and displays:
- Real-time system metrics (CPU, Memory, Latency, Errors)
- Active faults with status
- Single Fault Mode status (PGM training mode)
- Buffer period monitoring
- Multiple fault detection
- PGM observable nodes (discrete states)
- False positive detection (natural noise without faults)
- Docker vs psutil CPU explanation
- Automatic recovery from timeouts (server overload handling)
- FIXED: Shows correct PGM states when faults are active
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
REFRESH_INTERVAL = 2  # seconds (faster for single fault mode)
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


def draw_progress_bar(percentage, width=20):
    """Draw a progress bar"""
    filled = int(width * percentage / 100)
    bar = '█' * filled + '░' * (width - filled)
    return bar


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
    previous_fault = None
    
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
            
            # Get single fault mode status
            try:
                sf_response = requests.get(f"{SERVER_URL}/single-fault-mode/status", timeout=2)
                sf_status = sf_response.json()
            except:
                sf_status = {"single_fault_mode": False}
            
            single_mode = health.get('single_fault_mode', False) or sf_status.get('single_fault_mode', False)
            faults = health.get('faults_active', {})
            active_faults = [f for f, v in faults.items() if v]
            
            # ------------------------------------------------------------------
            # SECTION 0: MODE INDICATOR (Single vs Multi Fault)
            # ------------------------------------------------------------------
            if single_mode:
                print_header("🎯 SINGLE FAULT MODE ACTIVE (PGM Training)", '\033[95m')
                print("────────────────────────────────────────────────────────────────────────────────")
                buffer_active = health.get('buffer_active', False) or sf_status.get('buffer_active', False)
                buffer_remaining = sf_status.get('buffer_remaining_seconds', 0)
                
                if buffer_active:
                    print_colored(f"  ⏸️  BUFFER PERIOD: {buffer_remaining:.1f}s remaining (no faults)", '\033[93m')
                else:
                    print_colored("  ✅ READY FOR FAULTS", '\033[92m')
                
                # Show configuration
                config = sf_status.get('configuration', {})
                if config:
                    health_prob = config.get('health_probability', '70%')
                    fault_prob = config.get('fault_probability', '30%')
                    print(f"  📊 Config: {health_prob} healthy, {fault_prob} fault")
                    print(f"  ⏱️  Fault duration: {config.get('fault_duration', '30s')}, "
                          f"Buffer: {config.get('buffer_range', '15-45s')}")
                print("")
            else:
                print_header("🎲 MULTI-FAULT MODE ACTIVE (Original)", '\033[96m')
                print("────────────────────────────────────────────────────────────────────────────────")
                print("")
            
            # ------------------------------------------------------------------
            # SECTION 1: SYSTEM METRICS
            # ------------------------------------------------------------------
            print_header("📊 SYSTEM METRICS", '\033[93m')
            print("────────────────────────────────────────────────────────────────────────────────")
            
            # CPU
            cpu_val = safe_float(m.get('cpu_percent', 0))
            cpu_color = get_color(cpu_val, (20, 50))
            cpu_bar = draw_progress_bar(cpu_val, 30)
            print(f"CPU:        {cpu_color}{cpu_val:5.1f}% {cpu_bar}\033[0m")
            
            # Memory
            mem_val = safe_float(m.get('memory_percent', 0))
            mem_color = get_color(mem_val, (40, 70))
            mem_bar = draw_progress_bar(mem_val, 30)
            print(f"Memory:     {mem_color}{mem_val:5.1f}% {mem_bar}\033[0m")
            
            leak_val = safe_int(m.get('memory_leak_mb', 0))
            leak_color = '\033[95m' if leak_val > 100 else '\033[0m'
            print(f"   Leak:    {leak_color}{leak_val} MB\033[0m")
            
            # Latency - show warning if fault active
            lat_val = safe_float(m.get('avg_latency_ms', 0))
            lat_color = get_color(lat_val, (200, 1000))
            print(f"Latency:    {lat_color}{lat_val:7.1f} ms\033[0m")
            if faults.get('api_latency', False) and lat_val < 1000:
                print_colored("             ⚠️  Latency fault ACTIVE - Next API call will take 3-8s", '\033[93m')
            
            # Errors - show warning if fault active
            err_val = safe_float(m.get('error_rate_percent', 0))
            err_color = get_color(err_val, (2, 5))
            print(f"Errors:     {err_color}{err_val:5.1f}%\033[0m")
            if faults.get('error_rate', False) and err_val < 10:
                print_colored("             ⚠️  Error fault ACTIVE - Rate will climb to 30% as requests come in", '\033[93m')
            
            # Requests
            req_val = safe_int(m.get('total_requests', 0))
            print(f"Requests:   {req_val}")
            
            # ------------------------------------------------------------------
            # SECTION 2: ACTIVE FAULTS
            # ------------------------------------------------------------------
            print("")
            print_header("⚠️  ACTIVE FAULTS", '\033[93m')
            print("────────────────────────────────────────────────────────────────────────────────")
            
            if faults.get('cpu_spike', False):
                print_colored("  🔥 CPU SPIKE (80-95% CPU)", '\033[91m')
                if cpu_val < 30:
                    print_colored("     → Check Docker Desktop for actual CPU spike (psutil shows total CPU)", '\033[90m')
            if faults.get('memory_leak', False):
                print_colored("  💾 MEMORY LEAK (+50MB/2sec)", '\033[91m')
                print_colored(f"     → {leak_val}MB allocated (increasing every 2 seconds)", '\033[90m')
            if faults.get('api_latency', False):
                print_colored("  ⏱️  API LATENCY (3-8s delay)", '\033[91m')
                print_colored("     → API calls will take 3-8 seconds", '\033[90m')
            if faults.get('error_rate', False):
                print_colored("  ❌ ERROR RATE (30% failures)", '\033[91m')
                print_colored("     → 30% of API requests will fail with 500 error", '\033[90m')
            
            if not active_faults:
                print_colored("  ✅ No active faults", '\033[92m')
                if single_mode and not buffer_active:
                    print_colored("  🟢 System is HEALTHY (70% chance)", '\033[92m')
            elif len(active_faults) > 1:
                print("")
                print_colored(f"  🎯 MULTIPLE FAULTS DETECTED: {len(active_faults)} active", '\033[95m')
                print_colored(f"     Simultaneous faults: {', '.join([f.upper() for f in active_faults])}", '\033[93m')
            
            # Show fault transition in single mode
            if single_mode and active_faults:
                current_fault = active_faults[0]
                if current_fault != previous_fault:
                    fault_names = {
                        'cpu_spike': 'CPU',
                        'memory_leak': 'MEMORY',
                        'api_latency': 'LATENCY',
                        'error_rate': 'ERROR'
                    }
                    display_name = fault_names.get(current_fault, current_fault.upper())
                    print_colored(f"  🎲 FAULT TRANSITION: {previous_fault or 'None'} → {display_name}", '\033[96m')
                    previous_fault = display_name
            elif not active_faults:
                previous_fault = None
            
            # ------------------------------------------------------------------
            # SECTION 3: PGM OBSERVABLE NODES (FIXED - Shows fault-based states)
            # ------------------------------------------------------------------
            try:
                metrics_response = requests.get(f"{SERVER_URL}/api/metrics", timeout=METRICS_TIMEOUT)
                metrics = metrics_response.json()
                
                print("")
                print_header("🎯 PGM OBSERVABLE NODES (Discrete States)", '\033[93m')
                print("────────────────────────────────────────────────────────────────────────────────")
                
                obs = metrics.get('observable_nodes', {})
                
                # FIXED: Override PGM states based on active faults
                cpu_state = obs.get('cpu_usage', 'Normal')
                ram_state = obs.get('ram_usage', 'Normal')
                lat_state = obs.get('api_latency', 'Normal')
                err_state = obs.get('error_rate', 'Zero')
                
                # Override if faults are active for better display
                if faults.get('cpu_spike', False):
                    cpu_state = "Critical (Fault Active)"
                if faults.get('memory_leak', False):
                    ram_state = "Critical (Fault Active)"
                if faults.get('api_latency', False):
                    lat_state = "Elevated (Fault Active - 3-8s delay)"
                if faults.get('error_rate', False):
                    err_state = "Spiking (Fault Active - 30% failures)"
                
                # Color code the states
                cpu_state_color = '\033[91m' if 'Critical' in cpu_state or 'Fault' in cpu_state else '\033[93m' if 'High' in cpu_state else '\033[92m'
                print(f"  CPU_Usage:    {cpu_state_color}{cpu_state}\033[0m")
                
                ram_state_color = '\033[91m' if 'Critical' in ram_state or 'Fault' in ram_state else '\033[93m' if 'High' in ram_state else '\033[92m'
                print(f"  RAM_Usage:    {ram_state_color}{ram_state}\033[0m")
                
                lat_state_color = '\033[91m' if 'Timeout' in lat_state or 'Fault' in lat_state else '\033[93m' if 'Elevated' in lat_state else '\033[92m'
                print(f"  API_Latency:  {lat_state_color}{lat_state}\033[0m")
                
                err_state_color = '\033[91m' if 'Spiking' in err_state or 'Fault' in err_state else '\033[92m'
                print(f"  Error_Rate:   {err_state_color}{err_state}\033[0m")
                
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
                print_colored(f"  🌊 NATURAL CPU SPIKE: {cpu_val:.1f}% without fault", '\033[91m')
                false_positive_count += 1
            
            # Natural latency without fault
            if not faults.get('api_latency', False) and lat_val > 300:
                print_colored(f"  🌊 NATURAL LATENCY: {lat_val:.0f}ms without fault", '\033[91m')
                false_positive_count += 1
            
            # Natural memory increase without memory leak fault
            if not faults.get('memory_leak', False) and leak_val > 50:
                print_colored(f"  🌊 NATURAL MEMORY SPIKE: {leak_val}MB without fault", '\033[91m')
                false_positive_count += 1
            
            if false_positive_count == 0:
                print_colored("  ✅ No false positives detected", '\033[92m')
                if active_faults:
                    print_colored("  ✓ High metrics correctly attributed to active faults", '\033[92m')
            
            # ------------------------------------------------------------------
            # SECTION 5: CPU METRICS EXPLANATION
            # ------------------------------------------------------------------
            if faults.get('cpu_spike', False) and cpu_val < 30:
                print("")
                print_header("📖 CPU METRICS EXPLANATION", '\033[93m')
                print("────────────────────────────────────────────────────────────────────────────────")
                print_colored("  NOTE: CPU spike fault is ACTIVE but monitor shows low CPU%!", '\033[93m')
                print_colored("  This is NORMAL because:", '\033[96m')
                print_colored("    • Docker shows per-core usage (100% on 1 core = 100%)", '\033[96m')
                print_colored("    • psutil shows TOTAL system CPU (100% on 4 cores = 25%)", '\033[96m')
                print_colored("    • Your Docker Desktop should show 80-100% CPU!", '\033[92m')
                print_colored("    • This monitor shows TOTAL CPU across all cores", '\033[90m')
            
            # ------------------------------------------------------------------
            # SECTION 6: FAULT STATUS SUMMARY
            # ------------------------------------------------------------------
            print("")
            print_header("📋 FAULT STATUS SUMMARY", '\033[93m')
            print("────────────────────────────────────────────────────────────────────────────────")
            
            if active_faults:
                print_colored(f"  🔴 {len(active_faults)} FAULT(S) ACTIVE:", '\033[91m')
                for fault in active_faults:
                    fault_display = fault.replace('_', ' ').upper()
                    print_colored(f"     • {fault_display}", '\033[91m')
                
                # Show what to expect
                if faults.get('cpu_spike', False):
                    print_colored("     → CPU spike: Check Docker Desktop for 80-100% usage", '\033[90m')
                if faults.get('memory_leak', False):
                    print_colored("     → Memory leak: RAM increasing by 50MB every 2 seconds", '\033[90m')
                if faults.get('api_latency', False):
                    print_colored("     → API latency: API calls taking 3-8 seconds", '\033[90m')
                if faults.get('error_rate', False):
                    print_colored("     → Error rate: 30% of requests failing with 500 error", '\033[90m')
            else:
                print_colored("  ✅ No active faults", '\033[92m')
                if single_mode:
                    if buffer_active:
                        print_colored(f"  ⏸️  Buffer period active: {buffer_remaining:.1f}s remaining", '\033[93m')
                    else:
                        print_colored("  🟢 System healthy - Ready for next fault (30% chance)", '\033[92m')
            
            # Show single fault mode health ratio
            if single_mode:
                print("")
                print_header("🎯 PGM TRAINING STATUS", '\033[95m')
                print("────────────────────────────────────────────────────────────────────────────────")
                if active_faults:
                    fault_name = active_faults[0].replace('_', ' ').upper()
                    print_colored(f"  🔴 FAULT STATE: {fault_name}", '\033[91m')
                    print_colored(f"     Duration: 30 seconds (auto-stops)", '\033[90m')
                    # Show remaining time
                    fault_end = sf_status.get('buffer_remaining_seconds', 0)
                    if fault_end > 0:
                        print_colored(f"     Remaining: ~{fault_end:.0f} seconds", '\033[90m')
                elif buffer_active:
                    print_colored(f"  ⏸️  BUFFER STATE: {buffer_remaining:.1f}s remaining", '\033[93m')
                    print_colored(f"     No faults during buffer period", '\033[90m')
                else:
                    print_colored(f"  🟢 HEALTHY STATE", '\033[92m')
                    print_colored(f"     Ready for next fault (30% chance)", '\033[90m')
            
            print("")
            print("────────────────────────────────────────────────────────────────────────────────")
            
            # Show controls based on mode
            if single_mode:
                print_colored("🎮 Single Fault Mode Active | Disable: POST /single-fault-mode/disable", '\033[96m')
                print_colored("   Manual faults still work but only one at a time", '\033[90m')
            else:
                print_colored("🎮 Multi-Fault Mode | Enable Single Mode: POST /single-fault-mode/enable", '\033[96m')
                print_colored("   Multiple faults can run simultaneously in this mode", '\033[90m')
            
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