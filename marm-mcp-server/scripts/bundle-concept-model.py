#!/usr/bin/env python3
"""Fetch the pinned spaCy English pipeline into MARM package data."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import tempfile
import urllib.request
import zipfile
from pathlib import Path


MODEL_NAME = "en_core_web_sm"
MODEL_VERSION = "3.8.0"
MODEL_WHEEL_URL = (
    "https://github.com/explosion/spacy-models/releases/download/"
    f"{MODEL_NAME}-{MODEL_VERSION}/"
    f"{MODEL_NAME}-{MODEL_VERSION}-py3-none-any.whl"
)
MODEL_WHEEL_SHA256 = "1932429db727d4bff3deed6b34cfc05df17794f4a52eeb26cf8928f7c1a0fb85"
MODEL_PATH = (
    Path(__file__).resolve().parents[1] / "marm_mcp_server" / "models" / MODEL_NAME
)
REQUIRED_FILES = ("config.cfg", "ner/model")


def _is_complete(path: Path) -> bool:
    if not all((path / required).is_file() for required in REQUIRED_FILES):
        return False
    try:
        with (path / "meta.json").open(encoding="utf-8") as metadata_file:
            return json.load(metadata_file).get("version") == MODEL_VERSION
    except (OSError, json.JSONDecodeError):
        return False


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as wheel_file:
        for chunk in iter(lambda: wheel_file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _extract_model(wheel_path: Path, destination: Path) -> None:
    prefix = f"{MODEL_NAME}/{MODEL_NAME}-{MODEL_VERSION}/"
    with zipfile.ZipFile(wheel_path) as archive:
        members = [name for name in archive.namelist() if name.startswith(prefix)]
        if not members:
            raise RuntimeError(f"{wheel_path.name} does not contain {MODEL_NAME}")
        for member in members:
            relative = Path(member).relative_to(prefix)
            target = destination / relative
            if not target.resolve().is_relative_to(destination.resolve()):
                raise RuntimeError(f"Unsafe archive member: {member}")
            target.parent.mkdir(parents=True, exist_ok=True)
            if not member.endswith("/"):
                with archive.open(member) as source, target.open("wb") as output:
                    shutil.copyfileobj(source, output)


def bundle_model(*, force: bool = False) -> Path:
    if _is_complete(MODEL_PATH) and not force:
        print(f"Bundled concept model already present: {MODEL_PATH}")
        return MODEL_PATH

    MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="marm-concept-model-") as temporary:
        wheel_path = Path(temporary) / f"{MODEL_NAME}-{MODEL_VERSION}.whl"
        print(f"Downloading bundled concept model {MODEL_NAME} {MODEL_VERSION}...")
        urllib.request.urlretrieve(MODEL_WHEEL_URL, wheel_path)
        if _sha256(wheel_path) != MODEL_WHEEL_SHA256:
            raise RuntimeError("Downloaded concept model failed SHA-256 verification")
        extracted = Path(temporary) / MODEL_NAME
        extracted.mkdir()
        _extract_model(wheel_path, extracted)
        if not _is_complete(extracted):
            raise RuntimeError("Downloaded concept model is missing required files")
        if MODEL_PATH.exists():
            shutil.rmtree(MODEL_PATH)
        shutil.move(str(extracted), MODEL_PATH)

    print(f"Bundled concept model ready: {MODEL_PATH}")
    return MODEL_PATH


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="redownload the model")
    args = parser.parse_args()
    bundle_model(force=args.force)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
