# MARM MCP Server - Test Suite

Professional test suite for MARM Universal MCP Server v2.2.6

## Test Coverage

### Docker Production Tests (Primary)
- **`test_docker_memory_usage.py`** - Docker container memory analysis
  - Real Docker container memory usage
  - Container health validation
  - Production memory footprint

- **`test_docker_performance.py`** - Docker container performance
  - Endpoint response times via HTTP
  - Concurrent request handling
  - Production performance metrics

- **`test_docker_integration.py`** - Docker end-to-end testing
  - Complete workflow validation
  - Production container reliability
  - Integration scoring system

- **`test_docker_mcp_size_limits.py`** - Docker MCP compliance
  - 1MB response limit enforcement
  - Production size compliance
  - MCP protocol validation

- **`test_docker_security.py`** - Docker security testing
  - SQL injection protection
  - XSS content sanitization
  - Input validation security
  - Rate limiting verification

### Local Development Tests (Secondary)
- **`test_mcp_size_limits.py`** - Local MCP compliance testing
- **`test_memory_usage.py`** - Local memory footprint analysis  
- **`test_performance.py`** - Local response time benchmarking
- **`test_integration.py`** - Local end-to-end workflow testing
- **`test_security.py`** - Local security feature testing

## Running Tests

### Docker Production Tests (Recommended)

**Prerequisites:** Docker container must be running:
```bash
docker run -d --name marm-mcp-server -p 8001:8001 -v ~/.marm:/home/marm/.marm lyellr88/marm-mcp-server:latest
```

**Run All Docker Tests:**
```bash
# Memory usage analysis
python tests/test_docker_memory_usage.py

# Performance benchmarking  
python tests/test_docker_performance.py

# End-to-end integration testing
python tests/test_docker_integration.py

# MCP compliance validation
python tests/test_docker_mcp_size_limits.py

# Security testing
python tests/test_docker_security.py
```

**Quick Docker Test Suite:**
```bash
# Run all 5 Docker tests sequentially
python tests/test_docker_memory_usage.py && \
python tests/test_docker_performance.py && \
python tests/test_docker_integration.py && \
python tests/test_docker_mcp_size_limits.py && \
python tests/test_docker_security.py
```

### Local Development Tests (For Development)

**Prerequisites:** Local server running:
```bash
python server.py
```

**Run Local Tests:**
```bash
# Install testing framework
pip install pytest requests psutil

# Run all local tests
python -m pytest tests/test_*.py -v --ignore=tests/test_docker_*.py

# Run specific local tests
python -m pytest tests/test_performance.py -v       # Performance benchmarks
python -m pytest tests/test_integration.py -v       # End-to-end workflows
python -m pytest tests/test_mcp_size_limits.py -v   # MCP compliance
python -m pytest tests/test_security.py -v          # Security testing
```

### Standalone Memory Test (No Dependencies)
```bash
# Simple memory benchmarking
python tests/test_memory_usage.py
```

## Test Requirements

### For Docker Tests (Primary)
- **Docker** - Container runtime
- **requests** - HTTP client (usually included with Python)
- **subprocess** - Process execution (built-in Python module)

### For Local Tests (Development)
- **pytest** - Test framework
- **requests** - HTTP client for API testing
- **psutil** - System resource monitoring

## Test Categories

### 🔧 **Compliance Tests**
Ensure MARM adheres to MCP protocol specifications and size limits.

### ⚡ **Performance Tests**  
Validate response times, memory usage, and scalability under load.

### 🔄 **Integration Tests**
Test complete workflows and multi-component interactions.

---

*These tests validate MARM's production-ready status and enterprise-grade reliability.*