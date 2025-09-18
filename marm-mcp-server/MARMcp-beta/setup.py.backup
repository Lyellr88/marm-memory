#!/usr/bin/env python3
"""
MARM MCP Server - Professional Windows Installer
Handles Python environment setup, dependency management, and validation.
"""

import sys
import subprocess
import os
import urllib.request
from pathlib import Path

class MARMInstaller:
    def __init__(self):
        self.python_min = (3, 8)
        self.venv_name = "marm-env"
        
    def check_python_version(self):
        """Validate Python version requirements"""
        print("🔍 Checking Python version...")
        
        if sys.version_info < self.python_min:
            print(f"❌ Python {self.python_min[0]}.{self.python_min[1]}+ required")
            print(f"   Found: {sys.version_info.major}.{sys.version_info.minor}")
            sys.exit(1)
            
        print(f"✅ Python {sys.version_info.major}.{sys.version_info.minor} detected")
    
    def run_command(self, cmd, description):
        """Execute command with error handling"""
        print(f"▶️  {description}")
        try:
            # Use shell=False for security - split command into list
            if isinstance(cmd, str):
                cmd = cmd.split()
            result = subprocess.run(cmd, shell=False, check=True,
                                  capture_output=True, text=True)
            return result.stdout
        except subprocess.CalledProcessError as e:
            print(f"❌ Failed: {description}")
            print(f"   Error: {e.stderr}")
            sys.exit(1)
    
    def create_virtual_env(self):
        """Create and activate virtual environment"""
        if Path(self.venv_name).exists():
            print("♻️  Using existing virtual environment")
        else:
            self.run_command(f"python -m venv {self.venv_name}", 
                           "Creating virtual environment")
    
    def install_dependencies(self):
        """Install Python packages from requirements.txt"""
        pip_path = Path(self.venv_name) / "Scripts" / "pip.exe"
        python_path = Path(self.venv_name) / "Scripts" / "python.exe"
        
        # Upgrade pip
        self.run_command(f'"{pip_path}" install --upgrade pip', 
                        "Upgrading pip")
        
        # Install requirements
        self.run_command(f'"{pip_path}" install -r requirements.txt', 
                        "Installing MARM dependencies")
        
        # Pre-download ML models
        print("🧠 Pre-downloading AI models...")
        model_code = """
from sentence_transformers import SentenceTransformer
import sys
try:
    print('Downloading semantic model...')
    SentenceTransformer('all-MiniLM-L6-v2')
    print('✅ AI models ready!')
except Exception as e:
    print(f'⚠️  Model download failed: {e}')
    sys.exit(1)
"""
        
        with open("_temp_model_download.py", "w") as f:
            f.write(model_code)
            
        try:
            self.run_command(f'"{python_path}" _temp_model_download.py', 
                           "Downloading AI models")
        finally:
            if Path("_temp_model_download.py").exists():
                os.remove("_temp_model_download.py")
    
    def validate_installation(self):
        """Run system checks"""
        python_path = Path(self.venv_name) / "Scripts" / "python.exe"
        self.run_command(f'"{python_path}" server.py --check-deps', 
                        "Validating installation")
    
    def show_completion_message(self):
        """Display usage instructions"""
        print("\n" + "="*50)
        print("✅ MARM MCP Server installed successfully!")
        print("="*50)
        print("\n🔧 To start the server:")
        print(f"   {self.venv_name}\\Scripts\\python.exe server.py")
        print("\n🔗 Connect to Claude Desktop:")
        print("   Add MCP server: http://localhost:8001")
        print("\n💡 Tip: Keep this terminal window for easy access")
    
    def install(self):
        """Main installation process"""
        try:
            print("🚀 MARM MCP Server Installation")
            print("="*50)
            
            self.check_python_version()
            self.create_virtual_env()
            self.install_dependencies()
            self.validate_installation()
            self.show_completion_message()
            
        except KeyboardInterrupt:
            print("\n❌ Installation cancelled by user")
            sys.exit(1)
        except Exception as e:
            print(f"\n❌ Installation failed: {e}")
            sys.exit(1)

if __name__ == "__main__":
    installer = MARMInstaller()
    installer.install()
