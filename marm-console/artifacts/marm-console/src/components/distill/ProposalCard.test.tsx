import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { ProposalCard } from './ProposalCard';
import type { DistillProposal } from '@/lib/marm-types';

/** These exercise the card directly, with handlers passed unconditionally.
 *
 *  That is the whole point of the file. `Distill.tsx` already withholds the
 *  handlers when a proposal has no id, so a test driven through the page
 *  cannot tell whether the card's own guard exists — removing it left the page
 *  suite entirely green. A component that can be reused has to defend itself,
 *  and that defence needs a test that can see it.
 */
function proposal(over: Partial<DistillProposal> = {}): DistillProposal {
  return {
    id: 'p-1',
    content: 'The concept graph reached 186 edges per memory at paragraph length.',
    score: 0.9,
    reasons: ['names its subject'],
    verdict: 'new',
    cosine: 0.3,
    ...over,
  };
}

afterEach(cleanup);

describe('ProposalCard', () => {
  it('offers no actions when the proposal was never staged, even if handlers are passed', () => {
    const onApply = vi.fn();
    const onDiscard = vi.fn();
    render(
      <ProposalCard
        proposal={proposal({ id: undefined, verdict: 'duplicate', cosine: 0.97, staged: false })}
        onApply={onApply}
        onDiscard={onDiscard}
      />,
    );

    // Without the guard these render and call the handler with `undefined`,
    // which the API would reject as a malformed request.
    expect(screen.queryByRole('button', { name: /keep it/i })).toBeNull();
    expect(screen.queryByRole('button', { name: /discard/i })).toBeNull();
  });

  it('offers actions on a staged proposal', () => {
    render(<ProposalCard proposal={proposal()} onApply={vi.fn()} onDiscard={vi.fn()} />);
    expect(screen.getByRole('button', { name: /keep it/i })).toBeTruthy();
    expect(screen.getByRole('button', { name: /discard/i })).toBeTruthy();
  });

  it('hides the cosine on a new verdict, where it means nothing', () => {
    // Below the near band there is no relationship, so a number there invites
    // a comparison that does not exist.
    render(<ProposalCard proposal={proposal({ verdict: 'new', cosine: 0.31 })} />);
    expect(screen.queryByText(/0\.310/)).toBeNull();
  });

  it('shows the cosine on a near verdict, where it is the reason to look', () => {
    render(<ProposalCard proposal={proposal({ verdict: 'near', cosine: 0.87 })} />);
    expect(screen.getByText(/0\.870/)).toBeTruthy();
  });

  it('disables both actions while one is in flight', () => {
    render(<ProposalCard proposal={proposal()} onApply={vi.fn()} onDiscard={vi.fn()} busy />);
    expect(screen.getByRole('button', { name: /keep it/i }).hasAttribute('disabled')).toBe(true);
    expect(screen.getByRole('button', { name: /discard/i }).hasAttribute('disabled')).toBe(true);
  });

  it('labels an analyst proposal\u2019s evidence as the source it cites', () => {
    render(<ProposalCard proposal={proposal({ origin: 'analyst', evidence: 'def apply():\n    claim()' })} />);
    expect(screen.getByText(/the source it cites/i)).toBeTruthy();
    expect(screen.queryByText(/what was actually said/i)).toBeNull();
  });
});
