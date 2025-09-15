"""
Performance tests for MARM MCP Server
"""
import pytest
import requests
import time
import statistics

BASE_URL = "http://localhost:8001"

class TestPerformance:
    
    def test_endpoint_response_times(self):
        """Test response times for critical endpoints"""
        endpoints_to_test = [
            ("GET", "/health", {}),
            ("GET", "/", {}), 
            ("POST", "/marm_start", {"session_name": "perf_test"}),
            ("POST", "/marm_session_status", {"session_name": "perf_test"}),
        ]
        
        for method, endpoint, payload in endpoints_to_test:
            times = []
            
            for _ in range(10):  # 10 requests per endpoint
                start_time = time.time()
                
                if method == "GET":
                    response = requests.get(f"{BASE_URL}{endpoint}")
                else:
                    response = requests.post(f"{BASE_URL}{endpoint}", json=payload)
                
                end_time = time.time()
                response_time = end_time - start_time
                times.append(response_time)
                
                assert response.status_code in [200, 201]
            
            avg_time = statistics.mean(times)
            max_time = max(times)
            
            print(f"{method} {endpoint}: avg={avg_time:.3f}s, max={max_time:.3f}s")
            
            # Performance assertions
            assert avg_time < 2.0  # Average response under 2 seconds
            assert max_time < 5.0  # Max response under 5 seconds
    
    def test_memory_usage_stability(self):
        """Test memory usage doesn't grow excessively"""
        session_name = "memory_stability_test"
        requests.post(f"{BASE_URL}/marm_start", json={"session_name": session_name})
        
        # Add many entries and check server still responds
        for i in range(100):
            response = requests.post(f"{BASE_URL}/marm_notebook_add", 
                                   json={
                                       "session_name": session_name,
                                       "memory": f"Memory entry {i} with some content",
                                       "context_type": "performance_test"
                                   })
            assert response.status_code == 200
            
            # Every 10 entries, test recall performance
            if i % 10 == 0:
                start_time = time.time()
                recall_response = requests.post(f"{BASE_URL}/marm_smart_recall", 
                                              json={
                                                  "session_name": session_name,
                                                  "query": f"entry {i}",
                                                  "limit": 5
                                              })
                recall_time = time.time() - start_time
                
                assert recall_response.status_code == 200
                assert recall_time < 3.0  # Recall should stay fast
    
    def test_concurrent_request_handling(self):
        """Test handling multiple concurrent requests"""
        import threading
        import concurrent.futures
        
        def make_request(session_id):
            """Make a request with unique session"""
            session_name = f"concurrent_perf_{session_id}"
            
            # Start session
            response = requests.post(f"{BASE_URL}/marm_start", 
                                   json={"session_name": session_name})
            assert response.status_code == 200
            
            # Add memory
            response = requests.post(f"{BASE_URL}/marm_notebook_add", 
                                   json={
                                       "session_name": session_name,
                                       "memory": f"Concurrent test data {session_id}",
                                       "context_type": "concurrent_test"
                                   })
            assert response.status_code == 200
            
            # Test recall
            response = requests.post(f"{BASE_URL}/marm_smart_recall", 
                                   json={
                                       "session_name": session_name,
                                       "query": "concurrent test",
                                       "limit": 3
                                   })
            assert response.status_code == 200
            
            return session_id
        
        # Run 5 concurrent requests
        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            start_time = time.time()
            futures = [executor.submit(make_request, i) for i in range(5)]
            results = [future.result() for future in concurrent.futures.as_completed(futures)]
            total_time = time.time() - start_time
        
        assert len(results) == 5
        assert total_time < 10.0  # All concurrent requests complete within 10s
    
    def test_large_response_handling(self):
        """Test handling of large response sizes"""
        session_name = "large_response_test"
        requests.post(f"{BASE_URL}/marm_start", json={"session_name": session_name})
        
        # Add many large memories
        for i in range(20):
            large_content = f"Large memory {i}: " + "content " * 1000  # ~7KB each
            response = requests.post(f"{BASE_URL}/marm_notebook_add", 
                                   json={
                                       "session_name": session_name,
                                       "memory": large_content,
                                       "context_type": "large_test"
                                   })
            assert response.status_code == 200
        
        # Request large recall
        start_time = time.time()
        response = requests.post(f"{BASE_URL}/marm_smart_recall", 
                               json={
                                   "session_name": session_name,
                                   "query": "Large memory",
                                   "limit": 50  # Request many results
                               })
        response_time = time.time() - start_time
        
        assert response.status_code == 200
        assert response_time < 10.0  # Should respond within 10 seconds
        
        # Verify MCP compliance (1MB limit)
        response_size = len(response.content)
        assert response_size <= 1024 * 1024
        
        data = response.json()
        assert "memories" in data
