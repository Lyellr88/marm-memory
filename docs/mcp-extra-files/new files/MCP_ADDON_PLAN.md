# MARM MCP Server - Addon and Enhancement Plan

**Last Updated:** 2025-09-04

## Overview

This document outlines future enhancements and addon features for the MARM MCP Server after the core refactoring is complete. These improvements will add advanced functionality, analytics, and operational features to the system.

---

## Planned Enhancements

### 1. Add Scheduler Support

Implement APScheduler for periodic tasks:

- **Memory cleanup**: Remove old/unused memories based on retention policies
- **Documentation refresh**: Periodically reload documentation from files
- **Database optimization**: Run maintenance tasks like index rebuilding
- **Backup automation**: Schedule regular database backups

Implementation approach:

```python
# In services/scheduler.py
from apscheduler.schedulers.asyncio import AsyncIOScheduler

class MARMTaskScheduler:
    def __init__(self, memory_system):
        self.scheduler = AsyncIOScheduler()
        self.memory = memory_system
    
    def add_periodic_cleanup_task(self, hours=24):
        self.scheduler.add_job(
            self.memory.cleanup_old_memories,
            'interval',
            hours=hours
        )
    
    def start(self):
        self.scheduler.start()
```

### 2. Expand Event System

Add more granular event types:

- `memory_accessed`: Track when memories are recalled
- `notebook_modified`: Track notebook changes
- `session_ended`: Handle session cleanup
- `context_bridge_created`: Track workflow transitions
- `user_feedback_received`: Handle user feedback on responses

Example new event handler:

```python
# In services/automation.py
async def track_popular_commands(data: dict):
    """Track which commands are used most frequently"""
    command = data.get('command')
    # Update usage statistics in database
    pass

events.on('command_executed', track_popular_commands)
```

### 3. Add Metrics/Analytics

Implement usage tracking and analytics:

- Command usage frequency
- Response accuracy metrics (user feedback)
- Memory access patterns
- Session duration and activity
- Peak usage times

Implementation approach:

```python
# In core/analytics.py
class MARMAnalytics:
    def __init__(self, db_path: str = "/data/analytics.db"):
        self.db_path = db_path
        self.init_database()
    
    async def log_command_usage(self, command: str, user_id: str = None):
        """Log when a command is used"""
        # Store in SQLite database
        pass
    
    async def get_usage_statistics(self) -> dict:
        """Retrieve usage statistics"""
        # Return analytics data
        pass
```

### 4. Add Backup/Export Functionality

Implement data export and backup features:

- **Session export**: Export all memories from a session as JSON/CSV
- **Notebook export**: Export notebook entries
- **Full backup**: Complete database backup
- **Import functionality**: Restore from backups

Example endpoint:

```python
# In endpoints/system.py
@app.get("/marm_export_session/{session_name}")
async def marm_export_session(session_name: str, format: str = "json"):
    """Export session data in specified format"""
    # Implementation
    pass
```

### 5. Add Configuration Options

Make the server configurable:

- Database path (already partially implemented for Docker)
- Semantic search model selection
- Retention policies for memories
- Logging levels and outputs
- Port and host configuration
- Documentation paths

Implementation approach:

```python
# In config/settings.py
import os
from typing import Optional

class MARMSettings:
    # Database configuration
    DATABASE_PATH: str = os.getenv("MARM_DB_PATH", "/data/marm_memory.db")
    
    # Server configuration
    HOST: str = os.getenv("MARM_HOST", "0.0.0.0")
    PORT: int = int(os.getenv("MARM_PORT", "8001"))
    
    # Semantic search
    SEMANTIC_MODEL: str = os.getenv("MARM_SEMANTIC_MODEL", "all-MiniLM-L6-v2")
    
    # Documentation paths
    DOCS_PATH: str = os.getenv("MARM_DOCS_PATH", "../GitHub docs")
    
    # Retention policies
    MEMORY_RETENTION_DAYS: Optional[int] = int(os.getenv("MARM_RETENTION_DAYS", "0")) or None  # 0 = no cleanup
```

### 6. Web Search Integration (Pro Feature)

**MARM + Web Search = AI Memory + Real-Time Intelligence**

Add intelligent web search capabilities that integrate with existing memory:

- **Memory-aware web queries**: Use stored context to refine search results
- **Automatic knowledge synthesis**: Combine web findings with existing memories
- **Smart result curation**: Filter and prioritize based on user's knowledge base
- **Auto-learning**: Store valuable discoveries for future reference

Implementation approach:

```python
# In services/web_search.py
class MARMWebSearch:
    def __init__(self, memory_system, search_providers: list):
        self.memory = memory_system
        self.providers = search_providers  # Google, Bing, specialized APIs
    
    async def smart_web_search(self, query: str, context_type: str = "general"):
        """Perform memory-aware web search"""
        # 1. Search MARM memory for existing context
        memory_context = await self.memory.smart_recall(query, limit=5)
        
        # 2. Enhance query with memory context
        enhanced_query = self._enhance_query_with_context(query, memory_context)
        
        # 3. Search web with enhanced query
        web_results = await self._search_web(enhanced_query)
        
        # 4. Cross-reference with stored knowledge
        filtered_results = self._filter_with_memory(web_results, memory_context)
        
        # 5. Auto-store valuable findings
        await self._auto_store_findings(query, filtered_results)
        
        return {
            "web_results": filtered_results,
            "memory_context": memory_context,
            "synthesis": self._synthesize_results(memory_context, filtered_results)
        }
    
    def _enhance_query_with_context(self, query: str, context: list) -> str:
        """Use memory context to create more targeted search queries"""
        # Implementation: analyze context and refine search terms
        pass
    
    async def _search_web(self, query: str) -> list:
        """Search across configured web providers"""
        # Implementation: search Google, Bing, etc.
        pass
    
    def _filter_with_memory(self, web_results: list, memory_context: list) -> list:
        """Filter web results based on existing knowledge"""
        # Implementation: remove redundant info, prioritize new insights
        pass
    
    async def _auto_store_findings(self, query: str, results: list):
        """Automatically store valuable web findings in memory"""
        # Implementation: identify and store key insights
        pass
```

New endpoints for web search:

```python
# In endpoints/web_search.py
@app.post("/marm_web_search")
async def marm_web_search(query: str, context_type: str = "general", store_results: bool = True):
    """Search web with memory context integration"""
    # Pro feature - requires authentication
    pass

@app.post("/marm_research_assistant") 
async def marm_research_assistant(topic: str, depth: str = "standard"):
    """Comprehensive research combining memory + web search"""
    # Multi-step research workflow
    pass

@app.post("/marm_trend_monitor")
async def marm_trend_monitor(keywords: list, frequency: str = "daily"):
    """Monitor web trends related to stored interests"""
    # Scheduled trend monitoring
    pass
```

**Pro Tier Features:**
- Real-time web search integration
- Memory-aware query enhancement
- Automatic knowledge synthesis
- Research workflow automation
- Trend monitoring and alerts
- Custom search provider configuration

**Revenue Model:**
- **Beta**: Free local memory system
- **Pro**: Memory + Web intelligence + Cloud deployment
- **Enterprise**: Custom APIs + Team memory + Advanced analytics

---

## Implementation Priority

1. **Phase 1**: Configuration Options (enables flexible deployment)
2. **Phase 2**: Scheduler Support (automated maintenance)
3. **Phase 3**: Enhanced Event System (better tracking)
4. **Phase 4**: Backup/Export Functionality (data safety)
5. **Phase 5**: Metrics/Analytics (usage insights)
6. **Phase 6**: Web Search Integration (Pro feature launch)

---

## Benefits of These Enhancements

- **Operational Excellence**: Automated maintenance and monitoring
- **Data Safety**: Backup and export capabilities
- **User Insights**: Analytics and usage tracking
- **Flexibility**: Configurable deployment options
- **Scalability**: Enhanced event system for complex workflows
- **Professional Features**: Enterprise-ready functionality
- **Competitive Advantage**: Memory + Web intelligence platform
- **Revenue Generation**: Clear Pro tier value proposition

These enhancements will transform MARM from a functional prototype into a production-ready AI memory system with unique market positioning as an intelligent research and memory platform.