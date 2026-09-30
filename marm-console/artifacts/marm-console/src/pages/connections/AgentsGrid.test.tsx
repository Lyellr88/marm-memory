import { cleanup, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { AgentsGrid } from './AgentsGrid';
import type { Agent, AgentsResponse } from '@/lib/marm-types';

const agentsState = vi.hoisted(() => ({
  data: undefined as AgentsResponse | undefined,
  isLoading: false,
  isError: false,
  error: null as unknown,
}));
const idle = vi.hoisted(() => ({ mutate: vi.fn(), isPending: false, variables: undefined }));

vi.mock('@/hooks/use-marm-queries', () => ({
  useAgents: () => agentsState,
  useProjects: () => ({ data: [] }),
  useAgentScope: () => ({ data: undefined, isLoading: false, isError: false, error: null }),
  useConfigureAgent: () => idle,
  useRemoveAgent: () => idle,
  useTestAgent: () => idle,
  useInstallAgentSkill: () => idle,
}));

function agent(over: Partial<Agent> = {}): Agent {
  return {
    id: 'cursor',
    label: 'Cursor',
    detected: true,
    transports: ['http', 'stdio'],
    scopes: ['user'],
    user: { scope: 'user', project: null, config_path: 'C:\\Users\\me\\.cursor\\mcp.json', config_exists: true, state: 'missing', transport_detected: null, current_entry: null },
    skill: { supported: false, installed: false },
    notes: [],
    unavailable: {},
    ...over,
  };
}

function response(over: Partial<AgentsResponse> = {}): AgentsResponse {
  return { auth_required: false, configure_allowed: true, configure_blocked_reason: null, clients: [agent()], ...over };
}

beforeEach(() => {
  agentsState.data = response();
  agentsState.isLoading = false;
  agentsState.isError = false;
  agentsState.error = null;
});

afterEach(cleanup);

describe('AgentsGrid', () => {
  it('renders a card per agent with its state pill', () => {
    agentsState.data = response({
      clients: [
        agent({ id: 'cursor', label: 'Cursor' }),
        agent({ id: 'codex', label: 'Codex CLI', user: { ...agent().user, state: 'configured' } }),
        agent({ id: 'antigravity', label: 'Antigravity', user: { ...agent().user, state: 'different' } }),
        agent({ id: 'qwen', label: 'Qwen Code', user: { ...agent().user, state: 'unreadable' } }),
      ],
    });
    render(<AgentsGrid onRequest={() => {}} allowedTransports={['http', 'stdio']} />);

    expect(screen.getByText('Cursor')).toBeTruthy();
    expect(screen.getByText('Not connected')).toBeTruthy();
    expect(screen.getByText('Connected')).toBeTruthy();
    expect(screen.getByText('Needs update')).toBeTruthy();
    expect(screen.getByText("Can't read file")).toBeTruthy();
  });

  it('shows the blocked banner and disables the actions on every card', () => {
    agentsState.data = response({
      configure_allowed: false,
      configure_blocked_reason: 'The Console is not bound to loopback.',
      clients: [agent({ id: 'cursor' }), agent({ id: 'codex', label: 'Codex CLI' })],
    });
    render(<AgentsGrid onRequest={() => {}} allowedTransports={['http', 'stdio']} />);

    expect(screen.getByText('The Console is not bound to loopback.')).toBeTruthy();
    const connects = screen.getAllByRole('button', { name: 'Connect' });
    expect(connects).toHaveLength(2);
    connects.forEach((button) => expect((button as HTMLButtonElement).disabled).toBe(true));
  });

  it('shows agents that have a transport allowed on this tab', () => {
    agentsState.data = response({
      clients: [
        agent({ id: 'cursor', label: 'Cursor' }),
        agent({ id: 'claude-desktop', label: 'Claude Desktop', transports: ['stdio', 'docker-stdio'] }),
      ],
    });
    render(<AgentsGrid onRequest={() => {}} allowedTransports={['http', 'docker-stdio']} />);

    expect(screen.getByText('Cursor')).toBeTruthy();
    expect(screen.getByText('Claude Desktop')).toBeTruthy();
    expect(screen.getAllByRole('button', { name: 'Docker STDIO' })).toHaveLength(1);
  });

  it('groups agents under CLI and IDE headings and sends Claude Desktop and unknown ids to Other', () => {
    agentsState.data = response({
      clients: [
        agent({ id: 'codex', label: 'Codex CLI' }),
        agent({ id: 'claude-desktop', label: 'Claude Desktop' }),
        agent({ id: 'vscode', label: 'VS Code' }),
        agent({ id: 'newtool', label: 'New Tool' }),
      ],
    });
    render(<AgentsGrid onRequest={() => {}} allowedTransports={['http', 'stdio']} />);

    const headings = screen.getAllByRole('heading', { level: 3 }).map((h) => h.textContent);
    expect(headings).toEqual(['CLI tools', 'IDEs', 'Other']);
    const order = screen.getAllByText(/^(Codex CLI|Claude Desktop|VS Code|New Tool)$/).map((el) => el.textContent);
    expect(order).toEqual(['Codex CLI', 'VS Code', 'Claude Desktop', 'New Tool']);
  });

  it('puts Grok Build and OpenCode under CLI tools, Cline, Antigravity, Cursor and Devin under CLI and IDE, and Claude Desktop under Other', () => {
    agentsState.data = response({
      clients: [
        agent({ id: 'claude-desktop', label: 'Claude Desktop' }),
        agent({ id: 'grok', label: 'Grok Build' }),
        agent({ id: 'hermes', label: 'Hermes Agent', scopes: ['user'] }),
        agent({ id: 'opencode', label: 'OpenCode' }),
        agent({ id: 'cline', label: 'Cline', scopes: ['user'] }),
        agent({ id: 'antigravity', label: 'Antigravity' }),
        agent({ id: 'cursor', label: 'Cursor' }),
        agent({ id: 'devin', label: 'Devin' }),
      ],
    });
    render(<AgentsGrid onRequest={() => {}} allowedTransports={['http', 'stdio']} />);

    const headings = screen.getAllByRole('heading', { level: 3 }).map((h) => h.textContent);
    expect(headings).toEqual(['CLI tools', 'CLI and IDE', 'Other']);
    const order = screen.getAllByText(/^(Grok Build|Hermes Agent|OpenCode|Cline|Antigravity|Cursor|Devin|Claude Desktop)$/).map((el) => el.textContent);
    expect(order).toEqual(['Grok Build', 'Hermes Agent', 'OpenCode', 'Cline', 'Antigravity', 'Cursor', 'Devin', 'Claude Desktop']);
  });

  it('puts Zed under IDEs beside VS Code', () => {
    agentsState.data = response({
      clients: [agent({ id: 'vscode', label: 'VS Code' }), agent({ id: 'zed', label: 'Zed', scopes: ['user'] })],
    });
    render(<AgentsGrid onRequest={() => {}} allowedTransports={['http', 'stdio']} />);

    const headings = screen.getAllByRole('heading', { level: 3 }).map((h) => h.textContent);
    expect(headings).toEqual(['IDEs', 'Other']);
    expect(screen.getAllByText(/^(VS Code|Zed)$/).map((el) => el.textContent)).toEqual(['VS Code', 'Zed']);
  });

  it('hides a group with no agents', () => {
    agentsState.data = response({ clients: [agent({ id: 'vscode' })] });
    render(<AgentsGrid onRequest={() => {}} allowedTransports={['http', 'stdio']} />);

    const headings = screen.getAllByRole('heading', { level: 3 }).map((h) => h.textContent);
    expect(headings).toEqual(['IDEs', 'Other']);
  });

  it('shows the error when agents cannot be read', () => {
    agentsState.data = undefined;
    agentsState.isError = true;
    agentsState.error = new Error('Connections are down.');
    render(<AgentsGrid onRequest={() => {}} allowedTransports={['http', 'stdio']} />);

    expect(screen.getByText('Connections are down.')).toBeTruthy();
  });

  it('ends the grid with a request card that calls onRequest', async () => {
    const user = userEvent.setup();
    const onRequest = vi.fn();
    render(<AgentsGrid onRequest={onRequest} allowedTransports={['http', 'stdio']} />);

    const last = screen.getAllByRole('button').at(-1) as HTMLElement;
    expect(last.textContent).toBe('Request a connection');
    await user.click(last);
    expect(onRequest).toHaveBeenCalledTimes(1);
  });
});
