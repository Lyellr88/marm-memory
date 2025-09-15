# MARM Local Setup Guide

[![Requirements](https://img.shields.io/badge/Requirements-Node.js%20v16%2B-blue?style=flat-square&logo=node.js&logoColor=white)](https://nodejs.org/)
[![AI Provider](https://img.shields.io/badge/AI%20Provider-Replicate%20(Meta%20Llama%204)-orange?style=flat-square&logo=meta&logoColor=white)](https://replicate.com/)

## **[Document]** Table of Contents

- [Quick Start Options](#quick-start-options)
- [Prerequisites](#prerequisites)
- [Installation Steps](#installation-steps)
- [About Llama 4 Maverick via Replicate](#about-llama-4-maverick-via-replicate)
- [Troubleshooting](#troubleshooting)
- [File Structure](#file-structure)
- [Development](#development)
- [Advanced: Using Different AI Models](#advanced-using-different-ai-models)
- [Support](#support)
- [Additional Features](#additional-features)
- [Next Steps](#next-steps)

## Quick Start Options

| Option | Setup Time | Requirements | Best For |
|--------|------------|--------------|----------|
| **[Demo] Online Demo** | 0 minutes | Web browser only | Quick testing, feature exploration |
| **[Local] Local Install** | 5 minutes | Node.js + API token | Development, customization, privacy |

**[Demo] Online Demo:** <https://marm-systems-chatbot.onrender.com>  
**[Local] Local Install:** Follow steps below for full control and customization

---

## Prerequisites

| Requirement | Installation | Verification |
|-------------|--------------|--------------|
| **Node.js v16+** | Windows: [nodejs.org](https://nodejs.org/) \| Mac: `brew install node` \| Linux: `sudo apt install nodejs npm` | `node --version` |
| **Git** | [git-scm.com](https://git-scm.com/) | `git --version` |
| **Replicate API** | [replicate.com/account/api-tokens](https://replicate.com/account/api-tokens) | Free $10 credit included |

---

## Installation Steps

### 1. Clone the Repository

```bash
git clone https://github.com/Lyellr88/MARM-Systems.git
cd MARM-Systems/webchat
```

### 2. Install Dependencies

```bash
npm install
```

### 3. Get Your Replicate API Token

**MARM is powered by Meta Llama 4 Maverick via Replicate**

1. **Visit:** <https://replicate.com/account/api-tokens>
2. **Create account**
3. **Generate a new API token**
4. **Copy the token**

#### **[Tip]** Pricing Information

- **Free tier:** $10 credit (thousands of conversations)
- **Cost:** ~$0.65 per million output tokens
- **Performance:** 95% cost reduction vs. premium providers
- **Model:** Llama 4 Maverick (400B params, 10M context)

### 4. Configure Environment

Create a `.env` file in the `webchat` directory:

```bash
# Create .env file
touch .env
```

Add your Replicate API token to `.env`:

```bash
# Add your Replicate API token
REPLICATE_API_TOKEN=your_replicate_api_token_here
```

### 5. Start the Server

```bash
npm start
```

### 6. Open in Browser

Visit: <http://localhost:8080>

---

## About Llama 4 Maverick via Replicate

### Why This Stack?

MARM uses Meta's Llama 4 Maverick through Replicate because:

- **[Feature] Advanced reasoning:** 400B parameter multimodal model
- **[Quick] Fast responses:** 3-4 second response times with streaming
- **[Feature] Cost efficient:** 95% cheaper than premium AI providers
- **[Security] Reliable:** Enterprise-grade Replicate infrastructure
- **[Target] MARM optimized:** Perfect for memory-accurate conversations

---

## Troubleshooting

| Problem | Solution | Commands |
|---------|----------|----------|
| **Module not found errors** | Reinstall dependencies | `rm -rf node_modules package-lock.json` → `npm install` |
| **API token not found** | Check .env file in webchat directory, restart server | Verify `REPLICATE_API_TOKEN=your_token` → `npm start` |
| **Port already in use** | Kill process or use different port | `lsof -ti:8080 \| xargs kill -9` or `PORT=3000 npm start` |
| **CORS errors** | Server configured for localhost only | For production, additional CORS configuration needed |

---

## File Structure

```txt
MARM-Systems/
├── webchat/
│   ├── src/
│   │   ├── chatbot/          # Core chatbot logic & server
│   │   │   ├── server.js     # Express server with Replicate integration
│   │   │   ├── replicateHelper.js # Llama 4 Maverick API integration
│   │   │   └── ...           # Other core modules
│   │   ├── logic/            # MARM v2.0 protocol logic
│   │   └── style/            # Modular CSS components
│   ├── package.json          # Dependencies
│   ├── .env                  # Your Replicate API token (create this)
│   └── index.html            # Main interface
├── GitHub docs/              # Documentation
└── README.md                 # Project overview
```

---

## Advanced: Using Different AI Models

### **[Launch]** Universal LLM Support

**MARM's secret superpower:** Your Replicate API token gives you access to **1000+ AI models**, not just Llama 4 Maverick!

### How to Switch Models

1. **Find a model** on [Replicate.com](https://replicate.com/explore)
2. **Copy the model path** (e.g., `meta/llama-3.1-405b-instruct`)
3. **Edit one line** in `webchat/src/chatbot/server.js`:

```javascript
// Line 48 - Change this URL to any Replicate model:
const url = 'https://api.replicate.com/v1/models/YOUR-CHOSEN-MODEL/predictions';
```

4. **Restart server:** `npm start`

### Popular Model Options

| Model | Strengths | Cost | Speed |
|-------|-----------|------|-------|
| `meta/llama-4-maverick-instruct` | Industry-leading intelligence, 400B total params, multimodal (current) | Very Low | Medium |
| `meta/llama-3-8b-instruct` | Massive context, complex analysis | Low | Medium |
| `anthropic/claude-4-sonnet` | Superior coding assistant, precise reasoning | Medium | Fast |
| `deepseek-ai/deepseek-r1` | Advanced reasoning, RL-trained, o1-competitive | Low | Very Fast |
| `openai/gpt-5` | Creative writing, broad knowledge, latest training | Medium/Low | Fast |

**Bottom Line:** MARM is a universal AI interface - one setup, access to 1000+ models on Replicate.

### Model-Specific Optimization

Some models perform better with different settings. Edit these in `src/replicateHelper.js`:

```javascript
function createRequestBody(prompt) {
  return {
    prompt: prompt,
    temperature: 0.7,    // 0.1-1.0 (lower = more focused)
    max_tokens: 8192,    // Adjust based on model limits
    top_p: 0.9          // 0.1-1.0 (controls diversity)
  };
}
```

**Benefits:** Specialized models for different tasks, cost control, speed optimization, and privacy through secure MARM interface.

---

## Support

- **Issues:** <https://github.com/Lyellr88/MARM-Systems/issues>
- **Documentation:** See `GitHub docs/` folder
- **Live Demo:** <https://marm-systems-chatbot.onrender.com>

---

## License

This project is licensed under the MIT License - see the [LICENSE](https://github.com/Lyellr88/MARM-Systems/blob/main/LICENSE) file for details.

---

## Features & Development

| Category | Features |
|----------|----------|
| **File Upload** | Text/code files with syntax highlighting, AI analysis |
| **MARM Protocol** | Toggle structured/free conversation mode, persistent state |
| **Voice Features** | Text-to-speech, configurable settings, interrupt/resume |
| **Session Management** | Save/load conversations, persistent memory, context preservation |
| **Development** | Hot reload, modular ES6 architecture, XSS protection, fast responses |

---

## Next Steps

After local installation:

1. **Try MARM commands:** `/start marm`, `/deep dive`, `/notebook`
2. **Upload files:** Test the file analysis feature
3. **Explore features:** Voice synthesis, session saving, dark mode
4. **Read documentation:** [HANDBOOK.md](HANDBOOK.md) for full command reference
5. **Join community:** Star the repo and share feedback!

---

## 📁 Project Documentation

### **Usage Guides**

- **[MARM-HANDBOOK.md](https://github.com/Lyellr88/MARM-Systems/blob/MARM-main/MARM-HANDBOOK.md)** - Original MARM protocol handbook for chatbot usage
- **[MCP-HANDBOOK.md](https://github.com/Lyellr88/MARM-Systems/blob/MARM-main/MCP-HANDBOOK.md)** - Complete MCP server usage guide with commands, workflows, and examples
- **[PROTOCOL.md](https://github.com/Lyellr88/MARM-Systems/blob/MARM-main/PROTOCOL.md)** - Quick start commands and protocol reference
- **[FAQ.md](https://github.com/Lyellr88/MARM-Systems/blob/MARM-main/docs/FAQ.md)** - Answers to common questions about using MARM

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
- **[DESCRIPTION.md](https://github.com/Lyellr88/MARM-Systems/blob/MARM-main/docs/DESCRIPTION.md)** - Protocol purpose and vision overview
- **[CHANGELOG.md](https://github.com/Lyellr88/MARM-Systems/blob/MARM-main/docs/CHANGELOG.md)** - Version history and updates
- **[ROADMAP.md](https://github.com/Lyellr88/MARM-Systems/blob/MARM-main/docs/ROADMAP.md)** - Planned features and development roadmap
- **[LICENSE](https://github.com/Lyellr88/MARM-Systems/blob/MARM-main/docs/LICENSE)** - MIT license terms
