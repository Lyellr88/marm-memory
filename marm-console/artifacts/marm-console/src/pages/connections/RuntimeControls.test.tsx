import { cleanup, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { RuntimeControls } from './RuntimeControls';
import type { ConnectionsOverview } from '@/lib/marm-types';

const state = vi.hoisted(() => ({ start: vi.fn(), stop: vi.fn(), restart: vi.fn(), job: { busy: false, data: undefined as unknown } }));
vi.mock('@/hooks/use-marm-queries', () => ({
  useStartRuntime: () => ({ mutate: state.start }),
  useStopRuntime: () => ({ mutate: state.stop }),
  useStartRuntimeRestart: () => ({ mutate: state.restart }),
  useRuntimeControlJob: () => state.job,
}));
beforeEach(() => { vi.clearAllMocks(); state.job = { busy: false, data: undefined }; });
afterEach(cleanup);

function overview(runtime: Partial<ConnectionsOverview['runtime']> = {}): ConnectionsOverview {
  return { version: 'test', os: 'Windows', runtime: { state: 'ready', managed: true, url: 'http://127.0.0.1:8001/mcp', profile: 'standard', controls_allowed: true, port_owner: 'marm', ...runtime }, auth: { mode: 'local', key_file_exists: false }, agents: { connected: 0, detected: 0 }, skills_installed: 0, checklist: [] };
}

it('confirms stop before invoking it, and cancel does nothing', async () => {
  const user = userEvent.setup();
  render(<RuntimeControls overview={overview()} />);
  await user.click(screen.getByRole('button', { name: 'Stop server' }));
  expect(state.stop).not.toHaveBeenCalled();
  await user.click(screen.getByRole('button', { name: 'Cancel' }));
  expect(state.stop).not.toHaveBeenCalled();
  await user.click(screen.getByRole('button', { name: 'Stop server' }));
  const dialog = screen.getByRole('alertdialog');
  expect(within(dialog).getByText(/The Console stays open/)).toBeTruthy();
  await user.click(within(dialog).getByRole('button', { name: 'Stop server' }));
  expect(state.stop).toHaveBeenCalledTimes(1);
});

it('offers Start in stopped compact mode and blocks unknown ownership', async () => {
  const user = userEvent.setup();
  const { rerender } = render(<RuntimeControls overview={overview({ state: 'stopped', managed: false, port_owner: 'none', can_start: true })} compact />);
  await user.click(screen.getByRole('button', { name: 'Start server' }));
  expect(state.start).toHaveBeenCalledTimes(1);
  rerender(<RuntimeControls overview={overview({ state: 'stopped', managed: false, port_owner: 'unknown', intended_port: 9234, can_start: false })} compact />);
  expect(screen.getByRole('button', { name: 'Start server' }).hasAttribute('disabled')).toBe(true);
  expect(screen.getByText('Could not check port 9234. Try again.')).toBeTruthy();
});

it('disables lifecycle actions while the shared job runs', () => {
  state.job = { busy: true, data: { kind: 'restart', status: 'running' } };
  render(<RuntimeControls overview={overview()} />);
  for (const name of ['Restart server', 'Stop server']) expect(screen.getByRole('button', { name }).hasAttribute('disabled')).toBe(true);
  expect(screen.getByText('Restarting the runtime...')).toBeTruthy();
});

it('blocks controls on non-loopback Consoles', () => {
  render(<RuntimeControls overview={overview({ controls_allowed: false })} />);
  expect(screen.getByText(/Changes are turned off here/)).toBeTruthy();
  for (const name of ['Restart server', 'Stop server', 'View log']) expect(screen.getByRole('button', { name }).hasAttribute('disabled')).toBe(true);
});
