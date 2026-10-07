import asyncio
import os
from collections.abc import Callable
from pathlib import Path
from typing import Literal

from fastapi import HTTPException
from pydantic import BaseModel, Field

from ..core import runtime_flags
from . import local_llm, model_discovery
from .analyst import profile as analyst_profile


class RuntimeLlmRequest(BaseModel):
    """A change to the optional local generative model.

    Both fields are optional and only what is sent is applied, so the toggle
    and the model picker do not each have to know the other's current value to
    avoid clobbering it.
    """

    enabled: bool | None = None
    #: An empty string clears the preference and returns to whatever is served.
    model: str | None = Field(default=None, max_length=512)
    #: An empty string clears the override and returns to MARM_LLM_URL.
    endpoint: str | None = Field(default=None, max_length=512)
    #: The analyst profile. An empty string returns to MARM_ANALYST_PROFILE.
    profile: Literal["", "general", "small", "large"] | None = None
    #: Whether Automated Guardrails may apply unattended; saved, so it beats
    #: MARM_ANALYST_AUTO_APPLY. An empty string returns to the environment.
    auto_apply: bool | Literal[""] | None = None


class RuntimeLlmRootRequest(BaseModel):
    """Add or remove a directory that Browse and discovery may look inside."""

    path: str = Field(min_length=1, max_length=4096)
    remove: bool = False


def _llm_status() -> dict:
    """Generation status, with the saved switch folded in."""
    status = local_llm.status()
    status["source"] = runtime_flags.source(runtime_flags.LLM_ENABLED)
    name, source = analyst_profile.selected_name()
    status["analyst_profile"] = {
        "name": name,
        "source": source,
        "profiles": {key: p.to_public() for key, p in analyst_profile.PROFILES.items()},
        "active": analyst_profile.resolve(name).to_public(),
    }
    from ..services.analyst import review

    status["analyst_auto_apply"] = {
        "enabled": review.auto_apply_allowed(),
        "source": runtime_flags.source(runtime_flags.ANALYST_AUTO_APPLY),
    }
    return status


def _served_id_for(model: dict, served: list[dict]) -> str | None:
    """The id a runtime would accept for this on-disk model, if any.

    Clicking a row in the installed list should select that model, and this is
    what decides whether it CAN be selected. A file on disk is only loadable by
    name if the runtime already knows about it -- Ollama loads any pulled tag
    on demand, LM Studio JIT-loads anything it has registered -- so a disk-only
    model that the runtime has never seen is not selectable however switchable
    the runtime is in general.

    Matched three ways because the two sides name the same model differently:
    Ollama's `llama3.2:8b` is exactly its manifest name, while LM Studio serves
    `publisher/repo` for a file discovery reports as
    `publisher/repo/weights.gguf`. Matching on path first is the most reliable
    where the runtime reports one at all.
    """
    path = str(model.get("path") or "")
    name = str(model.get("name") or "")
    stem = name.rsplit("/", 1)[-1]
    for entry in served:
        served_id = entry.get("id")
        if not served_id:
            continue
        served_path = entry.get("path")
        if served_path and path and str(served_path) == path:
            return str(served_id)
        if served_id == name or served_id == stem:
            return str(served_id)
        # `publisher/repo` against `publisher/repo/file.gguf`.
        if name.startswith(f"{served_id}/"):
            return str(served_id)
    return None


async def apply_llm_update(
    req: RuntimeLlmRequest, llm_status: Callable[[], dict]
) -> dict:
    """Apply one local-model change; `llm_status` builds the status returned after it."""
    if req.enabled is not None:
        runtime_flags.set_bool(runtime_flags.LLM_ENABLED, req.enabled)
    if req.profile is not None:
        # Chosen by the operator, never derived from the model being served.
        if req.profile:
            runtime_flags.set_(runtime_flags.ANALYST_PROFILE, req.profile)
        else:
            runtime_flags.clear(runtime_flags.ANALYST_PROFILE)
    if req.auto_apply == "":
        runtime_flags.clear(runtime_flags.ANALYST_AUTO_APPLY)
    elif req.auto_apply is not None:
        runtime_flags.set_bool(runtime_flags.ANALYST_AUTO_APPLY, req.auto_apply)

    applied_model: str | None = None
    rejected: str | None = None

    if req.endpoint is not None:
        chosen = req.endpoint.strip().rstrip("/")
        if not chosen:
            runtime_flags.clear(runtime_flags.LLM_ENDPOINT)
        elif local_llm._host(chosen) is None:
            rejected = f"{chosen} is not a valid URL: it has no host to connect to."
        elif not local_llm._is_loopback(chosen) and not local_llm.ALLOW_REMOTE:
            # Refused here as well as in `endpoint()`, so the Console gets a
            # reason rather than silently saving a value that will be ignored.
            # `ALLOW_REMOTE` has to be honoured for that to be true: `endpoint()`
            # accepts a non-loopback URL once the operator has stated the
            # override in full, and without this clause the Console refused to
            # save the very endpoint the server would then have used.
            rejected = (
                f"{chosen} is not a loopback address. MARM only talks to a model "
                "on this machine."
            )
        elif local_llm._is_marm_itself(chosen):
            rejected = f"{chosen} is MARM's own port. Point it at the model server."
        else:
            runtime_flags.set_(runtime_flags.LLM_ENDPOINT, chosen)
            # A different server serves different models, so a model chosen for
            # the old one is meaningless against the new one.
            runtime_flags.clear(runtime_flags.LLM_MODEL)
        local_llm.invalidate_settings_cache()
        local_llm.invalidate_servers_cache()
    if req.model is not None:
        chosen = req.model.strip()
        if not chosen:
            runtime_flags.clear(runtime_flags.LLM_MODEL)
        else:
            info = await asyncio.to_thread(local_llm.runtime_info, force=True)
            if not info.get("can_switch"):
                # Refusing rather than saving a preference that cannot take
                # effect. A stored choice the runtime ignores is exactly the
                # silent no-op this whole feature exists to avoid.
                rejected = info.get("reason") or (
                    "This runtime does not support selecting a model."
                )
            else:
                served = {
                    str(entry.get("id"))
                    for entry in (info.get("served") or [])
                    if entry.get("id")
                }
                if served and chosen not in served:
                    rejected = (
                        f"{chosen!r} is not served by {info.get('runtime')}. "
                        "Load it in that runtime first."
                    )
                else:
                    runtime_flags.set_(runtime_flags.LLM_MODEL, chosen)
                    applied_model = chosen

    local_llm.invalidate_settings_cache()
    status = await asyncio.to_thread(llm_status)
    if rejected:
        status["rejected"] = rejected
    if applied_model:
        status["applied_model"] = applied_model
    return {"status": "success", "llm": status}


async def update_llm_roots(req: RuntimeLlmRootRequest) -> dict:
    """Add or remove a directory that discovery and Browse may look inside."""
    target = Path(req.path).expanduser()
    saved = runtime_flags.get(runtime_flags.LLM_MODEL_ROOTS) or ""
    roots = [r for r in saved.split(os.pathsep) if r]

    if req.remove:
        roots = [r for r in roots if r != str(target)]
    else:
        if model_discovery.too_broad(target):
            raise HTTPException(
                status_code=422,
                detail=f"{target} is too broad to be a model directory.",
            )
        if not target.is_dir():
            raise HTTPException(
                status_code=422, detail=f"{target} is not a directory MARM can see."
            )
        if str(target) not in roots:
            roots.append(str(target))

    runtime_flags.set_(runtime_flags.LLM_MODEL_ROOTS, os.pathsep.join(roots))
    # The scan caches a resolved root list, so it has to be told.
    model_discovery.invalidate()
    # Named `configured_roots` because `discover()` also returns `roots` -- the
    # full candidate list with an `exists` flag -- and spreading it over a key
    # of the same name silently changed the shape depending on ordering.
    return {
        "status": "success",
        "configured_roots": roots,
        **(await asyncio.to_thread(model_discovery.discover, force=True)),
    }
