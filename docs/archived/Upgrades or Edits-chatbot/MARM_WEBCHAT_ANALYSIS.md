# MARM Webchat Folder Analysis
## Phase 1: Backend Logic Documentation

## 📁 Folder Structure Overview
```
webchat/
├── src/
│   ├── chatbot/
│   │   ├── chatbot.js        # Main entry point and initialization
│   │   ├── core.js           # Core orchestration and state management
│   │   ├── commands.js       # Command handling and specific command logic
│   │   ├── sessionUI.js      # Session UI management
│   │   ├── ui.js             # General UI functions
│   │   ├── voice.js          # Voice synthesis functionality
│   │   └── state.js          # Application state management
│   ├── logic/
│   │   ├── marmLogic.js      # Core MARM protocol logic
│   │   ├── session.js        # Session management
│   │   ├── storage.js        # Storage and persistence
│   │   ├── notebook.js       # Notebook management
│   │   ├── docs.js           # Documentation loading/search
│   │   ├── constants.js      # Configuration constants
│   │   ├── utils.js          # Utility functions
│   │   ├── summary.js        # Session summary compilation
│   │   └── formatting.js     # Text formatting utilities
│   ├── security/
│   │   └── xssProtection.js  # XSS sanitization functions
│   └── replicateHelper.js    # Replicate API integration
├── data/                     # Documentation files
├── style/                    # CSS styling
└── tests/                    # Test files
```

## 🧠 Core Chatbot Logic

### Main Entry Point (chatbot.js)
- **Initialization**: Sets up all components on DOMContentLoad
- **Event Handling**: Manages form submission, keyboard shortcuts, UI interactions
- **Component Integration**: Connects all modules (core, UI, voice, commands, session)

### Core Orchestration (core.js)
- **Rate Limiting**: 1-second cooldown between messages
- **Message Processing Pipeline**:
  1. Input validation (length, type)
  2. Command detection (/ prefix)
  3. Standard message routing
  4. Error handling with retries
- **MARM Integration**: Context injection when active
- **Response Handling**: Proper error handling and user feedback

### State Management (state.js)
- **Application State**: Tracks session, MARM mode, UI preferences
- **Persistence**: localStorage integration for session continuity
- **Validation**: Ensures state integrity

## 🎯 Message Processing Logic

### Input Handling
- **Validation**: String type, 15k character limit, non-empty
- **Rate Limiting**: 1-second cooldown enforcement
- **Command Routing**: / prefix detection and command dispatch
- **Standard Messages**: Direct processing through AI pipeline

### Context Injection (When MARM Active)
1. **Session History**: `getSessionContext()` with trimming
2. **Notebook Data**: `manageUserNotebook()` for personal knowledge
3. **Documentation**: `searchDocs()` for protocol references
4. **System Instructions**: MARM protocol guidelines

### Response Generation Flow
1. **Retry Logic**: 2 attempts with fallback prompts
2. **Error Handling**: Null/undefined response detection
3. **Safety Filter Detection**: "I can't help with that" pattern matching
4. **Content Formatting**: Markdown processing and cleaning

## 📚 Memory/Context Logic

### Session Management
- **Session Creation**: Named containers for conversation organization
- **History Tracking**: Message pairs (user/bot) with timestamps
- **Context Trimming**: Automatic size management to prevent overflow

### Notebook System
- **Entry Management**: Add, use, show, delete, clear, status
- **Personal Knowledge**: User-defined facts treated as absolute truth
- **Activation**: Multiple entries can be active simultaneously

### Documentation Integration
- **Pre-loading**: All markdown files loaded at startup
- **Semantic Search**: Keyword-based documentation lookup
- **Protocol Enforcement**: Core MARM documentation always available

## 🔄 State Transition Logic

### MARM Protocol States
- **Inactive**: Standard chat mode
- **Active**: Memory-aware mode with context injection
- **Session-Based**: Independent session containers

### Command-Driven Transitions
- `/start marm` - Activate protocol
- `/refresh marm` - Reaffirm protocol adherence
- `/log session:` - Create/switch session containers
- `/log entry:` - Add structured log entries

## 🔧 API Integration Logic

### Replicate API Integration (replicateHelper.js)
- **Model Endpoint**: Meta Llama 4 Maverick
- **Request Formatting**: Proper prompt construction with system instructions
- **Streaming Support**: Real-time response delivery
- **Error Handling**: Timeout, network, and API error management
- **Retry Logic**: Exponential backoff with jitter

### Event System Integration
- **Custom Events**: `events.emit()` for automation triggers
- **Event Handlers**: Registered callbacks for system actions
- **Lifecycle Events**: start, refresh, log, notebook operations

## 🔄 Data Flow Patterns

### Request Flow
```
User Input → Input Validation → Command Detection →
Context Injection (if MARM) → AI Processing →
Response Validation → UI Display → Session Storage
```

### Context Flow (MARM Active)
```
Session History → Notebook Entries → Documentation →
System Instructions → User Message → AI Processing
```

### Event Flow
```
User Action → Event Emission → Handler Execution →
State Update → UI Refresh → Storage Persistence
```

## 📋 Business Logic Rules

### Command Processing Rules
- Commands must start with /
- Specific command syntax enforced
- Context-aware responses based on current state
- Proper error messages for invalid usage

### MARM Protocol Rules
- Session context always injected when active
- Notebook entries treated as absolute truth
- Documentation search for protocol queries
- Structured logging with date-topic-summary format

### Memory Management Rules
- Session-based isolation
- Automatic history trimming
- Size limits and pruning thresholds
- Persistence across browser sessions

## 🎯 Key Features Implementation

### 1. MARM Protocol (/start marm, /refresh marm)
- Protocol activation with context loading
- Session state management
- Protocol documentation injection

### 2. Logging System (/log session:, /log entry:, /log show:, /log delete:)
- Structured session management
- Date-topic-summary entry format
- History display and deletion

### 3. Reasoning Tools (/summary:, /context_bridge:, /deep dive)
- Session summarization
- Context bridging for workflow transitions
- Enhanced accuracy mode with reasoning

### 4. Notebook System (/notebook add:, /notebook use:, etc.)
- Personal knowledge library
- Entry activation as instructions
- Management commands (show, delete, clear, status)

### 5. Voice Synthesis
- Text-to-speech for bot responses
- Speed and pitch controls
- Speaking state management

## 🔒 Security Features

### XSS Protection
- HTML sanitization for all user inputs
- Dangerous tag removal
- Attribute filtering
- Content escaping

### Input Validation
- Length limits
- Type checking
- Format validation
- Error handling

## 📊 System Architecture Patterns

### Modular Design
- Clear separation of concerns
- Component-based architecture
- Reusable utility functions
- Event-driven communication

### Error Handling
- Try/catch blocks throughout
- User-friendly error messages
- Graceful degradation
- Logging for debugging

### Performance Optimization
- Lazy loading where appropriate
- Efficient database queries
- Memory management
- Caching strategies

This analysis captures the essential backend logic, data flows and architectural patterns of the webchat folder that need to be preserved when migrating to the new UI.
