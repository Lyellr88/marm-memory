# Security Policy

## Reporting a Vulnerability

Please report security issues privately by emailing:

**support@marmemory.com**

Do not open a public GitHub issue or pull request for vulnerabilities that could expose user memory, logs, notebook data, authentication gaps, deployment risks, secrets, or other sensitive details.

Helpful reports include:

- A short summary of the issue
- Affected version, commit, Docker image, or install path
- Reproduction steps or proof of concept
- Impact assessment
- Suggested fix, if known

We will review valid reports as quickly as possible and coordinate a fix before public disclosure.

## Scope

Security-sensitive areas include:

- MARM MCP server HTTP, STDIO, and WebSocket transports
- Memory, log, notebook, compaction, and system endpoints
- Docker and remote deployment defaults
- Authentication, API key handling, and rate limiting
- Database access, file paths, and local data exposure
- GitHub Actions, package publishing, and release automation

## Public Disclosure

Please give us time to investigate and release a fix before sharing vulnerability details publicly. We are happy to credit responsible disclosures when the reporter wants public acknowledgment.
