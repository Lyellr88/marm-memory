import { cleanup, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { DockerTab } from './DockerTab';
import { MarmApiError } from '@/lib/marm-api';
import type { Agent, DockerConfig, DockerContainer, DockerJob, DockerOverview } from '@/lib/marm-types';

type Callbacks = { onSuccess?: (result: unknown) => void; onError?: (err: unknown) => void };

type Mutation = { mutate: ReturnType<typeof vi.fn>; isPending: boolean };
type Refetching = { data: unknown; isError: boolean; error: unknown; isFetching: boolean; refetch: ReturnType<typeof vi.fn> };

const state = vi.hoisted(() => ({
  docker: { data: undefined, isLoading: false, isError: false, error: null, isFetching: false, refetch: vi.fn() } as Refetching & { isLoading: boolean },
  job: undefined as unknown,
  jobIds: [] as Array<string | null>,
  logs: { data: undefined, isError: false, error: null, isFetching: false, refetch: vi.fn() } as Refetching,
  logsEnabled: [] as boolean[],
  compose: { data: undefined, isError: false, error: null } as Record<string, unknown>,
  composeEnabled: [] as boolean[],
  update: { mutate: vi.fn(), isPending: false } as Mutation,
  actions: {} as Record<string, Mutation>,
  controls: {} as Record<string, Mutation>,
  write: { mutate: vi.fn(), isPending: false } as Mutation,
  agentsTarget: [] as Array<string | undefined>,
  agentScopeTarget: [] as Array<string | undefined>,
  configure: { mutate: () => {}, isPending: false, variables: undefined } as Record<string, unknown>,
  agents: [] as unknown[],
}));

vi.mock('@/hooks/use-marm-queries', () => {
  const idle = { mutate: () => {}, isPending: false, variables: undefined };
  return {
    useDocker: () => state.docker,
    useUpdateDockerConfig: () => state.update,
    useDockerAction: (kind: string) => state.actions[kind],
    useDockerControl: (kind: string) => state.controls[kind],
    useDockerJob: (id: string | null) => { state.jobIds.push(id); return { data: state.job }; },
    useDockerLogs: (enabled: boolean) => { state.logsEnabled.push(enabled); return state.logs; },
    useDockerCompose: (enabled: boolean) => { state.composeEnabled.push(enabled); return state.compose; },
    useWriteDockerCompose: () => state.write,
    useAgents: (target?: string) => {
      state.agentsTarget.push(target);
      return { data: { auth_required: true, configure_allowed: true, configure_blocked_reason: null, clients: state.agents }, isLoading: false, isError: false, error: null };
    },
    useProjects: () => ({ data: [] }),
    useAgentScope: (_id: string, _scope: string, _project: unknown, _enabled: boolean, target?: string) => {
      state.agentScopeTarget.push(target);
      return { data: undefined, isLoading: false, isError: false, error: null };
    },
    useConfigureAgent: () => state.configure,
    useRemoveAgent: () => idle,
    useTestAgent: () => idle,
    useInstallAgentSkill: () => idle,
  };
});

function config(over: Partial<DockerConfig> = {}): DockerConfig {
  return { port: 8001, tag: 'latest', data_dir: 'C:\\Users\\me\\.marm', repos: ['C:\\code\\app'], memory: null, cpus: null, expose_network: false, profile: 'standard', rate_limit_rpm: null, ...over };
}

function container(over: Partial<DockerContainer> = {}): DockerContainer {
  return {
    state: 'running',
    name: 'marm-mcp-server',
    health: 'healthy',
    image: 'lyellr88/marm-mcp-server:latest',
    profile: 'standard',
    ports: { '8001/tcp': [{ HostIp: '127.0.0.1', HostPort: '8001' }] },
    mounts: [{ source: 'C:\\Users\\me\\.marm', destination: '/home/marm/.marm' }],
    ...over,
  };
}

function overview(over: Partial<DockerOverview> = {}): DockerOverview {
  return {
    engine: { available: true, daemon: true, version: '27.0.1', reason: null },
    in_container: false,
    read_only_reason: null,
    container: container(),
    config: config(),
    url: 'http://127.0.0.1:8001/mcp',
    ...over,
  };
}

function agent(): Agent {
  return {
    id: 'cursor',
    label: 'Cursor',
    detected: true,
    transports: ['http', 'stdio', 'docker-stdio'],
    scopes: ['user'],
    user: { scope: 'user', project: null, config_path: 'C:\\Users\\me\\.cursor\\mcp.json', config_exists: true, state: 'missing', transport_detected: null, current_entry: null },
    skill: { supported: false, installed: false },
    notes: [],
    unavailable: {},
  };
}

function settling(result: unknown) {
  return vi.fn((_vars: unknown, opts?: Callbacks) => opts?.onSuccess?.(result));
}

function failing(error: unknown) {
  return vi.fn((_vars: unknown, opts?: Callbacks) => opts?.onError?.(error));
}

function setDocker(data: DockerOverview) {
  state.docker = { ...state.docker, data };
}

beforeEach(() => {
  state.docker = { data: overview(), isLoading: false, isError: false, error: null, isFetching: false, refetch: vi.fn(() => Promise.resolve()) };
  state.job = undefined;
  state.jobIds = [];
  state.logs = { data: { lines: ['line one', 'line two'] }, isError: false, error: null, isFetching: false, refetch: vi.fn(() => Promise.resolve()) };
  state.logsEnabled = [];
  state.compose = { data: { path: 'C:\\Users\\me\\.marm\\docker-compose.yml', exists: false, yaml: 'services:\n  marm:\n    image: x', command: 'docker compose up -d' }, isError: false, error: null };
  state.composeEnabled = [];
  state.update = { mutate: settling(undefined), isPending: false };
  state.actions = {
    pull: { mutate: settling({ job_id: 'pull-1' }), isPending: false },
    start: { mutate: settling({ job_id: 'start-1' }), isPending: false },
    recreate: { mutate: settling({ job_id: 'recreate-1' }), isPending: false },
  };
  state.controls = {
    stop: { mutate: settling(undefined), isPending: false },
    restart: { mutate: settling(undefined), isPending: false },
  };
  state.write = { mutate: settling({ path: 'C:\\Users\\me\\.marm\\docker-compose.yml', command: 'docker compose up -d' }), isPending: false };
  state.agentsTarget = [];
  state.agentScopeTarget = [];
  state.configure = { mutate: vi.fn(), isPending: false, variables: undefined };
  state.agents = [agent()];
});

afterEach(cleanup);

const renderTab = () => render(<DockerTab onRequestConnection={() => {}} />);
const button = (name: string | RegExp) => screen.getByRole('button', { name }) as HTMLButtonElement;
const field = (label: string) => screen.getByLabelText(label) as HTMLInputElement;

describe('DockerTab engine states', () => {
  it('says Docker is not installed and links to the installer', () => {
    setDocker(overview({ engine: { available: false, daemon: false, version: null, reason: 'docker not found' } }));
    renderTab();

    expect(screen.getByText('Docker is not installed on this machine.')).toBeTruthy();
    const link = screen.getByRole('link', { name: 'Install Docker Desktop' });
    expect(link.getAttribute('href')).toBe('https://docs.docker.com/get-docker/');
    expect(screen.queryByRole('button', { name: 'Pull latest' })).toBeNull();
  });

  it('says the daemon is not running and offers a working refresh', async () => {
    setDocker(overview({ engine: { available: true, daemon: false, version: null, reason: 'daemon down' } }));
    renderTab();

    expect(screen.getByText('Docker is installed but not running. Start Docker Desktop, then refresh.')).toBeTruthy();
    expect(screen.queryByRole('button', { name: 'Pull latest' })).toBeNull();
    await userEvent.setup().click(button('Refresh'));
    expect(state.docker.refetch).toHaveBeenCalledTimes(1);
  });

  it('shows the read-only reason inside a container and disables every action and field', () => {
    setDocker(overview({ in_container: true, read_only_reason: 'The Console runs inside a container.' }));
    renderTab();

    expect(screen.getByText('The Console runs inside a container.')).toBeTruthy();
    for (const name of ['Restart', 'Stop', 'Pull latest', 'Save', 'Save and recreate container', 'Write compose file', 'Add repository']) {
      expect(button(name).disabled, name).toBe(true);
    }
    expect(field('Image tag').disabled).toBe(true);
    expect(field('Host port').disabled).toBe(true);
    expect(field('Repository folder 1').disabled).toBe(true);
    expect((screen.getByRole('switch', { name: 'Reachable from other devices' }) as HTMLButtonElement).disabled).toBe(true);
  });
});

describe('DockerTab container card', () => {
  it('shows image, running pill, health, host port, mounts and profile', () => {
    renderTab();

    expect(screen.getByText('lyellr88/marm-mcp-server:latest')).toBeTruthy();
    expect(screen.getByText('Running').className).toContain('emerald');
    expect(screen.getByText('healthy')).toBeTruthy();
    expect(screen.getByText('127.0.0.1:8001 to 8001/tcp')).toBeTruthy();
    expect(screen.getByText(/C:\\Users\\me\\\.marm to \/home\/marm\/\.marm/)).toBeTruthy();
    expect(screen.getAllByText('standard').length).toBeGreaterThan(0);
  });

  it('offers Restart, Stop and Pull latest while running', () => {
    renderTab();
    expect(button('Restart').disabled).toBe(false);
    expect(button('Stop').disabled).toBe(false);
    expect(button('Pull latest').disabled).toBe(false);
    expect(screen.queryByRole('button', { name: 'Start' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Create and start' })).toBeNull();
  });

  it('offers Start with an amber pill when the container has exited', async () => {
    setDocker(overview({ container: container({ state: 'exited' }) }));
    renderTab();

    expect(screen.getByText('Exited').className).toContain('amber');
    expect(screen.queryByRole('button', { name: 'Stop' })).toBeNull();
    await userEvent.setup().click(button('Start'));
    expect(state.actions.start.mutate).toHaveBeenCalledTimes(1);
    expect(screen.getByText('Starting container...')).toBeTruthy();
  });

  it('offers Create and start with a grey Not created pill when absent', async () => {
    setDocker(overview({ container: { state: 'absent', name: 'marm-mcp-server' } }));
    renderTab();

    expect(screen.getByText('Not created').className).toContain('border-border');
    expect(screen.queryByRole('button', { name: 'Restart' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Logs' })).toBeNull();
    await userEvent.setup().click(button('Create and start'));
    expect(state.actions.start.mutate).toHaveBeenCalledTimes(1);
  });

  it('restarts immediately and shows an error when it fails', async () => {
    const user = userEvent.setup();
    renderTab();
    await user.click(button('Restart'));
    expect(state.controls.restart.mutate).toHaveBeenCalledTimes(1);

    state.controls.restart = { mutate: failing(new MarmApiError(500, 'Docker refused the restart.')), isPending: false };
    cleanup();
    renderTab();
    await user.click(button('Restart'));
    expect(screen.getByText('Docker refused the restart.')).toBeTruthy();
  });

  it('asks before stopping and only stops on confirm', async () => {
    const user = userEvent.setup();
    renderTab();

    await user.click(button('Stop'));
    const dialog = within(screen.getByRole('dialog'));
    expect(dialog.getByText('Agents using Docker lose MARM until you start it again.')).toBeTruthy();
    expect(state.controls.stop.mutate).not.toHaveBeenCalled();

    await user.click(dialog.getByRole('button', { name: 'Cancel' }));
    expect(state.controls.stop.mutate).not.toHaveBeenCalled();

    await user.click(button('Stop'));
    await user.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Stop' }));
    expect(state.controls.stop.mutate).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole('dialog')).toBeNull();
  });

  it('toggles the last 200 log lines and refreshes them', async () => {
    const user = userEvent.setup();
    renderTab();
    expect(screen.queryByLabelText('Container logs')).toBeNull();
    expect(state.logsEnabled.every((enabled) => enabled === false)).toBe(true);

    await user.click(button('Logs'));
    expect(screen.getByLabelText('Container logs').textContent).toBe('line one\nline two');
    expect(state.logsEnabled.at(-1)).toBe(true);

    await user.click(button('Refresh logs'));
    expect(state.logs.refetch).toHaveBeenCalledTimes(1);

    await user.click(button('Hide logs'));
    expect(screen.queryByLabelText('Container logs')).toBeNull();
  });
});

describe('DockerTab job progress', () => {
  it('names the job while it runs and polls its id, then reports seconds when done', async () => {
    const user = userEvent.setup();
    state.job = { job_id: 'pull-1', kind: 'pull', status: 'running' } satisfies DockerJob;
    renderTab();
    await user.click(button('Pull latest'));

    expect(screen.getByText('Pulling image...')).toBeTruthy();
    expect(state.jobIds.at(-1)).toBe('pull-1');
    expect(button('Pull latest').disabled).toBe(true);
    expect(button('Restart').disabled).toBe(true);

    state.job = { job_id: 'pull-1', kind: 'pull', status: 'done', seconds: 12.34 } satisfies DockerJob;
    cleanup();
    renderTab();
    await user.click(button('Pull latest'));
    expect(screen.getByText('Image pulled in 12.3 s')).toBeTruthy();
    expect(button('Pull latest').disabled).toBe(false);
  });

  it('shows the error detail when the job fails', async () => {
    state.job = { job_id: 'start-1', kind: 'start', status: 'error', detail: 'port 8001 is already in use' } satisfies DockerJob;
    setDocker(overview({ container: container({ state: 'exited' }) }));
    renderTab();
    await userEvent.setup().click(button('Start'));

    expect(screen.getByText('port 8001 is already in use')).toBeTruthy();
    expect(screen.queryByText('Starting container...')).toBeNull();
  });

  it('shows the request error when the job cannot start', async () => {
    state.actions.pull = { mutate: failing(new MarmApiError(409, 'Docker routes are read-only here.')), isPending: false };
    renderTab();
    await userEvent.setup().click(button('Pull latest'));
    expect(screen.getByText('Docker routes are read-only here.')).toBeTruthy();
  });
});

describe('DockerTab run configuration', () => {
  it('fills the form from the saved config and starts clean', () => {
    setDocker(overview({ config: config({ port: 9000, tag: '2.5', memory: '2g', cpus: '1.5', rate_limit_rpm: 300, profile: 'swarm' }) }));
    renderTab();

    expect(field('Image tag').value).toBe('2.5');
    expect(field('Host port').value).toBe('9000');
    expect(field('Memory').value).toBe('2g');
    expect(field('CPUs').value).toBe('1.5');
    expect(field('Data folder').value).toBe('C:\\Users\\me\\.marm');
    expect(field('Repository folder 1').value).toBe('C:\\code\\app');
    expect((screen.getByLabelText('Profile') as HTMLSelectElement).value).toBe('swarm');
    expect(field('Rate limit per minute').value).toBe('300');
    expect(screen.getByText('Mounted read-only so MARM can index them.')).toBeTruthy();
    expect(screen.getByText('Requires a key. MARM creates one if needed.')).toBeTruthy();
    expect(screen.getByText('No unsaved changes.')).toBeTruthy();
    expect(button('Save').disabled).toBe(true);
  });

  it('tracks dirty state, saves the typed config, and discards', async () => {
    const user = userEvent.setup();
    renderTab();

    await user.clear(field('Host port'));
    await user.type(field('Host port'), '9100');
    await user.type(field('Memory'), '4g');
    await user.selectOptions(screen.getByLabelText('Profile'), 'trusted');
    await user.click(screen.getByRole('switch', { name: 'Reachable from other devices' }));
    expect(screen.getByText('You have unsaved changes.')).toBeTruthy();

    await user.click(button('Save'));
    expect(state.update.mutate).toHaveBeenCalledTimes(1);
    expect((state.update.mutate as ReturnType<typeof vi.fn>).mock.calls[0][0]).toEqual(config({ port: 9100, memory: '4g', profile: 'trusted', expose_network: true }));
    expect(screen.getByText('No unsaved changes.')).toBeTruthy();

    await user.type(field('Image tag'), 'x');
    expect(screen.getByText('You have unsaved changes.')).toBeTruthy();
    await user.click(button('Discard'));
    expect(field('Image tag').value).toBe('latest');
    expect(screen.getByText('No unsaved changes.')).toBeTruthy();
  });

  it('returns to clean when an edit is typed back to the saved value', async () => {
    const user = userEvent.setup();
    renderTab();
    await user.type(field('Image tag'), 'x');
    await user.type(field('Image tag'), '{Backspace}');
    expect(screen.getByText('No unsaved changes.')).toBeTruthy();
    expect(button('Save').disabled).toBe(true);
  });

  it('blocks saving an out-of-range port', async () => {
    const user = userEvent.setup();
    renderTab();
    await user.clear(field('Host port'));
    await user.type(field('Host port'), '70000');

    expect(button('Save').disabled).toBe(true);
    expect(button('Save and recreate container').disabled).toBe(true);
    expect(screen.getByText('Enter a port from 1 to 65535 and a whole number for the rate limit.')).toBeTruthy();
  });

  it('shows a save error from the server', async () => {
    state.update = { mutate: failing(new MarmApiError(422, 'port must be between 1 and 65535')), isPending: false };
    const user = userEvent.setup();
    renderTab();
    await user.type(field('Image tag'), 'x');
    await user.click(button('Save'));
    expect(screen.getByText('port must be between 1 and 65535')).toBeTruthy();
  });

  it('confirms before saving and recreating, then saves first and starts the recreate job', async () => {
    const user = userEvent.setup();
    renderTab();
    await user.type(field('Image tag'), '-beta');

    await user.click(button('Save and recreate container'));
    expect(state.update.mutate).not.toHaveBeenCalled();
    expect(state.actions.recreate.mutate).not.toHaveBeenCalled();

    await user.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Save and recreate' }));
    expect((state.update.mutate as ReturnType<typeof vi.fn>).mock.calls[0][0]).toEqual(config({ tag: 'latest-beta' }));
    expect(state.actions.recreate.mutate).toHaveBeenCalledTimes(1);
    expect(state.jobIds.at(-1)).toBe('recreate-1');
    expect(screen.getByText('Recreating container...')).toBeTruthy();
  });

  it('does not recreate when saving fails', async () => {
    state.update = { mutate: failing(new MarmApiError(422, 'bad tag')), isPending: false };
    const user = userEvent.setup();
    renderTab();
    await user.type(field('Image tag'), ' x');
    await user.click(button('Save and recreate container'));
    await user.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Save and recreate' }));

    expect(state.actions.recreate.mutate).not.toHaveBeenCalled();
    expect(screen.getByText('bad tag')).toBeTruthy();
  });

  it('adds and removes repository rows and saves them trimmed without blanks', async () => {
    const user = userEvent.setup();
    renderTab();

    await user.click(button('Add repository'));
    await user.type(field('Repository folder 2'), '  C:\\code\\api  ');
    await user.click(button('Add repository'));
    expect(screen.getByLabelText('Repository folder 3')).toBeTruthy();

    await user.click(button('Remove repository 1'));
    expect(field('Repository folder 1').value).toBe('  C:\\code\\api  ');
    expect(screen.queryByLabelText('Repository folder 3')).toBeNull();

    await user.click(button('Save'));
    expect((state.update.mutate as ReturnType<typeof vi.fn>).mock.calls[0][0].repos).toEqual(['C:\\code\\api']);
  });

  it('sends an empty rate limit as null and a typed one as a number', async () => {
    const user = userEvent.setup();
    setDocker(overview({ config: config({ rate_limit_rpm: 300 }) }));
    renderTab();
    await user.clear(field('Rate limit per minute'));
    await user.click(button('Save'));
    expect((state.update.mutate as ReturnType<typeof vi.fn>).mock.calls[0][0].rate_limit_rpm).toBeNull();
  });
});

describe('DockerTab compose file', () => {
  it('previews the yaml with its command only after asking', async () => {
    const user = userEvent.setup();
    renderTab();
    expect(state.composeEnabled.every((enabled) => enabled === false)).toBe(true);
    expect(screen.queryByLabelText('Compose file preview')).toBeNull();

    await user.click(button('Preview compose'));
    expect(state.composeEnabled.at(-1)).toBe(true);
    expect(screen.getByLabelText('Compose file preview').textContent).toContain('image: x');
    expect(screen.getByText('docker compose up -d')).toBeTruthy();

    await user.click(button('Hide compose preview'));
    expect(screen.queryByLabelText('Compose file preview')).toBeNull();
  });

  it('writes the file and shows its path and command', async () => {
    await userEvent.setup().click((renderTab(), button('Write compose file')));

    expect((state.write.mutate as ReturnType<typeof vi.fn>).mock.calls[0][0]).toBe(false);
    expect(screen.getByText('C:\\Users\\me\\.marm\\docker-compose.yml')).toBeTruthy();
    expect(screen.getByText('docker compose up -d')).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Copy command' })).toBeTruthy();
  });

  it('on 409 names the existing file and re-posts with overwrite true', async () => {
    const mutate = vi.fn((overwrite: boolean, opts?: Callbacks) => {
      if (!overwrite) opts?.onError?.(new MarmApiError(409, 'exists', { detail: { reason: 'exists', path: 'C:\\Users\\me\\.marm\\docker-compose.yml' } }));
      else opts?.onSuccess?.({ path: 'C:\\Users\\me\\.marm\\docker-compose.yml', command: 'docker compose up -d', backup_path: 'C:\\Users\\me\\.marm\\docker-compose.yml.marm-backup' });
    });
    state.write = { mutate, isPending: false };
    const user = userEvent.setup();
    renderTab();

    await user.click(button('Write compose file'));
    expect(screen.getByText('A compose file already exists at C:\\Users\\me\\.marm\\docker-compose.yml.')).toBeTruthy();
    expect(mutate.mock.calls[0][0]).toBe(false);

    await user.click(button('Overwrite'));
    expect(mutate.mock.calls[1][0]).toBe(true);
    expect(screen.queryByText(/already exists/)).toBeNull();
    expect(screen.getByText(/Compose file written to/)).toBeTruthy();
  });

  it('shows a 409 that is not an existing file as an error instead of an overwrite prompt', async () => {
    state.write = { mutate: failing(new MarmApiError(409, 'Repository path must exist.', { detail: 'Repository path must exist.' })), isPending: false };
    renderTab();
    await userEvent.setup().click(button('Write compose file'));
    expect(screen.getByText('Repository path must exist.')).toBeTruthy();
    expect(screen.queryByRole('button', { name: 'Overwrite' })).toBeNull();
    expect(screen.queryByText(/already exists/)).toBeNull();
  });

  it('shows other write failures as errors instead of an overwrite prompt', async () => {
    state.write = { mutate: failing(new MarmApiError(500, 'disk full')), isPending: false };
    renderTab();
    await userEvent.setup().click(button('Write compose file'));
    expect(screen.getByText('disk full')).toBeTruthy();
    expect(screen.queryByRole('button', { name: 'Overwrite' })).toBeNull();
  });
});

describe('DockerTab agents', () => {
  it('asks for the docker agent list and offers only HTTP and Docker STDIO', () => {
    renderTab();

    expect(screen.getByRole('heading', { name: 'Agents on Docker' })).toBeTruthy();
    expect(state.agentsTarget.every((target) => target === 'docker')).toBe(true);
    expect(state.agentScopeTarget.every((target) => target === 'docker')).toBe(true);
    const group = within(screen.getByRole('group', { name: 'Transport' }));
    expect(group.getByRole('button', { name: 'HTTP' })).toBeTruthy();
    expect(group.getByRole('button', { name: 'Docker STDIO' })).toBeTruthy();
    expect(group.queryByRole('button', { name: 'STDIO' })).toBeNull();
  });

  it('sends target docker with a connect request', async () => {
    renderTab();
    await userEvent.setup().click(button('Connect'));

    expect(state.configure.mutate).toHaveBeenCalledTimes(1);
    expect((state.configure.mutate as ReturnType<typeof vi.fn>).mock.calls[0][0]).toEqual({
      id: 'cursor',
      body: { scope: 'user', transport: 'http', dry_run: true, target: 'docker' },
    });
  });
});
