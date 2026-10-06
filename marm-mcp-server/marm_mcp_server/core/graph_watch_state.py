import hashlib
import os
import subprocess
import sys
from pathlib import Path
from typing import Optional

import structlog

logger = structlog.get_logger(__name__)

_GIT_TIMEOUT_SECONDS = 15

_UNBORN_HEAD = ""


def _git_env() -> dict[str, str]:
    """A scrubbed environment for a git call on a user-chosen repository.

    Inherited GIT_* variables belong to whatever launched the server, not to the
    repo being polled, and GIT_DIR or GIT_WORK_TREE would point our -C somewhere
    else entirely. GIT_OPTIONAL_LOCKS=0 keeps a status check from taking
    .git/index.lock and rewriting the index -- which matters even more now than
    it used to: a watcher would see that rewrite as a change and re-trigger the
    very check that caused it.
    """
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env["GIT_OPTIONAL_LOCKS"] = "0"
    return env


def _git(root: str, *args: str) -> Optional[str]:
    """Run one git command in `root`. None means "could not tell", never "no change".

    core.fsmonitor names a program git will execute, and it is read from the
    polled repository's own config: honoring it would let any repo MARM watches
    run a program of its choosing whenever this fires.
    """
    creationflags = 0
    if sys.platform == "win32":
        creationflags = subprocess.CREATE_NO_WINDOW
    try:
        proc = subprocess.run(
            ["git", "-c", "core.fsmonitor=false", "-C", root, *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="surrogateescape",
            timeout=_GIT_TIMEOUT_SECONDS,
            env=_git_env(),
            creationflags=creationflags,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        logger.debug("graph_auto_index.git_failed", root=root, error=str(exc))
        return None
    if proc.returncode != 0:
        return None
    return proc.stdout.strip()


def is_git_repo(root: str) -> bool:
    return (Path(root) / ".git").exists()


def git_source_state(root: str) -> Optional[tuple[str, str]]:
    """(HEAD, content_hash) for the repo AT `root`, or None if git could not answer.

    content_hash is sensitive to the bytes that changed, not just which paths
    are dirty. It combines the diff against HEAD -- covers staged and unstaged
    changes to tracked files in one command -- with a content hash of every
    non-ignored untracked path, so a second edit to an already-dirty file, or
    a same-length edit to an untracked one, produces a new signature. Nothing
    here is logged; only the digest is ever kept.

    A None result must be treated as "no change". Re-indexing on a git error
    would turn a broken repo into a re-index on every single evaluation.

    The `.git` check is not redundant with the caller's. Git's repository
    discovery walks upward from `-C`, so on a directory that is not itself a
    repo this would report an ancestor's state: an indexed subdirectory of some
    other repo would then re-index whenever anything anywhere in that parent
    changed.
    """
    if not is_git_repo(root):
        return None
    head = _git(root, "rev-parse", "HEAD")
    if head is None:
        if _git(root, "rev-parse", "--is-inside-work-tree") != "true":
            return None
        head = _UNBORN_HEAD
        unborn = True
    else:
        unborn = False

    diff_output: str
    if unborn:
        diff_cached = _git(root, "diff", "--no-ext-diff", "--no-textconv", "--cached")
        if diff_cached is None:
            return None
        diff_unstaged = _git(root, "diff", "--no-ext-diff", "--no-textconv")
        if diff_unstaged is None:
            return None
        diff_output = diff_cached + "\x1e" + diff_unstaged
    else:
        diff_head = _git(root, "diff", "--no-ext-diff", "--no-textconv", "HEAD")
        if diff_head is None:
            return None
        diff_output = diff_head

    untracked_raw = _git(root, "ls-files", "--others", "--exclude-standard", "-z")
    if untracked_raw is None:
        return None
    fingerprints = []
    for path in untracked_raw.split("\x00"):
        if not path:
            continue
        full_path = os.path.join(root, path)
        try:
            if os.path.islink(full_path):
                target_text = os.readlink(full_path)
                digest = hashlib.sha256(
                    target_text.encode("utf-8", "surrogateescape")
                ).hexdigest()
            else:
                hasher = hashlib.sha256()
                with open(full_path, "rb") as fh:
                    for chunk in iter(lambda: fh.read(1 << 20), b""):
                        hasher.update(chunk)
                digest = hasher.hexdigest()
        except OSError:
            continue
        fingerprints.append(f"{path}:{digest}")

    digest_input = "\x1f".join([diff_output, *sorted(fingerprints)])
    content_hash = hashlib.sha256(
        digest_input.encode("utf-8", "surrogateescape")
    ).hexdigest()
    return (head, content_hash)


class _Watched:
    """Per-project watch state. Disposable in memory: the durable baseline
    lives in graph_watch_state, so losing this costs at most one extra
    re-index rather than a wrong "unchanged" verdict."""

    __slots__ = (
        "content_hash",
        "debounce_deadline",
        "evaluated_generation",
        "failed",
        "generation",
        "git_head",
        "is_git",
        "last_index_reason",
        "last_indexed",
        "reconcile_deadline",
        "retry_after",
        "root",
        "watch_mode",
    )

    def __init__(self, root: str) -> None:
        self.root = root
        self.is_git = is_git_repo(root)
        self.git_head: Optional[str] = None
        self.content_hash: Optional[str] = None
        self.last_indexed: Optional[str] = None
        self.last_index_reason: Optional[str] = None
        self.retry_after: float = 0.0
        self.failed = False
        self.generation = 0
        self.evaluated_generation = 0
        self.debounce_deadline: Optional[float] = None
        self.reconcile_deadline: float = float("-inf")
        self.watch_mode = "disabled"
