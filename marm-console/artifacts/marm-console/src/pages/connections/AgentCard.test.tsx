import { cleanup, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { AgentCard } from './AgentCard';
import type { Agent, AgentScopeState } from '@/lib/marm-types';

const hooks = vi.hoisted(() => ({
  scopeCalls: [] as unknown[][],
  scopeData: undefined as unknown,
  projects: [] as Array<{ name: string; display_name?: string; root_path: string }>,
  configure: { mutate: vi.fn(), isPending: false, variables: undefined as unknown },
  remove: { mutate: vi.fn(), isPending: false },
  test: { mutate: vi.fn(), isPending: false },
  skill: { mutate: vi.fn(), isPending: false },
}));

vi.mock('@/hooks/use-marm-queries', () => ({
  useProjects: () => ({ data: hooks.projects }),
  useAgentScope: (...args: unknown[]) => {
    hooks.scopeCalls.push(args);
    return { data: hooks.scopeData, isLoading: false, isError: false, error: null };
  },
  useConfigureAgent: () => hooks.configure,
  useRemoveAgent: () => hooks.remove,
  useTestAgent: () => hooks.test,
  useInstallAgentSkill: () => hooks.skill,
}));

function scopeState(over: Partial<AgentScopeState> = {}): AgentScopeState {
  return {
    scope: 'user',
    project: null,
    config_path: 'C:\\Users\\me\\.cursor\\mcp.json',
    config_exists: true,
    state: 'missing',
    transport_detected: null,
    current_entry: null,
    ...over,
  };
}

function agent(over: Partial<Agent> = {}): Agent {
  return {
    id: 'cursor',
    label: 'Cursor',
    detected: true,
    transports: ['http', 'stdio', 'docker-stdio'],
    scopes: ['user', 'project'],
    user: scopeState(),
    skill: { supported: true, installed: false },
    notes: [],
    unavailable: {},
    ...over,
  };
}

function settle(result: unknown) {
  return vi.fn((_vars: unknown, opts?: { onSuccess?: (data: unknown) => void }) => {
    opts?.onSuccess?.(result);
  });
}

function fail(err: Error) {
  return vi.fn((_vars: unknown, opts?: { onError?: (e: unknown) => void }) => {
    opts?.onError?.(err);
  });
}

function renderCard(a: Agent, opts: { allowed?: Array<'http' | 'stdio' | 'docker-stdio'>; allowedConfigure?: boolean } = {}) {
  return render(<AgentCard agent={a} allowedTransports={opts.allowed ?? ['http', 'stdio']} configureAllowed={opts.allowedConfigure ?? true} />);
}

const PREVIEW = {
  client: 'cursor',
  transport: 'http',
  scope: 'user',
  config_path: 'C:\\Users\\me\\.cursor\\mcp.json',
  action: 'add',
  entry: { url: 'http://127.0.0.1:8001/mcp' },
  backup_path: 'C:\\Users\\me\\.cursor\\mcp.json.marm-backup',
  method: 'file',
  notes: ['Cursor reads MARM_API_KEY from your environment.'],
};

beforeEach(() => {
  hooks.scopeCalls = [];
  hooks.scopeData = undefined;
  hooks.projects = [];
  hooks.configure = { mutate: vi.fn(), isPending: false, variables: undefined };
  hooks.remove = { mutate: vi.fn(), isPending: false };
  hooks.test = { mutate: vi.fn(), isPending: false };
  hooks.skill = { mutate: vi.fn(), isPending: false };
});

afterEach(cleanup);

describe('AgentCard transport', () => {
  it('defaults to the detected transport when it is allowed', () => {
    renderCard(agent({ user: scopeState({ state: 'configured', transport_detected: 'stdio' }) }));

    expect(screen.getByRole('button', { name: 'STDIO' }).getAttribute('aria-pressed')).toBe('true');
    expect(screen.getByRole('button', { name: 'HTTP' }).getAttribute('aria-pressed')).toBe('false');
  });

  it('falls back to the first allowed transport when the detected one is not allowed', () => {
    renderCard(agent({ user: scopeState({ transport_detected: 'docker-stdio' }) }));

    expect(screen.getByRole('button', { name: 'HTTP' }).getAttribute('aria-pressed')).toBe('true');
    expect(screen.queryByRole('button', { name: 'Docker STDIO' })).toBeNull();
  });

  it('only offers transports the client supports, labelled in plain words', () => {
    renderCard(agent({ transports: ['stdio', 'docker-stdio'] }), { allowed: ['http', 'docker-stdio'] });

    expect(screen.queryByRole('button', { name: 'HTTP' })).toBeNull();
    expect(screen.getByRole('button', { name: 'Docker STDIO' })).toBeTruthy();
  });

  it('disables an unavailable transport and shows its reason', () => {
    renderCard(agent({ unavailable: { http: 'Needs the mcp-remote bridge.' } }));

    const http = screen.getByRole('button', { name: 'HTTP' }) as HTMLButtonElement;
    expect(http.disabled).toBe(true);
    expect(http.title).toBe('Needs the mcp-remote bridge.');
    expect(screen.getByText('HTTP: Needs the mcp-remote bridge.')).toBeTruthy();
    expect(screen.getByRole('button', { name: 'STDIO' }).getAttribute('aria-pressed')).toBe('true');
  });
});

describe('AgentCard scope', () => {
  it('requests the project scope and shows that file when a project is picked', async () => {
    const user = userEvent.setup();
    hooks.projects = [{ name: 'MARM-Systems', root_path: 'C:\\code\\MARM-Systems' }];
    renderCard(agent());

    hooks.scopeData = scopeState({ scope: 'project', project: 'C:\\code\\MARM-Systems', config_path: 'C:\\code\\MARM-Systems\\.cursor\\mcp.json', state: 'configured' });
    await user.selectOptions(screen.getByLabelText('Scope'), 'C:\\code\\MARM-Systems');

    expect(hooks.scopeCalls.at(-1)).toEqual(['cursor', 'project', 'C:\\code\\MARM-Systems', true, undefined]);
    expect(screen.getByText('C:\\code\\MARM-Systems\\.cursor\\mcp.json')).toBeTruthy();
    expect(screen.getByText('Connected')).toBeTruthy();
  });

  it('reveals a folder input for Another folder and queries only after Apply', async () => {
    const user = userEvent.setup();
    renderCard(agent());

    await user.selectOptions(screen.getByLabelText('Scope'), 'Another folder...');
    expect(hooks.scopeCalls.at(-1)).toEqual(['cursor', 'project', undefined, false, undefined]);

    await user.type(screen.getByLabelText('Folder path'), 'D:\\work\\site');
    await user.click(screen.getByRole('button', { name: 'Apply' }));

    expect(hooks.scopeCalls.at(-1)).toEqual(['cursor', 'project', 'D:\\work\\site', true, undefined]);
  });

  it('offers only Every project when the client has no project scope', () => {
    hooks.projects = [{ name: 'MARM-Systems', root_path: 'C:\\code\\MARM-Systems' }];
    renderCard(agent({ scopes: ['user'] }));

    const select = screen.getByLabelText('Scope') as HTMLSelectElement;
    expect(Array.from(select.options).map((o) => o.text)).toEqual(['Every project']);
  });
});

describe('AgentCard connect and update', () => {
  it('previews the write, then confirms with dry_run false and reports verified', async () => {
    const user = userEvent.setup();
    hooks.configure.mutate = settle(PREVIEW);
    renderCard(agent());

    await user.click(screen.getByRole('button', { name: 'Connect' }));

    expect(hooks.configure.mutate).toHaveBeenCalledWith({ id: 'cursor', body: { scope: 'user', transport: 'http', dry_run: true } }, expect.anything());
    expect(screen.getByText('Add entry')).toBeTruthy();
    expect(screen.getByText(/"url": "http:\/\/127\.0\.0\.1:8001\/mcp"/)).toBeTruthy();
    expect(screen.getByText('C:\\Users\\me\\.cursor\\mcp.json.marm-backup')).toBeTruthy();
    expect(screen.getByText('Cursor reads MARM_API_KEY from your environment.')).toBeTruthy();

    hooks.configure.mutate = settle({ ...PREVIEW, written: true, verified: true });
    await user.click(screen.getByRole('button', { name: 'Confirm' }));

    expect(hooks.configure.mutate).toHaveBeenCalledWith({ id: 'cursor', body: { scope: 'user', transport: 'http', dry_run: false } }, expect.anything());
    expect(screen.getByText('Written and verified. Restart Cursor to load it.')).toBeTruthy();
  });

  it('says so when the write could not be verified', async () => {
    const user = userEvent.setup();
    hooks.configure.mutate = settle(PREVIEW);
    renderCard(agent());
    await user.click(screen.getByRole('button', { name: 'Connect' }));

    hooks.configure.mutate = settle({ ...PREVIEW, written: true, verified: false });
    await user.click(screen.getByRole('button', { name: 'Confirm' }));

    expect(screen.getByText(/Written but not verified/)).toBeTruthy();
  });

  it('shows the server detail when the write fails', async () => {
    const user = userEvent.setup();
    hooks.configure.mutate = settle(PREVIEW);
    renderCard(agent());
    await user.click(screen.getByRole('button', { name: 'Connect' }));

    hooks.configure.mutate = fail(new Error('The file is locked by another program.'));
    await user.click(screen.getByRole('button', { name: 'Confirm' }));

    expect(screen.getByText('The file is locked by another program.')).toBeTruthy();
  });

  it('uses Update for a configured agent and sends the chosen transport and project', async () => {
    const user = userEvent.setup();
    hooks.projects = [{ name: 'MARM-Systems', root_path: 'C:\\code\\MARM-Systems' }];
    hooks.configure.mutate = settle({ ...PREVIEW, action: 'replace' });
    renderCard(agent({ user: scopeState({ state: 'configured', transport_detected: 'http' }) }));

    expect(screen.queryByRole('button', { name: 'Connect' })).toBeNull();
    await user.click(screen.getByRole('button', { name: 'STDIO' }));
    hooks.scopeData = scopeState({ scope: 'project', project: 'C:\\code\\MARM-Systems', state: 'configured', transport_detected: 'http' });
    await user.selectOptions(screen.getByLabelText('Scope'), 'C:\\code\\MARM-Systems');
    await user.click(screen.getByRole('button', { name: 'Update' }));

    expect(hooks.configure.mutate).toHaveBeenCalledWith(
      { id: 'cursor', body: { scope: 'project', project: 'C:\\code\\MARM-Systems', transport: 'stdio', dry_run: true } },
      expect.anything(),
    );
    expect(screen.getByText('Replace existing entry')).toBeTruthy();
  });

  it('cannot connect over a transport that is unavailable', () => {
    renderCard(agent({ transports: ['http'], unavailable: { http: 'Auth is on, use STDIO.' } }));

    expect((screen.getByRole('button', { name: 'Connect' }) as HTMLButtonElement).disabled).toBe(true);
  });
});

describe('AgentCard remove', () => {
  it('confirms first, then removes only after Remove is confirmed', async () => {
    const user = userEvent.setup();
    hooks.remove.mutate = settle({ client: 'cursor', config_path: 'x', action: 'remove', backup_path: 'x.bak', method: 'file', written: true, verified: true });
    renderCard(agent({ user: scopeState({ state: 'configured', transport_detected: 'http' }) }));

    await user.click(screen.getByRole('button', { name: 'Remove' }));
    expect(hooks.remove.mutate).not.toHaveBeenCalled();
    expect(screen.getByText(/Only MARM's entry is removed/)).toBeTruthy();

    const buttons = screen.getAllByRole('button', { name: 'Remove' });
    await user.click(buttons[buttons.length - 1]);

    expect(hooks.remove.mutate).toHaveBeenCalledWith({ id: 'cursor', body: { scope: 'user', dry_run: false } }, expect.anything());
    expect(screen.getByText('Removed. Backup saved.')).toBeTruthy();
  });
});

describe('AgentCard test', () => {
  async function runTest(result: unknown, configured = true) {
    const user = userEvent.setup();
    hooks.test.mutate = settle(result);
    renderCard(agent({ user: scopeState({ state: configured ? 'configured' : 'missing', transport_detected: 'http' }) }));
    await user.click(screen.getByRole('button', { name: 'Test' }));
    expect(hooks.test.mutate).toHaveBeenCalledWith({ id: 'cursor', body: { scope: 'user' } }, expect.anything());
  }

  it('reports tools and latency on success', async () => {
    await runTest({ ok: true, transport: 'http', tools: 16, latency_ms: 42, error: null });
    expect(screen.getByText('MARM answered: 16 tools in 42 ms')).toBeTruthy();
  });

  it.each([
    ['refused', 'MARM is not running at that address.'],
    ['timeout', 'MARM did not answer in time.'],
    ['unauthorized', 'MARM rejected the key. Check MARM_API_KEY.'],
    ['missing_entry', 'No MARM entry in this file yet. Connect first.'],
    ['spawn_failed', 'Could not start MARM from this entry.'],
  ])('explains %s in plain words', async (kind, text) => {
    await runTest({ ok: false, transport: null, tools: null, latency_ms: null, error: { kind, detail: 'raw detail' } });
    expect(screen.getByText(text)).toBeTruthy();
    expect(screen.queryByText('raw detail')).toBeNull();
  });

  it.each(['protocol', 'unsupported'])('shows the detail for %s', async (kind) => {
    await runTest({ ok: false, transport: null, tools: null, latency_ms: null, error: { kind, detail: 'Server returned no tools list.' } });
    expect(screen.getByText('Server returned no tools list.')).toBeTruthy();
  });

  it('puts Test after Connect for an agent that is not connected yet', () => {
    renderCard(agent());
    const labels = screen.getAllByRole('button').map((b) => b.textContent);
    expect(labels.indexOf('Connect')).toBeLessThan(labels.indexOf('Test'));
  });
});

describe('AgentCard skill', () => {
  it('installs the skill and reports it', async () => {
    const user = userEvent.setup();
    hooks.skill.mutate = settle({ state: 'installed', target: 'C:\\skills' });
    renderCard(agent());

    await user.click(screen.getByRole('button', { name: 'Install skill' }));

    expect(hooks.skill.mutate).toHaveBeenCalledWith('cursor', expect.anything());
    expect(screen.getByText('MARM skill installed for Cursor.')).toBeTruthy();
  });

  it('hides Install skill and shows an installed pill once it is installed', () => {
    renderCard(agent({ skill: { supported: true, installed: true } }));

    expect(screen.queryByRole('button', { name: 'Install skill' })).toBeNull();
    expect(screen.getByText('installed')).toBeTruthy();
  });

  it('hides Install skill when the agent has no skill support', () => {
    renderCard(agent({ skill: { supported: false, installed: false } }));

    expect(screen.queryByRole('button', { name: 'Install skill' })).toBeNull();
  });
});

describe('AgentCard special states', () => {
  it('renders xai as info only with its payload and no controls', () => {
    renderCard(
      agent({
        id: 'xai',
        label: 'Grok (xAI API)',
        transports: [],
        scopes: ['user'],
        notes: ['Grok needs a public HTTPS URL.'],
        user: scopeState({ config_path: null, expected_entry: { type: 'mcp', authorization: 'Bearer YOUR_KEY' } }),
      }),
    );

    expect(screen.getByText('Grok needs a public HTTPS URL.')).toBeTruthy();
    expect(screen.getByText(/"authorization": "Bearer YOUR_KEY"/)).toBeTruthy();
    expect(screen.queryByRole('button', { name: 'Connect' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Test' })).toBeNull();
    expect(screen.queryByLabelText('Scope')).toBeNull();
  });

  it('disables every action when configuring is blocked', () => {
    renderCard(agent(), { allowedConfigure: false });

    for (const name of ['Connect', 'Test', 'Install skill']) {
      expect((screen.getByRole('button', { name }) as HTMLButtonElement).disabled).toBe(true);
    }
  });

  it('disables Update, Remove and Test when blocked on a configured agent', () => {
    renderCard(agent({ user: scopeState({ state: 'configured', transport_detected: 'http' }) }), { allowedConfigure: false });

    for (const name of ['Test', 'Update', 'Remove']) {
      expect((screen.getByRole('button', { name }) as HTMLButtonElement).disabled).toBe(true);
    }
  });
});
