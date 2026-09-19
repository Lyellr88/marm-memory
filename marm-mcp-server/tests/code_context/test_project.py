from marm_mcp_server.services.code_context.project import resolve, short_name

P = [
    {"name": "home-u-Code-A-proj", "root_path": "/home/u/Code/A/proj"},
    {"name": "home-u-Code-A-proj-nested", "root_path": "/home/u/Code/A/proj/nested"},
    {"name": "home-u-Code-B-other", "root_path": "/home/u/Code/B/other"},
]


def test_deepest_containing_root_wins():
    """A nested repo must resolve to itself, not to its parent."""
    assert resolve(P, cwd="/home/u/Code/A/proj/nested/src")["name"].endswith("nested")


def test_parent_resolves_to_parent():
    assert (
        resolve(P, cwd="/home/u/Code/A/proj/lib")["root_path"] == "/home/u/Code/A/proj"
    )


def test_sibling_prefix_is_not_containment():
    """/home/u/Code/A/project must NOT match the root /home/u/Code/A/proj."""
    assert resolve(P, cwd="/home/u/Code/A/project") is None


def test_explicit_name():
    assert resolve(P, cwd="/tmp", explicit="home-u-Code-B-other")["root_path"].endswith(
        "other"
    )


def test_explicit_path():
    assert resolve(P, cwd="/tmp", explicit="/home/u/Code/B/other")["name"].endswith(
        "other"
    )


def test_explicit_miss_returns_none_rather_than_a_wrong_project():
    assert resolve(P, cwd="/home/u/Code/A/proj", explicit="nope") is None


def test_no_projects():
    assert resolve([], cwd="/anywhere") is None


def test_short_name_uses_basename():
    assert short_name(P[0]) == "proj"


def test_short_name_tolerates_trailing_slash():
    assert short_name({"name": "x", "root_path": "/home/u/Code/A/proj/"}) == "proj"
