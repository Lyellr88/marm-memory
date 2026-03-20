# MARM Local Setup Guide

[![Requirements](https://img.shields.io/badge/Requirements-Node.js%20v16%2B-blue?style=flat-square&logo=node.js&logoColor=white)](https://nodejs.org/)
[![AI Provider](https://img.shields.io/badge/AI%20Provider-Replicate%20(Meta%20Llama%204)-orange?style=flat-square&logo=meta&logoColor=white)](https://replicate.com/)

## 📚 Table of Contents

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

### Option 1: Try Online (Recommended)

Visit: <https://marm-systems-chatbot.onrender.com>

- No setup required
- Full MARM v2.0 protocol support
- Voice synthesis, dark mode, file uploads
- Mobile responsive design

### Option 2: Local Installation

Follow this guide to run MARM locally with your own Replicate API access.

---

## Prerequisites

- **Node.js** (v16 or higher)
- **Git** (for cloning)
- **Replicate API Token** (free tier available)

### Install Node.js

```bash
# Windows: Download from https://nodejs.org/
# macOS: 
brew install node

# Linux:
sudo apt update
sudo apt install nodejs npm
```

### Verify Installation

```bash
node --version
npm --version
```

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

#### 💡 Pricing Information

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

- **🆓 Generous free tier:** $10 credit (thousands of conversations)
- **🧠 Advanced reasoning:** 400B parameter multimodal model
- **⚡ Fast responses:** 3-4 second response times with streaming
- **💰 Cost efficient:** 95% cheaper than premium AI providers
- **🔒 Reliable:** Enterprise-grade Replicate infrastructure
- **🎯 MARM optimized:** Perfect for memory-accurate conversations

---

## Troubleshooting

### Common Issues

#### "Module not found" errors

```bash
# Reinstall dependencies
rm -rf node_modules package-lock.json
npm install
```

#### "API token not found" errors

1. Check your `.env` file exists in `webchat` directory
2. Verify `REPLICATE_API_TOKEN` is set correctly
3. Restart the server with `npm start`

#### "Port already in use" errors

```bash
# Kill process on port 8080
lsof -ti:8080 | xargs kill -9

# Or use different port
PORT=3000 npm start
```

#### "CORS errors" (if accessing from different domain)

The server is configured for localhost only. For production deployment, additional CORS configuration is needed.

---

## File Structure

```
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

## Development

### Making Changes

1. Edit files in `webchat/src/`
2. Server auto-restarts on changes
3. Refresh browser to see updates

### Development Features

- **Hot reload:** Server auto-restarts on file changes
- **Modular architecture:** Clean ES6 module separation
- **Security:** XSS protection and input sanitization
- **Performance:** Optimized for fast response times
- **MARM Protocol:** Full v2.0 specification support

---

## Advanced: Using Different AI Models

### 🚀 Universal LLM Support

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

**Choose based on your needs:**

- **Llama 4 Maverick**: Industry-leading multimodal model with 400B total params, groundbreaking intelligence at low cost ($0.25 input + $0.95 output)
- **Llama 3 8B**: Fast, efficient model for general conversations with massive context windows
- **Claude 4 Sonnet**: Premium coding assistant with exceptional reasoning and writing capabilities
- **DeepSeek R1**: Advanced reasoning model trained with reinforcement learning, competitive with OpenAI o1 for complex problem-solving
- **GPT-5**: Latest OpenAI model excelling at creative writing and comprehensive analysis

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

### Why This Matters

- **🎯 Specialized Models:** Use Code Llama for programming, Mistral for logic, etc.
- **💰 Cost Control:** Choose cheaper models for simple tasks
- **⚡ Speed Options:** Fast models for real-time chat, powerful models for deep analysis
- **🔬 Experimentation:** Test cutting-edge models as they're released
- **🛡️ Privacy:** All models run through same secure MARM interface

**Bottom Line:** MARM is a universal AI interface. One setup, endless possibilities.

---

## Support

- **Issues:** <https://github.com/Lyellr88/MARM-Systems/issues>
- **Documentation:** See `GitHub docs/` folder
- **Live Demo:** <https://marm-systems-chatbot.onrender.com>

---

## License

This project is licensed under the MIT License - see the [LICENSE](https://github.com/Lyellr88/MARM-Systems/blob/main/LICENSE) file for details.

---

## Additional Features

### File Upload System

- Upload text/code files (`.txt`, `.js`, `.html`, `.css`, `.json`, `.md`, `.py`, etc.)
- Automatic syntax highlighting and language detection
- AI analysis of uploaded file contents

### MARM Protocol Toggle

- Switch between MARM structured mode and free conversation
- Toggle button in floating action button (FAB) menu
- Maintains protocol state across sessions

### Voice Features

- Text-to-speech for bot responses
- Configurable voice settings
- Interrupt and resume capabilities

### Session Management

- Save and load conversation sessions
- Persistent memory across browser sessions
- Session isolation and context preservation

---

## Next Steps

After local installation:

1. **Try MARM commands:** `/start marm`, `/deep dive`, `/notebook`
2. **Upload files:** Test the file analysis feature
3. **Explore features:** Voice synthesis, session saving, dark mode
4. **Read documentation:** [HANDBOOK.md](HANDBOOK.md) for full command reference
5. **Join community:** Star the repo and share feedback!

---

### Related Documentation

- [README.md](README.md) – Project overview and quick start
- [HANDBOOK.md](HANDBOOK.md) – Complete MARM protocol guide
- [CHANGELOG.md](CHANGELOG.md) – Version history and updates
- [ROADMAP.md](ROADMAP.md) – Future development plans
- [CONTRIBUTING.md](CONTRIBUTING.md) – How to contribute
