# Acknowledgments

MARM has been shaped by early users, testers, reviewers, and open-source contributors who gave feedback when the project was still rough. This page recognizes that help and keeps a record of the community influence behind the project.

MARM started as a personal answer to a simple problem: AI tools forget too much between sessions. The project is now focused on the MARM MCP server, local memory workflows, Docker and STDIO transports, IDE/client integrations, and the dashboard for inspecting local memory data.

## What This Page Is For

This file is for recognition and project history. It is not the contribution guide.

For contribution workflow, issues, pull requests, tests, and local development expectations, use the dedicated `CONTRIBUTING.md` guide.

## Community Influence

MARM has benefited from people who:

- Tested the MCP server in real clients and IDEs
- Reported confusing install, Docker, and transport setup paths
- Helped validate memory workflows across actual projects
- Shared edge cases around local databases, auth keys, and multi-agent usage
- Reviewed docs and called out stale or unclear sections
- Forked or adapted the project in ways that exposed new use cases

Those contributions matter because MARM is most useful when it reflects how people actually work with AI tools, not only how the project is designed in isolation.

## Early Contributors

### **Early Pioneers**

#### u/CalamityThorazine & u/CrazyCrayfish  

**Community Champions** | [Reddit Thread – June 9, 2025](https://www.reddit.com/r/PromptEngineering/comments/1l7jtpn/i_analyzed_150_real_ai_complaints_then_built_a/)

Encouraged the move from temporary hosting (e.g., Google Drive) to GitHub, improving accessibility and trust. Their early interest helped validate public release and shaped the decision to publish the protocol in a permanent, versioned repository.

**Impact:** Made MARM accessible to the wider community through proper GitHub hosting

---

#### u/ophydian210  

**Protocol Architect** | [GitHub: Ophy21](https://github.com/Ophy21) | [Reddit Thread – June 10, 2025](https://www.reddit.com/r/PromptEngineering/comments/1l7jtpn/i_analyzed_150_real_ai_complaints_then_built_a/)

Provided early-stage critique and refinement feedback on memory simulation, session labeling, and user experience logic. Influenced the removal of the confidence scoring system, the creation of the `/show reasoning` command, and improvements to session lifecycle documentation.

**Impact:** Core protocol features like `/show reasoning` exist because of their feedback

---

#### u/Deminimis_opsec

**Technical Clarity Champion** | [Reddit Thread – June 10, 2025](https://www.reddit.com/r/PromptEngineering/comments/1l7jtpn/i_analyzed_150_real_ai_complaints_then_built_a/)

Provided critical technical feedback on MARM's limitations within non-API chat environments. Helped clarify the distinction between frontend prompt-layer protocols and backend memory architectures. Their input reinforced the importance of transparency around session scope, non-persistent memory, and the lack of backend execution in typical LLM interfaces.

**Impact:** MARM's transparent limitations documentation exists because of their insight

---

#### u/Angry_cactus

**Cross-Platform Validator** | [Reddit Thread – June 11, 2025](https://www.reddit.com/r/PromptEngineering/comments/1l7jtpn/i_analyzed_150_real_ai_complaints_then_built_a/)

Tested MARM across models and validated its performance in Gemini Pro. Provided feedback on LLM pseudo-memory behaviors, reply weighting, and the trade-offs between short-form prompts and structured memory. Their observations reinforced the session-based design choice and influenced future patch direction focused on continuity fail safes and compression-aware prompting.

**Impact:** Multi-model compatibility and session design principles shaped by their testing

---

#### u/MykoJai168  

**Vision Contributor** | Private DM - June 12, 2025 | (Referenced in [README.md](../README.md))

Sparked the architectural concept behind MARM's "Session Relay Tools" patch by proposing a layered, context-managed memory model. Offered collaboration, stress-testing interest, and early insight into multi-agent recall, which helped validate MARM's patch direction. Credited for contributing to the prompt-layer vision and user-side continuity design.

**Impact:** The foundation of MARM's memory architecture came from their collaborative vision

---

### u/LanaAugustine

**Active Tester** | Private DM - August 29, 2025

This user helped before MARM by actively testing and giving feedback on the protocols behind the project. Active testers make it much easier to see the user side of the system, so thank you for the contribution.

**Impact:** Valuable feedback that helped shape the protocols behind MARM

---

### **Core Contributors**

#### Neurosyn Labs

**Lightweight Memory Architect** | [GitHub: NeurosynLabs](https://github.com/NeurosynLabs)

Created **MARMalade V-1.0** — A lightweight memory kernel for ChatGPT, built on MARM principles with structured persistence, sovereign reasoning, and token-efficient context retention. Their implementation demonstrates how MARM concepts can be adapted into focused, efficient memory solutions for specific AI platforms.

**Impact:** Showed how MARM principles can be implemented as lightweight, specialized memory kernels

---

#### Jefferson Nunn

**Strategic Technology Advisor & Infrastructure Contributor** | [GitHub: jeffersonwarrior](https://github.com/jeffersonwarrior)

Jefferson brought a rare mix of technical depth, infrastructure experience, and professional communication to MARM during an important transition point. As a respected technology journalist and network infrastructure voice, he helped frame MARM less as a standalone prompt experiment and more as a practical memory layer that could support real developer workflows, agent systems, and future platform work.

His feedback pushed several important conversations forward: distributed vs. cloud memory, database scale, privacy-preserving architecture, agent coordination, MCP registry visibility, deployment strategy, and the role MARM could play as backend memory infrastructure for larger tools. He also helped stress-test the project's direction by challenging timing, market fit, and infrastructure tradeoffs instead of only focusing on code.

**Impact:** Helped mature MARM's technical direction from a memory protocol into infrastructure-minded MCP tooling, with stronger thinking around databases, deployment, privacy, agents, and long-term platform architecture

---

#### u/sabhi12

**AI Memory Systems Analyst** | [Reddit: sabhi12](https://www.reddit.com/user/sabhi12) | Private DM - July 2025

Provided deep technical analysis of LLM memory limitations and validation of MARM's core architecture. Key contributions include identifying the distinction between real memory vs. simulated memory in current AI systems, strategic feedback on memory types (short-term, long-term, permanent), and advanced ChatGPT integration techniques. Their industry perspective helped validate MARM's market positioning and technical approach to solving enterprise-grade AI memory challenges.

**Impact:** Strategic validation of MARM's memory architecture and identification of key market opportunities for AI memory intelligence

## Forks and Derivative Work

Forks, experiments, and unofficial adaptations are welcome. If you build on MARM, please make the relationship clear so users can distinguish official releases from community experiments.

- Use a unique project name for derivative work.
- Clearly state when a fork is unofficial or experimental.
- Avoid using official MARM version numbers for independent releases.
- Link back to the original repository when practical.

This keeps the ecosystem open while making it easy for users to find the official source of truth.

## Project Values

MARM is built around practical, transparent development:

- Solve real workflow problems before adding complexity.
- Be clear about limitations and tradeoffs.
- Prefer focused improvements over broad rewrites.
- Keep the project usable for local-first and open-source workflows.
- Treat feedback as part of the design process.

## Code of Conduct

Project discussions should stay respectful, direct, and useful.

- Be welcoming to new users and contributors.
- Disagree constructively and explain the technical reason.
- Keep issue threads focused on reproducible problems or clear proposals.
- Assume good intent, but keep standards high.

## Related Docs

- [README.md](../README.md) - Project overview and quick start
- [MCP-HANDBOOK.md](../MCP-HANDBOOK.md) - MCP usage guide
- [PROTOCOL.md](PROTOCOL.md) - Core memory protocol
- [CHANGELOG.md](../CHANGELOG.md) - Version history
- [ROADMAP.md](ROADMAP.md) - Current direction and planned work
