"""
Docker Manager for MARM CLI
Handles starting/stopping Ollama Docker container
"""

import subprocess
import time
import requests
from typing import Optional

class DockerManager:
    def __init__(self, container_name: str = "marm-ollama"):
        self.container_name = container_name
        self.ollama_url = "http://localhost:11434"

    def is_container_running(self) -> bool:
        """Check if Ollama container is running"""
        try:
            result = subprocess.run(
                ["docker", "ps", "--filter", f"name={self.container_name}", "--format", "{{.Names}}"],
                capture_output=True,
                text=True,
                check=True
            )
            return self.container_name in result.stdout
        except subprocess.CalledProcessError:
            return False

    def is_ollama_ready(self) -> bool:
        """Check if Ollama API is responding"""
        try:
            response = requests.get(f"{self.ollama_url}/api/tags", timeout=2)
            return response.status_code == 200
        except:
            return False

    def get_container_health(self) -> Optional[str]:
        """Get container health status (healthy, unhealthy, starting, or None)"""
        try:
            result = subprocess.run(
                ["docker", "inspect", "--format", "{{.State.Health.Status}}", self.container_name],
                capture_output=True,
                text=True,
                check=True
            )
            health = result.stdout.strip()
            return health if health else None
        except subprocess.CalledProcessError:
            return None

    def start_container(self, wait_for_ready: bool = True) -> bool:
        """Start Ollama container"""
        if self.is_container_running():
            print(f"✓ {self.container_name} is already running")
            return True

        print(f"Starting {self.container_name}...")
        try:
            # Start using docker-compose
            subprocess.run(
                ["docker-compose", "up", "-d"],
                check=True,
                cwd=r"C:\Users\lyell\Desktop\MARM-Systems\marm-cli"
            )

            if wait_for_ready:
                print("Waiting for Ollama to be ready...")
                for i in range(30):  # Wait up to 30 seconds
                    if self.is_ollama_ready():
                        print("✓ Ollama is ready!")
                        return True
                    time.sleep(1)
                print("⚠ Ollama started but API not responding")
                return False

            return True
        except subprocess.CalledProcessError as e:
            print(f"✗ Failed to start container: {e}")
            return False

    def stop_container(self) -> bool:
        """Stop Ollama container"""
        if not self.is_container_running():
            print(f"✓ {self.container_name} is not running")
            return True

        print(f"Stopping {self.container_name}...")
        try:
            subprocess.run(
                ["docker-compose", "down"],
                check=True,
                cwd=r"C:\Users\lyell\Desktop\MARM-Systems\marm-cli"
            )
            print("✓ Container stopped")
            return True
        except subprocess.CalledProcessError as e:
            print(f"✗ Failed to stop container: {e}")
            return False

    def pull_model(self, model_name: str = "codellama:13b") -> bool:
        """Pull a model inside the Docker container"""
        if not self.is_container_running():
            print("Container not running, starting it first...")
            if not self.start_container():
                return False

        print(f"Pulling model {model_name}...")
        try:
            subprocess.run(
                ["docker", "exec", self.container_name, "ollama", "pull", model_name],
                check=True
            )
            print(f"✓ Model {model_name} pulled successfully")
            return True
        except subprocess.CalledProcessError as e:
            print(f"✗ Failed to pull model: {e}")
            return False

    def ensure_running(self) -> bool:
        """Ensure container is running, start if needed"""
        if self.is_container_running() and self.is_ollama_ready():
            return True
        return self.start_container()


if __name__ == "__main__":
    # Test the manager
    manager = DockerManager()

    print("=== Docker Manager Test ===")
    print(f"Container running: {manager.is_container_running()}")
    print(f"Ollama ready: {manager.is_ollama_ready()}")

    # Start if not running
    manager.ensure_running()
