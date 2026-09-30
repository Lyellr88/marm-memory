import { cleanup, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ManualTab } from './ManualTab';
import { quoteArg } from './ManualCli';
import { MarmApiError } from '@/lib/marm-api';
import type { Agent, ConnectionsOverview, ManualAgentCommand, ManualCliCommand, ManualEndpoints, ManualEnvItem, ManualSnippetParams } from '@/lib/marm-types';

const state = vi.hoisted(() => ({
  overview: undefined as unknown,
  agents: [] as unknown[],
  commands: [] as unknown[],
  cli: [] as unknown[],
  endpoints: undefined as unknown,
  env: [] as unknown[],
  snippetCalls: [] as unknown[],
  commandCalls: [] as unknown[],
  send: vi.fn(() => true),
  available: true,
}));

vi.mock('@/lib/terminal-bridge', () => ({
  useTerminalBridge: () => ({ available: state.available, sendToTerminal: state.send }),
}));

vi.mock('@/hooks/use-marm-queries', () => ({
  useConnectionsOverview: () => ({ data: state.overview }),
  useAgents: () => ({ data: { auth_required: false, configure_allowed: true, configure_blocked_reason: null, clients: state.agents }, isLoading: false, isError: false, error: null }),
  useManualSnippet: (params: ManualSnippetParams | null) => {
    state.snippetCalls.push(params);
    if (params?.client === 'cursor' && params.scope === 'project' && params.transport === 'stdio') {
      return { data: undefined, isLoading: false, isError: true, error: new MarmApiError(422, 'Cursor does not support STDIO in one project.') };
    }
    return {
      data: params ? { client: params.client, os: params.os, path: `/paths/${params.client}/${params.os}.json`, format: 'json', text: `snippet ${params.client} ${params.os} ${params.transport} ${params.scope} ${params.target}`, notes: ['Restart the agent after saving.'] } : undefined,
      isLoading: false,
      isError: false,
      error: null,
    };
  },
  useManualAgentCommands: (params: unknown) => {
    state.commandCalls.push(params);
    return { data: { commands: state.commands }, isLoading: false, isError: false, error: null };
  },
  useManualCli: () => ({ data: { commands: state.cli }, isLoading: false, isError: false, error: null }),
  useManualEndpoints: () => ({ data: state.endpoints, isLoading: false, isError: false, error: null }),
  useManualEnv: () => ({ data: { items: state.env }, isLoading: false, isError: false, error: null }),
}));

function agent(over: Partial<Agent>): Agent {
  return {
    id: 'cursor',
    label: 'Cursor',
    detected: true,
    transports: ['http', 'stdio'],
    scopes: ['user', 'project'],
    user: { scope: 'user', config_path: null, config_exists: false, state: 'missing', transport_detected: null, current_entry: null },
    skill: { supported: false, installed: false },
    notes: [],
    unavailable: {},
    ...over,
  };
}

function overview(over: Partial<ConnectionsOverview> = {}): ConnectionsOverview {
  return {
    version: '2.54.1',
    os: 'Windows 11',
    runtime: { state: 'ready', managed: true, url: '127.0.0.1:8001', profile: 'standard' },
    auth: { mode: 'local', key_file_exists: false },
    agents: { connected: 0, detected: 0 },
    skills_installed: 0,
    checklist: [],
    ...over,
  };
}

function cliCommand(over: Partial<ManualCliCommand>): ManualCliCommand {
  return { command: 'start', help: 'Start the runtime', args: [], cli_only: false, cli_only_reason: null, ...over };
}

const ARG = { flag: null, choices: null, default: null, required: false, help: '', repeatable: false, type: 'str' as const };

function lastCall<T>(calls: unknown[]) {
  return calls[calls.length - 1] as T;
}

beforeEach(() => {
  state.overview = overview();
  state.agents = [agent({}), agent({ id: 'codex', label: 'Codex', transports: ['stdio'], scopes: ['user'] })];
  state.commands = [
    { client: 'claude', label: 'Claude Code', command: 'claude mcp add marm --transport http http://127.0.0.1:8001/mcp', note: '' },
    { client: 'cursor', label: 'Cursor', command: null, note: 'Cursor has no command line. Use the config file.' },
  ] satisfies ManualAgentCommand[];
  state.cli = [
    cliCommand({
      command: 'start',
      args: [
        { ...ARG, name: 'no_open', kind: 'flag', flag: '--no-open', type: 'str' },
        { ...ARG, name: 'profile', kind: 'option', flag: '--profile', choices: ['standard', 'swarm'], default: 'standard' },
        { ...ARG, name: 'port', kind: 'option', flag: '--port', type: 'int' },
      ],
    }),
    cliCommand({
      command: 'recall',
      help: 'Search memories',
      args: [
        { ...ARG, name: 'tag', kind: 'option', flag: '--tag', repeatable: true },
        { ...ARG, name: 'query', kind: 'positional', required: true },
      ],
    }),
    cliCommand({ command: 'docker start', help: 'Start the container' }),
    cliCommand({ command: 'key reveal', help: 'Show the key', cli_only: true, cli_only_reason: 'Prints a secret, so it stays in your own terminal.' }),
  ];
  state.endpoints = {
    mcp_url: 'http://127.0.0.1:8001/mcp',
    runtime_available: true,
    reason: null,
    groups: [
      { name: 'memory', routes: [{ method: 'POST', path: '/memory/store', summary: 'Store a memory' }, { method: 'GET', path: '/memory/list', summary: 'List memories' }] },
      { name: 'health', routes: [{ method: 'GET', path: '/health', summary: 'Health check' }] },
    ],
    console: [{ method: 'GET', path: '/api/overview', summary: 'Console overview' }],
  } satisfies ManualEndpoints;
  state.env = [
    { name: 'SERVER_PORT', group: 'Server', default: '8001', current: '9000', source: 'saved', setting_key: 'server.port', description: 'Port MARM listens on' },
    { name: 'MARM_API_KEY', group: 'Auth', default: null, current: 'sk-secret-value', source: 'env', setting_key: null, description: 'API key' },
    { name: 'MARM_LOG_LEVEL', group: 'Logging', default: 'INFO', current: 'INFO', source: 'default', setting_key: null, description: 'Log level' },
  ] satisfies ManualEnvItem[];
  state.snippetCalls = [];
  state.commandCalls = [];
  state.send.mockClear();
  state.available = true;
  window.history.replaceState(null, '', '/connections?tab=manual');
});

afterEach(cleanup);

async function openSection(user: ReturnType<typeof userEvent.setup>, name: string) {
  await user.click(within(screen.getByRole('navigation', { name: 'Manual sections' })).getByRole('button', { name }));
}

describe('ManualTab', () => {
  it('switches between the five sections and shows only the active one', async () => {
    const user = userEvent.setup();
    render(<ManualTab />);

    expect(screen.getByRole('heading', { name: 'Config files' })).toBeTruthy();
    expect(screen.getByLabelText('Agent')).toBeTruthy();

    await openSection(user, 'Agent commands');
    expect(screen.getByRole('heading', { name: 'Agent commands' })).toBeTruthy();
    expect(screen.queryByLabelText('Agent')).toBeNull();
    expect(screen.getByText('Claude Code')).toBeTruthy();

    await openSection(user, 'MARM CLI');
    expect(screen.getByLabelText('Command')).toBeTruthy();

    await openSection(user, 'API endpoints');
    expect(screen.getByText('http://127.0.0.1:8001/mcp')).toBeTruthy();

    await openSection(user, 'Environment');
    expect(screen.getByText('SERVER_PORT')).toBeTruthy();
  });

  it('config files sends the chosen selects to the snippet call and renders path, text and notes', async () => {
    const user = userEvent.setup();
    render(<ManualTab />);

    expect(lastCall(state.snippetCalls)).toEqual({ client: 'cursor', os: 'windows', transport: 'http', scope: 'user', target: 'local' });
    expect(screen.getByText('snippet cursor windows http user local')).toBeTruthy();
    expect(screen.getByText('/paths/cursor/windows.json')).toBeTruthy();
    expect(screen.getByText('Restart the agent after saving.')).toBeTruthy();

    const agentOptions = within(screen.getByLabelText('Agent')).getAllByRole('option').map((option) => option.textContent);
    expect(agentOptions).toEqual(['Cursor', 'Codex']);

    await user.selectOptions(screen.getByLabelText('Your system'), 'macos');
    await user.selectOptions(screen.getByLabelText('Target'), 'docker');
    await user.selectOptions(screen.getByLabelText('Transport'), 'stdio');
    await user.selectOptions(screen.getByLabelText('Scope'), 'project');
    expect(within(screen.getByLabelText('Scope')).getAllByRole('option').map((option) => option.textContent)).toEqual(['Every project', 'One project']);

    await user.selectOptions(screen.getByLabelText('Agent'), 'codex');
    expect(lastCall(state.snippetCalls)).toEqual({ client: 'codex', os: 'macos', transport: 'stdio', scope: 'user', target: 'docker' });
    expect(within(screen.getByLabelText('Transport')).getAllByRole('option').map((option) => option.textContent)).toEqual(['STDIO']);
    expect(screen.getByText('snippet codex macos stdio user docker')).toBeTruthy();
  });

  it('shows the 422 reason inline instead of a snippet', async () => {
    const user = userEvent.setup();
    render(<ManualTab />);

    await user.selectOptions(screen.getByLabelText('Transport'), 'stdio');
    await user.selectOptions(screen.getByLabelText('Scope'), 'project');

    expect(screen.getByText('Cursor does not support STDIO in one project.')).toBeTruthy();
    expect(screen.queryByText(/^snippet cursor/)).toBeNull();
  });

  it('agent commands pass the selects, copy, and send the exact command; a null command shows its note only', async () => {
    const user = userEvent.setup();
    render(<ManualTab />);
    await openSection(user, 'Agent commands');

    expect(lastCall(state.commandCalls)).toEqual({ transport: 'http', scope: 'user', target: 'local' });
    await user.selectOptions(screen.getByLabelText('Target'), 'docker');
    expect(lastCall(state.commandCalls)).toEqual({ transport: 'http', scope: 'user', target: 'docker' });

    const claudeCommand = 'claude mcp add marm --transport http http://127.0.0.1:8001/mcp';
    expect(screen.getByText(claudeCommand)).toBeTruthy();
    await user.click(screen.getByRole('button', { name: 'Copy Claude Code command' }));
    expect(await navigator.clipboard.readText()).toBe(claudeCommand);

    await user.click(screen.getByRole('button', { name: 'Send to terminal' }));
    expect(state.send).toHaveBeenCalledTimes(1);
    expect(state.send).toHaveBeenCalledWith(claudeCommand);

    expect(screen.getByText('Cursor has no command line. Use the config file.')).toBeTruthy();
    expect(screen.getAllByRole('button', { name: /Sen[dt] to terminal/ })).toHaveLength(1);
  });

  it('CLI builder builds toggles, selects and numbers in flag order and sends the exact line', async () => {
    const user = userEvent.setup();
    render(<ManualTab />);
    await openSection(user, 'MARM CLI');

    const command = () => document.querySelector('pre')?.textContent;
    expect(command()).toBe('marm-memory start');
    await user.click(screen.getByRole('switch', { name: '--no-open' }));
    await user.selectOptions(screen.getByLabelText('--profile'), 'swarm');
    await user.type(screen.getByLabelText('--port'), '9000');
    expect(command()).toBe('marm-memory start --no-open --profile swarm --port 9000');

    await user.click(screen.getByRole('button', { name: 'Send to terminal' }));
    expect(state.send).toHaveBeenCalledWith('marm-memory start --no-open --profile swarm --port 9000');

    await user.click(screen.getByRole('switch', { name: '--no-open' }));
    expect(command()).toBe('marm-memory start --profile swarm --port 9000');
  });

  it('CLI builder puts the positional first, quotes values with spaces and edits repeatable lists', async () => {
    const user = userEvent.setup();
    render(<ManualTab />);
    await openSection(user, 'MARM CLI');

    await user.selectOptions(screen.getByLabelText('Command'), 'recall');
    const command = () => document.querySelector('pre')?.textContent;
    const controls = screen.getAllByRole('textbox');
    expect(controls[0].getAttribute('aria-label')).toBe('query');

    await user.type(screen.getByLabelText('query'), 'hello world');
    await user.click(screen.getByRole('button', { name: 'Add --tag' }));
    await user.click(screen.getByRole('button', { name: 'Add --tag' }));
    await user.type(screen.getByLabelText('--tag 1'), 'alpha');
    await user.type(screen.getByLabelText('--tag 2'), 'two words');
    expect(command()).toBe('marm-memory recall "hello world" --tag alpha --tag "two words"');

    await user.click(screen.getByRole('button', { name: 'Remove --tag 1' }));
    expect(command()).toBe('marm-memory recall "hello world" --tag "two words"');
  });

  it('groups commands by top-level word and lists cli_only commands as copy-only', async () => {
    const user = userEvent.setup();
    render(<ManualTab />);
    await openSection(user, 'MARM CLI');

    const select = screen.getByLabelText('Command');
    expect(within(select).getAllByRole('group').map((group) => group.getAttribute('label'))).toEqual(['start', 'recall', 'docker']);
    expect(within(select).queryByRole('option', { name: 'key reveal' })).toBeNull();

    const box = screen.getByText('Run these yourself').parentElement as HTMLElement;
    expect(within(box).getByText('marm-memory key reveal')).toBeTruthy();
    expect(within(box).getByText('Prints a secret, so it stays in your own terminal.')).toBeTruthy();
    expect(within(box).queryByRole('button', { name: /Send/ })).toBeNull();
    await user.click(within(box).getByRole('button', { name: 'Copy key reveal' }));
    expect(await navigator.clipboard.readText()).toBe('marm-memory key reveal');
    expect(state.send).not.toHaveBeenCalled();
  });

  it('endpoints filter by search and a selected row renders curl, Python and JavaScript', async () => {
    const user = userEvent.setup();
    render(<ManualTab />);
    await openSection(user, 'API endpoints');

    expect(screen.getByText('/health')).toBeTruthy();
    await user.type(screen.getByLabelText('Search endpoints'), 'store');
    expect(screen.getByText('/memory/store')).toBeTruthy();
    expect(screen.queryByText('/memory/list')).toBeNull();
    expect(screen.queryByText('/health')).toBeNull();

    await user.click(screen.getByText('Store a memory'));
    const block = () => document.querySelector('pre')?.textContent ?? '';
    expect(block()).toBe(['curl -X POST "http://127.0.0.1:8001/memory/store" \\', '  -H "Content-Type: application/json" \\', "  -d '{}'"].join('\n'));
    expect(block()).not.toContain('Authorization');

    await user.click(screen.getByRole('tab', { name: 'Python' }));
    expect(block()).toContain('requests.request(');
    expect(block()).toContain('"http://127.0.0.1:8001/memory/store"');
    expect(block()).not.toContain('Authorization');

    await user.click(screen.getByRole('tab', { name: 'JavaScript' }));
    expect(block()).toContain('fetch("http://127.0.0.1:8001/memory/store"');
    expect(block()).toContain('method: "POST"');
    expect(block()).not.toContain('Authorization');
  });

  it('adds the key header from the environment only in key mode and never a literal key', async () => {
    state.overview = overview({ auth: { mode: 'key', key_file_exists: true } });
    const user = userEvent.setup();
    render(<ManualTab />);
    await openSection(user, 'API endpoints');
    await user.click(screen.getByText('List memories'));

    const block = () => document.querySelector('pre')?.textContent ?? '';
    expect(block()).toBe(['curl "http://127.0.0.1:8001/memory/list" \\', '  -H "Authorization: Bearer $MARM_API_KEY"'].join('\n'));

    await user.click(screen.getByRole('tab', { name: 'Python' }));
    expect(block()).toContain("os.environ['MARM_API_KEY']");
    expect(block()).toContain('import os');

    await user.click(screen.getByRole('tab', { name: 'JavaScript' }));
    expect(block()).toContain('process.env.MARM_API_KEY');
    expect(block()).not.toMatch(/sk-|Bearer [A-Za-z0-9]{8,}/);
  });

  it('explains an unavailable runtime and keeps the Console API list collapsed until opened', async () => {
    state.endpoints = { ...(state.endpoints as ManualEndpoints), runtime_available: false, reason: 'The runtime is not running.', groups: [] };
    const user = userEvent.setup();
    render(<ManualTab />);
    await openSection(user, 'API endpoints');

    expect(screen.getByText('The runtime is not running.')).toBeTruthy();
    expect(screen.getByText('http://127.0.0.1:8001/mcp')).toBeTruthy();
    expect(screen.queryByText('/api/overview')).toBeNull();
    await user.click(screen.getByRole('button', { name: /Console API/ }));
    expect(screen.getByText('/api/overview')).toBeTruthy();
  });

  it('environment filters, shows the API key only as set or not set, and Change in Setup opens the Setup tab', async () => {
    const user = userEvent.setup();
    render(<ManualTab />);
    await openSection(user, 'Environment');

    expect(screen.queryByText('sk-secret-value')).toBeNull();
    const keyRow = screen.getByText('MARM_API_KEY').closest('tr') as HTMLElement;
    expect(within(keyRow).getByText('set')).toBeTruthy();

    const portRow = screen.getByText('SERVER_PORT').closest('tr') as HTMLElement;
    expect(within(portRow).getByText('9000')).toBeTruthy();
    expect(within(portRow).getByText('saved')).toBeTruthy();
    expect(screen.getAllByRole('button', { name: 'Change in Setup' })).toHaveLength(1);

    await user.type(screen.getByLabelText('Search variables'), 'log');
    expect(screen.queryByText('SERVER_PORT')).toBeNull();
    expect(screen.getByText('MARM_LOG_LEVEL')).toBeTruthy();
    await user.clear(screen.getByLabelText('Search variables'));

    await user.click(screen.getByRole('button', { name: 'Change in Setup' }));
    expect(window.location.search).toBe('?tab=setup');
  });

  it('shows Terminal unavailable with the copy fallback and no send button when the terminal cannot run', async () => {
    state.available = false;
    const user = userEvent.setup();
    render(<ManualTab />);
    await openSection(user, 'Agent commands');

    expect(screen.queryByRole('button', { name: 'Send to terminal' })).toBeNull();
    expect(screen.getByText(/Terminal unavailable/)).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Copy Claude Code command' })).toBeTruthy();
  });

  it('shows Terminal unavailable when the send is refused', async () => {
    state.send.mockReturnValueOnce(false);
    const user = userEvent.setup();
    render(<ManualTab />);
    await openSection(user, 'Agent commands');

    await user.click(screen.getByRole('button', { name: 'Send to terminal' }));
    expect(screen.getByText(/Terminal unavailable/)).toBeTruthy();
  });

  it('keeps the send button after a refused send so the next click can retry', async () => {
    state.send.mockReturnValueOnce(false).mockReturnValueOnce(true);
    const user = userEvent.setup();
    render(<ManualTab />);
    await openSection(user, 'Agent commands');

    await user.click(screen.getByRole('button', { name: 'Send to terminal' }));
    expect(screen.getByText(/Terminal unavailable/)).toBeTruthy();

    await user.click(screen.getByRole('button', { name: 'Send to terminal' }));
    expect(state.send).toHaveBeenCalledTimes(2);
    expect(screen.queryByText(/Terminal unavailable/)).toBeNull();
    expect(screen.getByRole('button', { name: 'Sent to terminal' })).toBeTruthy();
  });
});

describe('quoteArg', () => {
  it('leaves plain values and Windows paths alone', () => {
    expect(quoteArg('swarm')).toBe('swarm');
    expect(quoteArg('C:\\Users\\me\\.marm')).toBe('C:\\Users\\me\\.marm');
    expect(quoteArg('http://127.0.0.1:8001/mcp')).toBe('http://127.0.0.1:8001/mcp');
  });

  it('double-quotes whitespace and shell separators', () => {
    expect(quoteArg('hello world')).toBe('"hello world"');
    expect(quoteArg('a;b')).toBe('"a;b"');
    expect(quoteArg('say "hi"')).toBe('"say \\"hi\\""');
  });

  it('escapes backslashes in double-quoted values', () => {
    expect(quoteArg('C:\\Program Files\\')).toBe('"C:\\\\Program Files\\\\"');
    expect(quoteArg('C:\\Program Files\\x')).toBe('"C:\\\\Program Files\\\\x"');
  });

  it('keeps a backslash before a double quote as one literal backslash and one literal quote', () => {
    expect(quoteArg('a\\"b c')).toBe('"a\\\\\\"b c"');
    expect(quoteArg('x\\\\"y z')).toBe('"x\\\\\\\\\\"y z"');
  });

  it('single-quotes a value that would otherwise expand', () => {
    expect(quoteArg('$(id)')).toBe("'$(id)'");
    expect(quoteArg('`whoami`')).toBe("'`whoami`'");
  });

  it('escapes the expanding characters when a single quote rules out single quoting', () => {
    expect(quoteArg("it's $HOME")).toBe('"it\'s \\$HOME"');
  });
});
