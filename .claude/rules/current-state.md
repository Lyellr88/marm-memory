# Current Architecture (January 2026) 

**MARM Universal MCP Server:**

- **Backend**: Python FastAPI with production-grade architecture
- **Database**: SQLite with connection pooling and WAL mode optimization
- **AI Integration**: Semantic search with sentence-transformers (all-MiniLM-L6-v2)
- **MCP Compliance**: Full Model Context Protocol implementation with 1MB response limiting
- **WebSocket Support**: Real-time communication with complete HTTP/WebSocket parity (19 MCP methods)
- **Security**: IP-based rate limiting, error isolation, graceful degradation
- **Deployment**: Docker-ready with configurable settings
- **Performance**: Lazy loading, connection pooling, intelligent caching