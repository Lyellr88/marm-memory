"""Regression tests for the release-time spaCy model bundler."""

import importlib.util
import zipfile
from pathlib import Path


SCRIPT_PATH = Path(__file__).parents[1] / "scripts" / "bundle-concept-model.py"
SPEC = importlib.util.spec_from_file_location("bundle_concept_model", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
bundle_concept_model = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(bundle_concept_model)


def test_extract_model_flattens_official_wheel_layout(tmp_path):
    wheel_path = tmp_path / "model.whl"
    prefix = (
        f"{bundle_concept_model.MODEL_NAME}/"
        f"{bundle_concept_model.MODEL_NAME}-{bundle_concept_model.MODEL_VERSION}/"
    )
    with zipfile.ZipFile(wheel_path, "w") as wheel:
        wheel.writestr(f"{bundle_concept_model.MODEL_NAME}/__init__.py", "")
        wheel.writestr(f"{prefix}config.cfg", "[nlp]\nlang = 'en'\n")
        wheel.writestr(
            f"{prefix}meta.json",
            f'{{"version": "{bundle_concept_model.MODEL_VERSION}"}}',
        )
        wheel.writestr(f"{prefix}ner/model", b"model")

    destination = tmp_path / "model"
    destination.mkdir()
    bundle_concept_model._extract_model(wheel_path, destination)

    assert (destination / "config.cfg").is_file()
    assert (destination / "ner" / "model").is_file()
    assert bundle_concept_model._is_complete(destination)


def test_complete_model_requires_the_pinned_version(tmp_path):
    model_path = tmp_path / "model"
    (model_path / "ner").mkdir(parents=True)
    (model_path / "config.cfg").write_text("[nlp]\nlang = 'en'\n", encoding="utf-8")
    (model_path / "ner" / "model").write_bytes(b"model")
    (model_path / "meta.json").write_text('{"version": "0.0.0"}', encoding="utf-8")

    assert bundle_concept_model._is_complete(model_path) is False


def test_complete_model_rejects_non_object_metadata(tmp_path):
    """Valid-but-non-dict meta.json (null/list/string) must read as incomplete,
    not raise, so a damaged install can still be repaired with --force."""
    model_path = tmp_path / "model"
    (model_path / "ner").mkdir(parents=True)
    (model_path / "config.cfg").write_text("[nlp]\nlang = 'en'\n", encoding="utf-8")
    (model_path / "ner" / "model").write_bytes(b"model")

    for payload in ("null", "[1, 2]", '"3.8.0"'):
        (model_path / "meta.json").write_text(payload, encoding="utf-8")
        assert bundle_concept_model._is_complete(model_path) is False
