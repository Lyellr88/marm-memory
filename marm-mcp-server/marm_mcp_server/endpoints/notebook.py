from typing import Literal, Optional

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict

from ..core.models import NotebookRequest, RedactionSummary
from ..services.notebook import notebook_dispatch


class _ResponseModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class NotebookAddedResponse(_ResponseModel):
    status: Literal["success"]
    message: str
    name: str
    redacted: Optional[RedactionSummary] = None


class NotebookActiveEntry(_ResponseModel):
    name: str
    data: str


class NotebookUsedResponse(_ResponseModel):
    status: Literal["success"]
    message: str
    activated_entries: list[str]
    entries: list[NotebookActiveEntry]


class NotebookEntryPreview(_ResponseModel):
    name: str
    preview: str
    created_at: Optional[str]
    updated_at: Optional[str]


class NotebookShownResponse(_ResponseModel):
    status: Literal["success"]
    message: str
    entries: list[NotebookEntryPreview]
    total_count: int


class NotebookStatusResponse(_ResponseModel):
    status: Literal["success"]
    message: str
    active_entries: list[str]
    entries: list[NotebookActiveEntry]
    active_count: int


class NotebookClearedResponse(_ResponseModel):
    status: Literal["success"]
    message: str
    active_count: int


class NotebookSavedResponse(_ResponseModel):
    status: Literal["success"]
    message: str
    doc_id: int
    memory_id: Optional[str]
    mirror_status: Literal["synced", "pending"]
    redacted: Optional[RedactionSummary] = None


class NotebookErrorResponse(_ResponseModel):
    status: Literal["error"]
    message: str


NotebookResponse = (
    NotebookAddedResponse
    | NotebookUsedResponse
    | NotebookShownResponse
    | NotebookStatusResponse
    | NotebookClearedResponse
    | NotebookSavedResponse
    | NotebookErrorResponse
)


router = APIRouter(prefix="", tags=["Notebook"])


@router.post(
    "/marm_notebook",
    operation_id="marm_notebook",
    response_model=NotebookResponse,
    response_model_exclude_unset=True,
)
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
