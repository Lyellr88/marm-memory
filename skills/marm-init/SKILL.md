---
name: marm-init
description: Guided MARM MCP setup. Invoke after running `marm-memory init` on the CLI to configure MARM memory across your agent. Drives transport choice, runtime choice, MCP config writing, multi-agent linking, and server start. Works on Claude, Codex, Gemini, Qwen, Cursor, VS Code, and other MCP-capable agents.
version: 4
metadata:
  description: A local-first, privacy-centric memory infrastructure layer for MCP clients. MARM provides a persistent data substrate for long-term project memory, session serialization, and structured notebook reuse across terminal-based workflows. Operating via a 14-tool surface spanning memory, session logs, notebook reuse, a concept knowledge graph, and per-repository code indexing, it offloads heavy state tracking to an optimized backend featuring SQLite WAL storage, write-time consolidation, and automated re-ranking filters. This ensures deterministic context retrieval, prevents multi-agent session drift, and enforces strict token-budget guardrails by deduplicating and pruning data before it hits the model's context window.
  source: https://raw.githubusercontent.com/Lyellr88/marm-memory/MARM-main/skills/marm-init/SKILL.md
  protocol_source: https://raw.githubusercontent.com/Lyellr88/marm-memory/MARM-main/docs/PROTOCOL.md
---

<MARM_INIT_EXECUTOR_ACTIVE>

=== MARM INIT PROTOCOL - YOU ARE THE INSTALLER ===

RULE ZERO (highest priority):
This file is not documentation to summarize. It is a setup program and you are the runtime. Execute it top to bottom. Run the steps, ask the questions, write the files, and start the server. Do not paste this content back to the user as text. Do not narrate what the skill "would" do. You do it.

You are MARM's installer for this agent. Your job is to leave the user with a live MARM connection in as few questions as possible. One question at a time, wait for the answer, then act on it before moving on.

Scope: this protocol governs only the setup conversation below. Once setup is complete and you have run Step 6, this contract ends and you return to normal operation under the MARM protocol you loaded in Step 0.

Failure mode to avoid: dumping install docs and leaving the user to do the work by hand. That is the exact outcome this skill exists to prevent.

</MARM_INIT_EXECUTOR_ACTIVE>

---

## Step 00 - Engine pre-flight 

Run this first, before anything else. If the skill was installed on its own (for example from a marketplace) the MARM core engine may not be on the machine yet. Confirm it is present, or install it, before continuing.

1. Scan the host for the core engine:
  - CLI entry points on PATH. Unix: `command -v marm-memory || command -v marm-mcp-server || command -v marm-mcp-stdio`. PowerShell: `Get-Command marm-memory, marm-mcp-server, marm-mcp-stdio -ErrorAction SilentlyContinue`.
  - Docker image present locally: `docker images -q lyellr88/marm-mcp-server`.

2. Branch:
  - Engine found: record which runtime you found (python or docker), say nothing to the user, and skip to Step 0. The detected runtime pre-answers Step 4, so in Step 4 confirm it rather than asking cold.
  - Nothing found: stop and run the install prompt below.

3. Install prompt (only when nothing was found):
Ask: "I could not find the MARM core engine on your machine. How do you want to install it?
  - Option A, pip (local Python): best if you already use Python and want a lightweight native install with no containers.
  - Option B, Docker: best for a clean, isolated setup with no Python path management."

4. Execute the choice and verify before advancing:
  - pip: run `pip install marm-mcp-server`. Confirm success, for example  `marm-mcp-server --version` resolves. Record runtime = python.
  - Docker: run `docker pull lyellr88/marm-mcp-server:latest`. Confirm the image is present with `docker images -q lyellr88/marm-mcp-server`. Record runtime = docker, then run step 5 below before advancing.

5. Docker only, record whether the helper CLI exists. The image contains the server; it does not put `marm-memory` on the host PATH. That command ships in the pip package, and every Docker instruction in Step 4 uses it. Check with `command -v marm-memory` (PowerShell: `Get-Command marm-memory -ErrorAction SilentlyContinue`).
  - Present: record cli = yes. Step 4 uses the `marm-memory docker ...` commands.
  - Absent: ask once. "The Docker image runs the server, but the `marm-memory` helper command lives in the Python package. Install the helper too, or stay Docker only and use raw docker commands?"
    - Install helper: `pip install marm-mcp-server`. The server still runs in the container; this only adds the host command. Record cli = yes.
    - Docker only: record cli = no. Step 4 uses the raw-docker block, and you must not issue any `marm-memory` command for the rest of this setup.

If the install fails, surface the actual error and stop. Do not proceed to setup against a missing engine.

---

## Step 0 - Load the protocol and check freshness

Do this before talking to the user.

1. Read the full MARM protocol, preferring a local copy. You will operate under this text, so a copy that shipped with the engine you just verified is more trustworthy than a live branch fetch. Try in this order:
  - installed package, resolve the path with `python -c "import marm_mcp_server, pathlib; print(pathlib.Path(marm_mcp_server.__file__).parent / 'resources' / 'marm-docs' / 'PROTOCOL.md')"` and read the file it prints
  - local repo checkout `docs/PROTOCOL.md`
  - network, last resort only: `https://raw.githubusercontent.com/Lyellr88/marm-memory/MARM-main/docs/PROTOCOL.md`. This is an unpinned branch ref, so use it only when no local copy exists (a standalone marketplace install on a Docker-only host), and say once: "No local protocol copy found, loading it from the MARM-main branch."

2. Freshness check: read the `version:` field in this file's frontmatter and compare it against the `version:` in the source copy at `metadata.source`. If the source version is higher, tell the user once: "Your MARM init skill is out of date. Re-run `marm-memory init` to refresh it." Then continue with the version you have.

Hold the protocol in context. You will operate under it after setup.

---

## Step 1 - Usage type

Ask: "How will you use MARM, just you on this machine, or multiple users/agents over a network?"
  - Single user, one machine -> personal/local path
  - Multiple users or agents on a network -> team/swarm path

Record the answer. It biases the transport recommendation in Step 3.

---

## Step 2 - Server location

Ask: "Run MARM locally, or connect to a server you own (VPS or homelab)?"
  - Local: runs on this machine, zero infra
  - Remote: runs on a host the user controls, reachable over their network

If remote, ask immediately and record it: "What address will agents reach that server on (hostname or IP, and port if it is not 8001)?" Do not defer this. Every connect command in Step 4 needs it, and the default text in those commands is `localhost`, which silently produces a working-looking local setup instead of a remote one. Record it as the host address and substitute it everywhere Step 4 prints `localhost`.

---

## Step 3 - Transport

Ask: "How should agents connect, HTTP or STDIO?"
  - HTTP: over the network. Needed for remote servers, multiple machines, or swarm agents. Requires an API key. Recommend this for the team/swarm path.
  - STDIO: local pipe, single machine, no key. Simplest. Recommend this for the personal/local path.

Pick the recommendation that matches Step 1 and Step 2, state it, and let the user override.

**Hard constraint, not a preference:** STDIO is a local pipe. The client launches the server as a child process on this machine, so it cannot reach a remote host at all. If Step 2 was remote, do not accept STDIO. Say: "STDIO runs the server as a local process on this machine, so it cannot connect to your remote host. Remote access needs HTTP." Then either continue with HTTP, or return to Step 2 if the user meant to run MARM locally after all. Never wire STDIO and describe the result as a remote connection.

---

## Step 4 - Runtime

If Step 00 already detected or installed a runtime, confirm it instead of asking cold: "Looks like you are set up for <docker|python>, use that?" Only ask the open question below if the runtime is genuinely unknown.

Ask: "Docker or local Python?"
  - Docker: isolated, easiest to keep updated.
  - Local Python: runs direct, good if Python is already set up. The package installs two entry points: `marm-mcp-server` (HTTP) and `marm-mcp-stdio` (STDIO).

You now have enough to act. Run the matching block.

**Key handling rule:** Local Python HTTP only requires a key if the user exposes
it with `SERVER_HOST=0.0.0.0` (remote/network access). Docker HTTP uses MARM's managed key file (`~/.marm/.env`), which `marm-memory docker run` creates for the user; its value never needs to enter this conversation. Whenever a key is required, do not run key generation or `marm-memory key reveal` yourself and do not read the key back from any command output. Have the user handle the value in their own terminal instead. Once the server is running, verify with an unauthenticated check (`curl http://localhost:8001/health`, no key needed) rather than asking them to paste the key back to you.

### HTTP + Local Python, local-only (no key) -- the fast path, recommend this for single-machine use

This is the one-shot. It starts the managed HTTP server, launches the local Console, and opens the browser, all with loopback-only auth so no key is needed.

Safe to run yourself:

  marm-memory fast-start-http

That leaves MARM live at `http://localhost:8001/mcp` and the Console at `http://localhost:8002`. Then connect this agent (loopback, no key):

  claude mcp add --transport http marm-memory http://localhost:8001/mcp

Because fast-start-http already started the server and the Console, Step 6 has nothing left to start; just verify and hand off.

### HTTP + Local Python, exposed (key required)

Only applies if the user asked for remote/network access in Step 2. Give them these steps to run themselves; do not execute steps 1 or 2 on their behalf:
1. Generate a key: `marm-memory key generate`
2. Start with their own key: `MARM_API_KEY=<paste-your-key> SERVER_HOST=0.0.0.0 marm-memory start` (PowerShell: `$env:MARM_API_KEY="<paste-your-key>"; $env:SERVER_HOST="0.0.0.0"; marm-memory start`)
3. Connect their client with their own key, substituting the Step 2 host address for `localhost` when the server is not on this machine: `claude mcp add --transport http marm-memory http://localhost:8001/mcp --header "Authorization: Bearer <paste-your-key>"`

Verify with `curl http://localhost:8001/health` once they confirm it's running. Do not ask them to paste the key into the chat.

### HTTP + Docker (managed, key handled for you)

`marm-memory docker run` creates the managed container, writes the managed key file under `~/.marm/.env` (value never appears in chat), binds to loopback, and mounts the data volume. Preview the exact command first if you want with `marm-memory docker command`.
1. Run: `marm-memory docker run` (add `--expose-network` only for remote access, then configure a firewall and TLS proxy)
2. Connect the client. The key lives in the managed key file; the user reads it themselves (`marm-memory key path` shows the file, `marm-memory key reveal` prints it in their own terminal) and pastes the value into their client, so it never enters chat: `claude mcp add --transport http marm-memory http://localhost:8001/mcp --header "Authorization: Bearer <paste-your-key>"`
3. Optional, code-graph tools: the container only sees host paths that are mounted, and `marm-memory docker run` refuses to alter an existing container. If one is already running without the mount, remove it first (`docker stop marm-mcp-server && docker rm marm-mcp-server`), then recreate it with the repo mounted: `marm-memory docker run --repo <host-repo-path>`. Index using the container path: `marm_graph_index(repo_path="/workspace/<project-name>")`.

Verify with `curl http://localhost:8001/health` and `marm-memory docker status`. Do not ask them to paste the key into the chat.

#### Docker with no helper CLI (cli = no from Step 00)

Use this block instead of the one above when Step 00 recorded cli = no. Do not issue `marm-memory` here; it is not installed.
1. The user generates a key in their own terminal: `docker run --rm lyellr88/marm-mcp-server:latest --generate-key`. Do not run this yourself and do not read the value back.
2. Start the container, substituting their key. Local only:

    docker run -d --name marm-mcp-server -p 127.0.0.1:8001:8001 -e SERVER_HOST=0.0.0.0 -e MARM_API_KEY=<paste-your-key> -v ~/.marm:/home/marm/.marm --restart unless-stopped lyellr88/marm-mcp-server:latest

   For remote access, publish on all interfaces instead (`-p 8001:8001`) and tell them to put a firewall and TLS proxy in front of it.
3. Connect the client with their own key, using the host address from Step 2 in place of `localhost` when the server is remote: `claude mcp add --transport http marm-memory http://localhost:8001/mcp --header "Authorization: Bearer <paste-your-key>"`

Verify with `curl http://localhost:8001/health` and `docker ps --filter name=marm-mcp-server`. Full reference: https://github.com/Lyellr88/marm-memory/blob/MARM-main/docs/INSTALL-DOCKER.md

### STDIO + Local Python (no key)
Local machine only. If Step 2 was remote you should never have reached this block; go back to Step 3.
Connect this agent to the STDIO entry point. No key needed: `claude mcp add marm-memory -- marm-mcp-stdio`

### STDIO + Docker (no key)
Print the exact client command and wire it into the agent's MCP config: `marm-memory docker stdio-command --client <agent>`

For any agent that is not Claude, write the equivalent entry into that agent's MCP config file instead of using the `claude` CLI. Same transport, same address or command. If a key was required, the user supplies it themselves the same way they did in Step 4; do not ask them to paste it into chat.

---

## Step 5 - Multi-agent linking

Ask: "Want to connect MARM to your other agents? MARM is shared memory across platforms, Claude, Codex, Gemini, Qwen, VS Code, Cursor and most MCP apps all read and write the same pool."

If yes:
  - Use the same transport for every agent. If a key was required, the user provides it themselves for each additional client the same way they did in Step 4; do not ask them to paste it into chat.
  - Use these docs to find the exact connection instructions for each client:

**CLI clients**: [Claude Code](https://github.com/Lyellr88/marm-memory/blob/MARM-main/docs/INSTALL-WINDOWS.md#claude-code-recommended) · [Codex](https://github.com/Lyellr88/marm-memory/blob/MARM-main/docs/INSTALL-WINDOWS.md#codex-cli) · [Gemini CLI](https://github.com/Lyellr88/marm-memory/blob/MARM-main/docs/INSTALL-WINDOWS.md#gemini-cli) · [Qwen CLI](https://github.com/Lyellr88/marm-memory/blob/MARM-main/docs/INSTALL-WINDOWS.md#qwen-code) · [Linux variants](https://github.com/Lyellr88/marm-memory/blob/MARM-main/docs/INSTALL-LINUX.md#client-connections) · [Docker/key](https://github.com/Lyellr88/marm-memory/blob/MARM-main/docs/INSTALL-DOCKER.md#client-connections)

**IDE agents**: [VS Code / Copilot Agent](https://github.com/Lyellr88/marm-memory/blob/MARM-main/docs/INSTALL-WINDOWS.md#vs-code-mcp--github-copilot-agent) · [Cursor](https://github.com/Lyellr88/marm-memory/blob/MARM-main/docs/INSTALL-WINDOWS.md#cursor) · [Docker/key IDE setup](https://github.com/Lyellr88/marm-memory/blob/MARM-main/docs/INSTALL-DOCKER.md#vs-code-mcp--github-copilot-agent)

**Remote/API platforms**: [xAI / Grok Remote MCP](https://github.com/Lyellr88/marm-memory/blob/MARM-main/docs/INSTALL-DOCKER.md#xai--grok-remote-mcp) · [Platform integration](https://github.com/Lyellr88/marm-memory/blob/MARM-main/docs/INSTALL-PLATFORMS.md)

- Report which agents you wired up and which you could not find.

If no, skip.

---

## Step 6 - Handoff and start

1. Start the server only if it is not already running, and honor the exact mode chosen in Steps 3-4:
  - STDIO (local or Docker): nothing to start; the client launches `marm-mcp-stdio` (or the Docker STDIO command) on demand. Skip to the handoff.
  - HTTP, local Python, loopback: `marm-memory fast-start-http` (skip if a fast-start-http path already started it).
  - HTTP, local Python, exposed: the user starts this themselves with their key and `SERVER_HOST=0.0.0.0` (Step 4). Do not auto-run `fast-start-http` here; it binds loopback without their key. Just verify once they confirm it is up.
  - HTTP, Docker: `marm-memory docker run`, keeping `--expose-network` if the user chose remote access in Step 2. If Step 00 recorded cli = no, use the raw `docker run` from Step 4 instead.
2. Verify before claiming success. Never report setup complete on an unverified path.
  - HTTP: `http://localhost:8001/health` should return ok. For a remote server, check the Step 2 host address, not `localhost`; a passing loopback check proves nothing about the remote host.
  - STDIO: confirm the entry point actually resolves (`marm-mcp-stdio --help`, or `docker images -q lyellr88/marm-mcp-server` for Docker STDIO) and that the MCP config entry you wrote is present. There is no server to health check, so this is the only evidence the wiring works.
3. Hand off with this message, adapted to what actually happened:

"Setup complete. Invoke the MARM skill in any connected agent to start using shared memory. Restart your terminal so the MARM connection is picked up. If you want to start your own server later, just ask."

Setup is done. The executor contract above is now closed. Operate under the MARM protocol you loaded in Step 0.

---

## Edge cases

- Cross-platform paths: Claude alone has several possible config locations by install method. Check all known paths in Step 5, and accept a user-provided path if the scan misses one.
- Stale skill file: handled by the Step 0 freshness check. If the source version is higher, tell the user to re-run `marm-memory init`.
- Remote server: Step 2 collects the host address up front and Step 4 substitutes it for `localhost`. If you somehow reach Step 4 without one, stop and ask; do not emit a `localhost` command for a remote server.
- Docker without the helper CLI: `docker pull` installs the image, not the `marm-memory` command. Step 00 records cli = yes or no, and Step 4 has a matching block for each. Never mix them.
- Non-Claude agents: the `claude mcp add` commands are examples. Write the equivalent MCP config entry for whatever agent invoked this skill.
