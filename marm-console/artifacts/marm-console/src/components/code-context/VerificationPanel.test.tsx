import { afterEach, describe, expect, it } from 'vitest';
import { cleanup, render, screen } from '@testing-library/react';
import { VerificationPanel } from './VerificationPanel';
import type { AnswerVerification } from '@/lib/marm-types';

const base: AnswerVerification = {
  state: 'verified',
  score: 1,
  citation_coverage: 1,
  source_span_support: 1,
  graph_memory_consistency: 1,
  claims: 2,
  cited_claims: 2,
  failures: [],
  hard_failures: [],
  abstained: false,
};

afterEach(cleanup);

describe('VerificationPanel', () => {
  it('labels a verified answer as verified', () => {
    render(<VerificationPanel verification={base} />);
    expect(screen.getByText('Verified')).toBeTruthy();
    expect(screen.queryByText(/weakest/i)).toBeNull();
  });

  it('shows the weakest check and the failures for an uncertain answer', () => {
    render(
      <VerificationPanel
        verification={{
          ...base,
          state: 'uncertain',
          score: 0.5,
          source_span_support: 0.5,
          failures: ['code span not in packet: `x`'],
        }}
      />,
    );
    expect(screen.getByText('Uncertain')).toBeTruthy();
    expect(screen.getByText(/code span not in packet/)).toBeTruthy();
    expect(screen.getByText(/weakest: source span support/i)).toBeTruthy();
  });

  it('never says grounded for a rejected answer, and leads with why', () => {
    render(
      <VerificationPanel
        verification={{
          ...base,
          state: 'rejected',
          score: 0,
          hard_failures: ['reference not in packet: [persist_all]'],
        }}
      />,
    );
    expect(screen.getByText('Rejected')).toBeTruthy();
    expect(screen.getByText(/reference not in packet/)).toBeTruthy();
    expect(screen.queryByText(/grounded/i)).toBeNull();
  });

  it('says an abstention is an honest answer, not a failure', () => {
    render(
      <VerificationPanel
        verification={{ ...base, state: 'uncertain', score: 0, claims: 0, cited_claims: 0, abstained: true }}
      />,
    );
    expect(screen.getByText(/does not show/i)).toBeTruthy();
  });
});
