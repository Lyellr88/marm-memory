import type { AgentConfig, DependencyCheck } from './types';

export const AGENT_CONFIGS: AgentConfig[] = [
  {
    id: 'claude',
    name: 'Claude Code',
    description: "Anthropic's AI assistant with advanced reasoning",
    commands: {
      windows: {
        install: 'irm https://claude.ai/install.ps1 | iex',
        launch: 'claude',
        verify: 'claude --version',
      },
      macos: {
        install: 'curl -fsSL https://claude.ai/install.sh | bash',
        launch: 'claude',
        verify: 'claude --version',
      },
      linux: {
        install: 'curl -fsSL https://claude.ai/install.sh | bash',
        launch: 'claude',
        verify: 'claude --version',
      },
    },
  },
  {
    id: 'codex',
    name: 'Codex',
    description: "OpenAI's code-focused AI assistant",
    commands: {
      windows: {
        install: 'powershell -ExecutionPolicy ByPass -c "irm https://chatgpt.com/codex/install.ps1 | iex"',
        launch: 'codex',
        verify: 'codex --version',
      },
      macos: {
        install: 'curl -fsSL https://chatgpt.com/codex/install.sh | sh',
        launch: 'codex',
        verify: 'codex --version',
      },
      linux: {
        install: 'curl -fsSL https://chatgpt.com/codex/install.sh | sh',
        launch: 'codex',
        verify: 'codex --version',
      },
    },
  },
  {
    id: 'grok',
    name: 'Grok Build',
    description: "xAI's terminal coding agent",
    commands: {
      windows: {
        install: 'irm https://x.ai/cli/install.ps1 | iex',
        launch: 'grok',
        verify: 'grok --version',
      },
      macos: {
        install: 'curl -fsSL https://x.ai/cli/install.sh | bash',
        launch: 'grok',
        verify: 'grok --version',
      },
      linux: {
        install: 'curl -fsSL https://x.ai/cli/install.sh | bash',
        launch: 'grok',
        verify: 'grok --version',
      },
    },
  },
  {
    id: 'hermes',
    name: 'Hermes Agent',
    description: "Nous Research's self-improving agent",
    commands: {
      windows: {
        install: 'iex (irm https://hermes-agent.nousresearch.com/install.ps1)',
        launch: 'hermes',
        verify: 'hermes --version',
      },
      macos: {
        install: 'curl -fsSL https://hermes-agent.nousresearch.com/install.sh | bash',
        launch: 'hermes',
        verify: 'hermes --version',
      },
      linux: {
        install: 'curl -fsSL https://hermes-agent.nousresearch.com/install.sh | bash',
        launch: 'hermes',
        verify: 'hermes --version',
      },
    },
  },
  {
    id: 'opencode',
    name: 'OpenCode',
    description: 'Open source coding agent for the terminal (needs Node.js)',
    commands: {
      windows: {
        install: 'npm install -g opencode-ai',
        launch: 'opencode',
        verify: 'opencode --version',
      },
      macos: {
        install: 'npm install -g opencode-ai',
        launch: 'opencode',
        verify: 'opencode --version',
      },
      linux: {
        install: 'npm install -g opencode-ai',
        launch: 'opencode',
        verify: 'opencode --version',
      },
    },
  },
  {
    id: 'cline',
    name: 'Cline',
    description: 'Cline agent for the terminal (needs Node.js)',
    commands: {
      windows: {
        install: 'npm install -g cline',
        launch: 'cline',
        verify: 'cline version',
      },
      macos: {
        install: 'npm install -g cline',
        launch: 'cline',
        verify: 'cline version',
      },
      linux: {
        install: 'npm install -g cline',
        launch: 'cline',
        verify: 'cline version',
      },
    },
  },
  {
    id: 'cursor',
    name: 'Cursor',
    description: 'Cursor agent for the terminal',
    commands: {
      windows: {
        install: "irm 'https://cursor.com/install?win32=true' | iex",
        launch: 'agent',
        verify: 'agent --version',
      },
      macos: {
        install: 'curl https://cursor.com/install -fsS | bash',
        launch: 'agent',
        verify: 'agent --version',
      },
      linux: {
        install: 'curl https://cursor.com/install -fsS | bash',
        launch: 'agent',
        verify: 'agent --version',
      },
    },
  },
  {
    id: 'devin',
    name: 'Devin',
    description: "Cognition's coding agent for the terminal",
    commands: {
      windows: {
        install: 'irm https://static.devin.ai/cli/setup.ps1 | iex',
        launch: 'devin',
        verify: 'devin --version',
      },
      macos: {
        install: 'curl -fsSL https://cli.devin.ai/install.sh | bash',
        launch: 'devin',
        verify: 'devin --version',
      },
      linux: {
        install: 'curl -fsSL https://cli.devin.ai/install.sh | bash',
        launch: 'devin',
        verify: 'devin --version',
      },
    },
  },
  {
    id: 'antigravity',
    name: 'Antigravity',
    description: "Google's agentic CLI, formerly Gemini CLI",
    commands: {
      windows: {
        install: 'irm https://antigravity.google/cli/install.ps1 | iex',
        launch: 'agy',
        verify: 'agy --version',
      },
      macos: {
        install: 'curl -fsSL https://antigravity.google/cli/install.sh | bash',
        launch: 'agy',
        verify: 'agy --version',
      },
      linux: {
        install: 'curl -fsSL https://antigravity.google/cli/install.sh | bash',
        launch: 'agy',
        verify: 'agy --version',
      },
    },
  },
];

export const DEPENDENCY_CHECKS: DependencyCheck[] = [
  {
    name: 'Node.js + npm',
    command: 'node --version; npm --version',
    installCommand: 'winget install --id OpenJS.NodeJS.LTS -e --source winget',
  },
  {
    name: 'Git',
    command: 'git --version',
    installCommand: 'winget install --id Git.Git -e --source winget',
  },
];
