from marm_mcp_server.services.analyst.packet import (
    build_packet,
    merge_packets,
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


def test_merge_appends_new_items_and_keeps_existing_handles():
    base = build_packet(_ctx())
    extra = build_packet(
        _ctx(
            symbols=[
                Symbol("pkg.svc.claim", "claim", "Function", "pkg/svc.py", 50, 60),
                Symbol("pkg.db.write", "write", "Function", "pkg/db.py", 1, 9),
            ],
            memories=[],
        )
    )
    merged = merge_packets(base, extra)
    assert [s.handle for s in merged.symbols] == ["S1", "S2", "S3"]
    assert merged.symbol("S3").qualified_name == "pkg.db.write"
    assert merged.packet_id != base.packet_id


def test_public_shape():
    pub = build_packet(_ctx()).to_public()
    assert set(pub) == {"packet_id", "project", "task", "symbols", "memories"}
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
