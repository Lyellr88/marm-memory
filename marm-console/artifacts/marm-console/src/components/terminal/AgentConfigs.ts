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
    id: 'antigravity',
    name: 'Antigravity (was Gemini CLI)',
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
