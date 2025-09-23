"""
Performance tests for MARM Docker Container
Tests actual production Docker container performance, not local development.

Usage:
1. Make sure MARM Docker container is running:
   docker run -d --name marm-mcp-server -p 8001:8001 -v marm_data:/app/data lyellr88/marm-mcp-server:latest
2. Run the script:
   python tests/test_docker_performance.py
"""

import requests
import time
import statistics
import threading
import concurrent.futures

BASE_URL = "http://localhost:8001"

def check_server_health():
    """Check if the MARM server is healthy and responsive."""
    try:
        response = requests.get(f"{BASE_URL}/health", timeout=5)
        return response.status_code == 200 and "healthy" in response.text
    except Exception:
        return False

def test_endpoint_response_times():
    """Test response times for critical endpoints"""
    print("Testing endpoint response times...")
    
    endpoints_to_test = [
        ("GET", "/health", {}),
        ("GET", "/docs", {}), 
    ]
    
    results = []
    
    for method, endpoint, payload in endpoints_to_test:
        print(f"  Testing {method} {endpoint}...")
        times = []
        
        for i in range(10):  # 10 requests per endpoint
            try:
                start_time = time.time()
                
                if method == "GET":
                    response = requests.get(f"{BASE_URL}{endpoint}", timeout=10)
                else:
                    response = requests.post(f"{BASE_URL}{endpoint}", json=payload, timeout=10)
                
                end_time = time.time()
                response_time = end_time - start_time
                times.append(response_time)
                
                if response.status_code not in [200, 201]:
                    print(f"    WARNING: Request {i+1} returned status {response.status_code}")
                    
            except Exception as e:
                print(f"    ERROR: Request {i+1} failed: {e}")
                times.append(10.0)  # Penalty time for failures
        
        if times:
            avg_time = statistics.mean(times)
            max_time = max(times)
            min_time = min(times)
            
            result = {
                'endpoint': f"{method} {endpoint}",
                'avg': avg_time,
                'max': max_time,
                'min': min_time,
                'success_rate': sum(1 for t in times if t < 5.0) / len(times) * 100
            }
            results.append(result)
            
            print(f"    avg={avg_time:.3f}s, max={max_time:.3f}s, min={min_time:.3f}s, success={result['success_rate']:.1f}%")
            
            # Performance assessment
            if avg_time < 0.5:
                print(f"    EXCELLENT: Very fast response times")
            elif avg_time < 1.0:
                print(f"    GOOD: Fast response times")
            elif avg_time < 2.0:
                print(f"    ACCEPTABLE: Reasonable response times")
            else:
                print(f"    SLOW: Response times may impact user experience")
    
    return results

def test_concurrent_request_handling():
    """Test handling multiple concurrent requests"""
    print("\nTesting concurrent request handling...")
    
    def make_health_request(request_id):
        """Make a health check request"""
        try:
            start_time = time.time()
            response = requests.get(f"{BASE_URL}/health", timeout=5)
            end_time = time.time()
            
            return {
                'id': request_id,
                'status': response.status_code,
                'time': end_time - start_time,
                'success': response.status_code == 200
            }
        except Exception as e:
            return {
                'id': request_id,
                'status': 0,
                'time': 5.0,
                'success': False,
                'error': str(e)
            }
    
    # Run 10 concurrent requests
    num_concurrent = 10
    print(f"  Running {num_concurrent} concurrent health checks...")
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=num_concurrent) as executor:
        start_time = time.time()
        futures = [executor.submit(make_health_request, i) for i in range(num_concurrent)]
        results = [future.result() for future in concurrent.futures.as_completed(futures)]
        total_time = time.time() - start_time
    
    successful = sum(1 for r in results if r['success'])
    avg_response_time = statistics.mean([r['time'] for r in results])
    
    print(f"  Completed {successful}/{num_concurrent} requests successfully")
    print(f"  Total time: {total_time:.3f}s, Average response: {avg_response_time:.3f}s")
    
    if successful == num_concurrent and total_time < 5.0:
        print(f"  EXCELLENT: All concurrent requests handled efficiently")
    elif successful >= num_concurrent * 0.8 and total_time < 10.0:
        print(f"  GOOD: Most concurrent requests handled well")
    else:
        print(f"  POOR: Concurrent request handling needs improvement")
    
    return {
        'total_requests': num_concurrent,
        'successful': successful,
        'total_time': total_time,
        'avg_response_time': avg_response_time,
        'success_rate': successful / num_concurrent * 100
    }

def test_server_stability():
    """Test server stability under repeated requests"""
    print("\nTesting server stability...")
    
    num_requests = 50
    print(f"  Making {num_requests} rapid health check requests...")
    
    times = []
    errors = 0
    
    for i in range(num_requests):
        try:
            start_time = time.time()
            response = requests.get(f"{BASE_URL}/health", timeout=3)
            end_time = time.time()
            
            times.append(end_time - start_time)
            
            if response.status_code != 200:
                errors += 1
                
        except Exception as e:
            errors += 1
            times.append(3.0)  # Penalty time
            
        # Small delay to avoid overwhelming
        time.sleep(0.1)
    
    if times:
        avg_time = statistics.mean(times)
        stability_score = (num_requests - errors) / num_requests * 100
        
        print(f"  Completed: {num_requests - errors}/{num_requests} successful")
        print(f"  Average response time: {avg_time:.3f}s")
        print(f"  Stability score: {stability_score:.1f}%")
        
        if stability_score >= 95 and avg_time < 1.0:
            print(f"  EXCELLENT: Very stable server performance")
        elif stability_score >= 90 and avg_time < 2.0:
            print(f"  GOOD: Stable server performance")
        else:
            print(f"  POOR: Server stability issues detected")
    
    return {
        'total_requests': num_requests,
        'errors': errors,
        'avg_time': avg_time if times else 0,
        'stability_score': stability_score if times else 0
    }

def main():
    """Main function to run all Docker performance tests."""
    print("--- MARM Docker Container Performance Tests ---")
    
    # 1. Check if container is running and healthy
    if not check_server_health():
        print("ERROR: MARM Docker container is not running or not healthy!")
        print("Start it with: docker run -d --name marm-mcp-server -p 8001:8001 -v marm_data:/app/data lyellr88/marm-mcp-server:latest")
        return
    
    print("Container is running and healthy, starting performance tests...\n")
    
    # 2. Run performance tests
    endpoint_results = test_endpoint_response_times()
    concurrent_results = test_concurrent_request_handling()
    stability_results = test_server_stability()
    
    # 3. Overall performance summary
    print("\n--- Performance Summary ---")
    
    # Calculate overall score
    scores = []
    
    # Endpoint performance (40% weight)
    if endpoint_results:
        avg_endpoint_time = statistics.mean([r['avg'] for r in endpoint_results])
        endpoint_score = max(0, 100 - (avg_endpoint_time * 50))  # Penalty for slow responses
        scores.append(endpoint_score * 0.4)
        print(f"Endpoint Performance: {endpoint_score:.1f}/100 (avg response: {avg_endpoint_time:.3f}s)")
    
    # Concurrent handling (30% weight)
    if concurrent_results:
        concurrent_score = concurrent_results['success_rate']
        scores.append(concurrent_score * 0.3)
        print(f"Concurrent Handling: {concurrent_score:.1f}/100 ({concurrent_results['successful']}/{concurrent_results['total_requests']} succeeded)")
    
    # Stability (30% weight)
    if stability_results:
        stability_score = stability_results['stability_score']
        scores.append(stability_score * 0.3)
        print(f"Server Stability: {stability_score:.1f}/100 ({stability_results['errors']} errors in {stability_results['total_requests']} requests)")
    
    # Overall assessment
    if scores:
        overall_score = sum(scores)
        print(f"\nOverall Performance Score: {overall_score:.1f}/100")
        
        if overall_score >= 90:
            print("EXCELLENT: Container performance is outstanding!")
        elif overall_score >= 75:
            print("GOOD: Container performance is solid")
        elif overall_score >= 60:
            print("ACCEPTABLE: Container performance is adequate")
        else:
            print("POOR: Container performance needs improvement")
    
    print("-" * 50)

if __name__ == "__main__":
    main()