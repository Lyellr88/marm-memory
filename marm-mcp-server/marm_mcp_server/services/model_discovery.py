"""Find the language models already on this machine, wherever they landed.

WHY SCAN DISK AT ALL WHEN THE ENDPOINT CAN BE ASKED
    Because `/v1/models` answers "what is loaded", and the question a reader
    actually has is "what could I load". On llama.cpp those differ by an order
    of magnitude: one served model against the dozen sitting in the directory
    next to it. The endpoint is authoritative about the present; the disk is
    the only source for the alternatives.

THE FOUR LAYOUTS THAT MATTER, AND WHY EACH NEEDS ITS OWN READER
    - LM Studio    `<root>/<publisher>/<repo>/<file>.gguf`. Plain files, and
                   the publisher/repo path IS the name people know it by.
    - Ollama       content-addressed. Weights are `blobs/sha256-<hex>` with no
                   extension and no name; the name lives in a manifest under
                   `manifests/<host>/<namespace>/<model>/<tag>`. Walking blobs
                   alone yields a list of hashes, which is useless to a reader,
                   so the manifest is the entry point and the blob is resolved
                   from it.
    - HuggingFace  `models--<org>--<name>/snapshots/<commit>/...`, where every
                   entry is a SYMLINK into `../../blobs/<etag>`. Following them
                   naively double-counts, and `os.path.getsize` on the link
                   reports the link, so size has to come from the resolved
                   target.
    - flat         a directory someone points `-m` at. No metadata at all.

WHAT THIS DELIBERATELY DOES NOT DO
    It does not open a single model file. Reading GGUF headers would give
    parameter counts and quantisation, and it would also mean parsing an
    attacker-influenced binary in a service six agents talk to, for a label.
    Everything here comes from paths, `stat`, and JSON the runtime wrote.
"""

from __future__ import annotations

import json
import os
import platform
import time
from pathlib import Path
from typing import Any, Iterator, Optional

import structlog

logger = structlog.get_logger(__name__)

#: Extensions that are a servable model rather than a sidecar. `.bin` is
#: deliberately absent: it collides with far too much that is not a model.
MODEL_SUFFIXES = frozenset({".gguf", ".safetensors", ".pt", ".pth", ".onnx"})

#: A projector is not a model -- it is loaded alongside one. Listing it as a
#: choice is how a reader ends up selecting something that cannot serve.
_NOT_A_MODEL = ("mmproj", "projector")

#: Scanning 62 GB of directory entries is not free, and the answer changes
#: when someone downloads a model, which is rare.
_TTL = float(os.environ.get("MARM_MODEL_SCAN_TTL") or 120.0)

#: A runaway tree must not hang the page that asked.
_MAX_DEPTH = 6
_MAX_RESULTS = 500

_cache: dict[str, Any] = {"at": 0.0, "value": None}


def _home() -> Path:
    return Path.home()


def _extra_roots() -> list[Path]:
    """Roots the operator added, from the saved flag and from the environment.

    This is how MARM is pointed at a directory it would never guess -- a
    second drive, a NAS mount, the directory a container bind-mounts. Both
    sources are read and merged rather than one overriding the other: the
    environment is how a deployment ships a default, the saved flag is what
    the Console writes, and losing either one would make the Console's "add a
    root" silently drop a directory the unit file had configured.
    """
    raw = os.environ.get("MARM_LLM_MODEL_ROOTS") or ""
    paths = [p for p in raw.split(os.pathsep) if p.strip()]
    try:
        from ..core import runtime_flags

        saved = runtime_flags.get(runtime_flags.LLM_MODEL_ROOTS) or ""
        paths.extend(p for p in saved.split(os.pathsep) if p.strip())
    except Exception:  # pragma: no cover - discovery must survive a flag read
        logger.debug("model_discovery: could not read the saved roots")
    roots = [Path(p).expanduser() for p in paths]
    return [r for r in roots if not too_broad(r)]


def too_broad(path: Path) -> bool:
    """A filesystem root, the home directory, or anything above it.

    Browse and the scan would then range over the whole disk.
    """
    try:
        resolved = path.expanduser().resolve()
        home = _home().resolve()
    except (OSError, RuntimeError):
        return True
    return resolved == Path(resolved.anchor) or home.is_relative_to(resolved)


def candidate_roots() -> list[dict[str, Any]]:
    """Every place a popular runtime stores models, on this OS.

    Returned whether or not it exists, with `exists` set, because "Ollama is
    not installed here" and "Ollama is installed and empty" are different
    answers and a reader looking for a missing model needs to tell them apart.
    """
    home = _home()
    system = platform.system()
    roots: list[tuple[str, Path]] = []

    # LM Studio keeps the same relative path on all three platforms.
    roots.append(("LM Studio", home / ".lmstudio" / "models"))
    roots.append(("LM Studio", home / ".cache" / "lm-studio" / "models"))

    # Ollama: OLLAMA_MODELS wins when set, which is how most people move it
    # off the system drive.
    env_ollama = os.environ.get("OLLAMA_MODELS")
    if env_ollama:
        roots.append(("Ollama", Path(env_ollama).expanduser()))
    roots.append(("Ollama", home / ".ollama" / "models"))
    if system == "Linux":
        # The packaged service runs as its own user, so the models are not
        # under the human's home at all.
        roots.append(("Ollama", Path("/usr/share/ollama/.ollama/models")))
        roots.append(("Ollama", Path("/var/lib/ollama/.ollama/models")))

    # HuggingFace, which is also where vLLM, TGI and transformers look.
    hf_hub = os.environ.get("HF_HUB_CACHE")
    hf_home = os.environ.get("HF_HOME")
    if hf_hub:
        roots.append(("HuggingFace", Path(hf_hub).expanduser()))
    elif hf_home:
        roots.append(("HuggingFace", Path(hf_home).expanduser() / "hub"))
    else:
        xdg = os.environ.get("XDG_CACHE_HOME")
        base = Path(xdg).expanduser() if xdg else home / ".cache"
        roots.append(("HuggingFace", base / "huggingface" / "hub"))

    # llama.cpp's own `-hf` download cache.
    if system == "Darwin":
        roots.append(("llama.cpp", home / "Library" / "Caches" / "llama.cpp"))
    else:
        roots.append(("llama.cpp", home / ".cache" / "llama.cpp"))
    roots.append(("node-llama-cpp", home / ".node-llama-cpp" / "models"))

    # GPT4All and Jan both use a plain directory of files.
    if system == "Darwin":
        roots.append(
            (
                "GPT4All",
                home / "Library" / "Application Support" / "nomic.ai" / "GPT4All",
            )
        )
    elif system == "Windows":
        local = os.environ.get("LOCALAPPDATA")
        if local:
            roots.append(("GPT4All", Path(local) / "nomic.ai" / "GPT4All"))
    else:
        roots.append(("GPT4All", home / ".local" / "share" / "nomic.ai" / "GPT4All"))
    roots.append(("Jan", home / "jan" / "models"))

    for extra in _extra_roots():
        roots.append(("Configured", extra))

    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for source, path in roots:
        key = str(path)
        if key in seen:
            continue
        seen.add(key)
        out.append(
            {
                "source": source,
                "path": key,
                "exists": path.is_dir(),
                "configured": source == "Configured",
            }
        )
    return out


def _size_of(path: Path) -> Optional[int]:
    """Size in bytes, resolving symlinks.

    The HuggingFace cache is entirely symlinks into `blobs/`, so a plain
    `lstat` here reports a few dozen bytes for a 5 GB model.
    """
    try:
        return path.stat().st_size
    except OSError:
        return None


def _is_model_file(path: Path) -> bool:
    if path.suffix.lower() not in MODEL_SUFFIXES:
        return False
    lowered = path.name.lower()
    return not any(marker in lowered for marker in _NOT_A_MODEL)


def _walk(root: Path, depth: int = 0) -> Iterator[Path]:
    """Bounded directory walk that survives what it cannot read.

    `os.scandir` rather than `rglob` so a single unreadable subdirectory --
    the Ollama system install, most often -- skips itself instead of aborting
    the traversal that contains it.
    """
    if depth > _MAX_DEPTH:
        return
    try:
        entries = list(os.scandir(root))
    except OSError:
        return
    for entry in entries:
        try:
            if entry.is_dir(follow_symlinks=False):
                yield from _walk(Path(entry.path), depth + 1)
            elif entry.is_file(follow_symlinks=True):
                yield Path(entry.path)
        except OSError:
            continue


def _ollama_models(root: Path) -> list[dict[str, Any]]:
    """Read Ollama's manifests, and resolve each to the blob it names.

    The manifest is an OCI image manifest: the weights are the layer whose
    mediaType ends `.model`, and its digest `sha256:<hex>` maps to the file
    `blobs/sha256-<hex>` -- colon to dash, which is the one transformation
    that makes this work and the one that is easy to get wrong.
    """
    manifests = root / "manifests"
    if not manifests.is_dir():
        return []
    found: list[dict[str, Any]] = []
    for manifest_path in _walk(manifests):
        try:
            with open(manifest_path) as handle:
                manifest = json.load(handle)
        except (OSError, ValueError):
            continue
        if not isinstance(manifest, dict):
            continue
        layers = manifest.get("layers")
        if not isinstance(layers, list):
            continue
        digest = None
        for layer in layers:
            if isinstance(layer, dict) and str(layer.get("mediaType", "")).endswith(
                ".model"
            ):
                digest = layer.get("digest")
                break
        if not isinstance(digest, str) or ":" not in digest:
            continue
        blob = root / "blobs" / digest.replace(":", "-")
        if not blob.is_file():
            continue
        # `.../manifests/<host>/<namespace>/<model>/<tag>` -> `model:tag`,
        # which is the string a person types at `ollama run`.
        parts = manifest_path.relative_to(manifests).parts
        name = f"{parts[-2]}:{parts[-1]}" if len(parts) >= 2 else manifest_path.name
        found.append(
            {
                "name": name,
                "path": str(blob),
                "size_bytes": _size_of(blob),
                "source": "Ollama",
                "format": "gguf",
                "root": str(root),
            }
        )
    return found


def _huggingface_models(root: Path) -> list[dict[str, Any]]:
    """One entry per cached repo revision, not one per shard.

    A sharded 70B is 15 `model-0000N-of-0000M.safetensors` files. Listing them
    individually would bury every other model in the dropdown and offer the
    reader fifteen choices that are all the same model, none of which can be
    loaded on its own.
    """
    found: list[dict[str, Any]] = []
    try:
        repos = [e for e in os.scandir(root) if e.is_dir()]
    except OSError:
        return []
    for repo in repos:
        if not repo.name.startswith("models--"):
            continue
        pretty = repo.name[len("models--") :].replace("--", "/")
        snapshots = Path(repo.path) / "snapshots"
        if not snapshots.is_dir():
            continue
        try:
            revisions = [e for e in os.scandir(snapshots) if e.is_dir()]
        except OSError:
            continue
        for revision in revisions:
            files = [p for p in _walk(Path(revision.path)) if _is_model_file(p)]
            if not files:
                continue
            total = sum(s for s in (_size_of(f) for f in files) if s is not None)
            suffix = files[0].suffix.lower().lstrip(".")
            found.append(
                {
                    "name": pretty,
                    "path": str(revision.path),
                    "size_bytes": total or None,
                    "source": "HuggingFace",
                    "format": suffix,
                    "root": str(root),
                    "shards": len(files),
                }
            )
    return found


def _plain_models(root: Path, source: str) -> list[dict[str, Any]]:
    """Every model file under a directory, named by its path below the root."""
    found = []
    for path in _walk(root):
        if not _is_model_file(path):
            continue
        try:
            name = str(path.relative_to(root))
        except ValueError:
            name = path.name
        found.append(
            {
                "name": name,
                "path": str(path),
                "size_bytes": _size_of(path),
                "source": source,
                "format": path.suffix.lower().lstrip("."),
                "root": str(root),
            }
        )
    return found


def discover(force: bool = False) -> dict[str, Any]:
    """Everything servable this machine has, with where it came from.

    Sorted largest first: on a box with a dozen models the interesting ones
    are the big ones, and a reader scanning for "the 27B" should not have to
    page past eight 300 MB embedding models to find it.
    """
    now = time.monotonic()
    cached = _cache["value"]
    if not force and cached is not None and (now - float(_cache["at"])) < _TTL:
        return dict(cached)

    roots = candidate_roots()
    models: list[dict[str, Any]] = []
    started = time.monotonic()
    for entry in roots:
        if not entry["exists"]:
            continue
        root = Path(entry["path"])
        source = entry["source"]
        try:
            if source == "Ollama":
                models.extend(_ollama_models(root))
            elif source == "HuggingFace":
                models.extend(_huggingface_models(root))
            else:
                models.extend(_plain_models(root, source))
        except Exception:  # pragma: no cover - a scan must never escape
            logger.exception("model_discovery: scanning a root raised", root=str(root))

    # De-duplicate on the resolved path: LM Studio and a configured root can
    # be the same directory reached two ways, and the same file must not be
    # offered twice.
    unique: dict[str, dict[str, Any]] = {}
    for model in models:
        try:
            key = str(Path(model["path"]).resolve())
        except OSError:
            key = model["path"]
        unique.setdefault(key, model)

    ordered = sorted(
        unique.values(), key=lambda m: (-(m.get("size_bytes") or 0), m["name"])
    )
    truncated = len(ordered) > _MAX_RESULTS
    value = {
        "models": ordered[:_MAX_RESULTS],
        "roots": roots,
        "total": len(ordered),
        "truncated": truncated,
        "scan_seconds": round(time.monotonic() - started, 3),
    }
    if truncated:
        # Same rule the recall scan follows: a list that silently stops is a
        # list that lies about what is on the machine.
        value["note"] = (
            f"Found {len(ordered):,} models; showing the {_MAX_RESULTS:,} largest. "
            "Narrow the search by configuring MARM_LLM_MODEL_ROOTS."
        )
    _cache["at"] = now
    _cache["value"] = value
    return dict(value)


def invalidate() -> None:
    """Drop the scan cache, for when a root is added from the Console."""
    _cache["at"] = 0.0
    _cache["value"] = None


def _allowed_roots() -> list[Path]:
    """The directories Browse may look inside, fully resolved.

    Resolved once here so containment is decided on real paths. A root that is
    itself a symlink would otherwise compare unequal to the resolved child
    beneath it, and every listing under it would be refused.
    """
    roots = []
    for entry in candidate_roots():
        if not entry["exists"]:
            continue
        try:
            roots.append(Path(entry["path"]).resolve())
        except OSError:
            continue
    return roots


def _contained(target: Path, roots: list[Path]) -> bool:
    """Whether `target` is inside one of `roots`, after symlinks.

    THE RESOLUTION IS THE CHECK. Comparing the path as typed would let
    `<root>/../../etc` pass a prefix test and then read somewhere else
    entirely, and on a machine where a model directory is a symlink to another
    drive -- which is the normal way people put 60 GB of weights on a second
    disk -- an unresolved comparison also wrongly refuses the legitimate case.
    """
    for root in roots:
        try:
            if target == root or target.is_relative_to(root):
                return True
        except (OSError, ValueError):
            continue
    return False


def browse(path: Optional[str] = None) -> dict[str, Any]:
    """List directories and model files under one of the known model roots.

    Scoped rather than free-range on purpose. This is a filesystem-reading API
    on a service six agents talk to, so it answers only inside directories a
    model runtime already uses, plus whatever the operator added themselves.
    It never returns file contents -- only names, sizes and types.
    """
    roots = _allowed_roots()
    listing: dict[str, Any] = {
        "roots": [str(r) for r in roots],
        "path": None,
        "parent": None,
        "entries": [],
    }
    if path is None:
        return listing

    try:
        target = Path(path).expanduser().resolve()
    except (OSError, ValueError):
        return {**listing, "error": "That path could not be resolved."}

    if not _contained(target, roots):
        # Naming the roots rather than just refusing: the usual cause is a
        # model kept somewhere MARM was never told about, and the fix is to
        # add that directory as a root, which the reader cannot guess.
        return {
            **listing,
            "error": (
                "That path is outside every known model directory. Add it as a "
                "root first if you keep models there."
            ),
        }
    if not target.is_dir():
        return {**listing, "error": "That path is not a directory."}

    entries: list[dict[str, Any]] = []
    try:
        for entry in sorted(os.scandir(target), key=lambda e: e.name.lower()):
            try:
                if entry.is_dir(follow_symlinks=True):
                    entries.append(
                        {"name": entry.name, "path": entry.path, "kind": "directory"}
                    )
                elif _is_model_file(Path(entry.path)):
                    entries.append(
                        {
                            "name": entry.name,
                            "path": entry.path,
                            "kind": "model",
                            "size_bytes": _size_of(Path(entry.path)),
                        }
                    )
            except OSError:
                continue
    except OSError:
        return {**listing, "error": "That directory could not be read."}

    parent = target.parent
    return {
        **listing,
        "path": str(target),
        # A parent outside every root is not offered, so Browse cannot be
        # walked upward out of the directories it is scoped to.
        "parent": str(parent) if _contained(parent, roots) else None,
        "entries": entries,
    }


def validate(path: str) -> dict[str, Any]:
    """Whether a path is something MARM could hand a runtime as a model.

    Deliberately permissive about WHAT the model is and strict about whether
    it exists and is readable. MARM does not load the file, so judging a GGUF
    by its header would be asserting something it never verifies; judging that
    the file is there and the process can open it is exactly what MARM knows.
    """
    try:
        target = Path(path).expanduser().resolve()
    except (OSError, ValueError):
        return {"valid": False, "reason": "That path could not be resolved."}
    if target.is_dir():
        shards = [p for p in _walk(target) if _is_model_file(p)]
        if not shards:
            return {
                "valid": False,
                "reason": "That directory holds no model files.",
                "path": str(target),
            }
        return {
            "valid": True,
            "path": str(target),
            "kind": "directory",
            "shards": len(shards),
            "size_bytes": sum(s for s in (_size_of(p) for p in shards) if s),
        }
    if not target.is_file():
        return {"valid": False, "reason": "No such file.", "path": str(target)}
    if not _is_model_file(target):
        known = ", ".join(sorted(MODEL_SUFFIXES))
        return {
            "valid": False,
            "reason": f"Not a recognised model file. Expected one of: {known}.",
            "path": str(target),
        }
    if not os.access(target, os.R_OK):
        return {
            "valid": False,
            "reason": "The MARM process cannot read that file.",
            "path": str(target),
        }
    return {
        "valid": True,
        "path": str(target),
        "kind": "file",
        "size_bytes": _size_of(target),
        "format": target.suffix.lower().lstrip("."),
    }
