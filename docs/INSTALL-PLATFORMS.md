# MARM v2.9.1 MCP Server - Platform Integration Guide

## Table of Contents

- [Overview](#overview-connecting-marm-to-apps--platforms)
- [Part 1: Base Application Integration](#part-1-base-application-integration)
  - [Claude (Anthropic)](#claude-anthropic)
  - [ChatGPT (OpenAI)](#chatgpt-openai)
  - [Gemini (Google)](#gemini-google)
  - [Grok (xAI)](#grok-xai)
- [Part 2: Developer Integration](#part-2-developer-integration)
- [Part 3: Coming Soon - Unified SDK Solutions](#part-3-coming-soon---unified-sdk-solutions)
- [Platform Comparison Summary](#platform-comparison-summary)
- [Best Practices](#best-practices)

---

## Overview: Connecting MARM to Apps & Platforms

This guide provides platform-specific instructions for integrating the MARM MCP Server with major AI applications and developer platforms.

**Important:** This covers **base applications** and **API integrations** - not CLI tools. For CLI setup, see the dedicated docs folder for install guides [Docs](https://github.com/Lyellr88/MARM-Systems/tree/MARM-main/docs)

---

## Part 1: Base Application Integration

### **Claude (Anthropic)**

#### **Claude Web App (claude.ai)**

**Supported:** ✅ Remote MCP servers
**Requirements:** Pro, Max, Team, or Enterprise plans

**Setup Process:**

1. Log in to [claude.ai](https://claude.ai) in your browser
2. Go to **Settings > Connectors**
3. Click **"+ Add custom connector"**
4. Enter your MARM server URL: `http://your-server.com:8001/mcp`
5. Tools automatically available in web and mobile apps

#### **Claude Mobile Apps (iOS/Android)**

**Supported:** ✅ Remote servers only (no localhost)
**Requirements:** Pro+ plans, must configure via web first

**Setup Process:**

1. First configure via claude.ai web app (above)
2. Mobile app automatically syncs connected tools
3. Enable/disable tools per chat in mobile app settings

#### **Claude Workbench (Developer)**

**Supported:** ✅ Full MCP integration
**Requirements:** Anthropic API access

**Setup Process:**

1. In Workbench interface, select **"Tools"** or **"MCP Server"** integration
2. Add MARM URL: `http://localhost:8001/mcp`
3. Define tool usage in your agent configuration
4. Test tool calls with prompt triggers

---

### **ChatGPT (OpenAI)**

#### **ChatGPT Base App (chat.openai.com)**

**Supported:** ✅ Developer Mode only (Sept 2025 update)
**Requirements:** ChatGPT Pro, Business, Enterprise, or Education plans

**Setup Process:**

1. Enable **Developer Mode** in ChatGPT settings
2. Navigate to **Connectors** section
3. Add custom connector with MARM URL: `http://your-server.com:8001/mcp`
4. Supports both read and write actions

**Limitations:**

- Remote servers only (no localhost support)
- Implementation is basic compared to Claude
- GPT-5 not fully MCP-ready yet

#### **OpenAI Playground**

**Supported:** ✅ Testing only (does not execute)
**Requirements:** OpenAI API access

**How it works:**

- Playground generates tool calls but doesn't execute them
- Shows function call output for inspection
- Manually provide tool responses to test model behavior
- Prevents accidental real-world actions during development

---

### **Gemini (Google)**

#### **Gemini Base App (gemini.google.com)**

**Supported:** ❌ No MCP support

#### **Google AI Studio**

**Supported:** ⚠️ Limited function calling (not full MCP)
**Requirements:** Google AI Studio access

**How it works:**

- Generates function calls as structured output
- Does not execute tools during testing
- Must use Gemini SDK in your own application for execution
- Manual tool definition required (no auto-discovery)

---

### **Grok (xAI)**

#### **Grok Base App (grok.com & Mobile)**

**Supported:** ❌ Not compatible with standard MARM deployment

Grok's MCP connector support requires a **public HTTPS URL**. MARM runs on `localhost:8001` by default and Docker binds to `127.0.0.1` — xAI's servers cannot reach either. You would need to host MARM on a public server with a domain and TLS certificate for this to work.

#### **Grok Developer Platform**

**Supported:** ✅ Remote MCP via xAI API
**Requirements:** xAI Developer API access

**Current Status:**

- Remote MCP Tools support Streaming HTTP and SSE transports
- `localhost` does not work — xAI connects from its own infrastructure
- Requires a publicly resolvable HTTPS MARM endpoint
- Authenticate by passing `authorization: "Bearer <MARM_API_KEY>"` in the tool config header

---

## Part 2: Developer Integration

### **Adding MARM to Custom Applications**

If you're building your own application with any LLM provider, here's the basic pattern:

**1. Install MCP Client:**

```bash
pip install mcp
```

**2. Connect to MARM:**

```python
from mcp.client.streamable_http import streamablehttp_client
from mcp import ClientSession

async with streamablehttp_client("http://localhost:8001/mcp") as (read, write, _):
    async with ClientSession(read, write) as session:
        await session.initialize()
        tools = await session.list_tools()
        result = await session.call_tool("marm_smart_recall", {"query": "test"})
```

**3. Use with your LLM:**

- **OpenAI:** Pass `tools` to `chat.completions.create()`
- **Anthropic:** Use `tools` parameter in Claude API
- **Google:** Convert to Gemini's function calling format
- **Grok:** Use xAI Remote MCP Tools with your hosted MARM endpoint

Each provider has different API patterns, but the MARM connection stays the same. If you're developing, you already know how to integrate tools with your chosen LLM platform.

---

## Platform Comparison Summary

| Platform | Base App Support | Developer Support | MCP Ready | Notes |
|----------|------------------|-------------------|-----------|-------|
| **Claude** | ✅ Full (Remote) | ✅ Full | ✅ Yes | Best MCP support |
| **ChatGPT** | ⚠️ Developer Mode | ✅ API + Playground | ⚠️ Basic | Sept 2025 addition |
| **Gemini** | ❌ None | ⚠️ Function Calling | ❌ No | Manual definitions required |
| **Grok** | ❌ None (requires public HTTPS) | ✅ API Remote MCP | ✅ Yes | Requires public HTTPS endpoint; no localhost |

---

## Best Practices

**For Production Applications:**

- Use remote MARM deployment (not localhost)
- Implement proper error handling for tool calls
- Cache frequently accessed memories
- Monitor tool usage and performance

**For Development:**

- Start with Claude for best MCP experience
- Use Playground/Studio for testing without execution
- Test with multiple providers for compatibility
- Implement fallback for unsupported platforms

---

**Need Help?** Check our **[README.md](https://github.com/Lyellr88/MARM-Systems/blob/MARM-main/README.md)**  or [join Discord](https://discord.gg/EuBsHvSRks) for integration support.
