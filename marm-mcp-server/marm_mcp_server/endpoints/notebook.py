"""Notebook endpoints for MARM MCP Server."""

from fastapi import APIRouter

from ..core.models import NotebookRequest
from ..services.notebook import notebook_dispatch

router = APIRouter(prefix="", tags=["Notebook"])


@router.post("/marm_notebook", operation_id="marm_notebook")
async def marm_notebook(request: NotebookRequest):
    """
    📔 Unified notebook — add, use, show, status, or clear

    action="add": save or update an entry (name + data required)
    action="use": activate entries as instructions (names required, comma-separated)
    action="show": list all saved entries with previews
    action="status": show currently active entries
    action="clear": clear the active entry list
    """
    try:
        return await notebook_dispatch(
            action=request.action,
            name=request.name,
            data=request.data,
            names=request.names,
            session_name=request.session_name,
        )
    except Exception as e:
        print(f"Unexpected error in marm_notebook: {e}")
        return {"status": "error", "message": "Notebook operation failed."}
