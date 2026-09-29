import { describe, expect, it } from 'vitest';
import { AGENT_CONFIGS } from './AgentConfigs';

describe('Cursor terminal onboarding', () => {
  const cursor = AGENT_CONFIGS.find((agent) => agent.id === 'cursor');

  it('installs the agent with the documented per-OS commands', () => {
    expect(cursor?.commands.windows.install).toBe("irm 'https://cursor.com/install?win32=true' | iex");
    expect(cursor?.commands.macos.install).toBe('curl https://cursor.com/install -fsS | bash');
    expect(cursor?.commands.linux.install).toBe('curl https://cursor.com/install -fsS | bash');
  });

  it('launches and verifies through the agent binary on every platform', () => {
    for (const platform of ['windows', 'macos', 'linux'] as const) {
      expect(cursor?.commands[platform].launch).toBe('agent');
      expect(cursor?.commands[platform].verify).toBe('agent --version');
    }
  });
});
