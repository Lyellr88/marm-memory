# MARM MCPB bundle prototype

This directory contains the source for a local MCP Bundle (MCPB) release of
MARM. It runs the existing `marm_mcp_server.server_stdio:main` transport. It
does not expose an HTTP endpoint, proxy MCP traffic, or require OAuth.

## Build

Run this from the repository root after preparing release assets:

```powershell
python marm-mcp-server/scripts/bundle-concept-model.py
python scripts/build-mcpb.py
```

`build-mcpb.py` creates a clean UV-runtime bundle staging directory at
`dist/mcpb/marm-memory-<version>/`. It copies only MARM's runtime packages,
the bundled concept model, release metadata, and this bundle entry point. It
then invokes the pinned MCPB CLI through `npx` to produce
`dist/mcpb/marm-memory-<version>.mcpb`.

The bundle uses MCPB's `uv` server type. Its `mcp_config` runs
`uv run --locked`, and the archive carries a reviewed `uv.lock` generated from
the same runtime dependency list as `marm-mcp-server/pyproject.toml`.
`build-mcpb.py` rejects a dependency mismatch and runs `uv lock --check`
before packaging. No Python virtual environment or compiled wheels are
committed to the archive.

## Verified MCPB constraints

The build pins `@anthropic-ai/mcpb` to `2.1.2`. On September 20, 2026, that
CLI validated this bundle's `manifest_version: "0.4"` with `server.type:
"uv"`, packed it, and inspected the resulting archive on Windows. The same
command is part of CI on Windows, macOS, and Linux. Do not change the manifest
version or MCPB CLI pin without rerunning that validation on all three
platforms.

## First run and offline use

The bundle itself and normal memory storage are local. Its first installation
needs network access to resolve Python dependencies through the MCPB host's UV
runtime. The first feature use can also download MARM runtime artifacts:

- Semantic recall lazily downloads FastEmbed's
  `jinaai/jina-embeddings-v2-small-en` model.
- Code graph use lazily obtains the pinned `codebase-memory-mcp` engine.
- The concept extraction model is bundled during the release build, so it does
  not download at user first run.

After the Python dependencies and optional runtime artifacts are cached, MARM
can run offline. Features whose optional artifacts were not cached degrade
without blocking core memory tools.

## Release path

The build workflow validates the artifact on Linux, Windows, and macOS. The
canonical bundle uploads only after all three platforms pass.
Each CI build starts the staged bundle with the manifest's exact
`uv run --locked --project <stage> <stage>/marm_mcpb_entry.py` command and verifies
an MCP initialize followed by `tools/list` before upload.
Before publishing a release, open that resulting `.mcpb` in a host that
supports MCPB on each operating system and perform an MCP initialize plus
`tools/list` exchange. Attach the validated `.mcpb` artifact to the matching
GitHub release, then publish that stdio bundle to Smithery.

`Build MARM MCPB artifact` creates a downloadable CI artifact for pull-request
and manual verification. This prototype intentionally does not publish or
attach release assets. Add a release-job upload only after the clean-host
checks are automated and Smithery confirms support for the MCPB manifest
version. The automated stdio smoke uses the staged locked UV runtime; it does
not replace a host-managed desktop installation test. CI artifacts are
unsigned. Decide whether Smithery or the target desktop host requires a
release signing certificate before adding an automated GitHub-release upload.

## Maintenance

The bundle is mostly self-maintaining:

- Tool additions flow into the MCPB manifest from `server.json`, with parity
  checked by tests.
- The bundle version is read from MARM's `pyproject.toml`.
- Dependency changes fail the build until the MCPB dependency file and
  `uv.lock` are refreshed.
- New files within `marm_mcp_server` and `marm_graph` are copied automatically.

Manual changes are only needed for a new top-level runtime package, an external
asset or model location, or a changed STDIO entry-point architecture. The build
and CI catch normal growth cases.
