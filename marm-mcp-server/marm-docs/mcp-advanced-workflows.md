# MARM MCP Server - Advanced Workflows & Migration

## Cross-App Memory Strategies, Migration Guide, and Best Practices

**MARM v2.2.6** - Universal MCP Server for AI Memory Intelligence

---

## Cross-App Memory Strategies

### Multi-LLM Session Organization

**Strategy**: Use LLM-specific session names to track contributions:

```txt
Sessions:
- claude-code-review-2025-01
- qwen-research-analysis-2025-01  
- gemini-creative-writing-2025-01
- cross-ai-project-planning-2025-01
```

### Memory Sharing Workflow

1. **Individual Sessions**: Each AI works in named sessions
2. **Cross-Pollination**: Use `marm_smart_recall` to find relevant insights
3. **Synthesis Sessions**: Create shared sessions where AIs build on each other's work

---

## Pro Tips & Best Practices

### Memory Management

**Log Compaction**: Use `marm_summary`, delete entries, replace with summary
**Session Naming**: Include LLM name for cross-referencing
**Strategic Logging**: Focus on key decisions, solutions, discoveries, configurations

### Search Strategies

**Global Search**: Use `search_all=True` to search across all sessions
**Natural Language Search**: "authentication problems with JWT tokens" vs "auth error"
**Temporal Search**: Include timeframes in queries

### Workflow Optimization

**Notebook Stacking**: Combine multiple entries for complex workflows
**Session Lifecycle**: Start → Work → Reference → End with compaction

---

## Advanced Workflows

### Project Memory Architecture

```txt
Project Structure:
├── project-name-planning/          # Initial design and requirements
├── project-name-development/       # Implementation details
├── project-name-testing/          # QA and debugging notes  
├── project-name-deployment/       # Production deployment
└── project-name-retrospective/    # Lessons learned
```

### Knowledge Base Development

1. **Capture**: Use `marm_contextual_log` for new learnings
2. **Organize**: Create themed sessions for knowledge areas
3. **Synthesize**: Regular `marm_summary` for knowledge consolidation
4. **Apply**: Convert summaries to `marm_notebook_add` entries

### Multi-AI Collaboration Pattern

```txt
Phase 1: Individual Research
- Each AI works in dedicated sessions
- Focus on their strengths (Claude=code, Qwen=analysis, Gemini=creativity)

Phase 2: Cross-Pollination  
- Use marm_smart_recall to find relevant insights
- Build upon previous work

Phase 3: Synthesis
- Create collaborative sessions  
- Combine insights for comprehensive solutions
```

---

## Migration from MARM Commands

### Transitioning from Text-Based MARM

If you're familiar with the original text-based MARM protocol, the MCP server provides enhanced capabilities while maintaining familiar workflows:

**Command Mapping**:

| Chatbot Command      | MCP Equivalent      | How It Works                                  |
| -------------------- | ------------------- | --------------------------------------------- |
| `/start marm`        | `marm_start`        | Claude calls automatically when needed        |
| `/refresh marm`      | `marm_refresh`      | Claude calls to maintain protocol adherence   |
| `/log session: name` | `marm_log_session`  | Claude organizes work into sessions           |
| `/log entry: details`| `marm_log_entry`    | Claude logs milestones and decisions          |
| `/summary: session`  | `marm_summary`      | Claude generates summaries on request         |
| `/notebook add: item`| `marm_notebook_add` | Claude stores reference information           |
| Manual memory search | `marm_smart_recall` | Claude searches semantically                  |

### Key Improvements in MCP Version

**Enhanced Memory System**:

- Semantic search replaces keyword matching
- Cross-app memory sharing between AI clients
- Automatic content classification
- Data storage with SQLite

**Advanced Features**:

- Multi-AI collaboration workflows
- Global search with `search_all=True`
- Context bridging between topics
- System health monitoring

### Migration Tips

1. **Session Organization**: Use descriptive session names instead of manual date tracking
2. **Memory Management**: Leverage auto-classification instead of manual categorization
3. **Notebook System**: Convert text-based instructions to structured notebook entries
4. **Search Strategy**: Use natural language queries instead of exact keywords

### Backward Compatibility

The MCP server maintains full compatibility with existing MARM concepts:

- Same core commands with enhanced capabilities
- Familiar logging and notebook workflows
- Consistent memory management principles
- Enhanced performance and reliability

---

## Troubleshooting

### Memory Not Finding Expected Results

**Solution**: Check content classification - your memory might be in a different category
**Tool**: Use `marm_log_show` to browse all entries manually

### Session Confusion

**Solution**: Use `marm_current_context` to check current session
**Prevention**: Always name sessions descriptively

### Performance Issues

**Solution**: Use log compaction - `marm_summary` followed by entry cleanup
**Tool**: `marm_system_info` to check database statistics

### Lost Context

**Solution**: `marm_refresh` to reset MARM behavior
**Recovery**: `marm_smart_recall` to find related previous conversations

---

## FAQ

### General Usage

**Q: How is MARM different from basic AI memory?**
A: MARM uses semantic understanding, not keyword matching. It finds related concepts even with different wording and works across multiple AI applications.

**Q: Can I use MARM with multiple AI clients simultaneously?**
A: Yes! MARM is designed for cross-app memory sharing. Each AI can access and contribute to the same memory store.

**Q: How much memory can MARM store?**
A: No hard limits - MARM uses efficient SQLite storage with semantic embeddings. Typical usage stores thousands of memories without performance issues.

### Memory Management FAQ

**Q: When should I create a new session vs. continuing an existing one?**
A: Create new sessions for distinct topics, projects, or time periods. Continue existing sessions for related work or follow-up discussions.

**Q: How does auto-classification work?**
A: MARM analyzes content using semantic models to determine if it's code, project work, book/research material, or general conversation.

**Q: Can I search across all sessions or just one?**
A: Both! `marm_smart_recall` can search globally (default) or within specific sessions using the session_name parameter.

### Technical Questions

**Q: What happens if MARM server is offline?**
A: Your AI client will work normally but without memory features. Memory resumes when MARM reconnects - no data loss.

**Q: How does semantic search work?**
A: MARM converts text to vector embeddings using sentence-transformers, then finds similar content using vector similarity rather than exact word matching.

**Q: Can I backup my MARM memory?**
A: Yes - MARM uses SQLite databases stored locally. Back up the `~/.marm/` directory to preserve all memories.

### Best Practices FAQ

**Q: How often should I use log compaction?**
A: At the end of significant sessions (5+ entries) or weekly for ongoing projects. This keeps memory efficient while preserving insights.

**Q: Should I log everything or be selective?**
A: Be selective - log decisions, solutions, insights, and key information. Avoid logging routine conversations or easily recreated content.

**Q: How do I organize memories for team collaboration?**
A: Use consistent session naming (include dates, project names, contributor names) and leverage cross-session search to find team insights.

### Integration & Setup FAQ

**Q: Which AI clients work with MARM?**
A: Any MCP-compatible client: Claude Code, Qwen CLI, Gemini CLI, and other Model Context Protocol implementations.

**Q: Do I need to restart MARM when switching between AI clients?**
A: No - MARM runs as a persistent service. Multiple AI clients can connect simultaneously to the same memory store.

**Q: How do I know if MARM is working correctly?**
A: Use `marm_system_info` to check server status, database statistics, and loaded capabilities. Look for "operational" status and healthy database counts.

>Built with ❤️ by MARM Systems - Universal MCP memory intelligence
