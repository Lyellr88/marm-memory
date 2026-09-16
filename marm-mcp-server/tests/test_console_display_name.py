"""`display_name` is a label, never an identity.

The Console shows the engine's project id as a card title with the repository
path directly beneath it, and the id is derived from that path -- so the card
says the same thing twice, and two projects under one parent truncate to the
same string. `_with_display_names` supplies a short label without touching
`name`, which is the graph database's filename and the /explorer/<name> route.
"""

from marm_mcp_server.console.mcp_client import _with_display_names


def _project(name: str, root_path: str) -> dict:
    return {
        "name": name,
        "root_path": root_path,
        "nodes": 0,
        "edges": 0,
        "status": "ready",
    }


def test_unique_basename_uses_the_basename_alone():
    projects = _with_display_names(
        [
            _project(
                "home-u-Code-Local_Only-Projects-Sawdust_Projects",
                "/home/u/Code/Local_Only-Projects/Sawdust_Projects",
            ),
            _project(
                "home-u-Code-Local_Only-Projects-nes-tron",
                "/home/u/Code/Local_Only-Projects/nes-tron",
            ),
        ]
    )
    assert [p["display_name"] for p in projects] == ["Sawdust_Projects", "nes-tron"]


def test_colliding_basenames_are_qualified_by_parent():
    """Two checkouts of one repo under different parents must stay distinguishable."""
    projects = _with_display_names(
        [
            _project("a", "/home/u/Code/Commercial_Private-Projects/HomeFile"),
            _project("b", "/home/u/Code/Commercial_Income-Projects/HomeFile"),
        ]
    )
    assert [p["display_name"] for p in projects] == [
        "Commercial_Private-Projects/HomeFile",
        "Commercial_Income-Projects/HomeFile",
    ]


def test_name_is_never_modified():
    """`name` is the db filename and the route key; only the label may change."""
    projects = _with_display_names(
        [
            _project(
                "home-u-Code-OSS_Public-Projects-RustyNES",
                "/home/u/Code/OSS_Public-Projects/RustyNES",
            ),
        ]
    )
    assert projects[0]["name"] == "home-u-Code-OSS_Public-Projects-RustyNES"


def test_trailing_slash_does_not_produce_an_empty_label():
    projects = _with_display_names(
        [_project("x", "/home/u/Code/Local_Only-Projects/nes-tron/")]
    )
    assert projects[0]["display_name"] == "nes-tron"


def test_missing_root_path_falls_back_to_the_project_id():
    """A project the engine reported without a usable path still gets a label."""
    projects = _with_display_names(
        [{"name": "orphan", "root_path": "", "nodes": 0, "edges": 0}]
    )
    assert projects[0]["display_name"] == "orphan"


def test_root_filesystem_path_is_labelled_without_a_bare_separator():
    projects = _with_display_names([_project("root", "/")])
    assert projects[0]["display_name"] == "root"
