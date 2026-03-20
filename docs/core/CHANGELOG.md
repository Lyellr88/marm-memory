# Changelog

## MARM Protocol – v2.2.5 Change Log

<details>
<summary> June 9th–13th: Initial Protocol Unification (v1.2 Launch)</summary>

### Added

- `/compile` command to generate one-line-per-entry summaries  
- Automatic reseed block generation for restoring context in new threads  
- Log schema enforcement for structured logging: `[YYYY-MM-DD | User | Intent | Outcome]`  
- Error handling for malformed log entries, including date autofill  
- `/show reasoning` command to reveal the AI's logic path  
- Manual Steps Justification section added to `HANDBOOK.md`  
- Consolidated Examples section showing real use cases for all major commands  
- Clarified optional system prompt behavior (not built-in; manual only)  
- New session management guidance: recap every 8–10 turns using `/compile`  

### Changed

- Unified session tools into default protocol behavior  
- README restructured for clarity:
  - Quick Start moved above initiation  
  - Core Features moved to `HANDBOOK.md`  
  - Acknowledgment behavior clarified  
- Protocol one-liner updated to reflect unified design

### Removed

- Legacy modular language and optional tool references  
- Confidence flag/scoring feature from all protocol outputs  
- All mentions of auto-save or speculative memory behavior  

</details>

---

<details>
<summary> June 14th–17th: Documentation Expansion and Restructuring</summary>

### Added

- `HANDBOOK.md`: full command reference and usage guide  
- Collapsible section formatting for all major handbook parts (Beginner, Advanced, Examples, Quick Reference)  
- "Why Manual Steps Matter" rationale  
- Expanded Limitations section  
- Slash-style command formatting standard:
  - `/start marm`  
  - `/log [SessionName]`  
  - `/guarded reply`  
  - `/show reasoning`  
  - `/compile [SessionName] --summary`  

### Changed
 
- README clarified and reorganized to align with handbook  
- Handbook structured into Beginner / Intermediate / Advanced use tiers  
- Emphasis on manual workflows and session recap cadence  

### Removed

- Embedded command list from README  
- "Back to top" anchors (due to GitHub collapsible quirks)  

</details>

---

<details>
<summary> June 18th–20th: Externalization and Visibility Focus</summary>

### Added

- AI-narrated walkthrough: 15-minute audio guide embedded in README  
- User Feedback section (collapsible, with real screenshots)  
- Featured on Google badge added to README header  
- `CONTRIBUTING.md` and Recognition Framework  
- Multi-tier GitHub Discussions and onboarding entry points  

### Changed

- README focus shifted to narrative onboarding:
  - "What → Why → How → Proof" sequence  
  - Replaced "Use Cases" with community-backed examples  
  - Light marketing layer added (clear, not exaggerated)  

</details>

---

<details>
<summary>June 21st-23rd: Protocol Expansion (v1.3 Launch)</summary>

### Added

- `/notebook` command to save custom info in a personal library  
  → Guides the AI to use only trusted user-provided data, not external sources  
- Passive reentry prompts to resume, archive, or reset context on return  
- Error handling for invalid `/log` entries, including date autofill suggestions  
- Filter support for `/compile --fields=` to create focused summaries  
- "What's New in v1.3" section added to `HANDBOOK.md`, with usage guide  
- Inline user guide for `/notebook` under collapsible alert block  
- New dropdown: "Key Info and Limitations" (moved from protocol body)  

### Changed

- "What MARM Solves" and "Why It Exists" sections updated to reflect v1.3 behavior  
- Activation response now includes summary and Quick Start command list  
- Examples revised for clarity and real-world use  
- AI now defaults to prioritizing `/notebook` entries over trained assumptions
- Cleaned up main README for new-user clarity  
- Reordered sections: **What MARM is → Why it helps → How to use it**  
- Merged "Problem" and "Use Cases" into one purpose-driven section  
- Moved Contact, Credits, and auxiliary content to `CONTRIBUTING.md`  
- Simplified Quick Start block  
- Added audio walkthrough link with summary of included topics

### Removed

- Key info and limitations from static protocol body (now placed in dropdown)  
- Redundant phrasing in command definitions and legacy guardrail notes  

</details>

---

<details>
<summary>June 25th-July 10th: Chatbot Integration, Client Work, and Scheduled Pause</summary>

### Context

- Focus shifted to finalizing a public chatbot that runs MARM logic directly from the repo. This feature will allow users to interact with MARM in real time and explore its functionality hands-on.
- Took a scheduled 5-day break for the July 4th holiday.
- Completed a consulting engagement re-engineering a deliverability protocol for a client, which temporarily paused MARM-specific development.

### Upcoming

- Final chatbot tweaks are in progress; once deployed, it will be featured directly in the GitHub repo.
- MARM refinements will resume, including minor protocol adjustments and test-driven formatting updates.

</details>

---

<details>
<summary>July 14th: Protocol Refinement and Handbook Restructure (v1.4 Launch)</summary>

### Added

- `/refresh marm` command to recenter AI mid-session, recommended every 8-10 turns
- Subcommands for `/notebook`: `key:[name]`, `get:[name]`, and `show:` for enhanced data management
- "Your Objective" and "Safe Guard Check" sections for strict MARM identity and self-verification before responding
- "What's New in v1.4 (Upgrading from v1.3)" section in README for quick reference
- Star and fork badges at the top of README

### Changed

- `/log` command split into `/log session:[name]` and `/log entry [Date | User | Intent | Outcome]` for increased precision
- Clarified manual-only processes; removed ambiguous automation from all protocol sections
- Restructured HANDBOOK.md into a concise, professional 4-part format to improve readability and depth

### Removed

- Previous automated workflow references that implied non-manual AI actions
- Redundant explanations and repetitive content from HANDBOOK.md to streamline user experience

</details>

---

<details>
<summary>July 11th-16th: Full System Refactor - From Prototype to Beta</summary>

### Added

- **New UI Features:**
  - A dynamic, collapsible command menu to organize all MARM commands and improve usability.
  - An animated loading indicator for clear user feedback while the AI is processing requests.
  - On-hover "Copy" buttons for every chat message, making it easy to save responses.
  - Full dark mode support for all new UI components.
- **Enhanced Logic and Context:**
  - Full support for all MARM v1.4 commands, including the new `/start` and `/refresh` commands.
  - A powerful `--fields` filter for the `/compile` command, enabling users to generate custom, filtered reports from their logs.
  - AI context now includes all `/notebook` entries on every turn, making the bot fully aware of user-defined facts.
  - Keyword-aware document searching to provide more accurate answers for MARM-related queries.

### Changed

- **Core Interaction Model:**
  - Refactored the command handling system to a "hybrid" model. Most commands now trigger an AI-generated, natural language acknowledgment instead of a static text reply.
  - Updated the message display function to use `marked.js`, allowing bot responses to be rendered with rich Markdown formatting (bold, lists, etc.).
- **Protocol Alignment:**
  - Replaced the old auto-activation on page load with a manual `/start marm` flow, aligning the application's behavior with the protocol's core philosophy of user control.
  - Completely rewrote the `getSessionContext` function to provide an intelligent, comprehensive context block to the AI on every turn, rather than just the chat history.
- **Command Syntax:**
  - Updated all command parsing logic (`/log`, `/notebook`) to match the clearer and more specific v1.4 syntax.

### Removed

- **Outdated Code & Logic:**
  - Eliminated the old, rigid command logic and all of its hardcoded response strings.
  - Removed the automatic MARM activation flow.
  - Made the legacy `config.js` file completely obsolete, as its contents were integrated or replaced.

</details>

---

<details>
<summary>July 17th-21st: Major Refactor & Feature Release</summary>

### Overview

This release marks a complete transformation of the codebase from a monolithic structure to a modern, modular, barrel-pattern architecture. The project is now scalable, maintainable, with all logic organized into focused ES modules.

### Added

- **Session Persistence System**
  - Sessions now survive page refresh using dual storage strategy
  - Current session stored separately from saved sessions (CURRENT_SESSION_KEY)
  - Automatic session recovery on page load
  - Smart pruning at 5KB (PRUNING_THRESHOLD) to maintain performance
  - Session expiry after 30 days (SESSION_EXPIRY_DAYS)

- **Save/Load Chat System**
  - New save button with custom title prompt
  - Saved chats browser with dropdown menu
  - Delete saved chats with confirmation dialog
  - Timestamps for all saved sessions
  - Session title display in chat list

- **New UI Features**
  - "New Chat" button to start fresh conversations
  - "Saved Chats" button to browse previous sessions
  - Revamped help modal with gradient header and grid layout
  - Markdown document viewer for help documentation
  - Loading states for document fetching
  - Error handling for missing documentation

- **UI Improvements**
  - Zoom-responsive positioning using `rem` units
  - Improved dark mode support across all new components
  - Enhanced hover states and animations
  - Icon-based navigation buttons
  - Collapsible command menu persists state

### Changed

- **Architecture: Monolithic → Modular**
  - Split 900+ line `chatbot.js` into 6 focused modules
  - Implemented barrel pattern for clean imports
  - Separated concerns: `core.js`, `ui.js`, `voice.js`, `commands.js`, `state.js`
  - Logic modules: `constants.js`, `session.js`, `notebook.js`, `docs.js`, `summary.js`, `utils.js`
  - Each module <300 lines for readability and maintainability

- **CSS Organization**
  - Split single `style.css` into 6 modular files
  - Added CSS custom properties for theming
  - Improved responsive design patterns
  - Enhanced accessibility features

- **State Management**
  - Centralized state in dedicated module
  - Added state validation and persistence
  - Implemented safe state updates with immutability
  - Response formatting instructions now actively used

- **Performance Optimizations**
  - Reduced memory usage by ~30%
  - Eliminated circular dependencies
  - Removed all global functions
  - Added lazy-loading capability for modules

### Fixed

- Voice synthesis integration properly scoped
- Command menu state persistence
- Input validation and sanitization
- Error handling throughout application
- Dark mode consistency issues
- Response formatting now applied to all bot messages

### Removed

- Global `window.*` function pollution (12 functions removed)
- Circular dependencies between modules
- Duplicate state management code
- Inline event handlers (replaced with delegation)

</details>

---

<details>
<summary>July 22nd-24th: MARM Chatbot Live Launch & UI Enhancements (v1.5 Launch)</summary>

### Overview

Official launch of the MARM interactive chatbot on Render, featuring custom backgrounds, improved session management architecture, and enhanced error handling across the application.

### Added

- **Background Images System**
  - Light mode now supports custom background image (`images-bg.png`)
  - Dark mode uses separate background image (`images-dark-bg.png`)
  - Dynamic background switching based on theme preference

- **Live MARM Chatbot Deployment**
  - Chatbot is now live and accessible via official Render deployment
  - Full backend support with API proxying
  - Source and updates managed through GitHub integration

- **Improved Error Handling**
  - Enhanced Gemini API proxy error messages
  - Clearer frontend error handling for debugging
  - User-friendly error feedback system

### Changed

- **Session Management Architecture**
  - Moved all session-related UI logic to new `sessionUI.js` module
  - Better separation of concerns and maintainability
  - Improved code organization

- **Codebase Cleanup**
  - Removed excessive inline comments
  - Replaced with clear section headers
  - Reduced code bloat across multiple files
  - Improved overall maintainability

- **Deployment Configuration**
  - Switched from static site to Node.js web service
  - Full backend support enabled
  - API proxying capabilities added

### Fixed

- Session persistence issues across page refreshes
- Error handling for missing documentation files
- Dark mode toggle functionality
- Mobile responsive design issues
- Background image loading and switching

### Removed

- Excessive inline comments and code bloat
- Global function pollution
- Redundant session management code
- Unused deployment configurations

</details>

---

<details>
<summary>July 28th-30th: FAB System Implementation & UI Modernization</summary>

### Overview

This release introduces a complete UI/UX transformation with the implementation of a modern Floating Action Button (FAB) system, replacing the traditional floating buttons with an expandable, mobile-first design. The update includes comprehensive responsive design improvements, enhanced code block functionality, and significant architectural refinements for better user experience.

### Added

- **Floating Action Button (FAB) System**
  - Expandable circular FAB with smooth animations and staggered delays
  - Four primary actions: Dark Mode, Saved Chats, New Chat, Token Counter
  - Auto-close functionality when clicking outside FAB
  - Perfect circular design with hover effects and visual feedback
  - Mobile-first responsive design with desktop compatibility

- **Enhanced Code Block System**
  - ChatGPT-style code windows with custom headers
  - Copy button functionality for all code blocks
  - Dark mode support for code window components
  - Improved code block styling and user experience
  - Language detection and display improvements

- **Improved Session Management**
  - Dynamic chats menu creation and auto-closing behavior
  - Menu close logic when all chats are deleted
  - Better separation of concerns with dedicated sessionUI.js module
  - Enhanced user feedback and interaction patterns

- **Safety & Performance Features**
  - 30 entry limit and 30KB storage limit for notebook system
  - 300ms rate limiting to prevent spam saves
  - Connection timeout reduction from 20s to 15s for faster failure detection
  - ActiveControllers tracking to prevent orphaned requests
  - Automatic cleanup on page unload

### Changed

- **Mobile-First Architecture**
  - Replaced individual floating buttons with unified FAB system
  - Removed deprecated mobile button hiding rules
  - Improved spacing between Quick Commands ↔ Chat ↔ FAB
  - Better visual hierarchy and responsive design

- **Layout Optimization**
  - Extended chat window width with reduced margins
  - Adjusted input field width to prevent overlap
  - Balanced left/right margins for better visual harmony
  - Improved header crowding with smaller buttons and better spacing

- **Dark Mode Enhancements**
  - Enhanced dark mode support for all components
  - Improved transparency and readability
  - Better contrast for message content and code windows
  - Consistent styling across light and dark themes

- **GitHub Deployment Sync**
  - Updated gh-index.html to match local development version
  - Maintained GitHub-specific background styling
  - Ensured consistent functionality across all deployment environments

### Fixed

- FAB button functionality on Render deployment
- Circular button styling with proper border-radius
- Menu auto-closing behavior for saved chats
- Input field overlap with Send button
- Visual balance between chat window and action buttons

### Removed

- Individual floating buttons (token-counter-btn, newChatBtn, chatsBtn, darkModeToggle)
- Duplicate FAB structure outside form
- Deprecated mobile button hiding CSS rules
- Old button setup functions from ui.js and sessionUI.js
- Unused mobile-specific button styles

</details>

---

<details>
<summary>July 31st, 2025: Documentation Overhaul & Local Setup Improvements</summary>

### Added

- **SETUP.md** – New, in-depth local download and installation guide
- **config.js** – AI provider configuration file for universal API support
- **universalAIHelper.js** - Universal AI provider support
- **New screenshots** – Visuals of the webchat interface added to README

### Changed

- **README.md** –
  - Updated for v1.5
  - Added screenshots and visuals
  - Removed "What's New with MARM" section
  - Added local download quick setup section

### Improved

- **Consistency** – All documentation now reflects v1.5 and matches the current feature set
- **User onboarding** – Clearer quick start, setup, and troubleshooting for new users

</details>

---

<details>
<summary>August 5th, 2025: Readme Restructure </summary>

### Added

- **README-2.md creation** - Complete restructure for professional presentation
- **Enhanced PROTOCOL.md** - Complete copy-paste prompt with technical specs

### Changed

- **Documentation hierarchy** - Clear separation of concerns
- **Professional positioning** - Research/professional focus vs chatbot focus

### Removed

- **Redundant content** - Eliminated duplication
- **Overwhelming detail** - Moved to dedicated files
- **Chatbot-focused language** - Replaced with framework positioning

</details>

---

<details>
<summary>August 6-18, 2025: MARM v2.0 Production Launch </summary>

## **August 6-18, 2025: MARM v2.0 Production Launch**

**Core achievements: 95% cost reduction (Gemini → Llama 4), professional test suite (74 tests), protocol v2.0 evolution, security hardening, and complete UI modernization.**

### **Professional Testing Infrastructure Implementation**

- **Comprehensive Test Suite**: Added 74 passing tests across 4 modules - Voice (13), UI (16), State/Session (15), Commands (15), Security/Logic (15)
- **GitHub Actions Integration**: Automated testing on push/PR with Node.js 18.x & 20.x, test status badge added to README
- **ES Module Testing**: Full Jest configuration supporting modern JavaScript imports, browser API mocking (speechSynthesis, localStorage, DOM)
- **Quality Assurance**: 42.39% test coverage with detailed reports, error handling validation, edge case testing for all core functionality

### **Complete AI Provider Migration: Gemini → Llama 4 Maverick**

- **Backend Transformation**: Complete migration from Google Gemini API to Replicate Llama 4 Maverick (400B total parameters, 17B active × 128 experts)
- **Cost Optimization**: Achieved 95% operational cost reduction (.65 per million tokens output vs Claude Sonnet pricing)
- **Performance Upgrade**: Access to 10M token context limit with significantly improved response times
- **API Architecture**: Converted from Gemini's complex message format to Replicate's streamlined prompt-based system
- **Technical Implementation**: Complete rewrite of `server.js` streaming endpoint, new `replicateHelper.js` replacing `geminiHelper.js`

### **MARM Protocol Evolution: v1.5 → v2.0**

- **Identity Transformation**: Updated from generic assistant mode to "MARM IS memory incarnate" - core identity evolution
- **Response Optimization**: Replaced verbose "Response Contract" with concise "💭 Thinking Trail" format for user-friendly output
- **Command Modernization**:
  - `/contextual reply` → `/deep dive` (clearer functionality naming)
  - `/compile [SessionName] --summary` → `/summary: [session name] --summary` (better syntax)
  - Enhanced notebook commands: `/notebook use:`, `/notebook clear:`, `/notebook status:` (active management)
- **Memory System Overhaul**: Added conversation import system for mid-session MARM activation with complete context preservation

### **Complete UI/UX Modernization**

- **Visual Transformation**: Complete overhaul from "2010 vibes" to modern design standards with indigo (#6366f1) and amber (#f59e0b) color palette
- **Glassmorphism Effects**: Enhanced shadows and glass effects throughout interface for premium feel
- **Chat Message Cards**: Implemented card-style messages with glass effects, proper shadows, and user/bot visual distinction
- **Command Menu Redesign**: Complete transformation from sidebar to contextual popup button (⚡) positioned next to input field
- **Complete HTML/JavaScript Separation**: Moved all HTML templates from JavaScript files to HTML templates, clean separation of concerns

### **Security & Architecture Hardening**

- **XSS Protection System**: Comprehensive security module (`xssProtection.js`) with multiple sanitization levels
  - `sanitizeText()`: HTML entity escaping for plain text
  - `sanitizeHTML()`: Advanced sanitization with script/iframe blocking
  - `sanitizeHTMLStrict()`: Ultra-strict sanitization for user input
- **Storage Architecture**: Created centralized `storage.js` for localStorage operations with multi-tab synchronization
- **State Management Enhancement**: Private state object only accessible through `getState()`, immutable patterns with defensive copies

### **New Features & Capabilities**

- **File Upload System**: File upload button (📎) with text/code file support for 15+ file types, smart detection, automatic language detection and syntax highlighting
- **MARM Protocol Toggle**: Toggle button (🧠) in FAB menu for instant protocol switching between structured MARM and free mode with visual feedback

### **Critical Bug Fixes & System Stability**

- **MARM Memory Issues**: Fixed critical memory loss bug where MARM would lose all conversation context when activated mid-conversation
- **Session Persistence**: Fixed MARM forgetting conversation when toggled off and back on, now preserves existing session IDs
- **Performance Optimization**: Eliminated 60+ lines of duplicate code, replaced expensive JSON.stringify operations, request timeout optimization (15s → 45s)
- **Voice System**: Fixed TTS "interrupted" errors in speech synthesis by adding proper cancellation logic
- **Browser Compatibility**: Added cache-busting headers to server.js and version strings to prevent stale file serving

### **Impact Summary**

- **95% cost reduction** through AI provider optimization
- **Zero XSS vulnerabilities** with comprehensive protection
- **Production-ready architecture** with modern web standards
- **50+ files modified**, 1000+ lines changed
- **3 major new features**, 15+ critical issues resolved

</details>

---

<details>
<summary>August 20th – September 12th, 2025: Universal MCP Server Development (v2.2.4 Launch)</summary>

### Added

**Universal MCP Server Architecture:**

- **Production-ready FastAPI server** with Model Context Protocol implementation
- **19 complete MCP tools** for AI memory intelligence across all platforms
- **Docker containerization** with multi-stage builds and health monitoring
- **Semantic search engine** using sentence-transformers (all-MiniLM-L6-v2) with vector embeddings
- **Cross-platform memory database** - SQLite with WAL mode optimization and connection pooling
- **Multi-agent development workflow** - Claude (architecture), Gemini (validation), Qwen (research), ChatGPT (testing)

**MCP Tools Suite:**

- **Memory Intelligence**: `marm_smart_recall` (global semantic search), `marm_contextual_log` (intelligent storage)
- **Session Management**: `marm_start`, `marm_refresh` with enhanced protocol adherence
- **Logging System**: `marm_log_session`, `marm_log_entry`, `marm_log_show`, `marm_log_delete`
- **Notebook Management**: Complete CRUD operations with `marm_notebook_add`, `marm_notebook_use`, etc.
- **Workflow Tools**: `marm_summary`, `marm_context_bridge` for seamless transitions
- **System Utilities**: `marm_current_context`, `marm_system_info`, `marm_reload_docs`

**Production Features:**

- **Production-ready architecture** - FastAPI backend with rate limiting, IP-based protection, graceful degradation
- **Professional test suite** - 5 comprehensive diagnostic tests (security, performance, integration, memory usage, MCP compliance)
- **Health monitoring** - Comprehensive system status and performance tracking
- **Database optimization** - SQLite with connection pooling, WAL mode, efficient storage
- **Security hardening** - Input validation, error isolation, production-ready deployment
- **Analytics system** - Privacy-conscious usage tracking for platform optimization

**Multi-Platform Integration:**

- **Claude Code** integration with CLI commands (`claude mcp add marm-memory`)
- **Qwen CLI** and **Gemini CLI** full MCP tool access
- **Universal MCP compatibility** for any Model Context Protocol client
- **Cross-AI memory sharing** - All connected agents contribute to unified knowledge base

### Changed

- **Architecture evolution** from chatbot-focused to Universal MCP Server platform
- **Protocol enhancement** - Original MARM commands now available as MCP tools
- **Documentation restructure** - MCP server as primary product, chatbot as secondary demo
- **Development approach** - Multi-agent collaboration showcasing AI-assisted development
- **Memory model** - From session-based to persistent, searchable, semantic database

### Technical Achievements

- **Docker Hub deployment** - `lyellr88/marm-mcp-server:latest` for production use
- **Semantic search implementation** - AI embeddings for intelligent memory retrieval
- **Universal MCP Server implementation** - Platform-agnostic memory intelligence
- **Multi-AI workflows** - Demonstrated collaborative development between AI agents
- **Production deployment** - Production-ready with monitoring, health checks, and scaling

</details>

---

<details>
<summary>September 15th – September 18th, 2025: Production Stabilization & Registry Preparation</summary>

## **September 15th – September 18th, 2025: Production Stabilization & Registry Preparation**

**Core achievements: Multi-platform publishing setup, CI/CD workflow validation, documentation system overhaul, and repository cleanup - all focused on preparing MARM for official listing in the GitHub MCP Registry and enabling seamless pip install deployment.**

### **Multi-Platform Publishing & CI/CD**

- **PyPI Integration:**
  - Configured PyPI trusted publishing with proper project name alignment to `[project].name` in `pyproject.toml`
  - Resolved repository, workflow, and naming inconsistencies to ensure smooth, automated PyPI package releases
  - Enabled `pip install marm-mcp-server` for easy Python package installation

- **Docker Hub Support:**
  - Standardized source and build directories for clean Docker image creation
  - Refactored documentation and codebase to support fast, reliable Docker builds and pushes
  - Updated workflow scripts to match new folder structures after refactor
  - Enabled `docker pull lyellr88/marm-mcp-server:latest` for containerized deployment

- **MCP Registry Listing:**
  - Prepared the MCP server for listing and integration with the official MARM MCP service/agent registry
  - Ensured compliance with Model Context Protocol standards for automatic agent discovery
  - Enabled seamless integration with Claude Desktop and other MCP-compatible AI clients

### **CI/CD Workflows**

- **GitHub Actions:**
  - Enhanced, debugged, and validated workflows for PyPI, Docker, and registry deployment
  - Ensured all actions/scripts reference the updated project and documentation structure, removing legacy/obsolete paths
  - Implemented robust error handling and rollback mechanisms for production deployments

### **Documentation System Overhaul**

- **Auto-Loading/Modularized Docs:**
  - Migrated from hardcoded manual documentation lists to an automated loader for all `.md` files
  - Developed a context-type classifier and logging function for each loaded doc
  - Implemented essential-only doc loading (now only `PROTOCOL.md` and `README.md` loaded by default, with others available via recall), drastically reducing token/context bloat

- **Handbook and Docs Refactor:**
  - Split large handbooks into six logically-focused, easily-maintainable files (3 for MCP, 3 for the main system), improving structure and modularity
  - Maintained clear and robust logging for missing or misclassified essential docs

### **Refactoring & Repo Cleanup**

- **Legacy Removal:**
  - Eliminated outdated or redundant folders (`MARMcp-beta`), consolidating all code and documentation under a single, standardized directory structure
  - Validated and updated all file paths, scripts, and configuration files to ensure project integrity post-refactor

- **Multi-AI Validation:**
  - Coordinated use of Claude, Qwen, Gemini, and Comet for change verification, diff checking, and QA
  - Used a centralized CP Dump method for capturing and tracking change logs, error traces, and validation outputs during the transition

### **Impact Summary**

- **Production readiness** - Stabilized Universal MCP Server for public release
- **Registry compliance** - Prepared for official GitHub MCP Registry listing
- **Multi-platform deployment** - Enabled pip install, Docker pull, and MCP registry integration
- **Documentation excellence** - Modular, auto-loading system with reduced token overhead
- **Codebase cleanliness** - Eliminated legacy artifacts and standardized structure

</details>

---

<details>
<summary>September 19th-23rd, 2025: WebSocket Production Launch & Alpha Tester Resolution (v2.2.5 Launch)</summary>

## **September 19th-23rd, 2025: WebSocket Production Launch & Alpha Tester Resolution (v2.2.5 Launch)**

**Core achievements: Complete GitHub alpha tester feedback resolution (4/4 issues), full WebSocket production implementation with HTTP parity, OAuth authentication restoration, graceful shutdown infrastructure, and modernized dependency management - achieving zero outstanding issues and production-ready WebSocket MCP protocol.**

### **🎉 Complete GitHub Alpha Tester Issue Resolution (4/4)**

- **Issue #1 - WebSocket URL Implementation**:
  - Implemented complete WebSocket MCP protocol at `ws://localhost:8001/mcp/ws`
  - Achieved full HTTP/WebSocket parity with all 19 MCP methods
  - Added JSON-RPC 2.0 compliance with proper error handling
  - Integrated thread-safe connection management with rate limiting

- **Issue #2 - Parameter Consistency**:
  - Standardized parameter naming across all endpoints
  - Updated `marm_notebook_use` from `names` to `name` for consistency
  - Modified core models and endpoint handlers for unified API

- **Issue #3 - Docker Persistence**:
  - Updated all documentation with volume mount requirements
  - Standardized Docker commands with `-v marm_data:/app/data`
  - Ensured data persistence across container restarts

- **Issue #4 - Health/Readiness Monitoring**:
  - Enhanced `/health` endpoint with database connectivity testing
  - Added `/ready` endpoint with full functionality validation
  - Implemented Docker health checks with curl testing
  - Added comprehensive startup guidance and troubleshooting

### **🚀 WebSocket Production Implementation**

- **Complete MCP Protocol Support**:
  - All 19 MCP methods available via WebSocket protocol
  - Full HTTP/WebSocket feature parity achieved
  - Professional JSON-RPC 2.0 implementation with error handling

- **Production Architecture**:
  - Thread-safe WebSocket connection manager (`core/websocket_manager.py`)
  - Modular endpoint architecture (`endpoints/websocket.py`)
  - Clean import/export handler system for maintainability
  - Integration with existing security and rate limiting middleware

- **Connection Management**:
  - Connection pooling with configurable limits
  - Graceful connection cleanup and client session tracking
  - Broadcast and personal messaging capabilities
  - Proper WebSocket lifecycle management

### **🔧 Infrastructure & Authentication Improvements**

- **OAuth 2.0 Authentication Restoration**:
  - Restored complete OAuth implementation that mysteriously disappeared
  - Full authorization code flow with client credentials validation
  - Added `endpoints/oauth.py` with authorize, token, userinfo, revoke, debug endpoints
  - Excluded OAuth from MCP tool discovery with `include_in_schema=False`

- **Graceful Server Shutdown**:
  - Implemented signal handlers for SIGTERM/SIGINT (Unix systems)
  - Added WebSocket connection closure during shutdown
  - Created `core/shutdown_manager.py` for clean server termination
  - Fixed issue where MCP clients prevented server shutdown

- **Smart Dependency Management**:
  - Modernized `requirements.txt` from exact pins (==) to smart version ranges
  - Implemented `>=X.Y.Z,<X+1.0.0` pattern for automatic security updates
  - Updated to match actually installed working versions
  - Enabled automatic security patches without breaking changes

### **🏗️ Architecture & Documentation Enhancements**

- **Date Handling Architecture Fix**:
  - Fixed `marm_log_entry` incorrectly auto-adding date prefixes to user content
  - Connected `marm_log_session` to `marm_current_context` background tool
  - Sessions now get automatic dates while entries preserve exact user input
  - Proper separation of automated vs. user-controlled content

- **Package Structure Synchronization**:
  - Synchronized root-level development code with `marm_mcp_server/` package folder
  - Ensured PyPI package structure matches working development environment
  - Updated all new files: oauth.py, shutdown_manager.py, websocket_manager.py
  - Maintained proper Python package naming conventions

- **Comprehensive Documentation Updates**:
  - Updated all installation guides with WebSocket connection examples
  - Added natural language interface emphasis in MCP-HANDBOOK.md
  - Clarified background tool automation (marm_current_context)
  - Enhanced troubleshooting sections for connection issues

### **🐛 Technical Debt Resolution**

- **WebSocket Implementation Quality**:
  - Eliminated "sloppy" mixed approaches in favor of consistent patterns
  - Replaced inline handler architecture with clean import/export system
  - Fixed rate limiting middleware bug preventing WebSocket connections
  - Removed all stub implementations and placeholder code

- **Background File Analysis**:
  - Analyzed and confirmed safe removal of websocket_backup.py (374-line old architecture)
  - Validated setup.py.backup as outdated installer script
  - Confirmed cp dump.md contained only OAuth implementation (no other missing features)
  - Completed comprehensive backup file cleanup

- **Version Management**:
  - Coordinated v2.2.5 updates across all deployment files
  - Maintained surgical precision in version synchronization
  - Updated package metadata and documentation references

### **📊 Testing & Validation Framework**

- **Comprehensive Test Suite**:
  - Created bulletproof validation testing for all 19 MCP methods
  - Implemented sabotage-resistant error detection
  - Built systematic GitHub issue validation framework
  - Achieved 100% success rate on all production readiness criteria

- **WebSocket Protocol Validation**:
  - Tested JSON-RPC 2.0 compliance with malformed request handling
  - Validated connection management under load
  - Verified security integration and rate limiting functionality
  - Confirmed backward compatibility maintenance

### **Impact Summary**

- **Zero Outstanding Issues**: All 4 GitHub alpha tester issues completely resolved
- **Production WebSocket Ready**: Full HTTP/WebSocket parity with professional implementation
- **Enhanced Security**: OAuth restoration, graceful shutdown, and rate limiting integration
- **Modernized Infrastructure**: Smart dependency management and automated security updates
- **Beta Production Status**: WebSocket implementation ready for real-world testing and deployment
- **Developer Experience**: Comprehensive documentation with natural language interface guidance

### **Technical Achievements**

- **Complete CI/CD Compatibility**: Maintained deployment readiness across PyPI, Docker Hub, and MCP Registry
- **Professional Architecture**: Modular design with proper separation of concerns and security integration
- **Performance Optimization**: Lazy loading, connection pooling, and intelligent caching maintained
- **Cross-Platform Support**: Windows signal handling compatibility with Unix systems
- **Memory Management**: Efficient SQLite operations with WAL mode and connection pooling

**Next Phase**: Public launch announcement → Developer community building → Pro version development

</details>

---

<details>
<summary>September 25th, 2025: Security Hardening - 4 Critical Vulnerabilities Fixed (v2.2.5)</summary>

### Security Fixes

- **XSS Protection Enhancement**: Fixed malformed script tag bypass vulnerability
  - Updated regex pattern to handle spaces in closing tags: `</script >`, `< /script>`
  - Improved sanitization now blocks all script tag variations
  - Files: `core/memory.py` (both copies)

- **ReDoS Attack Mitigation**: Prevented regex backtracking DoS attacks
  - Added 10KB input length limit to prevent exponential regex processing
  - Large attack payloads now processed safely in <0.03s
  - Vulnerability: `py/polynomial-redos` in script tag regex patterns

- **Open Redirect Prevention**: Blocked phishing attempts via OAuth redirects
  - Added URL validation to restrict `redirect_uri` to localhost/relative paths only
  - Prevents external domain redirects that enable phishing attacks
  - Vulnerability: `CWE-601` in `marm_mcp_server/endpoints/oauth.py:98`
  - File: `marm_mcp_server/endpoints/oauth.py`

- **Stack Trace Exposure Protection**: Hidden internal error details from external users
  - Replaced `str(e)` exposures with generic error messages for health checks
  - Fixed 19+ WebSocket error handlers exposing internal implementation details
  - Added server-side logging while keeping client responses secure
  - Prevents disclosure of file paths, database strings, internal architecture
  - Vulnerability: `py/stack-trace-exposure` in health endpoints and WebSocket handlers
  - Files: `endpoints/system.py`, `endpoints/websocket_handlers_complete.py`

### Changed

- All error responses now return generic messages to external users
- Server-side logging enhanced for debugging while maintaining security
- OAuth flow restricted to development-safe redirect URIs

### Technical Notes

- All fixes follow "SIMPLE IS BETTER THAN COMPLICATED" principle
- Surgical changes maintain functionality while eliminating security risks
- Total files modified: 5 across 4 vulnerability categories
- All GitHub CodeQL security alerts resolved

</details>

---

<details>
<summary>March 20th, 2026: Pip Install Fix & Docs Cleanup (v2.2.7)</summary>

## **March 20th, 2026: Pip Install Fix & Docs Cleanup (v2.2.7)**

**Core achievements: Fixed broken pip install, added `python -m marm_mcp_server` support, documented active bugs and planned architecture improvements, cleaned up docs structure.**

### **Pip Install Fix**

- **Root Cause**: `marm_mcp_server/server.py` used absolute imports (`from middleware import ...`) — these work when running `python server.py` from root but fail when installed as a package
- **Fix**: Converted all absolute imports to relative imports across 16 files in `marm_mcp_server/`
- **Added `__main__.py`**: Created `marm_mcp_server/__main__.py` so `python -m marm_mcp_server` now works
- **Added entry functions**: Added `create_server()` and `main()` to `server.py` — `main()` serves as the pip CLI entry point (`marm-mcp-server` command), `create_server()` exposes the FastAPI app for external use
- **Windows PATH note**: `marm-mcp-server` CLI requires `C:\Users\{username}\AppData\Roaming\Python\Python3xx\Scripts\` in PATH; `python -m marm_mcp_server` works without any PATH changes and is now the recommended command

### **Documentation Cleanup**

- **New docs structure**: Reorganized into `archived/`, `core/`, `current/`, `future/`, `Visuals/` folders
- **Removed FAQ.md**: Base MARM questions moved to FAQ section in `MARM-HANDBOOK.md`; MCP tools table moved to `MCP-HANDBOOK.md`; chatbot-specific content deleted (chatbot retired)
- **Removed DESCRIPTION.md**: Fully redundant with README — deleted
- **New `current-issues.md`**: Created `docs/current/current-issues.md` to track active bugs and planned improvements with full context on root causes

### **Active Issues Documented**

- **`marm_log_session` not switching sessions**: Entries land in `main` instead of named session — session state not persisting before `marm_log_entry` fires
- **Planned: Token optimization** — lazy loading docs instead of bulk-loading at startup
- **Planned: Directory-based memory architecture** — per-project SQLite DBs with global cross-reference index
- **Planned: Remove duplicate root files** — single source of truth cleanup

### **Impact Summary**

- `pip install marm-mcp-server` now installs a working package
- `python -m marm_mcp_server` is the primary run command going forward
- Active bugs and architecture plans captured in dedicated tracking doc

</details>

---

## 📁 Project Documentation

### **Usage Guides**

- **[MARM-HANDBOOK.md](https://github.com/Lyellr88/MARM-Systems/blob/MARM-main/MARM-HANDBOOK.md)** - Original MARM protocol handbook for chatbot usage
- **[MCP-HANDBOOK.md](https://github.com/Lyellr88/MARM-Systems/blob/MARM-main/MCP-HANDBOOK.md)** - Complete MCP server usage guide with commands, workflows, and examples
- **[PROTOCOL.md](https://github.com/Lyellr88/MARM-Systems/blob/MARM-main/PROTOCOL.md)** - Quick start commands and protocol reference

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
- **[CHANGELOG.md](https://github.com/Lyellr88/MARM-Systems/blob/MARM-main/docs/CHANGELOG.md)** - Version history and updates
- **[ROADMAP.md](https://github.com/Lyellr88/MARM-Systems/blob/MARM-main/docs/ROADMAP.md)** - Planned features and development roadmap
- **[LICENSE](https://github.com/Lyellr88/MARM-Systems/blob/MARM-main/docs/LICENSE)** - MIT license terms
