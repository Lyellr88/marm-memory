<div align="center">
<picture>
  <img src="https://github.com/Lyellr88/MARM-Systems/blob/MARM-main/media/marm-main.jpg"
       alt="MARM - The AI That Remembers Your Conversations"
       width="700"
       height="350"
</picture>
<h1 align="center">MARM: The AI That Remembers Your Conversations</h1> 

Memory Accurate Response Mode v2.0 - The memory protocol for AI. Stop losing context. Stop hallucinations. Start controlling your conversations.  
  
![Stars](https://img.shields.io/github/stars/Lyellr88/MARM-Protocol?style=flat-square) ![Forks](https://img.shields.io/github/forks/Lyellr88/MARM-Protocol?style=flat-square) ![Tests](https://img.shields.io/badge/tests-74%20passing-brightgreen?style=flat-square) [![License](https://img.shields.io/badge/license-MIT-blue?style=flat-square)](https://github.com/Lyellr88/MARM-Systems/blob/MARM-main/LICENSE) ![Version](https://img.shields.io/badge/version-2.0-blue?style=flat-square)

[![Unlock Full Session Memory](https://img.shields.io/badge/Try_MARM-Live_Demo-FF6B6B?style=for-the-badge&logo=rocket&logoColor=white)](https://marm-systems-chatbot.onrender.com)
  
[![Official MARM](https://img.shields.io/badge/Official-MARM-blue?style=for-the-badge)](https://github.com/Lyellr88/MARM-Systems)

**Note:** This is the *official* MARM repository. All official versions and releases are managed here.

Forks may experiment, but official updates will always come from this repo.

</div>

---

## Overview

MARM is a protocol for AI reliability. It gives you control over memory and logic by letting you log sessions, store your own notes, and compile summaries. The result: fewer hallucinations, transparent reasoning, and conversations that stay on track.  

**Steer the AI instead of chasing it.**  

> For copy-and-paste protocol  users and full technical details, see [`PROTOCOL.md`](./PROTOCOL.md)

<div align="center">
<picture>
    <img src="https://github.com/Lyellr88/MARM-Systems/blob/MARM-main/media/google-overview.PNG"
         alt="MARM - The AI That Remembers Your Conversations"
         width="700"
         height="350"
</picture>
</div>
<p align="center">*Appears in Google AI Overview for AI memory protocol queries (as of Aug 2025)*

---

## Why I Built MARM  

MARM started with my own frustrations: AI losing context, repeating itself, and drifting off track. But I didn’t stop there. I asked a simple question in a few AI subreddits:  
*“What’s the one thing you wish your LLM could do better?”*  

The replies echoed the same pain points:  
- Keep memory accurate  
- Give users more control  
- Be transparent, not a black box  

That feedback confirmed the gap I already saw. I took those shared frustrations, found the middle ground, and built MARM. Early contributors validated the idea and shaped features, but the core system grew out of both personal trial and community insight.  

MARM is the result of combining individual persistence with collective needs, a protocol designed to solve what we all kept running into.  

**Discord**

Join Discord for upcoming features and builds, plus a safe space to share your work and get constructive feedback.

[MARM Discord](https://discord.gg/EuBsHvSRks)

---

## Before MARM vs After MARM

**Without MARM:**

- "Wait, what were we discussing about the database schema?"
- AI repeats previous suggestions you already rejected
- Loses track of project requirements mid-conversation
- Starts from scratch every time you return

**With MARM:**

- AI references your logged project notes and decisions
- Maintains context across multiple sessions  
- Builds on previous discussions instead of starting over
- Remembers what works and what doesn't for your project

---

## Why Use MARM?

Modern LLMs often lose context or fabricate information. MARM introduces a session memory kernel, structured logs, and a user-controlled knowledge library. Anchoring the AI to *your* logic and data. It’s more than a chatbot wrapper. It’s a methodology for accountable AI.

### Read Before You Start

- Start MARM in a **new session** for best results  
- MARM **does not persist** across threads  
- To resume long sessions, use `/summary:` and reseed manually  
- Commands are **manual by design** to ensure transparency and user control  

---

## Install Locally

<details> 
<Summary>Click here for local Chatbot install</Summary>
<br>

Run MARM on your own machine using Replicate API (Claude Sonnet 3.7). Great for developers, power users, or those who want full control.  

### Requirements

- Node.js v16+
- Git
- Replicate API Key (free or paid)

**Install Node.js first (if not installed):**

```bash
# Windows/Mac: Download from https://nodejs.org/
# Linux: sudo apt install nodejs npm
node --version  # Should show v16+
```

### 1. Clone the Repository

```bash
git clone https://github.com/Lyellr88/MARM-Systems.git
cd MARM-Systems/webchat
```

### 2. Install Dependencies

```bash
npm install
```

### 3. Add API Key

Create a `.env` file and add your Replicate key:

```bash
touch .env
echo "REPLICATE_API_TOKEN=your_token_here" >> .env
```

### 4. Start the App

```bash
npm start
```

### 5. Go to Website

```bash
http://localhost:8080
```

### Need detailed steps, troubleshooting, or multi-provider setup?

See [`SETUP.md`](./SETUP.md) for complete installation guide with Node.js setup and troubleshooting.

</details>

---

## Built For Research + Real Use

MARM is both a power-user tool and a research scaffold:

### AI Safety & Reasoning Research

- Study systematic reasoning in language models  
- Analyze memory persistence across sessions  
- Measure hallucination reduction with structured prompts  

### Business Intelligence

- Maintain context across long analytical threads  
- Build organizational knowledge into sessions  
- Reinforce consistent decision-making frameworks  

### Educational & Training Use

- Teach critical thinking via structured interaction  
- Build personalized learning repositories  
- Guide model reasoning with user-curated facts  

### Not built for

Small talk • Throwaway chats • Passive use  

---

## Key Features & Command Overview

### Key Features

- **Session memory kernel** – Tracks user intent and prompts clarification  
- **Structured logs** – Use `/log` and `/summary:` to build summaries  
- **Personal library** – Use `/notebook` to guide model outputs with your notes  
- **Accuracy guardrails** – Optional logic checks to reduce false outputs

### Command Overview

Session Commands

- `/start marm` → Activate protocol  
- `/refresh marm` → Reaffirm/reset context  

Core Commands

- `/log` → Start structured session logging  
- `/notebook` → Store key data  
- `/summary:` → Summarize and reseed sessions  

Advanced Tools

- `/deep dive` → Request context-aware response  
- `/show reasoning` → Reveal logic trail of last answer  

#### Quick Start (for copy and paste protocol)

```text
/start marm  
/log entry: [YYYY-MM-DD - topic - summary]  
/summary: SessionName
```

Need a walkthrough or troubleshooting help? The [`HANDBOOK.md`](./HANDBOOK.md) covers all aspects of using MARM.

---


<div align="center">
  <h3>🚀 Try MARM Chatbot Now - No Setup Required</h3>
  <a href="https://marm-systems-chatbot.onrender.com">
    <img src="https://img.shields.io/badge/Launch_Live_Demo-MARM_Chatbot-FF6B6B?style=for-the-badge&logo=rocket&logoColor=white" width="300">
  </a>
  <p><i>Experience all features instantly in your browser</i></p>
</div>

<div align="center">
<picture>
  <img src="https://github.com/Lyellr88/MARM-Systems/blob/MARM-main/media/chatbot-dark.png"
       width="700"
       height="350">
</picture>
</div>
  
### User Experience (Chatbot)

- **Browser optimized** - Professional web interface (browser only)  
- **Modern card-style chat** - Glass effects with indigo/amber color palette  
- **File upload system** - Upload and analyze text/code files with syntax highlighting  
- **MARM protocol toggle** - Switch between structured MARM mode and free conversation  
- **Command menu redesign** - Contextual popup menu next to input with glassmorphism effects    
- **Save and revisit chat sessions** - Name and organize your conversations with session persistence  
- **Enhanced notebook system** - Store user knowledge with add/use/clear/status commands  
- **Voice synthesis** - Listen to MARM responses (Chrome/Edge recommended)    
- **XSS protection** - Professional -level security with comprehensive input sanitization  
- **No setup required** - Just open and start chatting    
- **Professional error handling** - Clear feedback with improved timeout handling  

---

## Join the MARM Community

**Help build the future of AI memory - no coding required!**

[MARM Discord](https://discord.gg/deYpMSRP)

### Easy Ways to Get Involved

- **Try the demo** and share your experience
- **Star the repo** if MARM solves a problem for you
- **Share on social** - help others discover memory-enhanced AI
- **Open issues** with bugs, feature requests, or use cases
- **Join discussions** about AI reliability and memory

### For Developers

- **Build integrations** - MCP, browser extensions, API wrappers
- **Improve the protocol** - enhance memory systems
- **Add new platforms** - expand beyond web chat

### Growing Community

- **Active discussions** on Reddit and Discord
- **Real users** solving daily AI frustration

---

## Feedback & Community Mentions

MARM Systems is the official upstream source for all MARM-based tools.
Community forks and experiments (e.g., MARMalade, OAuth Wrappers) demonstrate the strength and adaptability of the protocol.

We welcome experimentation, these projects increase visibility and test new ideas.
For stable releases, full protocol governance, and long-term roadmap support, refer to this repository as the source of truth.

MARM is actively being tested and adopted across platforms.

- Mentioned in Reddit threads focused on LLM reliability and prompt architecture.
- Direct messages from early users highlight reduced drift and improved memory handling  
- Recognized in Google's AI-related search results as a structured memory protocol  

**Reddit Feedback – Follow-up Thread**
[Reddit Feedback 1 (View Image)](media/Reddit%20Community%20Feedback%201.jpg)

**Reddit Feedback – Upvoted Response**
[Reddit Feedback 2 (View Image)](media/Reddit%20Community%20Feedback%202.jpg)

*Additional feedback and screenshots will be added as adoption grows.*

---

<div align="center">
  
  [![Star History Chart](https://api.star-history.com/svg?repos=Lyellr88/MARM-Systems&type=Date)](https://star-history.com/#Lyellr88/MARM-Systems&Date)
</div>

---

### License & Usage Notice

This project is licensed under the MIT License. Forks and derivative works are permitted.  
However, use of the **MARM name** and **version numbering** is reserved for releases from the  
[official MARM repository](https://github.com/Lyellr88/MARM-Systems). Derivatives should clearly  
indicate they are unofficial or experimental.

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
- [SETUP.md](SETUP.md) - Local download setup guide.
- [PROTOCOL.md](PROTOCOL.md) - Quick Start, Copy and Paste Protocol, and Limitations.
