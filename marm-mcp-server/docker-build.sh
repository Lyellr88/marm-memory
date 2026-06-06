#!/bin/bash

# MARM MCP Server - Docker Build Script

set -e

echo "🐳 Building MARM Universal MCP Server Docker Container..."

IMAGE_NAME="marm-systems/marm-mcp-server"
TAG="latest"
VERSION="2.2.3"

mkdir -p ./data

echo "📦 Building Docker image..."
docker build \
    --build-arg VERSION=$VERSION \
    --tag $IMAGE_NAME:$TAG \
    --tag $IMAGE_NAME:$VERSION \
    .

echo "✅ Build complete!"
docker images | grep marm-systems

echo ""
echo "🚀 Ready to deploy! Use these commands:"
echo ""
echo "  # Run with Docker Compose (recommended):"
echo "  docker-compose up -d"
echo ""
echo "  # Or run directly:"
echo "  docker run -d --name marm-mcp-server -p 8001:8001 -v ~/.marm:/home/marm/.marm $IMAGE_NAME:$TAG"
echo ""
echo "  # Check status:"
echo "  docker-compose ps"
echo ""
echo "  # View logs:"
echo "  docker-compose logs -f marm-mcp-server"
echo ""
echo "📍 Server will be available at: http://localhost:8001/mcp"
echo "🔗 Connect to Claude Code: claude mcp add --transport http marm-memory http://localhost:8001/mcp"