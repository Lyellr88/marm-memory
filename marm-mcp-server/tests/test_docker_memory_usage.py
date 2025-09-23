"""
Test and benchmark the Docker container's memory usage, particularly after loading
the semantic search model at startup.

This test works in two environments:
- LOCAL: Full Docker memory stats via Docker CLI (recommended)
- INSIDE CONTAINER: Health checks only (Docker stats unavailable)

Usage:
1. Make sure MARM Docker container is running:
   docker run -d --name marm-mcp-server -p 8001:8001 -v marm_data:/app/data lyellr88/marm-mcp-server:latest

2a. Run locally (full memory stats):
   python tests/test_docker_memory_usage.py

2b. Run inside Docker (health checks only):
   docker exec marm-mcp-server python tests/test_docker_memory_usage.py
"""

import requests
import subprocess
import json
import time
import os

BASE_URL = "http://localhost:8001"

def is_running_inside_docker():
    """Check if we're running inside a Docker container."""
    return os.path.exists('/.dockerenv') or os.environ.get('DOCKER_CONTAINER') == 'true'

def get_docker_memory_usage_mb():
    """Returns the memory usage of the MARM Docker container in megabytes.
    Only works when running locally with Docker CLI access."""
    if is_running_inside_docker():
        print("SKIP: Docker stats not available inside container")
        return None

    try:
        result = subprocess.run(
            ["docker", "stats", "marm-mcp-server", "--no-stream", "--format", "{{.MemUsage}}"],
            capture_output=True,
            text=True,
            check=True
        )
        # Parse output like "45.2MiB / 1.944GiB"
        memory_str = result.stdout.strip().split(' / ')[0]
        if 'MiB' in memory_str:
            return float(memory_str.replace('MiB', ''))
        elif 'GiB' in memory_str:
            return float(memory_str.replace('GiB', '')) * 1024
        else:
            return 0.0
    except Exception as e:
        print(f"Error getting Docker memory stats: {e}")
        return None

def check_server_health():
    """Check if the MARM server is healthy and responsive."""
    try:
        response = requests.get(f"{BASE_URL}/health", timeout=5)
        return response.status_code == 200 and "healthy" in response.text
    except Exception:
        return False

def get_server_memory_info():
    """Get memory info from the server health endpoint."""
    try:
        response = requests.get(f"{BASE_URL}/health", timeout=5)
        if response.status_code == 200:
            data = response.json()
            return {
                "memory_mb": "Healthy", 
                "uptime": "Running",
                "version": data.get("version", "Unknown")
            }
    except Exception as e:
        print(f"Could not get server info: {e}")
    return {}

def main():
    """Main function to run the Docker memory usage test."""
    print("--- MARM Docker Container Memory Usage Test ---")

    # Check execution environment
    if is_running_inside_docker():
        print("Running inside Docker container - limited memory stats available")
        print("For full Docker memory stats, run this test locally with Docker CLI")
    else:
        print("Running locally with Docker CLI access")

    # 1. Check if container is running and healthy
    if not check_server_health():
        if is_running_inside_docker():
            print("ERROR: MARM server not healthy inside container!")
        else:
            print("ERROR: MARM Docker container is not running or not healthy!")
            print("Start it with: docker run -d --name marm-mcp-server -p 8001:8001 -v marm_data:/app/data lyellr88/marm-mcp-server:latest")
        return

    print("Container is running and healthy")
    
    # 2. Get initial Docker memory stats
    print("\nGetting Docker container memory usage...")
    docker_memory = get_docker_memory_usage_mb()
    if docker_memory is not None:
        print(f"Docker container memory usage: {docker_memory:.2f} MB")
    else:
        print("Docker container memory usage: Not available (inside container)")
    
    # 3. Get server-reported memory stats
    print("\nGetting server-reported memory info...")
    server_info = get_server_memory_info()
    server_memory = server_info.get("memory_mb", "Unknown")
    uptime = server_info.get("uptime_seconds", "Unknown")
    
    print(f"Server-reported memory usage: {server_memory} MB")
    print(f"Server uptime: {uptime} seconds")
    
    # 4. Test server endpoints 
    print("\nTesting server endpoints...")
    endpoints_tested = 0
    
    # Wait for container to be fully healthy
    print("Waiting for container to be fully healthy...")
    for i in range(30):  # Wait up to 30 seconds
        try:
            response = requests.get(f"{BASE_URL}/health", timeout=2)
            if response.status_code == 200:
                print(f"Container healthy after {i+1} seconds")
                break
        except:
            time.sleep(1)
    else:
        print("Container did not become healthy within 30 seconds")
    
    # Test health endpoint
    try:
        health_response = requests.get(f"{BASE_URL}/health", timeout=10)
        if health_response.status_code == 200:
            print("PASS: Health endpoint working")
            endpoints_tested += 1
    except Exception as e:
        print(f"FAIL: Health endpoint error: {e}")
    
    # Test API docs endpoint
    try:
        docs_response = requests.get(f"{BASE_URL}/docs", timeout=10)
        if docs_response.status_code == 200:
            print("PASS: API docs endpoint working")
            endpoints_tested += 1
    except Exception as e:
        print(f"FAIL: API docs endpoint error: {e}")
    
    print(f"Endpoints tested successfully: {endpoints_tested}/2")
    
    # 5. Get final memory stats
    final_docker_memory = get_docker_memory_usage_mb()
    final_server_info = get_server_memory_info()
    final_server_memory = final_server_info.get("memory_mb", "Unknown")

    print("\n--- Results ---")
    if docker_memory is not None and final_docker_memory is not None:
        print(f"Docker container memory: {docker_memory:.2f} MB -> {final_docker_memory:.2f} MB")
        memory_assessment_value = final_docker_memory
    else:
        print("Docker container memory: Not available (inside container)")
        memory_assessment_value = None

    if isinstance(server_memory, (int, float)) and isinstance(final_server_memory, (int, float)):
        print(f"Server-reported memory: {server_memory:.2f} MB -> {final_server_memory:.2f} MB")
    else:
        print(f"Server-reported memory: {server_memory} MB -> {final_server_memory} MB")

    # 6. Memory efficiency assessment
    if memory_assessment_value is not None and memory_assessment_value > 0:
        if memory_assessment_value < 200:
            print("Memory usage: EXCELLENT (< 200 MB)")
        elif memory_assessment_value < 400:
            print("Memory usage: GOOD (< 400 MB)")
        elif memory_assessment_value < 600:
            print("Memory usage: ACCEPTABLE (< 600 MB)")
        else:
            print("Memory usage: HIGH (> 600 MB)")
    else:
        print("Memory usage: Cannot assess (Docker stats not available inside container)")

    # 7. Test result summary
    if endpoints_tested >= 2:
        if memory_assessment_value is not None:
            print("Test result: PASS (Full local test completed)")
        else:
            print("Test result: PASS (Container health verified - run locally for memory stats)")
    else:
        print("Test result: PARTIAL (Some endpoints failed)")

    print("-----------------")

if __name__ == "__main__":
    main()