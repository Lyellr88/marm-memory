"""Notebook endpoints for MARM MCP Server."""

from fastapi import HTTPException, APIRouter

from ..core.models import NotebookRequest
from ..services.notebook import notebook_dispatch

router = APIRouter(prefix="", tags=["Notebook"])


@router.post("/marm_notebook", operation_id="marm_notebook")
async def marm_notebook(request: NotebookRequest):
    """
    Handle notebook actions (add, use, show, status, clear) by delegating to the notebook dispatch service.
    
    Supported actions:
    - add: save or update an entry (requires `name` and `data`).
    - use: activate entries as instructions (requires `names`, comma-separated).
    - show: list saved entries with previews.
    - status: show currently active entries.
    - clear: clear the active entry list.
    
    Parameters:
        request (NotebookRequest): Request containing `action` and optional `name`, `data`, and `names` fields.
    
    Returns:
        dict: The result object returned by the dispatch service.
    
    Raises:
        HTTPException: Raised with status 400 if the dispatch result reports an error, or with status 500 for unexpected failures.
    """
    try:
        result = await notebook_dispatch(
            action=request.action,
            name=request.name,
            data=request.data,
            names=request.names,
        )
        if result.get("status") == "error":
            raise HTTPException(status_code=400, detail=result["message"])
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Notebook operation failed: {str(e)}")
