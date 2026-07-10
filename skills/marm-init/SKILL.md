---
name: marm-init
description: Guided MARM MCP setup. Invoke after running `marm-init` on the CLI to configure MARM memory across your agent. Drives transport choice, runtime choice, MCP config writing, multi-agent linking, dashboard, and server start. Works on Claude, Codex, Gemini, Qwen, Cursor, VS Code, and other MCP-capable agents.
version: 1
metadata:
  description: A local-first, privacy-centric memory infrastructure layer for MCP clients. MARM provides a persistent data substrate for long-term project memory, session serialization, and structured notebook reuse across terminal-based workflows. Operating via a lean, 7-tool surface, it offloads heavy state tracking to an optimized backend featuring SQLite WAL storage, write-time consolidation, and automated re-ranking filters. This ensures deterministic context retrieval, prevents multi-agent session drift, and enforces strict token-budget guardrails by deduplicating and pruning data before it hits the model's context window. Includes a live web dashboard for managing memories, logs, and sessions.
  source: https://raw.githubusercontent.com/Lyellr88/marm-memory/MARM-main/skills/marm-init/SKILL.md
  protocol_source: https://raw.githubusercontent.com/Lyellr88/marm-memory/MARM-main/docs/PROTOCOL.md
---

<MARM_INIT_EXECUTOR_ACTIVE>

=== MARM INIT PROTOCOL - YOU ARE THE INSTALLER ===

RULE ZERO (highest priority):
This file is not documentation to summarize. It is a setup program and you are
the runtime. Execute it top to bottom. Run the steps, ask the questions, write
the files, and start the server. Do not paste this content back to the user as
text. Do not narrate what the skill "would" do. You do it.

You are MARM's installer for this agent. Your job is to leave the user with a
live MARM connection in as few questions as possible. One question at a time,
wait for the answer, then act on it before moving on.

Scope: this protocol governs only the setup conversation below. Once setup is
complete and you have run Step 7, this contract ends and you return to normal
operation under the MARM protocol you loaded in Step 0.

Failure mode to avoid: dumping install docs and leaving the user to do the work
by hand. That is the exact outcome this skill exists to prevent.

</MARM_INIT_EXECUTOR_ACTIVE>

---

## Step 00 - Engine pre-flight 

Run this first, before anything else. If the skill was installed on its own (for
example from a marketplace) the MARM core engine may not be on the machine yet.
Confirm it is present, or install it, before continuing.

1. Scan the host for the core engine:
   - CLI entry points on PATH. Unix: `command -v marm-mcp-server || command -v marm-mcp-stdio`. PowerShell: `Get-Command marm-mcp-server, marm-mcp-stdio -ErrorAction SilentlyContinue`.
   - Docker image present locally: `docker images -q lyellr88/marm-mcp-server`.

2. Branch:
   - Engine found: record which runtime you found (python or docker), say nothing to the user, and skip to Step 0. The detected runtime pre-answers Step 4, so in Step 4 confirm it rather than asking cold.
   - Nothing found: stop and run the install prompt below.

3. Install prompt (only when nothing was found):
   Ask: "I could not find the MARM core engine on your machine. How do you want to install it?
   - Option A, pip (local Python): best if you already use Python and want a
     lightweight native install with no containers.
   - Option B, Docker: best for a clean, isolated setup with no Python path
     management."

4. Execute the choice and verify before advancing:
   - pip: run `pip install marm-mcp-server`. Confirm success, for example
     `marm-mcp-server --version` resolves. Record runtime = python.
   - Docker: run `docker pull lyellr88/marm-mcp-server:2.20.0`. Confirm the image
     is present with `docker images -q lyellr88/marm-mcp-server`. Record
     runtime = docker.

   If the install fails, surface the actual error and stop. Do not proceed to
   setup against a missing engine.

---

## Step 0 - Load the protocol and check freshness

Do this before talking to the user.

1. Read the full MARM protocol from source:
   `https://raw.githubusercontent.com/Lyellr88/marm-memory/MARM-main/docs/PROTOCOL.md`
   If the network read fails, fall back in this order:
   - local repo `docs/PROTOCOL.md`
   - packaged copy `marm-mcp-server/marm-docs/PROTOCOL.md`
2. Freshness check: read the `version:` field in this file's frontmatter and
   compare it against the `version:` in the source copy at `metadata.source`.
   If the source version is higher, tell the user once:
   "Your MARM init skill is out of date. Re-run `marm-init` to refresh it."
   Then continue with the version you have.

Hold the protocol in context. You will operate under it after setup.

---

## Step 1 - Usage type

Ask: "How will you use MARM, just you on this machine, or multiple users/agents
over a network?"

- Single user, one machine -> personal/local path
- Multiple users or agents on a network -> team/swarm path

Record the answer. It biases the transport recommendation in Step 3.

---

## Step 2 - Server location

Ask: "Run MARM locally, or connect to a server you own (VPS or homelab)?"

- Local: runs on this machine, zero infra
- Remote: runs on a host the user controls, reachable over their network

If remote, you will need the host address later for the connect command.

---

## Step 3 - Transport

Ask: "How should agents connect, HTTP or STDIO?"

- HTTP: over the network. Needed for remote servers, multiple machines, or swarm
  agents. Requires an API key. Recommend this for the team/swarm path.
- STDIO: local pipe, single machine, no key. Simplest. Recommend this for the
  personal/local path.

Pick the recommendation that matches Step 1 and Step 2, state it, and let the
user override.

---

## Step 4 - Runtime

If Step 00 already detected or installed a runtime, confirm it instead of asking
cold: "Looks like you are set up for <docker|python>, use that?" Only ask the
open question below if the runtime is genuinely unknown.

Ask: "Docker or local Python?"

- Docker: isolated, easiest to keep updated.
- Local Python: runs direct, good if Python is already set up. The package
  installs two entry points: `marm-mcp-server` (HTTP) and `marm-mcp-stdio` (STDIO).

You now have enough to act. Run the matching block.

**Key handling rule:** Docker HTTP always requires an `MARM_API_KEY`; local Python HTTP only requires one if the user exposes it with `SERVER_HOST=0.0.0.0` (remote/network access). Whenever a key is required, do not run `--generate-key` yourself and do not read the key back from any command output. Print the steps below for the user to run in their own terminal instead, so the key value never enters this conversation. Once they confirm the server is running, verify with an unauthenticated check (`curl http://localhost:8001/health`, no key needed) rather than asking them to paste the key back to you.

### HTTP + Docker (key required)
Give the user these steps to run themselves; do not execute steps 1, 3, or 4 on their behalf:
1. Generate a key: `docker run --rm lyellr88/marm-mcp-server:2.20.0 --generate-key`
2. Pull the image (you may run this step, it has no secret in it): `docker pull lyellr88/marm-mcp-server:2.20.0`
3. Run, with their own key pasted in:
   ```
   docker run -d --name marm-mcp-server \
     -p 127.0.0.1:8001:8001 \
     -e SERVER_HOST=0.0.0.0 \
     -e MARM_API_KEY=<paste-your-key> \
     -v ~/.marm:/home/marm/.marm \
     lyellr88/marm-mcp-server:2.20.0
   ```
   For remote access, change the bind to `-p 8001:8001`.
4. Connect their MCP client with their own key (adapt the CLI shown for the active agent):
   `"agent" mcp add --transport http marm-memory http://localhost:8001/mcp --header "Authorization: Bearer <paste-your-key>"`

   Windows/PowerShell agents that use a bearer-token-env-var flag (for example Codex):
   ```
   $env:MARM_API_KEY="<paste-your-key>"
   codex mcp add marm-memory --url http://localhost:8001/mcp --bearer-token-env-var MARM_API_KEY
   ```
5. They can smoke test themselves: `curl -i -H "Authorization: Bearer <their-key>" http://127.0.0.1:8001/mcp` (PowerShell: `curl -i -H "Authorization: Bearer $env:MARM_API_KEY" http://127.0.0.1:8001/mcp`). `406` means auth reached the MCP endpoint; `401` means the key is missing or mismatched.
6. Optional, code-graph tools: the container cannot see host paths unless mounted. Add a second volume line for the repo to index, then use the container path (not the host path) with `marm_graph_index`:
   ```
   -v <host-repo-path>:/workspace/<project-name>
   ```
   `marm_graph_index(repo_path="/workspace/<project-name>")`. Mounts cannot be added to an already-running container; stop and recreate it with the mount to enable graph indexing.

Once they say it's running, verify with `curl http://localhost:8001/health` and confirm tools appear in their client. Do not ask them to paste the key into the chat.

### HTTP + Local Python, local-only (no key)
Default bind is loopback and needs no key. Safe to run yourself:
1. Start: `marm-mcp-server`
2. Connect: `claude mcp add --transport http marm-memory http://localhost:8001/mcp`

### HTTP + Local Python, exposed (key required)
Only applies if the user asked for remote/network access in Step 2. Give them these steps to run themselves; do not execute steps 1 or 2 on their behalf:
1. Generate a key: `marm-mcp-server --generate-key`
2. Start with their own key: `MARM_API_KEY=<paste-your-key> SERVER_HOST=0.0.0.0 marm-mcp-server` (PowerShell: `$env:MARM_API_KEY="<paste-your-key>"; $env:SERVER_HOST="0.0.0.0"; marm-mcp-server`)
3. Connect their client with their own key:
   `claude mcp add --transport http marm-memory http://localhost:8001/mcp --header "Authorization: Bearer <paste-your-key>"`

Verify with `curl http://localhost:8001/health` once they confirm it's running. Do not ask them to paste the key into the chat.

### STDIO + Docker
1. Connect this agent to the STDIO entry inside the image. No key needed.
   Write the MCP config so the agent launches `marm-mcp-stdio` in the container.

### STDIO + Local Python
1. No key needed.
2. Connect (Claude CLI shown):
   `claude mcp add marm-memory -- marm-mcp-stdio`

For any agent that is not Claude, write the equivalent entry into that agent's
MCP config file instead of using the `claude` CLI. Same transport, same address
or command. If a key was required, the user supplies it themselves the same way
they did in Step 4; do not ask them to paste it into chat.

---

## Step 5 - Multi-agent linking

Ask: "Want to connect MARM to your other agents? MARM is shared memory across
platforms, Claude, Codex, Gemini, Qwen, VS Code, Cursor and most MCP apps all
read and write the same pool."

If yes:
- Use the same transport for every agent. If a key was required, the user
  provides it themselves for each additional client the same way they did in
  Step 4; do not ask them to paste it into chat.
- Use these docs to find the exact connection instructions for each client:

  **CLI clients** — [Claude Code](https://github.com/Lyellr88/marm-memory/blob/MARM-main/docs/INSTALL-WINDOWS.md#claude-code-recommended) · [Codex](https://github.com/Lyellr88/marm-memory/blob/MARM-main/docs/INSTALL-WINDOWS.md#codex-cli) · [Gemini CLI](https://github.com/Lyellr88/marm-memory/blob/MARM-main/docs/INSTALL-WINDOWS.md#gemini-cli) · [Qwen CLI](https://github.com/Lyellr88/marm-memory/blob/MARM-main/docs/INSTALL-WINDOWS.md#qwen-code) · [Linux variants](https://github.com/Lyellr88/marm-memory/blob/MARM-main/docs/INSTALL-LINUX.md#client-connections) · [Docker/key](https://github.com/Lyellr88/marm-memory/blob/MARM-main/docs/INSTALL-DOCKER.md#client-connections)

  **IDE agents** — [VS Code / Copilot Agent](https://github.com/Lyellr88/marm-memory/blob/MARM-main/docs/INSTALL-WINDOWS.md#vs-code-mcp--github-copilot-agent) · [Cursor](https://github.com/Lyellr88/marm-memory/blob/MARM-main/docs/INSTALL-WINDOWS.md#cursor) · [Docker/key IDE setup](https://github.com/Lyellr88/marm-memory/blob/MARM-main/docs/INSTALL-DOCKER.md#vs-code-mcp--github-copilot-agent)

  **Remote/API platforms** — [xAI / Grok Remote MCP](https://github.com/Lyellr88/marm-memory/blob/MARM-main/docs/INSTALL-DOCKER.md#xai--grok-remote-mcp) · [Platform integration](https://github.com/Lyellr88/marm-memory/blob/MARM-main/docs/INSTALL-PLATFORMS.md)

- Report which agents you wired up and which you could not find.

If no, skip.

---

## Step 6 - Dashboard

Ask: "Want the MARM dashboard? It is a light UI to browse and manage your
memories."

If yes: start the server if it is not already running, then give the user the
address: http://localhost:8001/dashboard. If a key was required for this setup,
tell the user they will need to enter it in the dashboard's own UI; do not ask
them for it in chat.

If no, skip.

---

## Step 7 - Handoff and start

1. If the MARM server is not already running, start it now using the runtime and
   transport chosen above (Docker run command or the Python entry point). If it
   is already running, skip the start.
2. Verify HTTP setups with a health check: `http://localhost:8001/health` should
   return ok.
3. Hand off with this message, adapted to what actually happened:

   "Setup complete. Invoke the MARM skill in any connected agent to start using
   shared memory. Restart your terminal so the MARM connection is picked up. If
   you want to start your own server or the dashboard later, just ask."

Setup is done. The executor contract above is now closed. Operate under the MARM
protocol you loaded in Step 0.

---

## Step 8 - Email list (optional)

After the handoff message in Step 7, ask these two questions in order.
One at a time. Wait for the answer before asking the next.

1. "Has setting up MARM been useful so far?"
   - No: thank them and skip the rest of this step.
   - Yes: continue to question 2.

2. "Would you like to join the MARM email list to get updates?"
   - No: thank them and move on.
   - Yes: check if you have an email tool available in this session.
     * Email available: "I can send a quick opt-in to info@marmsystems.com
       for you, or I can give you the address to send yourself. Which do you
       prefer?" Do NOT send without explicit confirmation.
     * No email tool: "Send a quick email to info@marmsystems.com with
       subject 'MARM Opt-In' to join the list."

This step is informational only. Do not record or store the user's answer.

---

## Edge cases

- Cross-platform paths: Claude alone has several possible config locations by
  install method. Check all known paths in Step 5, and accept a user-provided
  path if the scan misses one.
- Stale skill file: handled by the Step 0 freshness check. If the source version
  is higher, tell the user to re-run `marm-init`.
- Remote server: the connect command in Step 4 uses `localhost`. Swap in the
  real host address when the server runs elsewhere.
- Non-Claude agents: the `claude mcp add` commands are examples. Write the
  equivalent MCP config entry for whatever agent invoked this skill.
