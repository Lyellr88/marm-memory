# MARM Pro: Context-Aware Scraper System

## Executive Summary

Transform MARM from a memory system into an intelligent research assistant that monitors user context and automatically collects relevant external resources. This single feature upgrade provides clear Pro differentiation while solving real developer workflow pain points.

## Core Concept

Build intelligent scrapers that monitor the user's MARM session context and automatically collect relevant external resources (Stack Overflow solutions, GitHub discussions, documentation) into a separate database. Users control when to review and selectively import useful findings into their main MARM memory system.

## Strategic Value Proposition

**"Stop losing context switching between MARM and Stack Overflow - let MARM research in the background while you work."**

### Solves Real Pain Points

- Developers constantly tab-switch to Stack Overflow/GitHub
- Lose context switching between MARM and research
- Manually copying solutions breaks flow
- External noise polluting curated memory

### Solution Benefits

- Background research assistant
- Separate database maintains purity
- User controls what gets promoted
- Context-aware searching

## Architecture Design

### Separate Database Strategy

- **Database**: Independent SQLite instance (`scraper_research.db`)
- **Isolation**: No automatic integration with core MARM memory system
- **Purpose**: Prevent external content from flooding user's curated memories
- **Control**: User decides what gets promoted to main memory

### Database Schema

```sql
CREATE TABLE research_findings (
    id INTEGER PRIMARY KEY,
    source TEXT NOT NULL,           -- 'stackoverflow', 'github', 'reddit', 'docs'
    url TEXT NOT NULL,
    title TEXT,
    content TEXT NOT NULL,
    query_context TEXT,             -- What triggered this search
    user_session TEXT,              -- Which MARM session context
    relevance_score REAL,           -- Basic scoring 0.0-1.0
    timestamp TEXT DEFAULT CURRENT_TIMESTAMP,
    content_hash TEXT,              -- For deduplication
    UNIQUE(url, content_hash)
);

CREATE TABLE scraper_settings (
    blacklist_keywords TEXT,        -- Never search these
    whitelisted_sources TEXT,       -- Only search these
    auto_scrape BOOLEAN DEFAULT FALSE  -- Require manual trigger
);
```

## Simple Command Interface

### User Control Commands (Enhanced)

```python
# MCP endpoints for scraper control
/scraper_status         # Show: on/off, database size, recent activity
/scraper_on            # Enable background collection
/scraper_off           # Disable background collection
/scraper_dump          # Export findings as readable text for review
/scraper_clear         # Clear database with confirmation prompt
/scraper_research "query"  # Manual trigger for specific research
/scraper_auto on       # Enable auto mode (opt-in)
```

## Context Detection Logic

### Trigger Analysis

Monitor MARM session activity for:

- Programming language mentions (Python, JavaScript, React, etc.)
- Framework references (FastAPI, Django, React, Next.js)
- Error messages or stack traces
- Technical concepts and patterns
- Library/package names

### Query Generation

```python
def generate_search_queries(marm_context):
    """Generate targeted search queries based on user's current work"""
    # Extract key terms from recent MARM entries
    # Combine with error patterns or implementation questions
    # Create specific queries for different sources

    return {
        'stackoverflow': f"{language} {framework} {error_pattern}",
        'github': f"{library} issues {implementation_context}",
        'reddit': f"{language} best practices {use_case}"
    }
```

## Scraping Strategy

### Source-Specific Approaches

**Stack Overflow API**

- Use official API to respect rate limits
- Search by tags and keywords from context
- Filter by answer quality and votes
- Extract question + accepted answer

**GitHub API**

- Search issues and discussions in relevant repos
- Filter by repository popularity and activity
- Focus on closed issues with solutions
- Extract issue description + resolution

**Reddit API (PRAW)**

- Target programming subreddits (r/learnpython, r/webdev, etc.)
- Search recent discussions matching user's context
- Filter by upvotes and comment quality
- Extract post + top comments

**Documentation Sites**

- Direct scraping with robots.txt compliance
- Focus on official docs for detected frameworks/libraries
- Extract relevant sections based on context keywords
- Cache to avoid repeated requests

### Rate Limiting and Ethics

- Respect robots.txt and Terms of Service
- Implement delays between requests (2-5 seconds)
- Use official APIs where available
- Rotate user agents and implement backoff strategies
- Cache results to minimize repeated requests

## Background Processing

### Scraper Daemon Design

```python
class ContextualScraper:
    def __init__(self, marm_memory_instance):
        self.marm = marm_memory_instance
        self.research_db = sqlite3.connect('scraper_research.db')
        self.enabled = False

    async def monitor_context_changes(self):
        """Watch for new MARM entries that suggest research opportunities"""
        while self.enabled:
            recent_entries = await self.marm.get_recent_entries(minutes=10)
            for entry in recent_entries:
                if self.should_research(entry):
                    await self.queue_research_task(entry)
            await asyncio.sleep(300)  # Check every 5 minutes

    def should_research(self, entry):
        """Determine if entry suggests need for external research"""
        research_indicators = [
            'error', 'issue', 'problem', 'how to', 'best way',
            'implementation', 'approach', 'solution', 'bug'
        ]
        return any(indicator in entry.content.lower() for indicator in research_indicators)
```

## User Workflow Integration

### Typical Usage Pattern

1. **User works in MARM**: Logs project progress, errors, implementation questions
2. **Scraper detects context**: Identifies research opportunities from recent entries
3. **Background collection**: Quietly gathers relevant external resources
4. **User reviews findings**: Uses `/scraper_dump` to see what was collected
5. **Selective import**: User manually adds valuable findings to main MARM memory
6. **Quality control**: User maintains curated memory system while accessing research

### Example Workflow

```
User: /marm_contextual_log "Working on FastAPI authentication, getting 401 errors with JWT tokens"

[Scraper detects: FastAPI + JWT + authentication + errors]
[Searches Stack Overflow: "FastAPI JWT 401 authentication"]
[Searches GitHub: "FastAPI JWT issues token validation"]
[Stores 3-5 relevant solutions in research database]

User: /scraper_dump
[Returns formatted list of findings with URLs and summaries]

User: /marm_contextual_log "Found solution - JWT secret encoding issue, tokens need bytes conversion"
```

## Technical Implementation Considerations

### Deduplication Strategy

- Content hashing to avoid storing identical solutions
- URL normalization to prevent duplicate entries
- Time-based filtering (don't re-scrape same sources within 24 hours)

### Relevance Scoring

```python
def calculate_relevance(content, user_context):
    """Basic relevance scoring based on keyword matching and context"""
    score = 0.0

    # Keyword overlap
    context_words = set(user_context.lower().split())
    content_words = set(content.lower().split())
    overlap = len(context_words.intersection(content_words))
    score += overlap * 0.1

    # Source quality indicators
    if 'accepted-answer' in content: score += 0.3
    if 'high-votes' in content: score += 0.2
    if 'official-docs' in content: score += 0.4

    return min(score, 1.0)
```

### Performance Optimization

- Async scraping to avoid blocking MARM operations
- Configurable collection frequency (default: 5-minute intervals)
- Maximum storage limits (e.g., 1000 entries, auto-cleanup oldest)
- Lazy loading of research database

## Security and Privacy

### Data Handling

- Only store public information that's already accessible
- No storage of user credentials or private data
- Clear data retention policies (auto-delete after 30 days)
- User control over data collection and deletion

### API Security

- Store API keys in environment variables
- Implement proper error handling for API failures
- Fallback to web scraping if APIs are unavailable
- Respect platform rate limits and terms of service

## Claude's Enhanced Command Suggestions

### Smart Filtering Commands

```python
/scraper_filter_by_source "stackoverflow"   # Show only SO results
/scraper_filter_by_score 0.8                # Show high-relevance only
/scraper_recent 24h                         # Show last 24 hours
/scraper_export_session "session_name"      # Export research for specific session
/scraper_promote "finding_id"               # Move research to main MARM memory
```

### Advanced Context Commands

```python
/scraper_context_analysis                   # Show what contexts trigger research
/scraper_learn_patterns                     # Analyze user's research preferences
/scraper_suggest_queries                    # Show potential research queries
/scraper_blacklist "keyword"                # Never research this term
/scraper_whitelist "framework"              # Always research this framework
```

### Research Quality Commands

```python
/scraper_rate "finding_id" 5                # Rate research quality (1-5)
/scraper_feedback "finding_id" "helpful"    # Improve relevance algorithm
/scraper_similar "finding_id"               # Find related research
/scraper_bookmark "finding_id"              # Mark for later review
```

## Monetization Strategy

### Free Tier Limitations

- Manual scraping only (`/scraper_research`)
- 50 searches/month
- Stack Overflow only
- 7-day research retention

### Pro Tier Features ($12-30/month)

- Auto-background scraping
- All sources (GitHub, Reddit, Documentation)
- Unlimited searches
- 30-day research retention
- Priority API access
- Advanced filtering and export

### Enterprise Features

- Custom source integrations
- Team research sharing
- Compliance controls
- Extended retention (1 year+)
- Dedicated API quotas

## Implementation Priority

### Phase 1: MVP Foundation (2-3 weeks)

- Basic scraper database and core commands
- Stack Overflow API integration only
- Simple context detection (keyword matching)
- Manual review workflow (`/scraper_dump`)

### Phase 2: Enhanced Intelligence (2-3 weeks)

- GitHub API integration
- Improved relevance scoring
- Background processing with rate limiting
- Advanced filtering commands

### Phase 3: Full System (3-4 weeks)

- Reddit API integration
- Documentation site scraping
- Deduplication and quality filtering
- Performance optimization and caching

## Technical Feasibility Analysis

### Easy Implementation Parts

- Stack Overflow API is well-documented and reliable
- GitHub API is robust with good rate limiting
- Reddit PRAW library simplifies Reddit integration
- SQLite separation maintains clean architecture

### Challenging Implementation Parts

- Rate limiting coordination across multiple APIs
- Accurate relevance scoring without ML
- Efficient deduplication at scale
- Background processing without blocking MARM operations

## Database Architecture Considerations

### Current MARM Database

```sql
-- Existing tables in marm_memory.db
memories (context logs, smart recall)
log_entries (structured logs)
notebook_entries (notebook)
sessions (session management)
```

### Scraper Database Integration

- **Option 1**: Separate `scraper_research.db` (recommended)
- **Option 2**: Additional tables in main database
- **SQLite Performance**: Can easily handle millions of rows
- **Isolation**: Research won't affect existing tools
- **Lazy Loading**: Only queries when scraper commands used

## Future Enhancement Possibilities

### Advanced Features (Not Initial Implementation)

- Machine learning for better relevance scoring
- Natural language processing for query optimization
- Integration with more specialized developer resources
- Collaborative filtering based on similar user contexts
- Export/import of research databases between users

### Integration Opportunities

- Connect with user's GitHub repositories for context
- Integration with IDE error logs and debugging sessions
- Slack/Discord bot for team research sharing
- Integration with project management tools (Jira, Trello)

## Success Metrics

### Technical Metrics

- Scraper uptime and reliability
- API response times and success rates
- Database performance with large datasets
- User adoption of scraper commands

### Utility Metrics

- Relevance scoring accuracy (user feedback)
- Conversion rate (scraped content → main memory)
- Time savings in research workflows
- User satisfaction with research quality

## Market Differentiation

### Revolutionary Value Proposition

**"The first AI memory system with intelligent background research"**

### Competitive Advantages

1. **Context-aware automation** - No manual research needed
2. **Clean separation** - Research doesn't pollute curated memory
3. **User control** - Complete ownership of what gets saved
4. **Multi-source intelligence** - Stack Overflow + GitHub + Reddit + Docs
5. **MCP protocol integration** - Works with any MCP-compatible AI

### Market Position

- **Beyond simple memory** - Active research assistance
- **Professional workflow** - Built for real developer needs
- **Privacy-conscious** - User controls all data collection
- **Future-proof** - Extensible to new research sources

## Business Impact

### Revenue Potential

- **Individual Pro**: $12-30/month with clear research productivity value
- **Team Plans**: Shared research findings across development teams
- **Enterprise**: Custom integrations with internal knowledge bases

### User Retention Strategy

- **Immediate value**: Solve research context-switching pain from day one
- **Growing intelligence**: Research database becomes more valuable over time
- **Network effects**: Better research leads to better MARM memories
- **Switching costs**: Accumulated research creates lock-in

## Advanced AI Enhancement: Hybrid Agent-Tool System

### 🤖 AI Agent + Web Scraper Evolution

#### Intelligent Research Agent Architecture

Instead of static pattern matching, use AI agents that intelligently orchestrate web scraping tools:

```txt
User Context → Research Agent → Tool Chain → Curated Results
```

#### Agent-Tool Chain Workflow

```python
# Auto-triggered intelligent research
research_agent = IntelligentResearchAgent()
research_agent.tools = [
    web_scraper_tool,
    content_analyzer_tool,
    relevance_scorer_tool,
    summary_generator_tool
]

# Agent orchestrates tool chain
findings = research_agent.search_and_analyze(user_context)
curated_results = research_agent.rank_and_filter(findings)
summary = research_agent.generate_summary(curated_results)
```

#### Enhanced Capabilities

- **Intelligent Query Generation**: AI creates better search terms than pattern matching
- **Content Analysis**: AI reads and summarizes findings before storage
- **Dynamic Solution Ranking**: Context-aware relevance scoring
- **Natural Language Interface**: "Find solutions for this specific error pattern"

#### Base Web Scraper Agent Template

**Agent Name**: `research-scraper-agent`

**Purpose**: General-purpose research agent that uses web scraping tools to find and analyze external resources based on dynamic context provided at runtime.

**Core Capabilities**:

- Execute web scraping tools with intelligent query generation
- Analyze and summarize collected content
- Score relevance based on provided context
- Present findings in digestible formats

**Usage Pattern**:

```python
# Main AI prompts research agent with specific context
prompt_research_agent(
    context="Current user problem/topic",
    sources=["stackoverflow", "github", "docs"],
    focus="specific research goal"
)

# Agent uses its tools intelligently
agent.generate_search_queries(context)
agent.scrape_sources(queries, sources)
agent.analyze_content(scraped_data)
agent.score_relevance(content, context)
agent.present_summary(filtered_results)
```

**Agent Design Philosophy**:

- **Context-Agnostic**: Works with any technical topic or problem domain
- **Tool-Focused**: Specialized in orchestrating scraping and analysis tools
- **AI-Directed**: Receives specific direction from main AI about what to research
- **Quality-Focused**: Emphasizes relevance and accuracy over quantity

**💡 Pro Tip for Documentation**:
*This hybrid agent-tool approach transforms static automation into intelligent assistance. The research agent becomes a specialist that the main AI can consult with specific questions, similar to how a developer might ask a colleague "Can you research X for me?" The agent handles the tedious scraping and filtering work while the main AI maintains conversation context and user relationship.*

#### Why This Beats Standard AI Web Tools

**Standard Web Tools (WebFetch, WebSearch)**:

- ❌ One-shot operations requiring manual prompting
- ❌ No memory of previous research
- ❌ No context awareness from user's work patterns
- ❌ Results disappear after conversation
- ❌ User must manually trigger each search

**MARM Research Agent System**:

- ✅ **Continuous Background Monitoring**: Watches MARM sessions for research opportunities
- ✅ **Persistent Research Database**: Builds searchable knowledge base over time
- ✅ **Context-Aware Intelligence**: Understands your project patterns and automatically researches relevant topics
- ✅ **Proactive Discovery**: Finds solutions before you explicitly ask
- ✅ **Quality Curation**: Deduplicates and scores findings for relevance

**Example Difference**:

```python
# Standard approach - Manual and temporary
User: "I'm getting JWT errors"
AI: Uses WebSearch → Returns results → Results lost after conversation

# MARM Research Agent - Automatic and persistent
User: Works on project with JWT mentions over several days
Agent: Automatically builds database of JWT solutions, patterns, best practices
User: Later accesses /scraper_dump for comprehensive JWT knowledge base
```

**Value Proposition**: Transform from "AI that searches when asked" to "AI that continuously learns your domain and builds institutional knowledge."

### Future Agent Integration Possibilities

#### Evolution Path: Basic Scraper → AI Agent System

- **Phase 1**: Deploy basic context-aware scraper (current spec)
- **Phase 2**: Add AI agent layer for intelligent query generation
- **Phase 3**: Full agent orchestration with tool chains
- **Phase 4**: Multi-agent research collaboration

#### Agent Ecosystem Architecture

```python
# Future multi-agent research system
class MARMResearchEcosystem:
    def __init__(self):
        self.scraper_agent = WebScraperAgent()
        self.analyzer_agent = ContentAnalysisAgent()
        self.curator_agent = RelevanceCurationAgent()
        self.summary_agent = KnowledgeDistillationAgent()

    async def orchestrate_research(self, user_context):
        # Agents collaborate to build comprehensive research
        raw_data = await self.scraper_agent.gather_sources(user_context)
        analyzed_content = await self.analyzer_agent.process_findings(raw_data)
        curated_results = await self.curator_agent.rank_and_filter(analyzed_content)
        knowledge_summary = await self.summary_agent.distill_insights(curated_results)
        return knowledge_summary
```

## Final Assessment

### Why This Beats Multi-AI Evolution

1. **Solves immediate pain** vs theoretical future need
2. **Clear monetization** path with obvious value proposition
3. **Technical feasibility** with existing APIs and tools
4. **User control** maintains MARM's privacy-first philosophy
5. **Extensible foundation** for future research enhancements

### Implementation Reality Check

- **Week 1-2**: Stack Overflow integration with basic commands
- **Week 3-4**: GitHub integration and background processing
- **Month 2**: Full system with Reddit and documentation scraping
- **Month 3**: Advanced filtering and enterprise features

## Strategic Recommendation

**Ship the MVP (Stack Overflow only) in the next MARM release to validate user demand. If adoption is strong, build the full multi-source system for Pro launch.**

This single feature transforms MARM from "memory tool" to "intelligent research assistant" - a much stronger value proposition for Pro pricing than incremental memory improvements.

---

*The Context-Aware Scraper System represents the evolution from static AI memory to dynamic research intelligence - positioning MARM as the definitive productivity platform for AI-assisted development workflows.*
