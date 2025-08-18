# MARM v2.0 - Memory Accurate Response Mode

**Production-ready AI chatbot with persistent memory, modern glassmorphism UI, and professional testing infrastructure.**

*Memory Accurate Response Mode v2.0* - Build smarter AI conversations with structured memory and transparent logic.

## 🚀 Quick Start

### Local Development

```bash
cd webchat
npm install
npm start
```

Open `http://localhost:8080` - the modern glassmorphism interface will load with floating message cards.

### Testing

```bash
npm test        # Run 74 comprehensive tests
npm run lint    # Code quality checks
```

---

## ✨ What's New in v2.0

### 🧠 **LLaMA 4 Maverick Integration**

- **Complete migration** from Google Gemini to Replicate LLaMA 4 (400B parameters)
- **95% cost reduction** while improving response quality and speed
- **10M token context limit** for extensive conversation histories
- **Advanced streaming** with real-time response delivery

### 🎨 **Modern Glassmorphism UI**

- **Floating message cards** on transparent glass background
- **Color-coded conversations** - White user cards, gold AI responses
- **2025 aesthetic** - Single-layer design, no nested windows
- **Perfect contrast** - Readable text with beautiful visual hierarchy

### 🧪 **Professional Testing Infrastructure**

- **74 comprehensive tests** covering Voice, UI, State, Commands, and Security
- **GitHub Actions CI/CD** with automated testing on push/PR
- **42% test coverage** with browser API mocking and edge case validation
- **Jest configuration** supporting ES modules and modern JavaScript

### 🔐 **Enterprise Security**

- **XSS protection** with comprehensive input sanitization
- **Content security** smart filtering preserving functionality
- **Session isolation** with proper data validation
- **File upload security** supporting 15+ file types with syntax highlighting

---

## 📁 Project Architecture

```text
webchat/
├── src/
│   ├── replicateHelper.js    # LLaMA 4 Maverick API integration
│   ├── chatbot/
│   │   ├── server.js         # Express proxy server for API calls
│   │   ├── chatbot.js        # Main entry point and orchestration
│   │   ├── commands.js       # Command handling (/start marm, /deep dive, /notebook, etc.)
│   │   ├── core.js           # Input validation and main chat loop
│   │   ├── state.js          # Centralized state management
│   │   ├── ui.js             # Modern glassmorphism UI rendering and interactions
│   │   ├── voice.js          # Text-to-speech with Google Voice integration
│   │   └── sessionUI.js      # Session management interface
│   ├── logic/
│   │   ├── constants.js      # MARM protocol constants and configuration
│   │   ├── docs.js           # Documentation loading and help system
│   │   ├── marmLogic.js      # Core MARM v2.0 protocol implementation
│   │   ├── notebook.js       # User notebook with key-value storage
│   │   ├── session.js        # Session persistence and context management
│   │   ├── storage.js        # LocalStorage operations with validation
│   │   ├── summary.js        # Session compilation and memory synthesis
│   │   └── utils.js          # Validation, debounce, and utility functions
│   └── security/
│       └── xssProtection.js  # Comprehensive security filtering
├── style/
│   ├── animations.css        # Bouncing dots, hover effects, transitions
│   ├── base.css              # Core glassmorphism styling and CSS variables
│   ├── chat.css              # Floating message cards and conversation styling
│   ├── command-menu.css      # Modern command popup interface
│   ├── components.css        # Reusable UI components (buttons, modals, forms)
│   └── main.css              # Main stylesheet coordination
├── tests/                    # Professional test suite
│   ├── chatbot.test.js       # Voice and Commands module tests (29 tests)
│   ├── logic.test.js         # Session and State management tests (30 tests)
│   └── security_replicate_html.test.js  # Security and UI tests (15 tests)
├── data/                     # Documentation and help content
│   ├── chatbotreadme.md      # This file
│   ├── description.md        # Protocol overview and features
│   ├── faq.md                # Frequently asked questions
│   ├── handbook.md           # Complete user guide and command reference
│   └── roadmap.md            # Development roadmap and future features
└── index.html                # Main MARM v2.0 web application
```

---

## 🎯 Core Features

### **Memory System**

- **Session Context & Recall** - Structured memory that builds across conversations
- **Folder-style organization** with named sessions (`/log session: [name]`)
- **Manual knowledge library** via notebook commands (`/notebook add: [key] [data]`)
- **Context preservation** - Mid-session MARM activation imports existing conversation

### **Advanced Commands**

- `/start marm` - Activate structured memory mode
- `/deep dive: [topic]` - Detailed analysis with reasoning transparency
- `/notebook add: [key] [data]` - Store persistent user information
- `/log entry: [YYYY-MM-DD-topic-summary]` - Create organized memory entries
- `/summary: [session]` - Generate transferable session summaries

### **Modern Interface**

- **File upload support** (📎) - Analyze 15+ file types with syntax highlighting
- **MARM toggle** (🤖) - Switch between structured and free conversation modes
- **Voice synthesis** (🔊) - Text-to-speech for all AI responses
- **Command menu** - Contextual popup interface next to input field
- **Glassmorphism design** - Floating cards on transparent glass background

---

## 🧪 Testing & Quality

### **Comprehensive Test Coverage**

```bash
npm test                    # Run all 74 tests
npm test -- --coverage     # Generate coverage report (42% coverage)
npm test -- --watch        # Watch mode for development
```

### **CI/CD Pipeline**

- **GitHub Actions** automated testing on every push/PR
- **Multi-environment testing** (Node.js 18.x & 20.x)
- **Test status badge** visible on repository homepage
- **Coverage reports** with detailed line-by-line analysis

### **Code Quality**

- **ES module architecture** with proper imports/exports
- **Browser API mocking** for comprehensive testing
- **Security validation** with XSS protection testing
- **Error handling** with comprehensive edge case coverage

---

## 📚 Documentation

- **[User Handbook](handbook.md)** - Complete guide to MARM commands and features
- **[FAQ](faq.md)** - Common questions and troubleshooting
- **[Protocol Description](description.md)** - Technical overview and architecture
- **[Development Roadmap](roadmap.md)** - Future features and enhancement plans

---

## 🔧 Development

### **Requirements**

- Node.js 18+
- Modern browser with ES module support
- 15MB disk space for dependencies

### **Environment Variables**

```bash
REPLICATE_API_TOKEN=your_token_here    # Required for LLaMA 4 integration
NODE_ENV=development                   # Optional: enables debug logging
```

### **Development Workflow**

1. `npm install` - Install dependencies
2. `npm start` - Start development server (port 8080)
3. `npm test` - Run test suite before commits
4. Edit files - Hot reload enabled for CSS/JS changes

---

## 📄 License

MIT License - See [LICENSE](../LICENSE) for details.

---

**MARM v2.0** - Where AI conversations become lasting memories. 🧠✨
