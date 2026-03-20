# MARM Systems - Coder Essentials

**Version**: 2.2.5 | **Target**: Coding agents, new developers | **Lines**: ~280

---

## Project Overview

### What is MARM?

MARM (Memory Accurate Response Mode) is a **Universal MCP Server** providing AI memory intelligence, semantic search, and structured reasoning for LLM agents. Three main components:

1. **MARM Universal MCP Server** (Python/FastAPI) - Production-ready memory backend
2. **MARM Webchat** (HTML/JS) - Web-based MARM protocol interface
3. **MARM New UI** (React/TypeScript) - Modern React interface with Tailwind CSS

### Current Status

- **Production Ready**: v2.2.5 deployed to PyPI, Docker Hub, and MCP Registry
- **WebSocket Support**: Complete HTTP/WebSocket parity with full MCP method coverage
- **Docker Containerized**: Multi-stage builds with 99.7/100 performance scores
- **Multi-Platform CI/CD**: GitHub Actions for automated publishing

### Strategic Position

MARM operates in the emerging MCP ecosystem as memory intelligence platform. Not competing with AI giants but providing specialized memory infrastructure.

---

## Architecture Deep Dive

### Technology Stack

```
MARM Universal MCP Server v2.2.5
├── Backend: FastAPI (0.115.4) + FastAPI-MCP (0.4.0)
├── Database: SQLite with WAL Mode + Connection Pooling
├── AI/ML: Sentence Transformers (all-MiniLM-L6-v2)
├── WebSocket: JSON-RPC 2.0 + Real-time MCP Protocol
├── Security: IP-based Rate Limiting + XSS Protection
├── Logging: Structured Logging (structlog)
├── Deployment: Docker Multi-stage + Health Monitoring
└── Memory Intelligence: Vector Embeddings + Auto-Classification
```

### Core Architecture Principles

1. **SIMPLE IS BETTER THAN COMPLICATED** - Never over-engineer basic tasks
2. **Modular Design** - Clean separation of concerns with endpoint routers
3. **Production-Grade** - Connection pooling, rate limiting, health checks
4. **MCP Compliance** - Full protocol implementation with size limits
5. **Memory Intelligence** - Semantic search with fallback to text search

### High-Level System Design

```
┌─────────────────┐    ┌──────────────────┐    ┌─────────────────┐
│   AI Clients    │    │   MARM Server    │    │   Memory Store  │
│ (Claude, Qwen)  │◄──►│   (FastAPI)      │◄──►│   (SQLite)      │
└─────────────────┘    └──────────────────┘    └─────────────────┘
       │                         │                        │
       │                         ▼                        │
┌─────────────────┐    ┌──────────────────┐    ┌─────────────────┐
│  WebSocket/HTTP │    │   MCP Protocol   │    │  Vector Search  │
│   Endpoints     │    │   (19 Methods)   │    │  (Embeddings)   │
└─────────────────┘    └──────────────────┘    └─────────────────┘
```

---

## Development Environment Setup

### Prerequisites

- **Python 3.10+** (Tested with 3.11)
- **Docker** (for containerized development)
- **Git** (for version control)
- **VS Code or equivalent** (with Python extensions)

### Quick Setup Commands

```bash
# 1. Clone the repository
git clone https://github.com/Lyellr88/MARM-Systems
cd MARM-Systems

# 2. Install MCP server dependencies
cd marm-mcp-server
pip install -r requirements.txt

# 3. Run development server
python server.py  # or: uvicorn server:app --reload --port 8001

# 4. Connect to Claude Code
claude mcp add marm-memory http://localhost:8001/mcp

# 5. Test connection
curl http://localhost:8001/health
```

### Docker Development Setup

```bash
# Build and run with Docker
docker build -t marm-mcp-server .
docker run -d --name marm-dev -p 8001:8001 -v marm_data:/app/data marm-mcp-server

# Development with hot reload
docker compose up --build
```

### UI Development Setup

**Webchat (Traditional)**:

```bash
cd webchat
# Serve with any static server
python -m http.server 8080
```

**New UI (React)**:

```bash
cd marm-new-ui
npm install
npm run dev  # Starts on port 5173
```

---

## Core Components & File Structure

### Project Directory Structure

```
MARM-Systems-MARM-main/
├── marm-mcp-server/           # Main MCP server (Python)
│   ├── server.py              # Main FastAPI application
│   ├── config/
│   │   └── settings.py        # Configuration management
│   ├── core/
│   │   ├── memory.py          # Memory system with SQLite pool
│   │   ├── models.py          # Pydantic request/response models
│   │   ├── events.py          # Event system for automation
│   │   ├── rate_limiter.py    # IP-based rate limiting
│   │   ├── response_limiter.py # MCP size compliance
│   │   └── websocket_manager.py # WebSocket connection handling
│   ├── endpoints/             # FastAPI routers
│   │   ├── session.py         # MARM protocol activation
│   │   ├── memory.py          # Smart recall & contextual logging
│   │   ├── logging.py         # Session logging system
│   │   ├── notebook.py        # Knowledge management
│   │   ├── reasoning.py       # Context bridging & summaries
│   │   ├── system.py          # Health checks & diagnostics
│   │   └── websocket.py       # WebSocket endpoints
│   ├── middleware/            # FastAPI middleware
│   │   ├── rate_limiting.py   # HTTP rate limiting
│   │   └── websocket_rate_limiting.py # WebSocket rate limiting
│   ├── services/              # Background services
│   │   ├── automation.py      # Event handlers
│   │   └── documentation.py   # Doc loading system
│   ├── tests/                 # Comprehensive test suite
│   ├── Dockerfile             # Multi-stage Docker build
│   ├── requirements.txt       # Python dependencies
│   └── pyproject.toml         # Package configuration
├── webchat/                   # Traditional web interface
│   ├── index.html             # Main chat interface
│   ├── src/chatbot/           # JavaScript modules
│   └── style/                 # CSS and assets
├── marm-new-ui/               # Modern React interface
│   ├── src/components/        # React components
│   ├── config/                # Build configuration
│   └── package.json           # npm dependencies
└── docs/                      # Documentation (install guides, etc.)
```

### Key File Responsibilities

| File | Purpose | Key Functions |
|------|---------|---------------|
| `server.py` | Main application entry point | FastAPI app, lifespan management, router inclusion |
| `core/memory.py` | Memory intelligence system | SQLite pool, semantic search, XSS protection |
| `core/models.py` | Request/response schemas | Pydantic models for API validation |
| `endpoints/memory.py` | Core memory operations | Smart recall, contextual logging |
| `endpoints/session.py` | MARM protocol management | Session activation, protocol loading |
| `config/settings.py` | Configuration management | Database paths, feature flags, rate limits |

---

## Development Philosophy

### Core Development Principles

1. **SIMPLE IS BETTER THAN COMPLICATED** - Avoid over-engineering
2. **Explain before executing** - Get buy-in before major changes
3. **Use TodoWrite proactively** - Track complex tasks
4. **Check files to confirm assumptions** - Verify current state
5. **Surgical vs wide-shot changes** - Targeted modifications preferred
6. **Keep backups via cp dump.txt** - Safety first
7. **Partnership over delegation** - Collaboration, not just execution

### The "Agent-Validator" Model

- **Supervisor (Human)**: Ryan Lyell - strategic direction, orchestration
- **Developer Agents (Claude/Qwen)**: Primary code generation, architecture
- **Validator Agent (Gemini)**: Line-by-line audits, quality assurance

### Communication Style (Ryan Lyell)

- **Direct Communication** - No fluff, get to the point
- **Practical Examples** - Show how it works, not just theory
- **Context First** - Explain the "why" before the "how"
- **Concise Responses** - Fewer than 4 lines unless detail needed
- **Multiple Options** - Present 2-3 approaches when possible
- **Partnership over delegation** - Collaborative problem-solving

---

## Getting Started Checklist

### For New Developers

- [ ] Clone repository and read this document
- [ ] Set up Python 3.10+ environment
- [ ] Install dependencies: `pip install -r requirements.txt`
- [ ] Start development server: `python server.py`
- [ ] Test health endpoint: `curl http://localhost:8001/health`
- [ ] Connect MCP client: `claude mcp add marm-memory http://localhost:8001/mcp`
- [ ] Run test suite: `pytest tests/`
- [ ] Read `.claude/CLAUDE.md` for project context
- [ ] Review recent commits for development patterns

### For Coding Agents

- [ ] Understand the SIMPLE IS BETTER principle
- [ ] Review architectural patterns in existing endpoints
- [ ] Practice with TodoWrite for task tracking
- [ ] Test changes with Docker environment
- [ ] Use structured logging for all output
- [ ] Follow the surgical change approach
- [ ] Validate MCP protocol compliance

**Next: Read CODER-API-TOOLS.md for complete API documentation**
