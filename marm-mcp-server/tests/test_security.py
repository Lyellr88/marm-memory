"""
Real Security Tests - No Ghosts, Just Facts
Tests actual security vulnerabilities with proper validation.
"""
import requests

BASE_URL = "http://localhost:8001"

def test_server_starts():
    """Test 1: Server starts without crashing"""
    response = requests.get(f"{BASE_URL}/health")
    assert response.status_code == 200
    print("Server starts successfully")

def test_xss_sanitization():
    """Test 2: XSS content is sanitized in API response"""
    payload = {"session_name": "security_test", "content": "<script>alert('XSS')</script>"}
    response = requests.post(f"{BASE_URL}/marm_contextual_log", json=payload)

    assert response.status_code == 200
    data = response.json()

    # The response should NOT contain the malicious script
    assert "<script>" not in data["content"]
    assert data["content"] == ""  # Should be empty after sanitization
    print("XSS content properly sanitized")

def test_content_limits():
    """Test 3: System handles large content gracefully"""
    # Test reasonable large content (10KB) - should work fine
    large_content = "X" * 10000  # 10KB - more reasonable size
    payload = {"session_name": "security_test", "content": large_content}
    response = requests.post(f"{BASE_URL}/marm_contextual_log", json=payload)

    # Should accept reasonable content and sanitize it properly
    # Check status code first
    if response.status_code != 200:
        print(f"Expected 200, got {response.status_code}: {response.text}")
    assert response.status_code == 200
    print("Large content handled gracefully")

if __name__ == "__main__":
    print("Running REAL Security Tests...")
    test_server_starts()
    test_xss_sanitization()
    test_content_limits()
    print("All security tests passed!")