"""Secrets never reach the store, and ordinary text about secrets does."""

import json
import sqlite3

import pytest
from conftest import load_isolated_server, local_client

from marm_mcp_server.core.redaction import (
    redact_secrets,
    redact_value,
    redaction_summary,
)

# Built from parts so the file itself carries no scannable secret.
AWS = "AKIA" + "IOSFODNN7" + "EXAMPLE"
GITHUB = "ghp_" + "a1B2c3D4e5F6g7H8i9J0" + "k1L2m3N4o5P6q7R8"
ANTHROPIC = "sk-ant-" + "api03-" + "x" * 32
OPENAI = "sk-proj-" + "Z" * 40
SLACK = "xoxb-" + "123456789012-abcdefghijkl"
GOOGLE = "AIza" + "S" * 35
STRIPE = "sk_live_" + "4eC39HqLyjWDarjtT1zdp7dc"
JWT = "eyJhbGciOiJIUzI1NiJ9" + "." + "eyJzdWIiOiIxMjM0In0" + "." + "abcDEF123456ghiJKL"
PEM = (
    "-----BEGIN RSA PRIVATE KEY-----\nMIIEpAIBAAKCAQEA7Vv\n"
    "-----END RSA PRIVATE KEY-----"
)


@pytest.mark.parametrize(
    ("text", "kind"),
    [
        (f"deploy with {AWS} today", "aws-access-key"),
        (f"token {GITHUB} pushed", "github-token"),
        (f"key is {ANTHROPIC}", "anthropic-key"),
        (f"OPENAI {OPENAI}", "openai-key"),
        (f"slack {SLACK}", "slack-token"),
        (f"maps {GOOGLE}", "google-api-key"),
        (f"billing {STRIPE}", "stripe-key"),
        (f"session {JWT}", "jwt"),
        (f"the key:\n{PEM}\nend", "private-key"),
        ("Authorization: Bearer " + "q" * 32, "bearer-token"),
        ("MARM_API_KEY=" + "s3cr3tValue1234567", "assigned-secret"),
        ('db_password: "' + "Hunter2Hunter2!" + '"', "assigned-secret"),
        ("TOKEN=" + "abc123", "assigned-secret"),
        ("password: " + "hunter2", "assigned-secret"),
        (
            "AWS_SECRET_ACCESS_KEY=" + "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
            "assigned-secret",
        ),
        ("SSH_PRIVATE_KEY=" + "b3BlbnNzaC1rZXk", "assigned-secret"),
        ("GCP_CREDENTIALS=" + "correcthorsebatterystaple", "assigned-secret"),
    ],
)
def test_a_secret_is_replaced_by_its_kind(text, kind):
    redacted, counts = redact_secrets(text)
    assert f"[redacted:{kind}]" in redacted
    assert counts == {kind: 1}
    for secret in (AWS, GITHUB, ANTHROPIC, OPENAI, SLACK, GOOGLE, STRIPE, JWT):
        assert secret not in redacted
    assert "MIIEpAIBAAKCAQEA7Vv" not in redacted


def test_a_private_key_cut_off_mid_block_is_still_removed():
    text = "-----BEGIN OPENSSH PRIVATE KEY-----\nb3BlbnNzaC1rZXktdjEAAAAABG5vbmU"
    redacted, counts = redact_secrets(text)
    assert counts == {"private-key": 1}
    assert "b3BlbnNzaC1" not in redacted


def test_an_assignment_keeps_its_name_and_loses_its_value():
    redacted, _ = redact_secrets("MARM_API_KEY=" + "s3cr3tValue1234567")
    assert redacted == "MARM_API_KEY=[redacted:assigned-secret]"


@pytest.mark.parametrize(
    "text",
    [
        "Supply MARM_API_KEY from the environment; it needs no key file.",
        "API_KEY=${MARM_API_KEY} in the compose file",
        "set TOKEN=<your-token> before starting",
        "MAX_TOKENS=4096 and the token count stays low",
        "commit 3f2a9c1e5b7d4a6f8e0c2b4d6f8a0c2e4b6d8f0a fixed it",
        "memory d132c54e-bdc3-40de-9f3a-ba91211a31ee was deleted",
        "scikit-learn and sk-learn are the same package",
        "password must be at least 12 characters",
        "the bearer of bad news",
        "we rotate every secret quarterly",
        "the session token: invalidated after logout",
        "MAX_TOKEN=128000 per request",
        "REQUIRE_PASSWORD=true in production",
        "AWS_ACCESS_KEY_ID is read from the environment",
    ],
)
def test_ordinary_text_about_secrets_is_untouched(text):
    assert redact_secrets(text) == (text, {})


def test_metadata_is_redacted_all_the_way_down():
    value = {"detail": [f"use {AWS}", {"nested": f"and {GITHUB}"}], "n": 3}
    assert redact_value(value) == {
        "detail": [
            "use [redacted:aws-access-key]",
            {"nested": "and [redacted:github-token]"},
        ],
        "n": 3,
    }


def _stored(db_path: str, table: str, column: str) -> list[str]:
    with sqlite3.connect(db_path) as conn:
        return [row[0] for row in conn.execute(f"SELECT {column} FROM {table}")]


def test_a_logged_secret_is_stored_and_recalled_redacted(monkeypatch, tmp_path):
    server = load_isolated_server(monkeypatch, tmp_path)
    client = local_client(server.app)

    logged = client.post(
        "/marm_log_entry",
        json={
            "entry": f"2026-09-27-deploy-rotated the key to {AWS} after the leak",
            "session_name": "redaction",
        },
    )
    assert logged.status_code == 200, logged.text
    assert logged.json()["redacted"] == {"count": 1, "kinds": {"aws-access-key": 1}}

    db = str(tmp_path / "marm_memory.db")
    stored = _stored(db, "log_entries", "full_entry") + _stored(
        db, "memories", "content"
    )
    assert stored and not any(AWS in row for row in stored)
    assert any("[redacted:aws-access-key]" in row for row in stored)

    recalled = client.post(
        "/marm_smart_recall",
        json={"query": "rotated the key after the leak", "session_name": "redaction"},
    )
    assert recalled.status_code == 200
    assert AWS not in recalled.text


def test_a_notebook_secret_is_stored_redacted(monkeypatch, tmp_path):
    server = load_isolated_server(monkeypatch, tmp_path)
    client = local_client(server.app)

    added = client.post(
        "/marm_notebook",
        json={"action": "add", "name": "creds", "data": f"github: {GITHUB}"},
    )
    assert added.status_code == 200, added.text
    assert added.json()["redacted"] == {"count": 1, "kinds": {"github-token": 1}}

    stored = _stored(str(tmp_path / "marm_memory.db"), "notebook_entries", "data")
    assert stored and not any(GITHUB in row for row in stored)


def test_console_writes_redact_content_and_metadata(monkeypatch, tmp_path):
    server = load_isolated_server(monkeypatch, tmp_path, write_queue_enabled=True)
    client = local_client(server.app)

    created = client.post(
        "/internal/memories",
        json={
            "content": "deploy notes",
            "session_name": "redaction",
            "metadata": {"body": f"used {AWS} for the upload"},
        },
    )
    assert created.status_code == 201, created.text
    assert created.json()["redacted"] == {"count": 1, "kinds": {"aws-access-key": 1}}
    memory_id = created.json()["id"]
    db = str(tmp_path / "marm_memory.db")
    assert not any(AWS in row for row in _stored(db, "memories", "metadata"))

    updated = client.put(
        f"/internal/memories/{memory_id}",
        json={
            "content": f"deploy notes, key {GITHUB}",
            "session_name": "redaction",
            "metadata": {"body": f"rotated to {GITHUB}"},
        },
    )
    assert updated.status_code == 200, updated.text
    # Content and metadata both: the caller is told about each.
    assert updated.json()["redacted"] == {"count": 2, "kinds": {"github-token": 2}}

    rows = _stored(db, "memories", "content") + _stored(db, "memories", "metadata")
    assert not any(AWS in row or GITHUB in row for row in rows)
    assert any("[redacted:github-token]" in row for row in rows)


class _Captured(BaseException):
    pass


@pytest.mark.asyncio
async def test_a_notebook_save_hands_the_docs_store_redacted_content(
    monkeypatch, tmp_path
):
    import importlib

    load_isolated_server(monkeypatch, tmp_path)
    notebook = importlib.import_module("marm_mcp_server.services.notebook")
    seen = {}

    class _Docs:
        def get_connection(self):
            import contextlib

            return contextlib.nullcontext(None)

        def save_doc(self, _conn, **kwargs):
            seen.update(kwargs)
            raise _Captured

    monkeypatch.setattr(notebook, "_get_docs_db", lambda: _Docs())
    with pytest.raises(_Captured):
        await notebook._save("creds", f"github: {GITHUB}")

    assert GITHUB not in seen["content"]
    assert "[redacted:github-token]" in seen["content"]


@pytest.mark.asyncio
async def test_promoting_an_existing_scratch_entry_redacts_what_it_saves(
    monkeypatch, tmp_path
):
    """A scratch entry written before redaction existed still holds the raw
    secret; promoting it with no data= must not carry that into the docs."""
    import contextlib
    import importlib

    load_isolated_server(monkeypatch, tmp_path)
    notebook = importlib.import_module("marm_mcp_server.services.notebook")
    added = await notebook._add("creds", "placeholder")
    assert added["status"] == "success", added
    with sqlite3.connect(str(tmp_path / "marm_memory.db")) as conn:
        changed = conn.execute(
            "UPDATE notebook_entries SET data = ? WHERE name = 'creds'",
            (f"github: {GITHUB}",),
        ).rowcount
    assert changed == 1
    seen = {}

    class _Docs:
        def get_connection(self):
            return contextlib.nullcontext(None)

        def save_doc(self, _conn, **kwargs):
            seen.update(kwargs)
            raise _Captured

    monkeypatch.setattr(notebook, "_get_docs_db", lambda: _Docs())
    with pytest.raises(_Captured):
        await notebook._save("creds", None)

    assert seen["source_notebook_name"] == "creds"
    assert GITHUB not in seen["content"]
    assert "[redacted:github-token]" in seen["content"]


@pytest.mark.asyncio
@pytest.mark.parametrize("action", ["add", "save"])
async def test_a_notebook_name_holding_a_credential_is_refused(
    monkeypatch, tmp_path, action
):
    """A redacted name could never be looked up again, so it is refused."""
    import importlib

    load_isolated_server(monkeypatch, tmp_path)
    notebook = importlib.import_module("marm_mcp_server.services.notebook")

    result = await getattr(notebook, f"_{action}")(f"key {GITHUB}", "some data")

    assert result["status"] == "error"
    assert GITHUB not in json.dumps(result)
    rows = _stored(str(tmp_path / "marm_memory.db"), "notebook_entries", "name")
    assert not any(GITHUB in row for row in rows)


# --- quoted values, metadata keys, and what the caller is told -------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (
            'password: "correct horse battery staple"',
            'password: "[redacted:assigned-secret]"',
        ),
        ("PASSWORD='hunter two 2'", "PASSWORD='[redacted:assigned-secret]'"),
        ('password: "nothing"', 'password: "nothing"'),
        ('password: "123456"', 'password: "123456"'),
        ('password: "false"', 'password: "false"'),
        (
            'message: "ordinary words here today"',
            'message: "ordinary words here today"',
        ),
        ('token: "${API_TOKEN}"', 'token: "${API_TOKEN}"'),
    ],
)
def test_a_quoted_secret_with_spaces_is_redacted_and_keeps_its_quotes(text, expected):
    assert redact_secrets(text)[0] == expected


def test_redaction_is_idempotent():
    once = redact_secrets(f'password: "correct horse battery staple" and {AWS}')[0]
    assert redact_secrets(once) == (once, {})


@pytest.mark.parametrize(
    ("metadata", "expected"),
    [
        ({"password": "hunter2x9"}, {"password": "[redacted:assigned-secret]"}),
        (
            {"auth": {"api_key": "abcdefghijklmnop1234"}},
            {"auth": {"api_key": "[redacted:assigned-secret]"}},
        ),
        ({"password": "nothing"}, {"password": "nothing"}),
        ({"token": "${TOKEN}"}, {"token": "${TOKEN}"}),
        ({"tokens": 1024}, {"tokens": 1024}),
        ({"note": "hunter2x9"}, {"note": "hunter2x9"}),
    ],
)
def test_a_metadata_value_is_judged_with_its_field_name(metadata, expected):
    assert redact_value(metadata) == expected


def test_the_summary_counts_what_content_and_metadata_lose():
    summary = redaction_summary(f"deploy with {AWS}", {"password": "hunter2x9"})
    assert summary == {
        "count": 2,
        "kinds": {"aws-access-key": 1, "assigned-secret": 1},
    }
    assert redaction_summary("nothing to see", {"note": "fine"}) is None


def test_a_clean_write_reports_no_redaction(monkeypatch, tmp_path):
    server = load_isolated_server(monkeypatch, tmp_path)
    client = local_client(server.app)
    logged = client.post(
        "/marm_log_entry",
        json={"entry": "2026-09-27-deploy-nothing secret here", "session_name": "r"},
    )
    assert logged.status_code == 200
    assert "redacted" not in logged.json()


def test_distill_reports_what_it_redacted_before_staging(monkeypatch, tmp_path):
    server = load_isolated_server(monkeypatch, tmp_path)
    client = local_client(server.app)
    proposed = client.post(
        "/marm_distill",
        json={
            "action": "propose",
            "text": f"We decided to rotate the deploy key {AWS} every month.",
            "session_name": "redaction",
        },
    )
    assert proposed.status_code == 200, proposed.text
    assert proposed.json()["redacted"] == {"count": 1, "kinds": {"aws-access-key": 1}}
    assert AWS not in proposed.text
