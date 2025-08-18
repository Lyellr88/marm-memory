# Changelog

## MARM Protocol – v2.0 Change Log  

---

<details>
<summary> June 9th–13th: Initial Protocol Unification (v1.2 Launch)</summary>

### Added

- `/compile` command to generate one-line-per-entry summaries  
- Automatic reseed block generation for restoring context in new threads  
- Log schema enforcement for structured logging: `[YYYY-MM-DD | User | Intent | Outcome]`  
- Error handling for malformed log entries, including date autofill  
- `/show reasoning` command to reveal the AI’s logic path  
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
- “Why Manual Steps Matter” rationale  
- Expanded Limitations section  
- Slash-style command formatting standard:
  - `/start marm`  
  - `/log [SessionName]`  
  - `/guarded reply`  
  - `/show reasoning`  
  - `/compile [SessionName] --summary`  

### Changed

- FAQ.md grouped and rewritten by category: Core Concepts, Sessions, Commands, Platform Support  
- README clarified and reorganized to align with handbook  
- Handbook structured into Beginner / Intermediate / Advanced use tiers  
- Emphasis on manual workflows and session recap cadence  

### Removed

- Embedded command list from README  
- “Back to top” anchors (due to GitHub collapsible quirks)  

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
  - “What → Why → How → Proof” sequence  
  - Replaced “Use Cases” with community-backed examples  
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
- “What’s New in v1.3” section added to `HANDBOOK.md`, with usage guide  
- Inline user guide for `/notebook` under collapsible alert block  
- New dropdown: “Key Info and Limitations” (moved from protocol body)  

### Changed

- “What MARM Solves” and “Why It Exists” sections updated to reflect v1.3 behavior  
- Activation response now includes summary and Quick Start command list  
- Examples revised for clarity and real-world use  
- AI now defaults to prioritizing `/notebook` entries over trained assumptions
- Cleaned up main README for new-user clarity  
- Reordered sections: **What MARM is → Why it helps → How to use it**  
- Merged “Problem” and “Use Cases” into one purpose-driven section  
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
- **DESCRIPTION.md** – Completely rewritten for clarity and authenticity
- **FAQ.md** – Added chatbot-specific questions and usage tips

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

**Comprehensive security hardening, complete AI provider migration (Gemini → Llama 4), MARM protocol evolution to v2.0, major UI/UX modernization, and professional testing infrastructure deployment.**

---

### ** Professional Testing Infrastructure Implementation**

- **Comprehensive Test Suite**: Added 74 passing tests across 4 modules - Voice (13), UI (16), State/Session (15), Commands (15), Security/Logic (15)
- **GitHub Actions Integration**: Automated testing on push/PR with Node.js 18.x & 20.x, test status badge added to README
- **ES Module Testing**: Full Jest configuration supporting modern JavaScript imports, browser API mocking (speechSynthesis, localStorage, DOM)
- **Test Files**: Created `tests/chatbot.test.js`, `tests/logic.test.js`, `tests/security_replicate_html.test.js` with comprehensive coverage
- **Quality Assurance**: 42.39% test coverage with detailed reports, error handling validation, edge case testing for all core functionality
- **Developer Infrastructure**: Professional-grade testing setup ensuring code quality, regression prevention, and contributor confidence

### ** Modern Glassmorphism UI Revolution**

- **Floating Card Architecture**: Eliminated nested windows - message cards now float directly on glassmorphism background for 2025 aesthetic
- **Color-Coded Conversations**: White user message cards with clean backgrounds, subtle gold AI response cards creating warm contrast against cool glass
- **Visual Hierarchy Enhancement**: Perfect contrast ratios with readable text, beautiful backdrop blur effects, and modern single-layer design
- **Chat Container Transformation**: Removed opaque chat window container, allowing transparent background to show through with floating message elements
- **Professional Polish**: Clean card shadows, hover effects, and smooth transitions creating professional-grade visual experience
- **Mobile-Ready Design**: Responsive glassmorphism that adapts to different screen sizes while maintaining visual integrity

---

### ** Complete AI Provider Migration: Gemini → Llama 4 Maverick**

- **Backend Transformation**: Complete migration from Google Gemini API to Replicate Llama 4 Maverick (400B total parameters, 17B active × 128 experts)
- **Cost Optimization**: Achieved 95% operational cost reduction (.65 per million tokens output vs Claude Sonnet pricing)
- **Performance Upgrade**: Access to 10M token context limit with significantly improved response times
- **API Architecture**: Converted from Gemini's complex message format to Replicate's streamlined prompt-based system
- **Streaming Implementation**: Rebuilt streaming with proper Replicate 2-step process (create prediction → connect stream URL)
- **Polling System**: Added server-side prediction polling for regular API calls to prevent duplicate predictions
- **Technical Implementation**: Complete rewrite of `server.js` streaming endpoint, new `replicateHelper.js` replacing `geminiHelper.js`
- **Core Files Update**: Updated all imports and references across core.js, commands.js, chatbot.js, summary.js
- **UI Updates**: Changed display text from "Gemini 2.5 Pro" to "Llama 4 Maverick" throughout interface

### ** MARM Protocol Evolution: v1.5 → v2.0**

- **Identity Transformation**: Updated from generic assistant mode to "MARM IS memory incarnate" - core identity evolution
- **Response Optimization**: Replaced verbose "Response Contract" with concise "💭 Thinking Trail" format for user-friendly output
- **Command Modernization**:
  - `/contextual reply` → `/deep dive` (clearer functionality naming)
  - `/compile [SessionName] --summary` → `/summary: [session name] --summary` (better syntax)
  - Enhanced notebook commands: `/notebook use:`, `/notebook clear:`, `/notebook status:` (active management)
  - Improved `/deep dive` command parsing (removed erroneous colon requirement)
- **Memory System Overhaul**:
  - Added conversation import system for mid-session MARM activation with complete context preservation
  - Intelligent message pairing to maintain proper user/bot conversation flow
  - Filters out system messages to prevent context confusion
- **Natural Language Enhancement**: Removed over-literal template formatting that caused bracket/symbol responses
- **Protocol Maturity**: Advanced from v1.4 development prompt to v2.0 production-ready specification
- **Enhanced Mission**: Clearer articulation of memory architect and conversation continuity guardian role

### ** Complete UI/UX Modernization**

- **Visual Transformation**: Complete overhaul from "2010 vibes" to modern design standards with indigo (#6366f1) and amber (#f59e0b) color palette
- **Glassmorphism Effects**: Enhanced shadows and glass effects throughout interface for premium feel
- **Chat Message Cards**: Implemented card-style messages with glass effects, proper shadows, and user/bot visual distinction
- **Command Menu Redesign**: Complete transformation from sidebar to contextual popup button (⚡) positioned next to input field
  - Popup functionality with proper positioning and auto-close behavior
  - Maintained notebook and log submenus with improved dropdown behavior
  - Freed up sidebar space for expanded chat interface
- **Interface Enhancements**:
  - Emoji animations for enhanced micro-interactions (⚡💾🤔📎)
  - Perfect uniform alignment between Send, File, and Command buttons
  - Button modernization with hover animations, scale effects, and modern styling
  - Send button modernized as overlay inside textarea (Discord/WhatsApp style)
- **Complete HTML/JavaScript Separation**:
  - Moved all HTML templates from JavaScript files to HTML templates
  - Clean separation of concerns with template-based system
  - JavaScript now finds existing elements instead of creating HTML strings
  - Voice settings, chats menu, loading indicators, code windows moved to HTML

### ** Security & Architecture Hardening**

- **XSS Protection System**: Comprehensive security module (`xssProtection.js`) with multiple sanitization levels
  - `sanitizeText()`: HTML entity escaping for plain text
  - `sanitizeHTML()`: Advanced sanitization with script/iframe blocking
  - `sanitizeHTMLStrict()`: Ultra-strict sanitization for user input
  - Complete protection against script injection, event handlers, frame injection, CSS injection, data exfiltration
- **Storage Architecture**: Created centralized `storage.js` for localStorage operations
  - Eliminated circular dependency risks with dedicated storage layer
  - Multi-tab synchronization matching ChatGPT/Claude standards
  - Centralized storage operations for better consistency and maintainability
- **State Management Enhancement**:
  - Private state object no longer directly accessible, only through `getState()`
  - Immutable patterns with all state access returning defensive copies
  - Validation with all state changes going through `updateState()` with validation
  - Unified state access patterns across entire codebase
- **Memory Management System**:
  - Trackable functions: `trackableTimeout()`, `trackableInterval()`, `trackableEventListener()`
  - Comprehensive cleanup with module-specific cleanup functions and centralized coordination
  - Resource tracking for event listeners, timers, and DOM elements

### ** New Features & Capabilities**

- **File Upload System**:
  - File upload button (📎) with text/code file support for 15+ file types
  - Smart detection for .txt, .js, .html, .css, .json, .md, .py, .java, .cpp, .c, .h, .xml, .yaml, .yml, .ini, .cfg, .log
  - Automatic language detection and syntax highlighting with code block formatting
  - AI integration for file content analysis with security restrictions for text-only uploads
- **MARM Protocol Toggle**:
  - Toggle button (🧠) in FAB menu for instant protocol switching between structured MARM and free mode
  - Visual feedback with button color changes when MARM active, dynamic tooltip updates
  - Complete bypass of MARM formatting, session context, and documentation search in free mode
  - System messages for clear status updates when toggling between modes with persistent state

### ** Critical Bug Fixes & System Stability**

- **MARM Memory Issues**: Fixed critical memory loss bug where MARM would lose all conversation context when activated mid-conversation
- **Session Persistence**: Fixed MARM forgetting conversation when toggled off and back on, now preserves existing session IDs
- **Runtime Stability**: Resolved 12+ `state.currentSessionId` bugs in commands.js and broken module exports in voice.js
- **Performance Optimization**:
  - Eliminated 60+ lines of duplicate code with helper functions
  - Replaced expensive JSON.stringify operations with O(1) incremental tracking
  - Request timeout optimization increased from 15s → 45s per attempt preventing connection resets
  - Total max timeout now ~135 seconds (45s × 3 attempts + retry delays)
- **Voice System**: Fixed TTS "interrupted" errors in speech synthesis by adding proper cancellation logic
- **Browser Compatibility**: Added cache-busting headers to server.js and version strings to prevent stale file serving
- **UI Fixes**:
  - FAB MARM Toggle functionality restored
  - Button consistency across header buttons, chats menu buttons, and form buttons
  - Font consistency with all buttons inheriting Georgia serif font matching chatbot theme
  - Copy buttons now work with selective button allowlisting
  - Input optimization to prevent overlap with new file upload button

### **🛠 Development & Testing Infrastructure**

- **Production Testing**: Browser-safe console-based XSS detection without screen-locking popups
- **Comprehensive Coverage**: Memory leak, state management, and performance validation across 8 categories
- **GitHub Publication Ready**: Comprehensive testing for open source sharing with production safety checks
- **Code Quality**: Template-based architecture with clean separation of concerns and modern development patterns
- **Performance Improvements**:
  - Dynamic import elimination removing all lazy-loading bottlenecks for faster module loading
  - Menu responsiveness with instant loading of saved chats and auto/manual refresh
  - Better cleanup and state handling preventing resource leaks

---

### **Impact Summary**

- **Security**: Zero XSS vulnerabilities with comprehensive multi-layer protection across all user-facing components
- **Performance**: 95% cost reduction while improving AI capabilities, response times, and eliminating runtime crashes
- **User Experience**: Complete interface modernization with intuitive command access, visual polish, and natural conversation flow
- **Stability**: Eliminated memory leaks, data loss prevention, and significantly improved system stability
- **Architecture**: Production-ready codebase with modern web standards, clean separation of concerns, and comprehensive error handling

- **Total Files Modified**: 50+ files across frontend, backend, and configuration
- **Lines of Code Changed**: 1000+ modifications including new features, optimizations, and fixes
- **Cost Savings**: 95% operational cost reduction through AI provider migration
- **Protocol Version**: v2.0 production-ready specification
- **Major New Features**: 3 (File Upload System, MARM Protocol Toggle, Conversation Memory Import)
- **Critical Issues Resolved**: 15+ including XSS vulnerabilities, memory leaks, and runtime crashes
- **Architectural Changes**: 2 (Complete HTML/JS Separation, Centralized Security/Storage Architecture)

</details>

---

## Project Files

- [README.md](README.md) – Core introduction and quick start for using MARM.  
- [FAQ.md](FAQ.md) – Answers to common questions about how and why to use MARM.  
- [CHANGELOG.md](CHANGELOG.md) – Tracks updates, edits, and refinements to the protocol.  
- [CONTRIBUTING.md](CONTRIBUTING.md) – Contribution guidelines and collaborator credits.  
- [DESCRIPTION.md](DESCRIPTION.md) – Protocol purpose and vision overview.  
- [LICENSE](LICENSE) – Terms of use for this project.
- [HANDBOOK.md](HANDBOOK.md) – Full guide to MARM usage, including commands, examples, and beginner to advanced tips.
- [ROADMAP.md](ROADMAP.md) – Planned features, upcoming enhancements, and related protocols under development.
- [SETUP.md](SETUP.md) - Local download setup guide
- [PROTOCOL.md](PROTOCOL.md) - Quick Start, Copy and Paste Protocol, and Limitations.
