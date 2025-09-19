# MARM V2.2.4 MCP Server - Platform Integration Guide

## 📖 Table of Contents

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

This guide provides platform-specific instructions for integrating the MARM MCP Server with major AI applications and developer platforms as of September 2025.

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

#### **Grok Base App**

**Supported:** ❌ No MCP support for consumer app

#### **Grok Developer Platform**

**Supported:** ⚠️ Same limitations as Gemini
**Requirements:** xAI API access

**Current Status:**

- Limited to CLI or custom developer builds
- No native MCP support in base application
- Manual function calling integration required

---

## Part 2: Developer Integration

### **Adding MARM to Custom Applications**

If you're building your own application with any LLM provider, here's the basic pattern:

**1. Install MCP Client:**

```bash
pip install fastapi-mcp-client
```

**2. Connect to MARM:**

```python
from fastapi_mcp_client import MCPClient

async with MCPClient("http://localhost:8001") as client:
    tools = await client.get_tools()  # Auto-discover MARM's 19 tools
    result = await client.call_operation("marm_system_info", {})
```

**3. Use with your LLM:**

- **OpenAI:** Pass `tools` to `chat.completions.create()`
- **Anthropic:** Use `tools` parameter in Claude API
- **Google/Grok:** Convert to their function calling format

Each provider has different API patterns, but the MARM connection stays the same. If you're developing, you already know how to integrate tools with your chosen LLM platform.

---

## Part 3: Coming Soon - Unified SDK Solutions

### **Future Integration Options**

For developers who want simplified multi-provider support:

**Unified SDK Platforms:**

- **AI SDK (Open Source)** - Single interface for all providers
- **KrakenD AI Gateway** - API gateway with tool standardization
- **LangChain MCP Support** - Framework-level integration

**Benefits:**

- Write tool integration once
- Automatic translation for each provider
- Standardized interface across all LLMs
- No provider-specific code changes needed

**Expected Timeline:** Q1 2026

---

## Platform Comparison Summary

| Platform | Base App Support | Developer Support | MCP Ready | Notes |
|----------|------------------|-------------------|-----------|-------|
| **Claude** | ✅ Full (Remote) | ✅ Full | ✅ Yes | Best MCP support |
| **ChatGPT** | ⚠️ Developer Mode | ✅ API + Playground | ⚠️ Basic | Sept 2025 addition |
| **Gemini** | ❌ None | ⚠️ Function Calling | ❌ No | Manual definitions required |
| **Grok** | ❌ None | ⚠️ Function Calling | ❌ No | CLI only currently |

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

---

### **Found Issues? We Want to Hear!**

If any tests fail or you encounter problems:

- **🐛 Open an [Issue]((https://github.com/Lyellr88/MARM-Systems/issues)**: Report problems on GitHub
- **🔧 Submit a [Pull Request](https://github.com/Lyellr88/MARM-Systems/pulls)**: Fixed it yourself? We welcome contributions!
- **💬 Join Discussions**: Share feedback and get help from the community

---

## 📁 Project Documentation

### **Usage Guides**

- **[MARM-HANDBOOK.md](https://github.com/Lyellr88/MARM-Systems/blob/MARM-main/MARM-HANDBOOK.md)** - Original MARM protocol handbook for chatbot usage
- **[MCP-HANDBOOK.md](https://github.com/Lyellr88/MARM-Systems/blob/MARM-main/MCP-HANDBOOK.md)** - Complete MCP server usage guide with commands, workflows, and examples
- **[PROTOCOL.md](https://github.com/Lyellr88/MARM-Systems/blob/MARM-main/PROTOCOL.md)** - Quick start commands and protocol reference
- **[FAQ.md](https://github.com/Lyellr88/MARM-Systems/blob/MARM-main/docs/FAQ.md)** - Answers to common questions about using MARM

### **MCP Server Installation** 

- **[INSTALL-DOCKER.md](https://github.com/Lyellr88/MARM-Systems/blob/MARM-main/docs/INSTALL-DOCKER.md)** - Docker deployment (recommended)
- **[INSTALL-WINDOWS.md](https://github.com/Lyellr88/MARM-Systems/blob/MARM-main/docs/INSTALL-WINDOWS.md)** - Windows installation guide
- **[INSTALL-LINUX.md](https://github.com/Lyellr88/MARM-Systems/blob/MARM-main/docs/INSTALL-LINUX.md)** - Linux installation guide
- **[INSTALL-PLATFORMS.md](https://github.com/Lyellr88/MARM-Systems/blob/MARM-main/docs/INSTALL-PLATFORMS.md)** - Platfrom installtion guide

### **Chatbot Installation**

- **[CHATBOT-SETUP.md](https://github.com/Lyellr88/MARM-Systems/blob/MARM-main/docs/CHATBOT-SETUP.md)** - Web chatbot setup guide

### **Project Information**

- **[README.md](https://github.com/Lyellr88/MARM-Systems/blob/MARM-main/README.md)** - This file - ecosystem overview and MCP server guide
- **[CONTRIBUTING.md](https://github.com/Lyellr88/MARM-Systems/blob/MARM-main/docs/CONTRIBUTING.md)** - How to contribute to MARM
- **[DESCRIPTION.md](https://github.com/Lyellr88/MARM-Systems/blob/MARM-main/docs/DESCRIPTION.md)** - Protocol purpose and vision overview
- **[CHANGELOG.md](https://github.com/Lyellr88/MARM-Systems/blob/MARM-main/docs/CHANGELOG.md)** - Version history and updates
- **[ROADMAP.md](https://github.com/Lyellr88/MARM-Systems/blob/MARM-main/docs/ROADMAP.md)** - Planned features and development roadmap
- **[LICENSE](https://github.com/Lyellr88/MARM-Systems/blob/MARM-main/docs/LICENSE)** - MIT license terms

---

>Built with ❤️ by MARM Systems - Universal MCP memory intelligence
