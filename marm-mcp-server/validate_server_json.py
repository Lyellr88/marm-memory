#!/usr/bin/env python3
"""
Validate server.json against MCP schema
"""
import json
import sys
import requests
import jsonschema
from pathlib import Path

def validate_server_json():
    """Validate the server.json file against the MCP schema"""

    # Load the server.json file
    server_json_path = Path(__file__).parent / "server.json"
    if not server_json_path.exists():
        print("❌ server.json not found")
        return False

    with open(server_json_path, 'r', encoding='utf-8') as f:
        server_config = json.load(f)

    print(f"[OK] Loaded server.json: {server_config['name']} v{server_config['version']}")

    # Fetch the schema
    schema_url = "https://static.modelcontextprotocol.io/schemas/2025-12-11/server.schema.json"
    print(f"[INFO] Fetching schema from {schema_url}")

    try:
        response = requests.get(schema_url, timeout=10)
        response.raise_for_status()
        schema = response.json()
        print("[OK] Schema downloaded successfully")
    except Exception as e:
        print(f"[ERROR] Failed to fetch schema: {e}")
        print("[WARN] Performing basic validation only")
        return validate_basic_structure(server_config)

    # Validate against schema
    try:
        jsonschema.validate(server_config, schema)
        print("[OK] server.json is valid according to MCP schema!")

        # Print summary
        print(f"\n[SUMMARY] Server Configuration Summary:")
        print(f"   Name: {server_config['name']}")
        print(f"   Version: {server_config['version']}")
        print(f"   Tools: {len(server_config.get('tools', []))}")
        print(f"   Packages: {len(server_config.get('packages', []))}")
        print(f"   Remotes: {len(server_config.get('remotes', []))}")

        return True

    except jsonschema.ValidationError as e:
        print(f"[ERROR] Validation error: {e.message}")
        print(f"   Path: {' -> '.join(str(p) for p in e.absolute_path)}")
        return False
    except Exception as e:
        print(f"[ERROR] Validation failed: {e}")
        return False

def validate_basic_structure(config):
    """Basic validation when schema is not available"""
    required_fields = ['name', 'description', 'version']

    for field in required_fields:
        if field not in config:
            print(f"[ERROR] Missing required field: {field}")
            return False

    print("[OK] Basic structure validation passed")
    return True

if __name__ == "__main__":
    success = validate_server_json()
    sys.exit(0 if success else 1)