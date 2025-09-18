"""
Integration tests for complete MARM workflows
"""
import pytest
import requests
import json
import time
from datetime import datetime

BASE_URL = "http://localhost:8001"

class TestMARMIntegration:
    
    def test_complete_workflow(self):
        """Test complete MARM session workflow"""
        session_name = f"integration_test_{int(time.time())}"
        
        # 1. Start session
        response = requests.post(f"{BASE_URL}/marm_start", 
                               json={"session_name": session_name})
        assert response.status_code == 200
        
        # 2. Add memories
        memories = [
            "Working on FastAPI project with SQLite database",
            "Implementing MCP protocol for AI agent communication", 
            "Added structured logging for production monitoring",
            "Created Docker containerization for easy deployment"
        ]
        
        for memory in memories:
            response = requests.post(f"{BASE_URL}/marm_notebook_add", 
                                   json={
                                       "session_name": session_name,
                                       "memory": memory,
                                       "context_type": "development"
                                   })
            assert response.status_code == 200
        
        # 3. Add log entries  
        response = requests.post(f"{BASE_URL}/marm_log_entry", 
                               json={
                                   "session_name": session_name,
                                   "entry": "Integration test completed successfully",
                                   "context_type": "test"
                               })
        assert response.status_code == 200
        
        # 4. Test recall functionality
        response = requests.post(f"{BASE_URL}/marm_smart_recall", 
                               json={
                                   "session_name": session_name,
                                   "query": "FastAPI database",
                                   "limit": 5
                               })
        assert response.status_code == 200
        data = response.json()
        assert len(data["memories"]) > 0
        
        # 5. Test context bridging
        response = requests.post(f"{BASE_URL}/marm_context_bridge", 
                               json={
                                   "session_name": session_name,
                                   "new_topic": "Performance optimization"
                               })
        assert response.status_code == 200
        
        # 6. Generate summary
        response = requests.post(f"{BASE_URL}/marm_summary", 
                               json={
                                   "session_name": session_name,
                                   "focus": "project overview"
                               })
        assert response.status_code == 200
        
        # 7. Check session status
        response = requests.post(f"{BASE_URL}/marm_session_status", 
                               json={"session_name": session_name})
        assert response.status_code == 200
        data = response.json()
        assert data["entries_count"] >= len(memories) + 1  # memories + log entry
        
        # 8. Clean up
        requests.post(f"{BASE_URL}/marm_session_clear", 
                     json={"session_name": session_name})
    
    def test_concurrent_sessions(self):
        """Test multiple concurrent MARM sessions"""
        sessions = [f"concurrent_test_{i}" for i in range(3)]
        
        # Start multiple sessions
        for session in sessions:
            response = requests.post(f"{BASE_URL}/marm_start", 
                                   json={"session_name": session})
            assert response.status_code == 200
        
        # Add different data to each session
        for i, session in enumerate(sessions):
            response = requests.post(f"{BASE_URL}/marm_notebook_add", 
                                   json={
                                       "session_name": session,
                                       "memory": f"Session {i} unique content",
                                       "context_type": "test"
                                   })
            assert response.status_code == 200
        
        # Verify session isolation
        for i, session in enumerate(sessions):
            response = requests.post(f"{BASE_URL}/marm_smart_recall", 
                                   json={
                                       "session_name": session,
                                       "query": f"Session {i}",
                                       "limit": 5
                                   })
            assert response.status_code == 200
            data = response.json()
            # Should find content from this session only
            assert len(data["memories"]) >= 1
    
    def test_large_data_handling(self):
        """Test handling of large amounts of data"""
        session_name = "large_data_test"
        requests.post(f"{BASE_URL}/marm_start", 
                     json={"session_name": session_name})
        
        # Add many memories
        for i in range(50):
            memory_content = f"Large dataset entry {i}: " + "x" * 1000  # 1KB each
            response = requests.post(f"{BASE_URL}/marm_notebook_add", 
                                   json={
                                       "session_name": session_name,
                                       "memory": memory_content,
                                       "context_type": "bulk_test"
                                   })
            assert response.status_code == 200
        
        # Test recall still works with large dataset
        response = requests.post(f"{BASE_URL}/marm_smart_recall", 
                               json={
                                   "session_name": session_name,
                                   "query": "dataset entry",
                                   "limit": 10
                               })
        assert response.status_code == 200
        data = response.json()
        assert len(data["memories"]) <= 10
        
        # Verify response size compliance
        response_size = len(response.content)
        assert response_size <= 1024 * 1024  # MCP 1MB limit
    
    def test_error_recovery(self):
        """Test system behavior under error conditions"""
        # Test with invalid session names
        invalid_sessions = ["", None, "x" * 1000]  # empty, null, too long
        
        for invalid_session in invalid_sessions:
            if invalid_session is not None:
                response = requests.post(f"{BASE_URL}/marm_start", 
                                       json={"session_name": invalid_session})
                # Should handle gracefully (400/422 error or sanitize)
                assert response.status_code in [200, 400, 422]
    
    def test_system_health_during_load(self):
        """Test system health endpoints under load"""
        # Generate some load
        for i in range(10):
            requests.post(f"{BASE_URL}/marm_start", 
                         json={"session_name": f"load_test_{i}"})
        
        # Check health endpoint
        response = requests.get(f"{BASE_URL}/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        
        # Check root endpoint
        response = requests.get(f"{BASE_URL}/")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "running"
