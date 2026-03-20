# MARM MCP Server - Docker Packaging Plan

**Last Updated:** 2025-09-04

## Goal

To package the entire Python MCP server, including all its code, dependencies, and the `GitHub docs` folder, into a single, self-contained **Docker image**.

This will make the server incredibly easy for you or any other user to run with a single command, without needing to install Python or download the documentation separately.

---

## The Plan

This is a three-step plan that we will execute next session.

### Step 1: Create the `Dockerfile`

We will create a `Dockerfile` in the `marm-mcp-server` directory. This file contains the instructions for Docker to build the image.

**`Dockerfile` Content:**

```dockerfile
# 1. Start with a lean, official Python base image
# (This is like a mini-operating system with Python pre-installed)
FROM python:3.11-slim

# 2. Set the working directory inside the container
# (This is where our application will live)
WORKDIR /app

# 3. Copy the requirements file first to leverage Docker's layer caching
# (This is an optimization so Docker doesn't reinstall dependencies every time)
COPY requirements.txt .

# 4. Install the Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# 5. Copy the rest of the application, including the 'GitHub docs' folder
# (This bundles all our code and documents into the image)
COPY . .

# 6. Expose the port the server will run on
# (This tells Docker that our application listens on port 8001)
EXPOSE 8001

# 7. Define the command to run the application when the container starts
CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8001"]
```

### Step 2: Make the Database Persistent (A Critical Change)

Right now, `server.py` saves the database to `marm_memory.db` in the same folder. In Docker, this is temporary. If we remove the container, the database and all the user's memory will be deleted.

We will make one small change to `server.py` to save the database to a special `/data` directory. This will allow us to store the database *outside* the container, making it permanent.

**Change in `server.py`:**

```python
# We will change this line in the MARMMemory class:
class MARMMemory:
    def __init__(self, db_path: str = "/data/marm_memory.db"): # Changed from "marm_memory.db"
        # ... rest of the code
```

### Step 3: Build and Run the Container

Once the files are ready, we will use these commands to build and run the server.

**To Build the Image:**
(This command packages everything into an image named `marm-mcp-server`)

```bash
docker build -t marm-mcp-server .
```

**To Run the Server:**
(This command starts the server and connects our permanent database folder)

```bash
docker run -d -p 8001:8001 --name marm-server -v ./marm_db_data:/data marm-mcp-server
```

* **`-v ./marm_db_data:/data` (The important part):** This creates a folder on your computer named `marm_db_data` and links it to the `/data` folder inside the container. The `marm_memory.db` file will be saved here, so it will be safe even if we stop or remove the container.

---

## End Result

After these steps, the entire MCP server will be running in a professional, self-contained Docker container. The user's memory will be safely stored on their computer, and starting the server will be as simple as one command.
