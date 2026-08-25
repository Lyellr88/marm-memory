from fastapi import APIRouter

from ..core.models import NotebookRequest
from ..services.notebook import notebook_dispatch

router = APIRouter(prefix="", tags=["Notebook"])


@router.post("/marm_notebook", operation_id="marm_notebook")
async def marm_notebook(request: NotebookRequest) -> dict:
    """
    📔 Unified notebook — add, use, show, status, clear, or save

    action="add": save or update a scratch entry (name + data required)
    action="use": activate entries as instructions (names required, comma-separated)
    action="show": list scratch entries for this session with previews
    action="status": show currently active entries
    action="clear": clear the active entry list
    action="save": promote a scratch entry (or new data) into the permanent docs store
    """
    try:
        return await notebook_dispatch(
            action=request.action,
            name=request.name,
            data=request.data,
            names=request.names,
            session_name=request.session_name,
            project=request.project,
            platform=request.platform,
        )
    except Exception as e:
        print(f"Unexpected error in marm_notebook: {e}")
        return {"status": "error", "message": "Notebook operation failed."}
