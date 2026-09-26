from marm_mcp_server.services.analyst.packet import (
    build_packet,
    render_packet,
)
from marm_mcp_server.services.code_context.compose import Context, Symbol


def _ctx(**over):
    ctx = Context(
        project={"name": "home-x-demo", "root_path": "/x/demo"},
        task="how does apply work",
        symbols=[
            Symbol(
                "pkg.svc.apply",
                "apply",
                "Function",
                "pkg/svc.py",
                10,
                40,
                source="def apply():\n    claim()\n",
                seeded=True,
            ),
            Symbol(
                "pkg.svc.claim",
                "claim",
                "Function",
                "pkg/svc.py",
                50,
                60,
                source="def claim():\n    pass\n",
            ),
        ],
        memories=[
            {"id": "m-1", "content": "apply claims before writing", "similarity": 0.9}
        ],
        links=[{"qualified_name": "pkg.svc.apply", "entity_name": "apply"}],
        graph_edges=[("pkg.svc.apply", "pkg.svc.claim", 1.0)],
    )
    for k, v in over.items():
        setattr(ctx, k, v)
    return ctx


def test_handles_are_stable_and_ordered():
    p = build_packet(_ctx())
    assert [s.handle for s in p.symbols] == ["S1", "S2"]
    assert [m.handle for m in p.memories] == ["M1"]
    assert p.symbol("S2").qualified_name == "pkg.svc.claim"
    assert p.memory("M1").memory_id == "m-1"


def test_packet_id_is_content_addressed():
    a, b = build_packet(_ctx()), build_packet(_ctx())
    assert a.packet_id == b.packet_id
    changed = build_packet(_ctx(task="something else"))
    assert changed.packet_id != a.packet_id


def test_links_and_edges_are_carried():
    p = build_packet(_ctx())
    assert ("pkg.svc.apply", "pkg.svc.claim") in p.edges
    assert ("M1", "pkg.svc.apply") in p.links


def test_caps_bound_the_packet():
    many = [Symbol(f"q.s{i}", f"s{i}", "Function", "f.py", i, i) for i in range(40)]
    p = build_packet(_ctx(symbols=many), max_symbols=5)
    assert len(p.symbols) == 5


def test_render_labels_every_item_with_its_handle():
    text = render_packet(build_packet(_ctx()))
    assert "[S1] apply" in text and "[S2] claim" in text
    assert "[M1]" in text and "apply claims before writing" in text
    assert "pkg/svc.py:10-40" in text


def test_by_name_matches_bare_and_qualified_casefolded():
    p = build_packet(_ctx())
    assert p.by_name("APPLY").handle == "S1"
    assert p.by_name("pkg.svc.claim").handle == "S2"
    assert p.by_name("nope") is None


def test_the_character_cap_bounds_the_packet_whatever_the_caller_asked():
    big = [
        Symbol(f"q.s{i}", f"s{i}", "Function", "f.py", i, i, source="x = 1\n" * 200)
        for i in range(10)
    ]
    p = build_packet(_ctx(symbols=big), max_symbols=10, max_chars=3000)
    assert len(render_packet(p)) <= 3000 + 400, "within the cap plus the header"
    assert p.omitted_symbols == 10 - len(p.symbols) > 0
    assert p.to_public()["omitted_symbols"] == p.omitted_symbols


def test_a_symbol_that_does_not_fit_is_cut_and_marked_truncated():
    one = [Symbol("q.a", "a", "Function", "f.py", 1, 9, source="y = 2\n" * 400)]
    p = build_packet(_ctx(symbols=one), max_chars=2000)
    assert p.symbols[0].truncated and len(p.symbols[0].source) < 2000
    assert "truncated" in render_packet(p)


def test_memory_takes_at_most_a_quarter_of_the_cap():
    mems = [{"id": f"m{i}", "content": "z" * 390} for i in range(8)]
    p = build_packet(_ctx(memories=mems), max_chars=4000)
    assert sum(len(m.content) for m in p.memories) <= 1000
    assert p.omitted_memories == 8 - len(p.memories)


def test_no_cap_keeps_every_counted_item():
    p = build_packet(_ctx())
    assert (p.omitted_symbols, p.omitted_memories) == (0, 0)


def test_public_shape():
    pub = build_packet(_ctx()).to_public()
    assert set(pub) == {
        "packet_id",
        "project",
        "task",
        "symbols",
        "memories",
        "chars",
        "omitted_symbols",
        "omitted_memories",
    }
    assert pub["symbols"][0] == {
        "handle": "S1",
        "qualified_name": "pkg.svc.apply",
        "name": "apply",
        "file_path": "pkg/svc.py",
        "start_line": 10,
        "end_line": 40,
    }


def test_a_source_containing_a_fence_cannot_break_the_packet():
    src = 'def doc():\n    """Example:\n    ```python\n    x = 1\n    ```\n    """\n'
    text = render_packet(
        build_packet(
            _ctx(
                symbols=[
                    Symbol("pkg.doc", "doc", "Function", "pkg/d.py", 1, 6, source=src)
                ]
            )
        )
    )
    assert "````" in text, "the fence must be longer than any backtick run inside"
