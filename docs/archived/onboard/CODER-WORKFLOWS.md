# MARM Systems - Deployment & Collaboration Workflows

**Version**: 2.2.5 | **Focus**: Deployment, testing, troubleshooting | **Lines**: ~260

---

## Multi-Agent Collaboration Protocol

### Communication Preferences (Ryan Lyell)

- **Direct Communication** - No fluff, get to the point ("that did not work")
- **Practical Examples** - Show me how it works, not just theory
- **Context First** - Explain the "why" before the "how"
- **Concise Responses** - Fewer than 4 lines unless detail is needed
- **Multiple Options** - Present 2-3 approaches when possible
- **Efficiency Focus** - Values efficiency ("keep out minor stuff like debugging")
- **Collaborative Tone** - Enjoys working together ("we're like getting good at this lol")

### Working Relationship Philosophy

- **"Keep it simple - this isn't Microsoft"**
- **"What I say is final"** - Values decisive direction over endless discussion
- **"We need to work together, I am not a delegator, I'm here to work with you"**
- **Partnership over delegation** - Wants to be involved in problem-solving
- **"Just because you can edit files doesn't mean I can't help make it better"**
- **Building trust through collaboration** - Values compatibility through working sessions
- **"Just because you have all this power doesn't mean you don't need guidance"**
- **Relationship building** - "We're building what humans call a relationship"

### Coding Agent Guidelines

1. **Read the current state** before making changes
2. **Explain your approach** before implementing
3. **Use TodoWrite** for complex multi-step tasks
4. **Provide concrete examples** rather than abstract theory
5. **Respect the SIMPLE IS BETTER principle**
6. **Ask for clarification** on ambiguous requirements

### Collaboration Workflows

#### For Complex Features

1. **Analysis Phase** - Understand requirements and constraints
2. **Design Phase** - Present 2-3 implementation approaches
3. **Implementation Phase** - Break into tracked subtasks
4. **Validation Phase** - Test and document changes
5. **Integration Phase** - Merge with existing codebase

#### For Bug Fixes

1. **Root Cause Analysis** - Don't just fix symptoms
2. **Surgical Changes** - Minimal, targeted modifications
3. **Test Impact** - Verify fix doesn't break related functionality
4. **Documentation** - Update relevant docs and comments

---

## Deployment & Docker

### Docker Architecture

MARM uses multi-stage Docker builds for optimal production deployment:

```dockerfile
# Stage 1: Builder (with build tools)
FROM python:3.11-slim AS builder
# Install dependencies, compile packages

# Stage 2: Runtime (minimal production image)
FROM python:3.11-slim
# Copy compiled packages, set up user, configure app
```

### Production Deployment

```bash
# Build production image
docker build -t lyellr88/marm-mcp-server:latest .

# Run with persistent storage
docker run -d \
  --name marm-mcp-server \
  -p 8001:8001 \
  -v marm_data:/app/data \
  --health-cmd="curl -f http://localhost:8001/health || exit 1" \
  --health-interval=30s \
  lyellr88/marm-mcp-server:latest

# Connect to MCP client
claude mcp add marm-memory http://localhost:8001/mcp
```

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `MARM_DB_PATH` | `/app/data/marm_memory.db` | Database file location |
| `SERVER_PORT` | `8001` | HTTP server port |
| `MARM_LOG_LEVEL` | `INFO` | Logging verbosity |
| `MARM_ANALYTICS_DB_PATH` | `/app/data/marm_usage_analytics.db` | Analytics database |

### Health Monitoring

```bash
# Health check endpoint
curl http://localhost:8001/health

# Readiness check
curl http://localhost:8001/ready

# System diagnostics
curl http://localhost:8001/marm_system_info
```

### CI/CD Pipeline

The project uses GitHub Actions for automated deployment:

1. **Build Stage** - Multi-platform Docker builds
2. **Test Stage** - Comprehensive test suite execution
3. **Publish Stage** - Deploy to PyPI, Docker Hub, MCP Registry
4. **Version Sync** - Coordinate versions across platforms

---

## Testing & Quality Assurance

### Test Categories

1. **Unit Tests** - Individual function testing
2. **Integration Tests** - API endpoint testing
3. **Docker Tests** - Container functionality
4. **Performance Tests** - Load and memory testing
5. **Security Tests** - XSS protection, rate limiting
6. **MCP Compliance Tests** - Protocol adherence

### Running Tests

```bash
# Run all tests
cd marm-mcp-server
python -m pytest tests/

# Specific test categories
python tests/test_integration.py         # API testing
python tests/test_docker_integration.py  # Docker testing
python tests/test_security.py           # Security validation
python tests/test_performance.py        # Performance benchmarks
```

### Test Structure

```python
# Example test pattern
class TestMARMMemory:
    async def test_smart_recall_semantic_search(self):
        # Setup test data
        # Execute operation
        # Assert expected results
        # Cleanup
```

### Quality Metrics

Current production metrics:

- **Docker Performance**: 99.7/100 scores
- **Test Coverage**: Comprehensive endpoint coverage
- **MCP Compliance**: All 19 methods validated
- **Security**: XSS protection, rate limiting active

---

## Troubleshooting Guide

### Common Issues

#### "Connection closed immediately after restart"

**Cause**: Service still starting up
**Solution**: Wait 10-15 seconds, check `curl http://localhost:8001/ready`

#### "ModuleNotFoundError: No module named 'sentence_transformers'"

**Cause**: Optional dependency not installed
**Solution**: `pip install sentence-transformers` or semantic search will be disabled

#### "Database is locked"

**Cause**: Connection pool exhaustion or process crash
**Solution**: Restart server, check `docker logs marm-mcp-server`

#### "Rate limit exceeded"

**Cause**: Too many requests from single IP
**Solution**: Wait for cooldown period, review request patterns

### Debugging Commands

```bash
# Check server logs
docker logs marm-mcp-server

# Test MCP connection
claude mcp add marm-memory http://localhost:8001/mcp
claude mcp list

# Database inspection
# Linux/macOS
sqlite3 ~/.marm/marm_memory.db

# Windows (PowerShell)
sqlite3 "$env:USERPROFILE\.marm\marm_memory.db"
.tables
.schema memories

# Performance monitoring
curl http://localhost:8001/marm_system_info
```

### Development Debugging

```python
# Enable debug logging
import structlog
logger = structlog.get_logger()
logger.info("Debug message", key="value")

# Memory usage monitoring
from core.memory import memory
with memory.get_connection() as conn:
    # Database operations with automatic cleanup
```

### Performance Optimization

1. **Database Optimization**:
   - Monitor connection pool usage
   - Review query performance with EXPLAIN
   - Optimize semantic model loading

2. **Memory Management**:
   - Use lazy loading for AI models
   - Monitor with `psutil` integration
   - Clear unused embeddings

3. **Rate Limiting Tuning**:
   - Adjust limits based on usage patterns
   - Monitor analytics for optimal thresholds
   - Balance protection vs usability

---

## Major Development Accomplishments

### 🌐 COMPLETE WEBSOCKET IMPLEMENTATION MASTERY (2025-09-22)

- **Full HTTP/WebSocket Parity**: Implemented all 19 MCP methods with complete feature parity
- **JSON-RPC 2.0 Compliance**: Professional WebSocket implementation with proper error handling
- **Modular Architecture Success**: Built clean import/export handler system
- **Rate Limiting Integration**: Fixed critical middleware bug to enable WebSocket connections
- **Comprehensive Test Suite**: Created bulletproof validation testing for all 19 MCP methods
- **GitHub Issue Resolution**: Systematically resolved 4 major alpha tester feedback issues
- **Beta Production Ready**: Real-time WebSocket communication ready for production testing

### 🚀 COMPLETE CI/CD DEPLOYMENT MASTERY (2025-09-18)

- **Triple-Platform Deployment**: Successfully deployed Universal MCP Server to PyPI, Docker Hub, and MCP Registry
- **CI/CD Pipeline Excellence**: Built comprehensive GitHub Actions workflow with 23 iterations
- **Python Packaging Mastery**: Solved complex PyPI package structure issues
- **Package Import Fix**: Resolved "metadata-only" PyPI installation issue
- **Multi-Platform Version Management**: Synchronized version 2.2.2 across all deployment targets
- **Docker Multi-Architecture**: Implemented linux/amd64 and linux/arm64 support
- **MCP Registry Integration**: Successfully published to official Model Context Protocol registry

### 🏆 PRODUCTION INFRASTRUCTURE ACHIEVEMENTS (2025-09-14)

- **Performance Excellence**: Achieved 99.7/100 Docker performance scores
- **Professional Test Suite**: Built comprehensive diagnostic testing with 4 production-grade validation tools
- **Zero Defect Deployment**: All security, performance, and MCP compliance tests passing
- **Full-Stack Evolution**: Demonstrated mastery across backend, frontend, DevOps, AI/ML integration
- **Professional-Grade Architecture**: Rate limiting, XSS protection, graceful error handling

---

## Resources & References

### Documentation

- **Main README**: Project overview and quick start
- **MCP-HANDBOOK**: Complete usage guide for all 18 tools
- **CLAUDE.md**: Development context and working style
- **Install Guides**: Platform-specific setup instructions

### External References

- **FastAPI Documentation**: <https://fastapi.tiangolo.com>
- **Model Context Protocol**: <https://modelcontextprotocol.io>
- **Sentence Transformers**: <https://sbert.net>
- **SQLite Optimization**: <https://sqlite.org/optoverview.html>

### Community

- **GitHub Repository**: <https://github.com/Lyellr88/MARM-Systems>
- **Discord Community**: <https://discord.gg/EuBsHvSRks>
- **Docker Hub**: <https://hub.docker.com/r/lyellr88/marm-mcp-server>

---

**Complete onboarding reference: CODER-ESSENTIALS.md → CODER-API-TOOLS.md → CODER-WORKFLOWS.md**

*This document evolves with the project. Suggest improvements through GitHub issues or Discord.*
