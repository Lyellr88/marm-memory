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


def test_malformed_root_path_is_dropped_not_raised():
    """A bad engine row must not turn the Console project list into a 500.

    `_with_display_names` calls `.rstrip("/")`, so a non-string `root_path`
    would raise AttributeError/TypeError mid-request.
    """
    from marm_mcp_server.console.mcp_client import _usable_project

    for bad in (123, ["/home/u/Code/proj"], None, "", "   ", {"path": "/x"}):
        assert not _usable_project({"name": "proj", "root_path": bad}), bad


def test_malformed_name_is_dropped():
    from marm_mcp_server.console.mcp_client import _usable_project

    for bad in (123, None, "", "   ", ["proj"]):
        assert not _usable_project({"name": bad, "root_path": "/home/u/p"}), bad


def test_well_formed_row_is_accepted():
    from marm_mcp_server.console.mcp_client import _usable_project

    assert _usable_project({"name": "proj", "root_path": "/home/u/Code/proj"})


def test_non_dict_row_is_dropped():
    from marm_mcp_server.console.mcp_client import _usable_project

    for bad in (None, "proj", ["proj"], 7):
        assert not _usable_project(bad), bad


def test_surviving_rows_still_normalise_when_a_bad_row_is_present():
    """One malformed row must not cost the good rows their labels."""
    from marm_mcp_server.console.mcp_client import _usable_project

    rows = [
        {"name": "a", "root_path": "/home/u/Code/A/proj"},
        {"name": "b", "root_path": 123},
        {"name": "c", "root_path": "/home/u/Code/B/other"},
    ]
    good = [r for r in rows if _usable_project(r)]
    assert [p["display_name"] for p in _with_display_names(good)] == ["proj", "other"]


def test_windows_root_with_trailing_separator():
    """root_path comes from whichever host owns the index, which may be Windows."""
    projects = _with_display_names([_project("c-work-repo", "C:\\work\\repo\\")])
    assert projects[0]["display_name"] == "repo"


def test_windows_collision_qualifies_with_the_windows_parent():
    projects = _with_display_names(
        [
            _project("a", "C:\\teamA\\repo"),
            _project("b", "C:\\teamB\\repo"),
        ]
    )
    assert [p["display_name"] for p in projects] == ["teamA/repo", "teamB/repo"]


def test_one_ancestor_is_not_always_enough():
    """/a/Team/repo and /b/Team/repo both shorten to Team/repo -- keep going."""
    projects = _with_display_names(
        [
            _project("a", "/a/Team/repo"),
            _project("b", "/b/Team/repo"),
        ]
    )
    labels = [p["display_name"] for p in projects]
    assert len(set(labels)) == 2, labels
    assert labels == ["a/Team/repo", "b/Team/repo"]


def test_an_unaffected_project_keeps_its_short_label():
    """Deepening a collision must not lengthen an unrelated project's label."""
    projects = _with_display_names(
        [
            _project("a", "/a/Team/repo"),
            _project("b", "/b/Team/repo"),
            _project("c", "/somewhere/solo"),
        ]
    )
    assert projects[2]["display_name"] == "solo"


def test_identical_roots_fall_back_to_the_unique_engine_id():
    projects = _with_display_names(
        [
            _project("id-one", "/same/path"),
            _project("id-two", "/same/path"),
        ]
    )
    assert [p["display_name"] for p in projects] == ["id-one", "id-two"]
