import { cleanup, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it } from 'vitest';
import { AddConnectionDialog } from './AddConnectionDialog';
import type { ConnectionsOverview } from '@/lib/marm-types';

const overview: ConnectionsOverview = {
  version: '2.54.1',
  os: 'Windows 11',
  runtime: { state: 'ready', managed: true, url: 'http://127.0.0.1:8001', profile: 'standard' },
  auth: { mode: 'local only', key_file_exists: true },
  agents: { connected: 3, detected: 9 },
  skills_installed: 2,
  checklist: [],
};

afterEach(cleanup);

function parseMailto(href: string) {
  const url = new URL(href);
  return { to: url.pathname, subject: url.searchParams.get('subject') ?? '', body: url.searchParams.get('body') ?? '' };
}

describe('AddConnectionDialog', () => {
  it('builds a mailto with the decoded subject and body, and never a key', async () => {
    const user = userEvent.setup();
    render(<AddConnectionDialog open onOpenChange={() => {}} overview={overview} />);

    await user.type(screen.getByLabelText('Tool name'), 'Zed & Friends');
    await user.selectOptions(screen.getByLabelText('How it connects'), 'STDIO');

    const link = screen.getByRole('link', { name: 'Open email' });
    const href = link.getAttribute('href') ?? '';
    expect(href.startsWith('mailto:support@marmemory.com?subject=')).toBe(true);
    expect(href).toContain(encodeURIComponent('Connection request: Zed & Friends'));

    const mail = parseMailto(href);
    expect(mail.to).toBe('support@marmemory.com');
    expect(mail.subject).toBe('Connection request: Zed & Friends');
    expect(mail.body).toContain('Tool: Zed & Friends');
    expect(mail.body).toContain('MARM version: 2.54.1');
    expect(mail.body).toContain('System: Windows 11');
    expect(mail.body).toContain('managed, ready, http://127.0.0.1:8001');
    expect(mail.body).toContain('Connects over: STDIO');
    expect(mail.body.toLowerCase()).not.toMatch(/key|token|bearer/);
    expect(href.toLowerCase()).not.toContain('token');
  });

  it('shows the same details in the preview and the address as selectable text', async () => {
    const user = userEvent.setup();
    render(<AddConnectionDialog open onOpenChange={() => {}} overview={overview} />);

    await user.type(screen.getByLabelText('Tool name'), 'JetBrains AI');
    expect(screen.getByText(/Subject: Connection request: JetBrains AI/)).toBeTruthy();
    expect(screen.getByText(/MARM version: 2.54.1/)).toBeTruthy();
    expect(screen.getByText('support@marmemory.com', { selector: 'span.select-all' })).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Copy email address' })).toBeTruthy();
  });

  it('has no email link until a tool name is entered', () => {
    render(<AddConnectionDialog open onOpenChange={() => {}} overview={overview} />);

    expect(screen.queryByRole('link', { name: 'Open email' })).toBeNull();
    expect(screen.getByRole('button', { name: 'Open email' }).hasAttribute('disabled')).toBe(true);
  });
});
