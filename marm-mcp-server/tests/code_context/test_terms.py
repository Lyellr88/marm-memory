from marm_mcp_server.services.code_context.terms import (
    content_terms,
    is_distinctive,
    looks_like_test,
    seed_query,
)


def test_filler_is_dropped_from_the_seed_query():
    """'the Cpu struct and how it steps the bus' must not seed on 'the'/'and'/'how'."""
    q = seed_query("the Cpu struct and how it steps the bus")
    assert "Cpu" in q and "struct" in q and "bus" in q
    for filler in ("the", "and", "how", "it"):
        assert filler not in q.split()


def test_seed_query_never_returns_empty():
    assert seed_query("the and of it") == "the and of it"


def test_terms_are_deduplicated_preserving_order():
    assert content_terms("cache Cache cache miss") == ["cache", "miss"]


def test_generic_identifiers_are_not_distinctive():
    for w in ("check", "run", "main", "config", "value", "test"):
        assert not is_distinctive(w)


def test_domain_identifiers_are_distinctive():
    for w in ("birdsmouth", "rafter", "Cpu_bus", "shed_model"):
        assert is_distinctive(w)


def test_short_names_are_not_distinctive():
    assert not is_distinctive("id") and not is_distinctive("fn")


def test_test_paths_are_recognised():
    for p in (
        "tests/test_x.py",
        "src/__tests__/a.ts",
        "a/b_test.go",
        "x/foo.test.ts",
        "y/bar.spec.js",
        "spec/models/user.rb",
    ):
        assert looks_like_test(p), p


def test_source_paths_are_not_flagged():
    for p in ("src/latest.py", "crates/contest/src/lib.rs", "app/protest.ts"):
        assert not looks_like_test(p), p


def test_test_function_names_are_recognised():
    assert looks_like_test("src/lib.rs", "test_parses_header")
    assert looks_like_test("src/lib.rs", "it_rejects_bad_input")
