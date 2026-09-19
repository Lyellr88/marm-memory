"""What accelerator this machine has, and how much of its memory is free.

WHY THIS IS SHELLING OUT RATHER THAN BINDING A LIBRARY
    The obvious answer is `pynvml`. It is also the wrong one here: it covers
    one vendor, it is a dependency MARM does not otherwise need, and on a
    machine with no NVIDIA driver it is dead weight that still has to be
    installed. `nvidia-smi`, `rocm-smi` and `system_profiler` ship WITH the
    driver they report on -- if the tool is missing, so is the GPU, which is
    exactly the answer we want. So this shells out, and treats "the command is
    not there" as a negative result rather than an error.

WHY EVERY FAILURE IS A MISSING FIELD RATHER THAN AN EXCEPTION
    This feeds a diagnostics pane. A pane that cannot render because a GPU
    probe raised is worse than a pane that says it could not tell -- and the
    machines most likely to make a probe fail (no driver, a container without
    /dev/nvidia*, an unusual vendor) are precisely the ones whose owners need
    the rest of the page. Nothing in here raises.

ON APPLE SILICON THERE IS NO SUCH THING AS FREE VRAM
    The GPU shares one pool with the CPU, so "VRAM total" is the machine's RAM
    and "free" is a moving target that belongs to the whole system. Reporting
    a unified figure as though it were dedicated video memory would tell a Mac
    owner they have 64 GB to spend on a model. `unified` says which it is, and
    the Console renders the two differently.
"""

from __future__ import annotations

import json
import os
import platform
import re
import shutil
import subprocess  # nosec B404 - fixed argv, no shell, vendor tools only
import time
from typing import Any, Optional

import structlog

logger = structlog.get_logger(__name__)

#: A probe costs a process spawn. Utilisation moves fast, totals never do, and
#: this is read by a page that polls -- so cache briefly rather than never.
_TTL = float(os.environ.get("MARM_GPU_PROBE_TTL") or 5.0)

#: A vendor tool that has wedged must not wedge the Console with it.
_TIMEOUT = 4.0

_cache: dict[str, Any] = {"at": 0.0, "value": None}


def _run(argv: list[str]) -> Optional[str]:
    """Run a vendor tool, or return None. Never raises, never uses a shell."""
    if not shutil.which(argv[0]):
        return None
    try:
        done = subprocess.run(  # nosec B603 - fixed argv from this module only
            argv,
            capture_output=True,
            text=True,
            timeout=_TIMEOUT,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        logger.debug("hardware: probe failed", tool=argv[0], error=str(exc))
        return None
    if done.returncode != 0:
        return None
    return done.stdout


def _int(value: str) -> Optional[int]:
    try:
        return int(float(value.strip().split()[0]))
    except (ValueError, IndexError):
        return None


def _nvidia() -> list[dict[str, Any]]:
    """NVIDIA, via the tool that ships with the driver.

    `nounits` matters: with units the CSV carries " MiB" on every cell and
    every parse has to strip it. The query order below is the field order in
    the row, so the two must be changed together.
    """
    out = _run(
        [
            "nvidia-smi",
            "--query-gpu=name,memory.total,memory.used,memory.free,"
            "utilization.gpu,driver_version",
            "--format=csv,noheader,nounits",
        ]
    )
    if not out:
        return []
    gpus = []
    for index, line in enumerate(out.strip().splitlines()):
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 6:
            continue
        total, used, free = _int(parts[1]), _int(parts[2]), _int(parts[3])
        gpus.append(
            {
                "index": index,
                "vendor": "NVIDIA",
                "name": parts[0],
                "memory_total_mb": total,
                "memory_used_mb": used,
                "memory_free_mb": free,
                "utilisation_percent": _int(parts[4]),
                "driver": parts[5] or None,
                "unified": False,
            }
        )
    return gpus


def _amd() -> list[dict[str, Any]]:
    """AMD, preferring sysfs over `rocm-smi`.

    sysfs is there whenever amdgpu is loaded, needs no ROCm install, and does
    not change its output format between releases -- `rocm-smi --json` has
    done both. The CLI is the fallback, not the first choice.
    """
    gpus: list[dict[str, Any]] = []
    import glob

    for index, total_path in enumerate(
        sorted(glob.glob("/sys/class/drm/card*/device/mem_info_vram_total"))
    ):
        base = os.path.dirname(total_path)
        try:
            with open(total_path) as handle:
                total_bytes = int(handle.read().strip())
        except (OSError, ValueError):
            continue
        used_bytes = None
        try:
            with open(os.path.join(base, "mem_info_vram_used")) as handle:
                used_bytes = int(handle.read().strip())
        except (OSError, ValueError):
            pass
        name = None
        for candidate in ("product_name", "device"):
            try:
                with open(os.path.join(base, candidate)) as handle:
                    name = handle.read().strip()
                    break
            except OSError:
                continue
        total_mb = total_bytes // (1024 * 1024)
        used_mb = used_bytes // (1024 * 1024) if used_bytes is not None else None
        gpus.append(
            {
                "index": index,
                "vendor": "AMD",
                "name": name or "AMD GPU",
                "memory_total_mb": total_mb,
                "memory_used_mb": used_mb,
                "memory_free_mb": (total_mb - used_mb) if used_mb is not None else None,
                "utilisation_percent": None,
                "driver": "amdgpu",
                "unified": False,
            }
        )
    if gpus:
        return gpus

    out = _run(["rocm-smi", "--showmeminfo", "vram", "--json"])
    if not out:
        return []
    try:
        parsed = json.loads(out)
    except ValueError:
        return []
    for index, (card, fields) in enumerate(sorted(parsed.items())):
        if not isinstance(fields, dict):
            continue
        total = used = None
        for key, value in fields.items():
            lowered = key.lower()
            if "total" in lowered and "vram" in lowered:
                total = _int(str(value))
            elif "used" in lowered and "vram" in lowered:
                used = _int(str(value))
        if total is None:
            continue
        # rocm-smi reports bytes here, unlike nvidia-smi's MiB.
        total_mb = total // (1024 * 1024)
        used_mb = used // (1024 * 1024) if used is not None else None
        gpus.append(
            {
                "index": index,
                "vendor": "AMD",
                "name": card,
                "memory_total_mb": total_mb,
                "memory_used_mb": used_mb,
                "memory_free_mb": (total_mb - used_mb) if used_mb is not None else None,
                "utilisation_percent": None,
                "driver": "rocm",
                "unified": False,
            }
        )
    return gpus


def _apple() -> list[dict[str, Any]]:
    """Apple Silicon: one unified pool, reported as such.

    `hw.memsize` is the whole machine's RAM and that IS the GPU's ceiling
    here. There is no free-VRAM number to report, because there is no VRAM --
    see the module docstring.
    """
    if platform.system() != "Darwin":
        return []
    total_mb = None
    out = _run(["sysctl", "-n", "hw.memsize"])
    if out:
        raw = _int(out)
        if raw:
            total_mb = raw // (1024 * 1024)
    name = None
    out = _run(["sysctl", "-n", "machdep.cpu.brand_string"])
    if out and out.strip():
        name = out.strip()
    if total_mb is None:
        return []
    return [
        {
            "index": 0,
            "vendor": "Apple",
            "name": name or "Apple Silicon",
            "memory_total_mb": total_mb,
            "memory_used_mb": None,
            "memory_free_mb": None,
            "utilisation_percent": None,
            "driver": "Metal",
            "unified": True,
        }
    ]


_INTEL_RE = re.compile(r"VGA|Display|3D controller", re.I)


def _intel() -> list[dict[str, Any]]:
    """Intel Arc / iGPU: present-and-named only.

    Intel exposes no stable free-memory counter comparable to the other two,
    and an integrated GPU's memory is system RAM anyway. Naming the device
    without inventing a VRAM figure is the honest amount to say.
    """
    out = _run(["lspci", "-mm"])
    if not out:
        return []
    gpus: list[dict[str, Any]] = []
    for line in out.splitlines():
        if not _INTEL_RE.search(line) or "Intel" not in line:
            continue
        fields = re.findall(r'"([^"]*)"', line)
        name = fields[2] if len(fields) > 2 else "Intel GPU"
        gpus.append(
            {
                "index": len(gpus),
                "vendor": "Intel",
                "name": name,
                "memory_total_mb": None,
                "memory_used_mb": None,
                "memory_free_mb": None,
                "utilisation_percent": None,
                "driver": "i915/xe",
                "unified": True,
            }
        )
    return gpus


def probe(force: bool = False) -> dict[str, Any]:
    """Every accelerator this machine will admit to, with its memory split.

    Vendors are tried in order of how much they can tell us. The first that
    answers wins, because a box with a discrete NVIDIA card also has an Intel
    iGPU on the PCI bus and listing both would bury the one running the model.
    """
    now = time.monotonic()
    cached = _cache["value"]
    if not force and cached is not None and (now - float(_cache["at"])) < _TTL:
        return dict(cached)

    gpus: list[dict[str, Any]] = []
    for finder in (_nvidia, _amd, _apple, _intel):
        try:
            gpus = finder()
        except Exception:  # pragma: no cover - a probe must never escape
            logger.exception("hardware: a GPU probe raised")
            gpus = []
        if gpus:
            break

    value = {
        "gpus": gpus,
        "platform": platform.system(),
        "detected": bool(gpus),
    }
    _cache["at"] = now
    _cache["value"] = value
    return dict(value)
