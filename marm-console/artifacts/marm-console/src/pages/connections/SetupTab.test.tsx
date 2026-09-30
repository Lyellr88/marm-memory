import { cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { SetupTab } from './SetupTab';
import { MarmApiError } from '@/lib/marm-api';
import type { ConnectionsOverview, RuntimeRestartJob, SetupSettings } from '@/lib/marm-types';

type Callbacks = { onSuccess?: (data: unknown) => void; onError?: (err: unknown) => void };

const state = vi.hoisted(() => ({
  settings: undefined as unknown,
  runtime: undefined as unknown,
  job: undefined as unknown,
  jobIds: [] as Array<string | null>,
  update: { mutate: vi.fn(), isPending: false },
  restart: { mutate: vi.fn(), isPending: false },
  profile: { mutate: vi.fn(), isPending: false, error: null as unknown },
  automation: { mutate: vi.fn(), isPending: false, error: null as unknown },
  llm: { mutate: vi.fn(), isPending: false, error: null as unknown },
}));

vi.mock('@/hooks/use-marm-queries', () => ({
  useSetupSettings: () => ({ data: state.settings, isLoading: false, isError: false, error: null }),
  useUpdateSetupSettings: () => state.update,
  useStartRuntimeRestart: () => state.restart,
  useRuntimeRestartJob: (id: string | null) => {
    state.jobIds.push(id);
    return { data: state.job };
  },
  useRuntimeSettings: () => ({ data: state.runtime }),
  useUpdateRuntimeProfile: () => state.profile,
  useUpdateRuntimeAutomation: () => state.automation,
  useUpdateLlmSettings: () => state.llm,
  useAgents: () => ({ data: { auth_required: false, configure_allowed: true, configure_blocked_reason: null, clients: [] }, isLoading: false, isError: false, error: null }),
}));

function settings(): SetupSettings {
  return {
    path: '~/.marm/settings.json',
    groups: [
      {
        id: 'server',
        label: 'Server',
        items: [
          { key: 'server.port', label: 'Port', help: 'Where MARM listens.', type: 'int', min: 1, max: 65535, default: 8001, value: 8001, source: 'default', overrides_env: false, live: false },
          { key: 'server.expose_network', label: 'Reachable from other devices', help: 'Binds to your network.', type: 'bool', default: false, value: false, source: 'default', overrides_env: false, live: false },
        ],
      },
      {
        id: 'graph',
        label: 'Indexing',
        items: [
          { key: 'graph.auto_index_mode', label: 'Index depth', help: 'How much each index reads.', type: 'choice', choices: ['full', 'moderate', 'fast'], default: 'moderate', value: 'moderate', source: 'saved', overrides_env: true, live: false },
        ],
      },
    ],
    live: { profile: 'standard', rate_limit_rpm: 80, auto_index_graph: true, auto_index_concept: true, llm_enabled: false },
  };
}

function overview(steps: Array<[string, boolean]>): ConnectionsOverview {
  return {
    version: '2.54.1',
    os: 'Windows 11',
    runtime: { state: 'ready', managed: true, url: '127.0.0.1:8001', profile: 'standard' },
    auth: { mode: 'local only', key_file_exists: false },
    agents: { connected: 3, detected: 9 },
    skills_installed: 2,
    checklist: steps.map(([label, done], index) => ({ id: `step-${index}`, label, done, detail: `detail ${index}` })),
  };
}

function settling(result: unknown) {
  return vi.fn((_vars: unknown, opts?: Callbacks) => opts?.onSuccess?.(result));
}

function failing(error: unknown) {
  return vi.fn((_vars: unknown, opts?: Callbacks) => opts?.onError?.(error));
}

const noOverview = overview([]);

beforeEach(() => {
  state.settings = settings();
  state.runtime = { profile: 'standard', rate_limit: { requests_per_minute: 80 }, automation: { graph: { enabled: true }, concept: { enabled: true } }, llm: { enabled: false } };
  state.job = undefined;
  state.jobIds = [];
  state.update = { mutate: settling(undefined), isPending: false };
  state.restart = { mutate: settling({ job_id: 'job-1' }), isPending: false };
  state.profile = { mutate: vi.fn(), isPending: false, error: null };
  state.automation = { mutate: vi.fn(), isPending: false, error: null };
  state.llm = { mutate: vi.fn(), isPending: false, error: null };
});

afterEach(cleanup);

describe('SetupTab checklist', () => {
  it('marks done steps, highlights the first unfinished one as next, and leaves the rest as to do', () => {
    render(<SetupTab overview={overview([['Installed', true], ['Runtime running', true], ['Connect your agents', false], ['Install the MARM skill', false], ['Index a project', false]])} onRequestConnection={() => {}} />);

    const step = (label: string) => screen.getByText(label).closest('li') as HTMLElement;
    expect(step('Installed').getAttribute('data-state')).toBe('done');
    expect(step('Runtime running').getAttribute('data-state')).toBe('done');
    expect(step('Connect your agents').getAttribute('data-state')).toBe('next');
    expect(step('Connect your agents').getAttribute('aria-current')).toBe('step');
    expect(step('Install the MARM skill').getAttribute('data-state')).toBe('todo');
    expect(step('Index a project').getAttribute('data-state')).toBe('todo');
    expect(within(step('Connect your agents')).getByText('detail 2')).toBeTruthy();
  });

  it('has no next step once everything is done', () => {
    render(<SetupTab overview={overview([['Installed', true], ['Index a project', true]])} onRequestConnection={() => {}} />);
    expect(document.querySelector('[data-state="next"]')).toBeNull();
  });
});

describe('SetupTab settings', () => {
  it('splits Runtime from Features and labels when each change applies', () => {
    render(<SetupTab overview={noOverview} onRequestConnection={() => {}} />);

    expect(screen.getByRole('heading', { name: 'Runtime' })).toBeTruthy();
    expect(screen.getByRole('heading', { name: 'Features' })).toBeTruthy();
    expect(screen.getAllByText('applies now')).toHaveLength(5);
    expect(screen.getAllByText('applies on restart')).toHaveLength(3);
    expect(screen.getByText('overrides env')).toBeTruthy();
    expect(screen.getByRole('switch', { name: 'Auto-index code projects' }).getAttribute('aria-checked')).toBe('true');
    expect(screen.getByRole('switch', { name: 'Local generation' }).getAttribute('aria-checked')).toBe('false');
  });

  it('marks a bool change unsaved and Discard puts it back', async () => {
    const user = userEvent.setup();
    render(<SetupTab overview={noOverview} onRequestConnection={() => {}} />);

    expect(screen.getByText('No unsaved changes.')).toBeTruthy();
    const save = screen.getByRole('button', { name: 'Save and apply' });
    expect(save.hasAttribute('disabled')).toBe(true);

    const toggle = screen.getByRole('switch', { name: 'Reachable from other devices' });
    await user.click(toggle);
    expect(toggle.getAttribute('aria-checked')).toBe('true');
    expect(screen.getByText('1 unsaved change. Save and apply restarts the runtime.')).toBeTruthy();
    expect(save.hasAttribute('disabled')).toBe(false);

    await user.click(screen.getByRole('button', { name: 'Discard' }));
    expect(toggle.getAttribute('aria-checked')).toBe('false');
    expect(screen.getByText('No unsaved changes.')).toBeTruthy();
  });

  it('counts an int and a choice change, and undoing one drops it from the count', async () => {
    const user = userEvent.setup();
    render(<SetupTab overview={noOverview} onRequestConnection={() => {}} />);

    const port = screen.getByLabelText('Port') as HTMLInputElement;
    await user.clear(port);
    await user.type(port, '9000');
    await user.selectOptions(screen.getByLabelText('Index depth'), 'fast');
    expect(screen.getByText('2 unsaved changes. Save and apply restarts the runtime.')).toBeTruthy();

    await user.selectOptions(screen.getByLabelText('Index depth'), 'moderate');
    expect(screen.getByText('1 unsaved change. Save and apply restarts the runtime.')).toBeTruthy();

    await user.click(screen.getByRole('button', { name: 'Discard' }));
    expect(port.value).toBe('8001');
    expect((screen.getByLabelText('Index depth') as HTMLSelectElement).value).toBe('moderate');
  });

  it('blocks Save and apply while an int is outside its range', () => {
    render(<SetupTab overview={noOverview} onRequestConnection={() => {}} />);

    fireEvent.change(screen.getByLabelText('Port'), { target: { value: '70000' } });
    expect(screen.getByText('Enter a whole number from 1 to 65535.')).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Save and apply' }).hasAttribute('disabled')).toBe(true);
  });

  it('confirms, saves the changed values, restarts, and shows the finished job', async () => {
    const user = userEvent.setup();
    render(<SetupTab overview={noOverview} onRequestConnection={() => {}} />);

    const port = screen.getByLabelText('Port');
    await user.clear(port);
    await user.type(port, '9000');
    await user.click(screen.getByRole('switch', { name: 'Reachable from other devices' }));
    await user.click(screen.getByRole('button', { name: 'Save and apply' }));

    expect(state.update.mutate).not.toHaveBeenCalled();
    const dialog = within(screen.getByRole('dialog'));
    expect(dialog.getByText('Save and apply?')).toBeTruthy();
    expect(dialog.getByText(/Port/)).toBeTruthy();

    state.job = { status: 'done', seconds: 2.8 } satisfies RuntimeRestartJob;
    await user.click(dialog.getByRole('button', { name: 'Save and restart' }));

    expect(state.update.mutate).toHaveBeenCalledTimes(1);
    expect(state.update.mutate.mock.calls[0][0]).toEqual({ 'server.port': 9000, 'server.expose_network': true });
    expect(state.restart.mutate).toHaveBeenCalledTimes(1);
    expect(state.jobIds).toContain('job-1');
    expect(screen.getByText('Runtime restarted in 2.8 s')).toBeTruthy();
    expect(screen.getByText('No unsaved changes.')).toBeTruthy();
  });

  it('shows a running restart as progress', async () => {
    const user = userEvent.setup();
    render(<SetupTab overview={noOverview} onRequestConnection={() => {}} />);

    await user.click(screen.getByRole('switch', { name: 'Reachable from other devices' }));
    await user.click(screen.getByRole('button', { name: 'Save and apply' }));
    state.job = { status: 'running' } satisfies RuntimeRestartJob;
    await user.click(screen.getByRole('button', { name: 'Save and restart' }));

    expect(screen.getByText('Restarting the runtime…')).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Save and apply' }).hasAttribute('disabled')).toBe(true);
  });

  it('shows the error when the restart job fails', async () => {
    const user = userEvent.setup();
    render(<SetupTab overview={noOverview} onRequestConnection={() => {}} />);

    await user.click(screen.getByRole('switch', { name: 'Reachable from other devices' }));
    await user.click(screen.getByRole('button', { name: 'Save and apply' }));
    state.job = { status: 'error', detail: 'Port 9000 is already in use.' } satisfies RuntimeRestartJob;
    await user.click(screen.getByRole('button', { name: 'Save and restart' }));

    expect(screen.getByText('Port 9000 is already in use.')).toBeTruthy();
  });

  it('on 409 keeps the saved values and shows the command to restart by hand', async () => {
    const user = userEvent.setup();
    state.restart = { mutate: failing(new MarmApiError(409, 'The runtime is not managed.', { command: 'marm-memory restart' })), isPending: false };
    render(<SetupTab overview={noOverview} onRequestConnection={() => {}} />);

    await user.click(screen.getByRole('switch', { name: 'Reachable from other devices' }));
    await user.click(screen.getByRole('button', { name: 'Save and apply' }));
    await user.click(screen.getByRole('button', { name: 'Save and restart' }));

    expect(state.update.mutate).toHaveBeenCalledTimes(1);
    expect(screen.getByText('Saved. Restart with:')).toBeTruthy();
    expect(screen.getByText('marm-memory restart')).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Copy restart command' })).toBeTruthy();
    expect(screen.getByText('No unsaved changes.')).toBeTruthy();
  });

  it('reads the command from a detail object on 409', async () => {
    const user = userEvent.setup();
    state.restart = { mutate: failing(new MarmApiError(409, 'x', { detail: { command: 'marm-memory start' } })), isPending: false };
    render(<SetupTab overview={noOverview} onRequestConnection={() => {}} />);

    await user.click(screen.getByRole('switch', { name: 'Reachable from other devices' }));
    await user.click(screen.getByRole('button', { name: 'Save and apply' }));
    await user.click(screen.getByRole('button', { name: 'Save and restart' }));

    expect(screen.getByText('marm-memory start')).toBeTruthy();
  });

  it('turns every control off with the reason after a 403', async () => {
    const user = userEvent.setup();
    state.update = { mutate: failing(new MarmApiError(403, 'The Console is not bound to loopback.')), isPending: false };
    render(<SetupTab overview={noOverview} onRequestConnection={() => {}} />);

    await user.click(screen.getByRole('switch', { name: 'Reachable from other devices' }));
    await user.click(screen.getByRole('button', { name: 'Save and apply' }));
    await user.click(screen.getByRole('button', { name: 'Save and restart' }));

    expect(screen.getAllByText(/The Console is not bound to loopback\./).length).toBeGreaterThan(0);
    expect(screen.getByText(/Changes are turned off here/)).toBeTruthy();
    expect(state.restart.mutate).not.toHaveBeenCalled();
    expect(screen.getByRole('switch', { name: 'Reachable from other devices' }).hasAttribute('disabled')).toBe(true);
    expect(screen.getByRole('switch', { name: 'Auto-index code projects' }).hasAttribute('disabled')).toBe(true);
    expect(screen.getByLabelText('Port').hasAttribute('disabled')).toBe(true);
  });
});

describe('SetupTab live switches', () => {
  it('apply straight away through the System endpoints and never count as unsaved', async () => {
    const user = userEvent.setup();
    render(<SetupTab overview={noOverview} onRequestConnection={() => {}} />);

    await user.click(screen.getByRole('switch', { name: 'Auto-index code projects' }));
    expect(state.automation.mutate).toHaveBeenCalledWith({ scope: 'graph', enabled: false }, expect.anything());

    await user.click(screen.getByRole('switch', { name: 'Auto-extract concepts' }));
    expect(state.automation.mutate).toHaveBeenCalledWith({ scope: 'concept', enabled: false }, expect.anything());

    await user.click(screen.getByRole('switch', { name: 'Local generation' }));
    expect(state.llm.mutate).toHaveBeenCalledWith({ enabled: true }, expect.anything());

    await user.selectOptions(screen.getByLabelText('Profile'), 'swarm');
    expect(state.profile.mutate).toHaveBeenCalledWith({ profile: 'swarm' }, expect.anything());

    await user.type(screen.getByLabelText('Rate limit per minute'), '120');
    await user.click(screen.getByRole('button', { name: 'Apply' }));
    expect(state.profile.mutate).toHaveBeenCalledWith({ profile: 'standard', rateLimitRpm: 120 }, expect.anything());

    expect(screen.getByText('No unsaved changes.')).toBeTruthy();
  });
});
