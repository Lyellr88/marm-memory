# MARM Protocol - Core Principles & Quick Start

## Understanding the Foundation of Memory Accurate Response Mode

**MARM v2.2.6** - Universal Protocol for AI Memory Intelligence

---

## Short Introduction

MARM is a universal protocol designed to improve memory continuity and response accuracy during AI conversations. This guide covers beginner guidance, command usage, and recovery strategies for when memory or accuracy begins to drift.

## What's New in v2.2.6

### MARM version updates

| Version | Key Features | Major Changes |
|---------|-------------|---------------|
| **v1.2** | Session Relay Tools | `/summary:`, reseeding, schema enforcement |
| **v1.3** | Manual Knowledge Library | `/notebook` commands introduced |
| **v1.4** | Enhanced Commands | Expanded `/log` and `/notebook` functionality |
| **v1.5** | Live Chatbot | Session persistence, voice synthesis, command menu |
| **v2.0** | Major Protocol Overhaul | Updated syntax, enhanced chatbot, Llama 4 Maverick |

### v2.2.6 (Current) - Universal MCP Server

#### MCP Server Architecture

- **19 Complete MCP Tools** - Full Model Context Protocol implementation with semantic search
- **Production FastAPI Backend** - SQLite with WAL mode, connection pooling, rate limiting
- **Cross-Platform Compatibility** - Works with Claude Code, Qwen CLI, Gemini CLI, Grok CLI
- **Docker Deployment** - Containerized with health monitoring and professional diagnostics

#### Memory Intelligence Features

- **Semantic Search** - AI-powered similarity search using sentence-transformers
- **Auto-Classification** - Content intelligently categorized (code, project, book, general)
- **Cross-Session Memory** - Memories persist across different AI agent conversations
- **Smart Recall** - Vector similarity search with context-aware fallbacks

#### Technical Excellence

- **Database Optimization** - Custom connection pooling with configurable limits
- **MCP Compliance** - 1MB response size management with intelligent truncation
- **Security Hardening** - IP-based rate limiting, XSS protection, error isolation
- **Performance Monitoring** - Built-in diagnostic tests and health validation

---

## Part I: Core Principles

### What is MARM?

MEMORY ACCURATE RESPONSE MODE (MARM) ensures accurate AI interactions by maintaining context through structured, user-directed controls. It prevents memory drift, improving AI transparency and reliability.

**Powered by Llama 4 Maverick** - 400B parameter multimodal model providing cost-effective AI intelligence.

### Why Manual Steps Matter

Manual logging, knowledge entry, and accuracy checks prevent silent drift. User visibility ensures context and accuracy remain aligned.

### User Controls

**Memory:**

- `/log session:` - Labels session (think of it as creating folders)
- `/log entry:` - Logs structured milestones (Schema enforced, corrects invalid formats)

**Knowledge:**

- `/notebook add:` - Add trusted user-defined info (Keep entries concise for token efficiency)
- `/notebook use:` - Activate entries as instructions (Multiple via comma: `name1,name2`)

**Accuracy:**

- `/deep dive` - Forces accuracy-driven responses (Includes self-checks and validation)
- `/show reasoning` - Displays AI's reasoning trail (Use for transparency and verification)

This approach ensures the AI works with **user-led intent**, reducing drift across sessions and platforms.
