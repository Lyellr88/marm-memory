# MARM MCP Server - Publishing Guide

This guide covers publishing the MARM Universal MCP Server to the MCP Registry with automated CI/CD workflows.

## 📦 Publishing Overview

The MARM server can be published through multiple channels:

1. **PyPI Package** (Python pip install)
2. **Docker Hub** (Container deployment)
3. **MCP Registry** (Official MCP protocol registry)

## 🚀 Automated Publishing (Recommended)

### GitHub Actions Workflow

The repository includes a complete GitHub Actions workflow (`.github/workflows/publish-mcp.yml`) that automatically:

1. **Validates** server.json against MCP schema
2. **Tests** the server startup and functionality
3. **Publishes to PyPI** when tagged
4. **Builds and pushes Docker images** to Docker Hub
5. **Publishes to MCP Registry** using GitHub OIDC

### Triggering a Release

```bash
# Tag a new version
git tag v2.1.0
git push origin v2.1.0

# GitHub Actions will automatically:
# ✅ Run tests and validation
# ✅ Publish to PyPI
# ✅ Build Docker images
# ✅ Register with MCP Registry
```

### Required Secrets

Set these in your GitHub repository secrets:

```
PYPI_API_TOKEN=pypi-...          # PyPI publishing token
DOCKER_USERNAME=lyellr88         # Docker Hub username
DOCKER_PASSWORD=dckr_pat_...     # Docker Hub access token
```

## 🛠️ Manual Publishing

### Prerequisites

1. **Install MCP Publisher CLI**

   ```bash
   # Download for your platform
   curl -L -o mcp-publisher https://github.com/modelcontextprotocol/publisher/releases/latest/download/mcp-publisher-linux-amd64
   chmod +x mcp-publisher
   sudo mv mcp-publisher /usr/local/bin/
   ```

2. **Validate Configuration**

   ```bash
   python validate_server_json.py
   ```

3. **Run Publishing Setup**

   ```bash
   python publish_to_mcp.py
   ```

### Publishing Steps

1. **Initialize MCP Registry** (first time only)

   ```bash
   mcp-publisher init
   ```

2. **Login to MCP Registry**

   ```bash
   # GitHub OIDC (recommended)
   mcp-publisher login github-oidc

   # Or GitHub Token
   mcp-publisher login github-token
   ```

3. **Publish to PyPI** (optional)

   ```bash
   python -m build
   python -m twine upload dist/*
   ```

4. **Build Docker Image** (optional)

   ```bash
   docker build -t lyellr88/marm-mcp-server:latest .
   docker push lyellr88/marm-mcp-server:latest
   ```

5. **Publish to MCP Registry**

   ```bash
   mcp-publisher publish
   ```

## 📋 Configuration Files

### server.json

- **Purpose**: MCP Registry configuration
- **Namespace**: `io.github.marm-systems/marm-mcp-server`
- **Deployment**: PyPI, Docker, and Remote SSE endpoints
- **Tools**: 19 memory management tools listed

### pyproject.toml

- **Purpose**: Python package configuration
- **Package Name**: `marm-mcp-server`
- **Entry Point**: `marm-mcp-server` command
- **Dependencies**: FastAPI, sentence-transformers, etc.

### .github/workflows/publish-mcp.yml

- **Purpose**: Automated CI/CD publishing
- **Triggers**: Version tags (v*)
- **Jobs**: Validate → Test → Publish (PyPI + Docker + MCP)

## 🔍 Validation

### Local Validation

```bash
# Validate server.json schema
python validate_server_json.py

# Test package build
python -m build --dry-run

# Test Docker build
docker build -t marm-test .
```

### Post-Publication Verification

- **PyPI**: <https://pypi.org/project/marm-mcp-server/>
- **Docker Hub**: <https://hub.docker.com/r/lyellr88/marm-mcp-server>
- **MCP Registry**: <https://registry.modelcontextprotocol.io/servers/io.github.marm-systems/marm-mcp-server>

## 📚 Installation Methods

### PyPI Installation

```bash
pip install marm-mcp-server
marm-mcp-server
```

### Docker Installation

```bash
docker run -d \
  --name marm-mcp-server \
  -p 8001:8001 \
  -v marm-data:/app/data \
  lyellr88/marm-mcp-server:latest
```

### Claude Desktop Integration

```json
{
  "mcpServers": {
    "marm-memory": {
      "command": "marm-mcp-server"
    }
  }
}
```

## ✅ Publishing Checklist

- [x] server.json validated against MCP schema
- [x] pyproject.toml configured for PyPI
- [x] GitHub Actions workflow created
- [x] Docker image builds successfully
- [x] Manual publishing scripts available
- [x] Documentation complete

## 🔧 Troubleshooting

### Common Issues

1. **Schema Validation Fails**
   - Check internet connection for schema download
   - Verify server.json syntax

2. **GitHub Actions Permission Denied**
   - Ensure `id-token: write` permission
   - Check repository secrets are set

3. **Docker Build Fails**
   - Verify Dockerfile syntax
   - Check base image availability

4. **PyPI Upload Fails**
   - Verify API token is valid
   - Check package name availability

## 📞 Support

- **Homepage**: <https://marmsystems.com>
- **Repository**: <https://github.com/MARM-Systems/MARM>
- **Issues**: <https://github.com/MARM-Systems/MARM/issues>
- **Contact**: <lyell@marmsystems.com>

---

**Ready to publish!** Use the automated GitHub Actions workflow for the smoothest experience, or follow the manual steps for more control.
