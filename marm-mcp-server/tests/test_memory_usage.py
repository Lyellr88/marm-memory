"""
Test and benchmark the server's memory usage, particularly after loading
the semantic search model at startup.

This is not a standard pytest file, but a runnable script to get a
real-world memory footprint measurement.

Usage:
1. Make sure you have psutil installed:
   pip install psutil
2. Run the script from the 'mcp-refactor' directory:
   python tests/test_memory_usage.py
"""

import os
import sys
import asyncio
import psutil
from fastapi import FastAPI

# Add the project root to the Python path to allow for correct imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from server import app  # Import the FastAPI app instance

def get_memory_usage_mb():
    """Returns the memory usage of the current process in megabytes."""
    process = psutil.Process(os.getpid())
    # rss (Resident Set Size) is a good measure of the actual memory the process is using.
    return process.memory_info().rss / (1024 * 1024)

async def run_startup_events(app_instance: FastAPI):
    """Manually trigger the startup events of a FastAPI application."""
    if app_instance.router.lifespan:
        # Modern lifespan context manager
        async with app_instance.router.lifespan_context(app_instance):
            pass
    else:
        # Legacy on_event handlers
        for event in app_instance.router.on_startup:
            await event()

async def main():
    """Main function to run the memory usage test."""
    print("--- MARM Server Memory Usage Test ---")
    
    # 1. Measure memory before startup
    mem_before = get_memory_usage_mb()
    print(f"Initial memory usage: {mem_before:.2f} MB")
    
    # 2. Manually trigger the application's startup events
    # This will load the documentation and the large sentence-transformer model.
    print("\nTriggering server startup events (this will load the model)...")
    await run_startup_events(app)
    print("Startup events complete.")
    
    # 3. Measure memory after startup
    mem_after = get_memory_usage_mb()
    print(f"\nMemory usage after startup: {mem_after:.2f} MB")
    
    # 4. Report the results
    model_load_cost = mem_after - mem_before
    print("\n--- Results ---")
    print(f"The semantic search model and initial data load increased memory usage by: {model_load_cost:.2f} MB")
    print("-----------------")

if __name__ == "__main__":
    asyncio.run(main())
