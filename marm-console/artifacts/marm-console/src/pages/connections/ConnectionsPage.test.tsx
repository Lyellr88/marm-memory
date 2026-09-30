import { cleanup, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ConnectionsPage } from './index';
import type { ConnectionsOverview } from '@/lib/marm-types';

const overviewState = vi.hoisted(() => ({ data: undefined as ConnectionsOverview | undefined }));

vi.mock('@/hooks/use-marm-queries', () => {
  const idle = { mutate: vi.fn(), isPending: false, error: null, data: undefined };
  return {
    useConnectionsOverview: () => overviewState,
    useSetupSettings: () => ({ data: undefined, isLoading: true, isError: false, error: null }),
    useUpdateSetupSettings: () => idle,
    useStartRuntimeRestart: () => idle,
    useRuntimeRestartJob: () => ({ data: undefined }),
    useRuntimeSettings: () => ({ data: undefined }),
    useUpdateRuntimeProfile: () => idle,
    useUpdateRuntimeAutomation: () => idle,
    useUpdateLlmSettings: () => idle,
    useAgents: () => ({ data: { auth_required: false, configure_allowed: true, configure_blocked_reason: null, clients: [] }, isLoading: false, isError: false, error: null }),
    useDocker: () => ({ data: { engine: { available: false, daemon: false, version: null, reason: 'docker not found' }, in_container: false, read_only_reason: null, container: { state: 'absent', name: 'marm-mcp-server' }, config: { port: 8001, tag: 'latest', data_dir: '~/.marm', repos: [], memory: null, cpus: null, expose_network: false, profile: 'standard', rate_limit_rpm: null }, url: 'http://127.0.0.1:8001/mcp' }, isLoading: false, isError: false, error: null, isFetching: false, refetch: vi.fn() }),
    useUpdateDockerConfig: () => idle,
    useDockerAction: () => idle,
    useDockerControl: () => idle,
    useDockerJob: () => ({ data: undefined }),
    useDockerLogs: () => ({ data: undefined }),
    useDockerCompose: () => ({ data: undefined }),
    useWriteDockerCompose: () => idle,
    useManualSnippet: () => ({ data: undefined, isLoading: true, isError: false, error: null }),
    useManualAgentCommands: () => ({ data: undefined, isLoading: true, isError: false, error: null }),
    useManualCli: () => ({ data: undefined, isLoading: true, isError: false, error: null }),
    useManualEndpoints: () => ({ data: undefined, isLoading: true, isError: false, error: null }),
    useManualEnv: () => ({ data: undefined, isLoading: true, isError: false, error: null }),
  };
});

function overview(over: Partial<ConnectionsOverview> = {}): ConnectionsOverview {
  return {
    version: '2.54.1',
    os: 'Windows 11',
    runtime: { state: 'ready', managed: true, url: '127.0.0.1:8001', profile: 'standard' },
    auth: { mode: 'local only', key_file_exists: false },
    agents: { connected: 3, detected: 9 },
    skills_installed: 2,
    checklist: [],
    ...over,
  };
}

beforeEach(() => {
  overviewState.data = overview();
  window.history.replaceState(null, '', '/connections');
});

afterEach(cleanup);

describe('ConnectionsPage', () => {
  it('shows the header, status strip values and the Setup tab first', () => {
    render(<ConnectionsPage />);

    expect(screen.getByText('Setup', { selector: 'div' })).toBeTruthy();
    expect(screen.getByRole('heading', { name: 'Connections' })).toBeTruthy();
    const strip = within(screen.getByLabelText('Setup status'));
    expect(strip.getByText('running')).toBeTruthy();
    expect(strip.getByText(/127\.0\.0\.1:8001/)).toBeTruthy();
    expect(strip.getByText('local only')).toBeTruthy();
    expect(strip.getByText('3 of 9 connected')).toBeTruthy();
    expect(strip.getByText('2 agents')).toBeTruthy();
    expect(strip.getByText('2.54.1')).toBeTruthy();
    expect(screen.getByRole('tab', { name: 'Setup' }).getAttribute('data-state')).toBe('active');
    expect(screen.getByText('Server settings')).toBeTruthy();
  });

  it('switches tabs, keeps ?tab in the address, and shows the Docker tab content', async () => {
    const user = userEvent.setup();
    render(<ConnectionsPage />);

    await user.click(screen.getByRole('tab', { name: 'Docker' }));
    expect(window.location.search).toBe('?tab=docker');
    expect(screen.getByText('MARM in Docker')).toBeTruthy();
    expect(screen.getByText('Docker is not installed on this machine.')).toBeTruthy();
    expect(screen.getByRole('heading', { name: 'Agents on Docker' })).toBeTruthy();
    expect(screen.queryByText('Server settings')).toBeNull();

    await user.click(screen.getByRole('tab', { name: 'Manual' }));
    expect(window.location.search).toBe('?tab=manual');
    const nav = within(screen.getByRole('navigation', { name: 'Manual sections' }));
    for (const name of ['Config files', 'Agent commands', 'MARM CLI', 'API endpoints', 'Environment']) expect(nav.getByRole('button', { name })).toBeTruthy();
    expect(screen.queryByText('Server settings')).toBeNull();

    await user.click(screen.getByRole('tab', { name: 'Setup' }));
    expect(window.location.search).toBe('?tab=setup');
    expect(screen.getByText('Server settings')).toBeTruthy();
  });

  it('opens on the tab named in the address and falls back to Setup for an unknown one', () => {
    window.history.replaceState(null, '', '/connections?tab=manual');
    const first = render(<ConnectionsPage />);
    expect(screen.getByRole('tab', { name: 'Manual' }).getAttribute('data-state')).toBe('active');
    first.unmount();

    window.history.replaceState(null, '', '/connections?tab=bogus');
    render(<ConnectionsPage />);
    expect(screen.getByRole('tab', { name: 'Setup' }).getAttribute('data-state')).toBe('active');
  });

  it('opens Add a connection from the header and from the request card', async () => {
    const user = userEvent.setup();
    render(<ConnectionsPage />);

    await user.click(screen.getByRole('button', { name: /Add a connection/ }));
    expect(screen.getByRole('dialog')).toBeTruthy();
    expect(screen.getByLabelText('Tool name')).toBeTruthy();
    await user.click(screen.getByRole('button', { name: 'Close' }));
    expect(screen.queryByRole('dialog')).toBeNull();

    await user.click(screen.getByRole('button', { name: 'Request a connection' }));
    expect(screen.getByRole('dialog')).toBeTruthy();
  });
});
