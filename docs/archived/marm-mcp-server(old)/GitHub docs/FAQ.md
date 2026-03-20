
# FAQ

## 🎯 Quick Start

**Q: How do I start using MARM?**  
Use `/start marm` as your first command, then `/log session: [name]` to organize your work.

**Q: Key commands?**  
`/deep dive` (accuracy), `/summary: [session]` (recap), `/notebook add:` (memory), `/show reasoning` (transparency).

**Q: When to log?**  
Use `/log entry: [YYYY-MM-DD-topic-summary]` for milestones, decisions, or breakthroughs.

**Q: Session getting generic?**  
Run `/refresh marm` → `/summary:` → `/deep dive` → reseed if needed.

**Q: How to resume work?**  
Use `/summary: [session]` to generate reseed block, paste in new chat with `/start marm`.

**Q: Live chatbot?**  
Available at [marm-systems-chatbot.onrender.com](https://marm-systems-chatbot.onrender.com) - no setup required.

**Q: What's new in v2.0?**  
Updated commands: `/deep dive` (was /contextual), `/summary:` (was /compile), enhanced `/notebook` verbs.

**Q: Platform support?**  
Works everywhere - ChatGPT, Claude, API, local models. Manual commands ensure consistency.

---

## 🚀 Getting Started & What is MARM

### Q: What is MARM and why should I use it?

MARM (Memory Accurate Response Mode) is an AI protocol that gives any chatbot persistent memory and enhanced reasoning. Unlike standard AI that forgets previous conversations, MARM builds living context that grows with each interaction.

**Key benefits:**

- **True memory** - Remembers everything across long projects
- **Session organization** - Folder-style structure for complex work
- **Enhanced accuracy** - Built-in fact-checking and reasoning validation
- **Platform universal** - Works with any AI (ChatGPT, Claude, local models)

### Q: How is MARM different from ChatGPT memory or Claude Projects?

**ChatGPT/Claude built-in memory:**

- Limited, opaque, no user control
- Platform-specific, can't transfer
- No validation or accuracy guarantees

**MARM:**

- Manual control over what gets remembered
- Portable across any AI platform
- Built-in accuracy validation with `/deep dive`
- Session summaries you can copy/paste anywhere
- Transparent - you see and control all context

### Q: Who is MARM for?

**Perfect for:**

- **Developers** - Long coding projects with context continuity
- **Researchers** - Complex analysis requiring memory accuracy
- **Writers** - Multi-session creative projects
- **Consultants** - Client work requiring detailed context retention
- **Anyone** doing serious work with AI over multiple conversations

**Not ideal for:**

- Quick, one-off questions
- Users who want fully automated AI (MARM requires manual commands)

---

## ⚙️ Setup & Installation

### Q: How do I install MARM locally?

1. **Try online first**: [marm-systems-chatbot.onrender.com](https://marm-systems-chatbot.onrender.com) - no setup required
2. **For local setup**: See [SETUP.md](SETUP.md) for complete installation guide
3. **Quick summary**: Node.js + Replicate API token + `npm start`

### Q: Do I need an API key?

**For online chatbot:** No - just visit the link and start using

**For local installation:** Yes - Replicate API token (free trial for new customers)

- Get token at [replicate.com/account/api-tokens](https://replicate.com/account/api-tokens)
- Free trial for new customers
- 96% cheaper than premium AI services

### Q: What are the system requirements?

**Minimal requirements:**

- **Online**: Any modern browser
- **Local**: Node.js v16+, 50MB storage
- **AI Backend**: Replicate account (or any AI API)
- **Platform**: Works on Windows, Mac, Linux

### Q: Can I use different AI models?

Yes! MARM works with 1000+ models on Replicate:

- **Default**: Llama 4 Maverick (400B params, multimodal)
- **Alternatives**: Claude, GPT, Mistral, Code Llama, etc.
- **Easy switching**: Change one line in server.js (see SETUP.md)

---

## 🔍 How MARM Compares

### Q: Why not just use ChatGPT memory?

**ChatGPT Memory limitations:**

- No control over what gets remembered
- Can't export or transfer conversations
- Memory degrades over time
- Platform-locked

**MARM advantages:**

- You control what gets logged with `/log entry:`
- Export summaries with `/summary:` for any platform
- Memory stays accurate with validation protocols
- Works with any AI, not just ChatGPT

### Q: How does this compare to other AI tools?

**vs. Claude Projects:**

- MARM is portable, Claude Projects are platform-locked
- MARM has validation protocols, Claude doesn't
- MARM works with any model, Claude is single-provider

**vs. Custom GPTs:**

- MARM focuses on memory architecture, not specific use cases
- MARM is transparent, Custom GPTs are black boxes
- MARM works everywhere, Custom GPTs only in ChatGPT Plus

**vs. RAG systems:**

- MARM is user-controlled, RAG is automated
- MARM uses session-based memory, RAG uses vector search
- MARM is lightweight, RAG requires infrastructure

### Q: What makes MARM different?

**Unique approach:**

- **Manual control** - You decide what gets remembered
- **Universal compatibility** - Works with any AI backend
- **Identity-based protocol** - AI becomes a memory architect, not just a chatbot
- **Transparent validation** - See the reasoning with `/show reasoning`
- **Session persistence** - Build knowledge that transfers anywhere

**Philosophy**: Memory accuracy through user control, not black box automation.

---

## 🤖 Live Chatbot

### Q: How do I use the live MARM chatbot?

Open [marm-systems-chatbot.onrender.com](https://marm-systems-chatbot.onrender.com):

1. Type `/start marm` to activate MARM v2.0 protocol
2. Use command menu (⚡ button) for quick access
3. Sessions auto-save and persist across refreshes
4. **Powered by Llama 4 Maverick** - 400B parameter multimodal model
5. Includes voice synthesis, adaptive dark/light mode, and file uploads (features are MVP)

### Q: Best practices for the chatbot?

- Start with `/start marm` and give context about your work
- Use `/notebook add:` for preferences, project context, or communication style
- Log regularly: `/log session: [name]` and `/log entry: [YYYY-MM-DD-topic-summary]`
- Run `/refresh marm` every 8-10 turns to prevent drift

### Q: Troubleshooting generic responses?

1. `/refresh marm` to recenter
2. `/notebook show:` to check context
3. `/deep dive` for next response
4. Re-explain your work briefly

---

## 🧠 Core Concepts

### Q: Why manual commands instead of automation?

MARM prioritizes transparency and control. Manual commands like `/log` and `/summary:` ensure you decide what gets remembered and when. This prevents hidden automation, reduces drift, and works consistently across platforms.

### Q: Does MARM fix hallucinations?

No. MARM is a user-side protocol, not a model fix. It helps mitigate hallucinations through structured prompting and manual session logging, but doesn't claim to eliminate them.

### Q: What's new in v2.0?

- `/deep dive` replaces `/contextual reply`
- `/summary:` replaces `/compile`  
- Enhanced `/notebook` with `add:`, `use:`, `show:`, `clear:`, `status:`
- Improved live chatbot with session persistence
- Updated command syntax throughout

---

## ⚙️ Commands

### Q: Essential command patterns?

```text
/start marm
/log session: ProjectName
/log entry: [2025-08-11-feature-completed]
/notebook add: style_guide [preferences]
/notebook use: style_guide
/deep dive [your question]
/summary: ProjectName
```

### Q: How does `/notebook` work?

- `add: [name] [data]` - Store information
- `use: [name1,name2]` - Activate as instructions  
- `show:` - List all entries
- `clear:` - Remove active entries
- `status:` - Show current active list

**Limitations:** Session-bound, doesn't persist across chats

### Q: When to use `/deep dive`?

Use when you need maximum accuracy, detailed reasoning, or responses grounded in session context. It forces strict guardrails and shows reasoning.

---

## 🛠️ Troubleshooting

### Q: Session losing context?

**4-step fix:**

1. `/refresh marm` to recenter
2. `/summary: [session]` to recap  
3. `/deep dive` for next response
4. Reseed in new chat if token limits hit

### Q: Platform-specific tips?

- **ChatGPT:** Use `/refresh marm` every 5-7 turns to counter assumption drift
- **Claude:** Requires disciplined reseed workflow, benefits from `/notebook` entries  
- **API/Local:** Treat as stateless, implement reseed blocks in system prompts

---

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

---

> Curious where MARM is heading?  
> See the [ROADMAP.md](ROADMAP.md) to view upcoming features and goals.
