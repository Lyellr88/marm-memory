#!/usr/bin/env python3
"""
Manual MCP Registry Publishing Script for MARM MCP Server

This script helps with the manual publishing process when GitHub Actions
is not available or for testing purposes.
"""

import os
import subprocess
import sys
import json
import platform
from pathlib import Path

def check_requirements():
    """Check if all requirements are met for publishing"""
    print("[INFO] Checking publishing requirements...")

    # Check if server.json exists
    if not Path("server.json").exists():
        print("[ERROR] server.json not found. Please create it first.")
        return False

    # Validate server.json
    try:
        subprocess.run([sys.executable, "validate_server_json.py"], check=True)
        print("[OK] server.json validation passed")
    except subprocess.CalledProcessError:
        print("[ERROR] server.json validation failed")
        return False

    print("[OK] All requirements met")
    return True

def install_mcp_publisher():
    """Install the MCP publisher CLI"""
    print("[INFO] Installing MCP Publisher CLI...")

    system = platform.system().lower()
    arch = platform.machine().lower()

    # Map Python platform names to publisher release names
    if system == "windows":
        binary_name = "mcp-publisher-windows-amd64.exe"
    elif system == "darwin":
        binary_name = "mcp-publisher-darwin-amd64"
    elif system == "linux":
        if "arm" in arch or "aarch64" in arch:
            binary_name = "mcp-publisher-linux-arm64"
        else:
            binary_name = "mcp-publisher-linux-amd64"
    else:
        print(f"[ERROR] Unsupported platform: {system}")
        return False

    # Download URL
    download_url = f"https://github.com/modelcontextprotocol/publisher/releases/latest/download/{binary_name}"

    print(f"[INFO] Downloading from: {download_url}")
    print(f"[INFO] Please manually download and install the MCP publisher:")
    print(f"       1. Download: {download_url}")
    print(f"       2. Make it executable and add to PATH")

    if system == "windows":
        print(f"       3. Rename to 'mcp-publisher.exe' and place in PATH")
    else:
        print(f"       3. chmod +x mcp-publisher && sudo mv mcp-publisher /usr/local/bin/")

    return True

def setup_authentication():
    """Setup authentication for MCP registry"""
    print("\n[INFO] Setting up MCP Registry authentication...")
    print("Choose authentication method:")
    print("1. GitHub OIDC (recommended for GitHub repos)")
    print("2. GitHub Personal Access Token")
    print("3. DNS Authentication (for custom domains)")

    choice = input("Enter choice (1-3): ").strip()

    if choice == "1":
        print("\n[INFO] GitHub OIDC Authentication:")
        print("Run: mcp-publisher login github-oidc")
        print("This requires the repository to be on GitHub with proper permissions.")

    elif choice == "2":
        print("\n[INFO] GitHub Personal Access Token:")
        print("1. Go to GitHub Settings > Developer settings > Personal access tokens")
        print("2. Create a token with 'repo' scope")
        print("3. Run: mcp-publisher login github-token")
        print("4. Enter your token when prompted")

    elif choice == "3":
        print("\n[INFO] DNS Authentication:")
        print("1. Add TXT record to your domain")
        print("2. Run: mcp-publisher login dns")
        print("3. Follow the DNS verification steps")

    else:
        print("[ERROR] Invalid choice")
        return False

    return True

def build_and_test():
    """Build and test the package before publishing"""
    print("\n[INFO] Building and testing package...")

    # Test Python package build
    try:
        print("[INFO] Testing Python package build...")
        subprocess.run([sys.executable, "-m", "build", "--dry-run"], check=True)
        print("[OK] Python package build test passed")
    except subprocess.CalledProcessError:
        print("[WARN] Python package build test failed (pip install build may be needed)")

    # Test Docker build
    try:
        print("[INFO] Testing Docker build...")
        result = subprocess.run(["docker", "--version"], capture_output=True, text=True)
        if result.returncode == 0:
            print("[INFO] Docker is available")
            print("[INFO] To test Docker build, run: docker build -t marm-test .")
        else:
            print("[WARN] Docker not available")
    except FileNotFoundError:
        print("[WARN] Docker not found")

    return True

def publish_instructions():
    """Provide publishing instructions"""
    print("\n" + "="*60)
    print("[INSTRUCTIONS] MARM MCP Server Publishing Instructions")
    print("="*60)

    print("\n1. Initialize MCP Registry (first time only):")
    print("   mcp-publisher init")

    print("\n2. Login to MCP Registry:")
    print("   mcp-publisher login github-oidc  # or github-token/dns")

    print("\n3. Publish to PyPI (optional, for pip install):")
    print("   python -m build")
    print("   python -m twine upload dist/*")

    print("\n4. Build and push Docker image (optional):")
    print("   docker build -t lyellr88/marm-mcp-server:latest .")
    print("   docker push lyellr88/marm-mcp-server:latest")

    print("\n5. Publish to MCP Registry:")
    print("   mcp-publisher publish")

    print("\n6. Verify publication:")
    print("   Check: https://registry.modelcontextprotocol.io/servers/io.github.marm-systems/marm-mcp-server")

    print("\n" + "="*60)
    print("[OK] Ready to publish! Follow the steps above.")
    print("="*60)

def main():
    """Main publishing workflow"""
    print("[SETUP] MARM MCP Server Publishing Setup")
    print("=" * 40)

    # Check requirements
    if not check_requirements():
        sys.exit(1)

    # Install publisher
    install_mcp_publisher()

    # Setup authentication
    setup_authentication()

    # Build and test
    build_and_test()

    # Provide instructions
    publish_instructions()

if __name__ == "__main__":
    main()