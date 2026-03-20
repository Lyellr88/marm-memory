# MARM MCP Server - Visual Documentation

Modern Mermaid diagrams to help new users understand the MARM Universal MCP Server architecture and workflows.

---

## MARM Architecture Overview

```mermaid
%%{init: {'theme': 'base', 'themeVariables': {'primaryColor': '#6366f1', 'primaryTextColor': '#1f2937', 'primaryBorderColor': '#4f46e5', 'lineColor': '#6b7280', 'secondaryColor': '#f3f4f6', 'tertiaryColor': '#e5e7eb', 'background': '#ffffff', 'secondaryTextColor': '#374151', 'tertiaryTextColor': '#6b7280'}}}%%
graph TB
    subgraph "Client Layer"
        A[Claude Code] --> |MCP Protocol| E
        B[Qwen CLI] --> |MCP Protocol| E
        C[Gemini CLI] --> |MCP Protocol| E
        D[Any MCP Client] --> |MCP Protocol| E
    end

    subgraph "MARM Universal MCP Server"
        E[FastAPI Server<br/>Port 8001] --> F[MCP Handler]
        F --> G[Rate Limiter<br/>60 req/min]
        G --> H[Response Limiter<br/>1MB MCP Compliance]
        H --> I[Endpoint Router]
    end

    subgraph "Core Intelligence"
        I --> J[Memory Engine]
        I --> K[Session Manager]
        I --> L[Notebook System]
        I --> M[Logging System]

        J --> N[Semantic Search<br/>all-MiniLM-L6-v2]
        J --> O[Auto Classification<br/>code / project / book / general]
        J --> P[Vector Embeddings<br/>Similarity Search]
    end

    subgraph "Data Layer"
        N --> Q[(SQLite Database<br/>WAL Mode)]
        O --> Q
        P --> Q
        K --> Q
        L --> Q
        M --> Q

        Q --> R[memories table<br/>embedding vectors]
        Q --> S[sessions table<br/>marm state]
        Q --> T[log_entries table<br/>structured logs]
        Q --> U[notebook_entries table<br/>reusable knowledge]
    end

    style E fill:#6366f1,stroke:#4f46e5,color:#ffffff
    style J fill:#10b981,stroke:#059669,color:#ffffff
    style Q fill:#f59e0b,stroke:#d97706,color:#ffffff
    style N fill:#8b5cf6,stroke:#7c3aed,color:#ffffff
```

---

## API Endpoints by Function

```mermaid
%%{init: {'theme': 'base', 'themeVariables': {'primaryColor': '#6366f1', 'primaryTextColor': '#1f2937', 'primaryBorderColor': '#4f46e5', 'lineColor': '#6b7280', 'secondaryColor': '#f3f4f6', 'tertiaryColor': '#e5e7eb', 'background': '#ffffff', 'secondaryTextColor': '#374151', 'tertiaryTextColor': '#6b7280'}}}%%
graph LR
    subgraph "Session Management"
        A[marm_start<br/>🚀 Activate Memory]
        B[marm_refresh<br/>🔄 Reset State]
        C[marm_current_context<br/>📅 Get Date/Time]
    end

    subgraph "Memory Intelligence"
        D[marm_smart_recall<br/>🧠 Semantic Search]
        E[marm_contextual_log<br/>💾 Auto-Classify Storage]
        F[marm_context_bridge<br/>🌉 Workflow Transitions]
    end

    subgraph "Structured Logging"
        G[marm_log_session<br/>📂 Create/Switch Session]
        H[marm_log_entry<br/>📝 Add Timestamped Entry]
        I[marm_log_show<br/>👁️ Display Logs]
        J[marm_log_delete<br/>🗑️ Remove Entries]
    end

    subgraph "Notebook System"
        K[marm_notebook_add<br/>📔 Store Knowledge]
        L[marm_notebook_use<br/>⚡ Activate Instructions]
        M[marm_notebook_show<br/>📋 Browse Entries]
        N[marm_notebook_delete<br/>❌ Remove Entry]
        O[marm_notebook_clear<br/>🧹 Clear Active List]
        P[marm_notebook_status<br/>ℹ️ Show Active Items]
    end

    subgraph "System Utilities"
        Q[marm_summary<br/>📊 Generate Summaries]
        R[marm_system_info<br/>🔧 Health & Statistics]
        S[marm_reload_docs<br/>📚 Refresh Documentation]
    end

    style A fill:#10b981,stroke:#059669,color:#ffffff
    style D fill:#8b5cf6,stroke:#7c3aed,color:#ffffff
    style G fill:#f59e0b,stroke:#d97706,color:#ffffff
    style K fill:#ef4444,stroke:#dc2626,color:#ffffff
    style Q fill:#6366f1,stroke:#4f46e5,color:#ffffff
```

---

## Installation Decision Tree

```mermaid
%%{init: {'theme': 'base', 'themeVariables': {'primaryColor': '#6366f1', 'primaryTextColor': '#1f2937', 'primaryBorderColor': '#4f46e5', 'lineColor': '#6b7280', 'secondaryColor': '#f3f4f6', 'tertiaryColor': '#e5e7eb', 'background': '#ffffff', 'secondaryTextColor': '#374151', 'tertiaryTextColor': '#6b7280'}}}%%
flowchart TD
    A[🚀 Want to try MARM?] --> B{What's your setup preference?}

    B -->|Quick Test<br/>30 seconds| C[🐳 Docker Run]
    B -->|Production Use<br/>Persistent data| D[🐳 Docker Compose]
    B -->|Development<br/>Local control| E[📦 PyPI Install]
    B -->|Maximum Control<br/>Source code| F[⚙️ Local Build]

    C --> C1[docker run -d --name marm-mcp-server<br/>-p 8001:8001 -v marm_data:/app/data<br/>lyellr88/marm-mcp-server]
    C1 --> G[claude mcp add marm-memory<br/>http://localhost:8001/mcp]

    D --> D1[Create docker-compose.yml<br/>with persistent volumes]
    D1 --> D2[docker-compose up -d]
    D2 --> G

    E --> E1[pip install marm-mcp-server==2.2.4]
    E1 --> E2[marm-mcp-server]
    E2 --> G

    F --> F1[git clone repository]
    F1 --> F2[Setup virtual environment]
    F2 --> F3[Install dependencies]
    F3 --> F4[python -m marm_mcp_server.main]
    F4 --> G

    G --> H[✅ Test with marm_start<br/>then marm_system_info]

    H --> I{Working correctly?}
    I -->|Yes| J[🎉 Start using 19 MCP tools<br/>for AI memory intelligence]
    I -->|No| K[🔧 Run diagnostic tests<br/>Check troubleshooting guide]

    style C fill:#10b981,stroke:#059669,color:#ffffff
    style D fill:#f59e0b,stroke:#d97706,color:#ffffff
    style E fill:#8b5cf6,stroke:#7c3aed,color:#ffffff
    style F fill:#ef4444,stroke:#dc2626,color:#ffffff
    style J fill:#6366f1,stroke:#4f46e5,color:#ffffff
```

---

## Memory Intelligence Workflow

```mermaid
%%{init: {'theme': 'base', 'themeVariables': {'primaryColor': '#6366f1', 'primaryTextColor': '#1f2937', 'primaryBorderColor': '#4f46e5', 'lineColor': '#6b7280', 'secondaryColor': '#f3f4f6', 'tertiaryColor': '#e5e7eb', 'background': '#ffffff', 'secondaryTextColor': '#374151', 'tertiaryTextColor': '#6b7280'}}}%%
graph TD
    subgraph "Input Processing"
        A[AI Agent Input<br/>Text/Code/Questions] --> B[Content Analysis]
        B --> C{Storage or Retrieval?}
    end

    subgraph "Storage Workflow"
        C -->|Store| D[marm_contextual_log<br/>Auto-Classify Content]
        D --> E[Generate Embeddings<br/>all-MiniLM-L6-v2]
        E --> F[Content Classification<br/>code | project | book | general]
        F --> G[Vector Storage<br/>SQLite + embeddings BLOB]
        G --> H[Session Association<br/>Link to current session]
    end

    subgraph "Retrieval Workflow"
        C -->|Retrieve| I[marm_smart_recall<br/>Semantic Query]
        I --> J[Query Embedding<br/>Convert to vectors]
        J --> K[Similarity Search<br/>Cosine similarity]
        K --> L[Ranking & Filtering<br/>Relevance scoring]
        L --> M[Context Assembly<br/>Prepare for AI agent]
    end

    subgraph "Intelligence Layer"
        N[Cross-Session Search<br/>search_all=True]
        O[Multi-AI Memory<br/>Claude + Qwen + Gemini]
        P[Context Bridging<br/>Workflow transitions]
        Q[Auto-Summarization<br/>Large context handling]
    end

    M --> N
    H --> O
    M --> P
    L --> Q

    subgraph "Output Delivery"
        R[Structured Response<br/>MCP 1MB compliance]
        S[Rate Limited<br/>60 req/min]
        T[Context-Aware Results<br/>Relevant memories]
    end

    N --> R
    O --> S
    P --> T
    Q --> T

    style D fill:#10b981,stroke:#059669,color:#ffffff
    style I fill:#8b5cf6,stroke:#7c3aed,color:#ffffff
    style E fill:#f59e0b,stroke:#d97706,color:#ffffff
    style K fill:#ef4444,stroke:#dc2626,color:#ffffff
    style R fill:#6366f1,stroke:#4f46e5,color:#ffffff
```

---

*Generated for MARM v2.2.4 - Universal MCP Server for AI Memory Intelligence*