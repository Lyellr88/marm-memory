"""
Integration tests for MARM Docker Container
Tests complete workflows using the actual production Docker container.

Usage:
1. Make sure MARM Docker container is running:
   docker run -d --name marm-mcp-server -p 8001:8001 -v marm_data:/app/data lyellr88/marm-mcp-server:latest
2. Run the script:
   python tests/test_docker_integration.py
"""

import requests
import time
import json

BASE_URL = "http://localhost:8001"

def check_server_health():
    """Check if the MARM server is healthy and responsive."""
    try:
        response = requests.get(f"{BASE_URL}/health", timeout=5)
        return response.status_code == 200 and "healthy" in response.text
    except Exception:
        return False

def test_basic_endpoints():
    """Test all basic endpoints are working"""
    print("Testing basic endpoints...")
    
    endpoints = [
        ("GET", "/health", "Health check endpoint"),
        ("GET", "/docs", "API documentation endpoint"), 
    ]
    
    results = []
    
    for method, endpoint, description in endpoints:
        try:
            if method == "GET":
                response = requests.get(f"{BASE_URL}{endpoint}", timeout=10)
            else:
                response = requests.post(f"{BASE_URL}{endpoint}", timeout=10)
            
            success = response.status_code in [200, 201]
            results.append({
                'endpoint': endpoint,
                'description': description,
                'status': response.status_code,
                'success': success
            })
            
            if success:
                print(f"  PASS: {description} ({endpoint}) - {response.status_code}")
            else:
                print(f"  FAIL: {description} ({endpoint}) - {response.status_code}")
                
        except Exception as e:
            results.append({
                'endpoint': endpoint,
                'description': description,
                'status': 0,
                'success': False,
                'error': str(e)
            })
            print(f"  ERROR: {description} ({endpoint}) - {e}")
    
    return results

def test_server_health_details():
    """Test server health endpoint provides detailed information"""
    print("\nTesting detailed health information...")
    
    try:
        response = requests.get(f"{BASE_URL}/health", timeout=5)
        
        if response.status_code == 200:
            try:
                data = response.json()
                
                print(f"  Server Status: {data.get('status', 'Unknown')}")
                print(f"  Version: {data.get('version', 'Unknown')}")
                print(f"  Service: {data.get('service', 'Unknown')}")
                
                if 'timestamp' in data:
                    print(f"  Last Response: {data['timestamp']}")
                
                # Check for expected health indicators
                health_score = 0
                if data.get('status') == 'healthy':
                    health_score += 40
                if 'version' in data:
                    health_score += 30
                if 'timestamp' in data:
                    health_score += 30
                
                print(f"  Health Score: {health_score}/100")
                
                if health_score >= 90:
                    print(f"  EXCELLENT: Full health information available")
                elif health_score >= 70:
                    print(f"  GOOD: Most health information available")
                else:
                    print(f"  BASIC: Minimal health information")
                
                return {'success': True, 'score': health_score, 'data': data}
                
            except json.JSONDecodeError:
                print(f"  WARNING: Health endpoint returned non-JSON response")
                return {'success': True, 'score': 50, 'data': {}}
        else:
            print(f"  FAIL: Health endpoint returned {response.status_code}")
            return {'success': False, 'score': 0}
            
    except Exception as e:
        print(f"  ERROR: Could not reach health endpoint: {e}")
        return {'success': False, 'score': 0}

def test_concurrent_health_checks():
    """Test server handles concurrent health checks"""
    print("\nTesting concurrent health checks...")
    
    import threading
    import concurrent.futures
    
    def health_check(request_id):
        try:
            start_time = time.time()
            response = requests.get(f"{BASE_URL}/health", timeout=5)
            duration = time.time() - start_time
            
            return {
                'id': request_id,
                'success': response.status_code == 200,
                'duration': duration,
                'status': response.status_code
            }
        except Exception as e:
            return {
                'id': request_id,
                'success': False,
                'duration': 5.0,
                'error': str(e)
            }
    
    # Run 15 concurrent health checks
    num_requests = 15
    print(f"  Running {num_requests} concurrent health checks...")
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=num_requests) as executor:
        start_time = time.time()
        futures = [executor.submit(health_check, i) for i in range(num_requests)]
        results = [future.result() for future in concurrent.futures.as_completed(futures)]
        total_time = time.time() - start_time
    
    successful = sum(1 for r in results if r['success'])
    avg_duration = sum(r['duration'] for r in results) / len(results)
    
    print(f"  Results: {successful}/{num_requests} successful")
    print(f"  Total time: {total_time:.3f}s")
    print(f"  Average response time: {avg_duration:.3f}s")
    
    success_rate = successful / num_requests * 100
    
    if success_rate == 100 and avg_duration < 1.0:
        print(f"  EXCELLENT: Perfect concurrent handling")
    elif success_rate >= 90 and avg_duration < 2.0:
        print(f"  GOOD: Strong concurrent handling")
    elif success_rate >= 80:
        print(f"  ACCEPTABLE: Basic concurrent handling")
    else:
        print(f"  POOR: Concurrent handling issues")
    
    return {
        'total_requests': num_requests,
        'successful': successful,
        'success_rate': success_rate,
        'total_time': total_time,
        'avg_duration': avg_duration
    }

def test_error_handling():
    """Test server error handling with invalid requests"""
    print("\nTesting error handling...")
    
    # Test various invalid requests
    invalid_tests = [
        ("GET", "/nonexistent", "Non-existent endpoint"),
        ("POST", "/health", "POST to GET-only endpoint"),
        ("GET", "/mcp", "MCP endpoint without proper headers"),
    ]
    
    error_handling_score = 0
    
    for method, endpoint, description in invalid_tests:
        try:
            if method == "GET":
                response = requests.get(f"{BASE_URL}{endpoint}", timeout=5)
            else:
                response = requests.post(f"{BASE_URL}{endpoint}", timeout=5)
            
            # Check if server handles errors gracefully (4xx or 5xx)
            if 400 <= response.status_code < 600:
                print(f"  PASS: {description} - Proper error response ({response.status_code})")
                error_handling_score += 1
            elif response.status_code == 200:
                print(f"  WARNING: {description} - Unexpected success")
            else:
                print(f"  UNEXPECTED: {description} - Status {response.status_code}")
                
        except requests.exceptions.Timeout:
            print(f"  TIMEOUT: {description} - Server took too long")
        except Exception as e:
            print(f"  ERROR: {description} - {e}")
    
    total_tests = len(invalid_tests)
    error_score = (error_handling_score / total_tests) * 100
    
    print(f"  Error Handling Score: {error_score:.1f}% ({error_handling_score}/{total_tests})")
    
    return {'score': error_score, 'passed': error_handling_score, 'total': total_tests}

def test_response_times_under_load():
    """Test response times remain stable under load"""
    print("\nTesting response times under load...")
    
    # Make 30 requests over 10 seconds
    num_requests = 30
    duration = 10
    delay = duration / num_requests
    
    print(f"  Making {num_requests} requests over {duration} seconds...")
    
    times = []
    errors = 0
    
    start_time = time.time()
    
    for i in range(num_requests):
        request_start = time.time()
        
        try:
            response = requests.get(f"{BASE_URL}/health", timeout=3)
            request_end = time.time()
            
            response_time = request_end - request_start
            times.append(response_time)
            
            if response.status_code != 200:
                errors += 1
                
        except Exception:
            errors += 1
            times.append(3.0)  # Penalty time
        
        # Maintain consistent request rate
        elapsed = time.time() - start_time
        expected_time = (i + 1) * delay
        if elapsed < expected_time:
            time.sleep(expected_time - elapsed)
    
    if times:
        avg_time = sum(times) / len(times)
        max_time = max(times)
        min_time = min(times)
        
        print(f"  Average response: {avg_time:.3f}s")
        print(f"  Min/Max response: {min_time:.3f}s / {max_time:.3f}s")
        print(f"  Errors: {errors}/{num_requests}")
        
        # Performance assessment
        performance_score = 100
        if avg_time > 1.0:
            performance_score -= 30
        if max_time > 3.0:
            performance_score -= 20
        if errors > 0:
            performance_score -= errors * 10
        
        performance_score = max(0, performance_score)
        
        print(f"  Load Performance Score: {performance_score}/100")
        
        if performance_score >= 90:
            print(f"  EXCELLENT: Consistent performance under load")
        elif performance_score >= 70:
            print(f"  GOOD: Stable performance under load")
        elif performance_score >= 50:
            print(f"  ACCEPTABLE: Some performance degradation")
        else:
            print(f"  POOR: Significant performance issues under load")
    
    return {
        'requests': num_requests,
        'errors': errors,
        'avg_time': avg_time if times else 0,
        'max_time': max_time if times else 0,
        'performance_score': performance_score if times else 0
    }

def main():
    """Main function to run all Docker integration tests."""
    print("--- MARM Docker Container Integration Tests ---")
    
    # 1. Check if container is running and healthy
    if not check_server_health():
        print("ERROR: MARM Docker container is not running or not healthy!")
        print("Start it with: docker run -d --name marm-mcp-server -p 8001:8001 -v marm_data:/app/data lyellr88/marm-mcp-server:latest")
        return
    
    print("Container is running and healthy, starting integration tests...\n")
    
    # 2. Run integration tests
    endpoint_results = test_basic_endpoints()
    health_results = test_server_health_details()
    concurrent_results = test_concurrent_health_checks()
    error_results = test_error_handling()
    load_results = test_response_times_under_load()
    
    # 3. Overall integration summary
    print("\n--- Integration Test Summary ---")
    
    # Calculate scores
    scores = []
    
    # Endpoint availability (25% weight)
    if endpoint_results:
        endpoint_score = sum(1 for r in endpoint_results if r['success']) / len(endpoint_results) * 100
        scores.append(endpoint_score * 0.25)
        print(f"Endpoint Availability: {endpoint_score:.1f}/100")
    
    # Health information (15% weight)
    if health_results:
        health_score = health_results['score']
        scores.append(health_score * 0.15)
        print(f"Health Information: {health_score:.1f}/100")
    
    # Concurrent handling (25% weight)
    if concurrent_results:
        concurrent_score = concurrent_results['success_rate']
        scores.append(concurrent_score * 0.25)
        print(f"Concurrent Handling: {concurrent_score:.1f}/100")
    
    # Error handling (15% weight)
    if error_results:
        error_score = error_results['score']
        scores.append(error_score * 0.15)
        print(f"Error Handling: {error_score:.1f}/100")
    
    # Load performance (20% weight)
    if load_results:
        load_score = load_results['performance_score']
        scores.append(load_score * 0.20)
        print(f"Load Performance: {load_score:.1f}/100")
    
    # Overall assessment
    if scores:
        overall_score = sum(scores)
        print(f"\nOverall Integration Score: {overall_score:.1f}/100")
        
        if overall_score >= 90:
            print("EXCELLENT: Container integration is outstanding!")
        elif overall_score >= 75:
            print("GOOD: Container integration is solid")
        elif overall_score >= 60:
            print("ACCEPTABLE: Container integration is adequate")
        else:
            print("POOR: Container integration needs improvement")
        
        # Recommendation
        if overall_score >= 80:
            print("READY: Container is ready for production deployment")
        elif overall_score >= 60:
            print("CAUTION: Container may need optimization before production")
        else:
            print("NOT READY: Container requires significant fixes")
    
    print("-" * 60)

if __name__ == "__main__":
    main()