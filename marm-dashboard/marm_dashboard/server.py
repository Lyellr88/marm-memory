"""FastAPI app for the MARM Dashboard plugin."""

from pathlib import Path
from time import perf_counter
from typing import Literal, Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import __version__
from . import db
from .auth import auth_middleware, is_valid_key
from .config import MARM_API_KEY

STATIC_DIR = Path(__file__).parent / "static"

app = FastAPI(
    title="MARM Dashboard",
    description="Local UI for MARM memory (reads ~/.marm/marm_memory.db)",
    version=__version__,
)

app.middleware("http")(auth_middleware)


class MemoryCreate(BaseModel):
    content: str = Field(..., min_length=1)
    session_name: str = Field(..., min_length=1)
    context_type: Literal["general", "code", "project", "book"] = "general"


class MemoryUpdate(BaseModel):
    content: str = Field(..., min_length=1)
    context_type: Literal["general", "code", "project", "book"] = "general"


class NotebookUpsert(BaseModel):
    name: str = Field(..., min_length=1)
    data: str = ""


class SessionCreate(BaseModel):
    session_name: str = Field(..., min_length=1)


class UnlockRequest(BaseModel):
    api_key: str = Field(..., min_length=1)


@app.get("/health")
def health():
    return {
        "status": "ok",
        "auth_required": bool(MARM_API_KEY),
    }


@app.get("/api/mcp-status")
def api_mcp_status():
    import json as _json
    import urllib.error
    import urllib.request

    started = perf_counter()
    try:
        with urllib.request.urlopen(
            "http://127.0.0.1:8001/health", timeout=2.5
        ) as resp:
            body = _json.loads(resp.read())
            return {
                "reachable": True,
                "status_code": getattr(resp, "status", 200),
                "latency_ms": round((perf_counter() - started) * 1000, 1),
                "body": body,
            }
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as e:
        return {
            "reachable": False,
            "latency_ms": round((perf_counter() - started) * 1000, 1),
            "error": e.__class__.__name__,
        }


@app.post("/api/auth/unlock")
def api_unlock(body: UnlockRequest):
    """Verify key for browser UI; client keeps it in memory for API calls."""
    if not MARM_API_KEY:
        return {"ok": True, "auth_required": False}
    if not is_valid_key(body.api_key.strip()):
        raise HTTPException(status_code=401, detail="Invalid API key")
    return {"ok": True, "auth_required": True}


@app.get("/api/summary")
def api_summary():
    try:
        return db.get_summary()
    except FileNotFoundError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e


@app.post("/api/sessions", status_code=201)
def api_create_session(body: SessionCreate):
    try:
        db.add_session(body.session_name)
        return {"status": "created", "session_name": body.session_name.strip()}
    except FileNotFoundError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@app.delete("/api/sessions")
def api_delete_all_sessions():
    try:
        count = db.delete_all_sessions()
        return {"status": "deleted", "count": count}
    except FileNotFoundError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e


@app.delete("/api/sessions/{session_name}")
def api_delete_session(session_name: str):
    try:
        if not db.delete_session(session_name):
            raise HTTPException(status_code=404, detail="Session not found")
        return {"status": "deleted", "session_name": session_name}
    except FileNotFoundError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e


@app.get("/api/sessions")
def api_sessions(q: Optional[str] = None):
    try:
        return {"items": db.list_sessions(q=q)}
    except FileNotFoundError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e


@app.get("/api/session-names")
def api_session_names():
    try:
        return {"items": db.list_session_names()}
    except FileNotFoundError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e


@app.get("/api/memories")
def api_memories(
    session: Optional[str] = None,
    q: Optional[str] = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    try:
        return db.list_memories(session=session, q=q, limit=limit, offset=offset)
    except FileNotFoundError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e


@app.post("/api/memories", status_code=201)
def api_create_memory(body: MemoryCreate):
    try:
        memory_id = db.add_memory(body.content, body.session_name, body.context_type)
        return {"id": memory_id, "status": "created"}
    except FileNotFoundError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@app.put("/api/memories/{memory_id}")
def api_update_memory(memory_id: str, body: MemoryUpdate):
    try:
        if not db.update_memory(memory_id, body.content, body.context_type):
            raise HTTPException(status_code=404, detail="Memory not found")
        return {"status": "updated", "id": memory_id}
    except FileNotFoundError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@app.delete("/api/memories")
def api_delete_all_memories(session: Optional[str] = Query(None)):
    try:
        count = db.delete_all_memories(session=session)
        return {"status": "deleted", "count": count}
    except FileNotFoundError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e


@app.delete("/api/memories/{memory_id}")
def api_delete_memory(memory_id: str):
    try:
        if not db.delete_memory(memory_id):
            raise HTTPException(status_code=404, detail="Memory not found")
        return {"status": "deleted", "id": memory_id}
    except FileNotFoundError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e


@app.delete("/api/logs")
def api_delete_all_logs():
    try:
        count = db.delete_all_logs()
        return {"status": "deleted", "count": count}
    except FileNotFoundError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e


@app.get("/api/logs")
def api_logs(
    session: Optional[str] = None,
    q: Optional[str] = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    try:
        return db.list_logs(session=session, q=q, limit=limit, offset=offset)
    except FileNotFoundError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e


@app.delete("/api/logs/{log_id}")
def api_delete_log(log_id: str):
    try:
        if not db.delete_log(log_id):
            raise HTTPException(status_code=404, detail="Log entry not found")
        return {"status": "deleted", "id": log_id}
    except FileNotFoundError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e


@app.get("/api/notebook")
def api_notebook(q: Optional[str] = None):
    try:
        return {"items": db.list_notebook(q=q)}
    except FileNotFoundError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e


@app.post("/api/notebook", status_code=201)
def api_upsert_notebook(body: NotebookUpsert):
    try:
        db.upsert_notebook(body.name, body.data)
        return {"status": "saved", "name": body.name.strip()}
    except FileNotFoundError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@app.delete("/api/notebook")
def api_delete_all_notebook():
    try:
        count = db.delete_all_notebook()
        return {"status": "deleted", "count": count}
    except FileNotFoundError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e


@app.delete("/api/notebook/{name}")
def api_delete_notebook(name: str):
    try:
        if not db.delete_notebook(name):
            raise HTTPException(status_code=404, detail="Notebook entry not found")
        return {"status": "deleted", "name": name}
    except FileNotFoundError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e


@app.get("/")
async def root():
    index = STATIC_DIR / "index.html"
    if index.exists():
        return FileResponse(index)
    raise HTTPException(status_code=404, detail="Dashboard UI not found")


if STATIC_DIR.exists():
    app.mount("/assets", StaticFiles(directory=STATIC_DIR / "assets"), name="assets")
