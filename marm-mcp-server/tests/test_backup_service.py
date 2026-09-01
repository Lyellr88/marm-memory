import sqlite3

import pytest

from marm_mcp_server.services import backup


@pytest.fixture
def live_db(monkeypatch, tmp_path):
    """A real database with real rows, so VACUUM INTO has something to prove."""
    path = tmp_path / "memory.db"
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE memories (id INTEGER PRIMARY KEY, content TEXT)")
    conn.executemany(
        "INSERT INTO memories (content) VALUES (?)",
        [(f"memory {index}",) for index in range(50)],
    )
    conn.commit()
    conn.close()
    monkeypatch.setattr(backup, "DEFAULT_DB_PATH", str(path))
    return path


def test_snapshot_is_a_complete_readable_copy(live_db):
    created = backup.create_backup()
    snapshot = backup.backup_dir() / created["name"]

    assert snapshot.is_file()
    copy = sqlite3.connect(snapshot)
    try:
        assert copy.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert copy.execute("SELECT COUNT(*) FROM memories").fetchone()[0] == 50
        assert (
            copy.execute("SELECT content FROM memories WHERE id = 1").fetchone()[0]
            == "memory 0"
        )
    finally:
        copy.close()


def test_snapshot_does_not_observe_writes_made_after_it(live_db):
    created = backup.create_backup()

    conn = sqlite3.connect(live_db)
    conn.execute("INSERT INTO memories (content) VALUES ('written later')")
    conn.commit()
    conn.close()

    copy = sqlite3.connect(backup.backup_dir() / created["name"])
    try:
        assert copy.execute("SELECT COUNT(*) FROM memories").fetchone()[0] == 50
    finally:
        copy.close()


def test_snapshots_taken_in_the_same_second_do_not_collide(live_db):
    first = backup.create_backup()
    second = backup.create_backup()

    assert first["name"] != second["name"]
    assert len(backup.list_backups()) == 2


def test_listing_is_newest_first_and_ignores_foreign_files(live_db):
    backup.create_backup()
    directory = backup.backup_dir()
    (directory / "notes.txt").write_text("not a snapshot", encoding="utf-8")
    (directory / "marm-memory-backup.db").write_text("wrong shape", encoding="utf-8")

    listed = backup.list_backups()

    assert len(listed) == 1
    assert listed == sorted(listed, key=lambda item: item["name"], reverse=True)


def test_listing_an_absent_directory_is_empty_not_an_error(live_db):
    assert not backup.backup_dir().exists()
    assert backup.list_backups() == []


def test_create_without_a_database_raises_rather_than_writing_an_empty_file(
    monkeypatch, tmp_path
):
    monkeypatch.setattr(backup, "DEFAULT_DB_PATH", str(tmp_path / "absent.db"))

    with pytest.raises(FileNotFoundError):
        backup.create_backup()

    assert not backup.backup_dir().exists()


@pytest.mark.parametrize(
    "name",
    [
        "../../../etc/passwd",
        "..\\..\\windows\\system32\\config\\sam",
        "marm-memory.db",
        "marm-memory-20260101-000000.db/../escape",
        "/etc/passwd",
        "",
    ],
)
def test_delete_rejects_anything_that_is_not_a_snapshot_name(live_db, name):
    with pytest.raises(ValueError):
        backup.delete_backup(name)


def test_delete_removes_only_the_named_snapshot(live_db):
    first = backup.create_backup()
    second = backup.create_backup()

    assert backup.delete_backup(second["name"]) is True

    remaining = [item["name"] for item in backup.list_backups()]
    assert remaining == [first["name"]]


def test_deleting_an_absent_snapshot_reports_false(live_db):
    backup.create_backup()

    assert backup.delete_backup("marm-memory-20200101-000000.db") is False
