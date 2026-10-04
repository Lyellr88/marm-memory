import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { CodeContextPage } from './CodeContext';
import { answerState, buildState, resetCodeContextTest, SUCCESS, symbol } from './CodeContext.testkit';

// The graph pane renders a canvas-backed force simulation; jsdom has no canvas,
// and what this page owns is the adapter, not the renderer.
vi.mock('react-force-graph-2d', () => ({ default: () => null }));
vi.mock('@/hooks/use-marm-queries', async () => (await import('./CodeContext.testkit')).queryMocks);

afterEach(resetCodeContextTest);

describe('CodeContextPage', () => {
  describe('the local evidence analyst', () => {
    const PACKET = {
      packet_id: 'pkt-7c1e',
      project: 'marm-systems',
      task: 'how does recall rank',
      symbols: [
        { handle: 'S1', qualified_name: 'marm.recall.rank_memories', name: 'rank_memories', file_path: 'marm/recall.py', start_line: 10, end_line: 11 },
      ],
      memories: [{ handle: 'M1', memory_id: 'm1', content: 'ranking is personalised PageRank' }],
    };
    const VERIFIED = {
      state: 'verified', score: 1, citation_coverage: 1, source_span_support: 1,
      graph_memory_consistency: 1, claims: 1, cited_claims: 1, failures: [], hard_failures: [], abstained: false,
    };

    function finished(over: Record<string, unknown>) {
      answerState.status = 'done';
      Object.assign(answerState as Record<string, unknown>, over);
    }

    it('labels a rejected answer as rejected, never grounded, and says why', () => {
      finished({
        grounding: 'rejected',
        hint: 'The answer cites persist_all, which the evidence packet does not contain.',
        verification: { ...VERIFIED, state: 'rejected', score: 0, hard_failures: ['reference not in packet: [persist_all]'] },
      });
      answerState.text = 'It calls [persist_all].';
      render(<CodeContextPage />);

      expect(screen.getByText('rejected answer')).toBeTruthy();
      expect(screen.queryByText('grounded answer')).toBeNull();
      expect(screen.getAllByText(/persist_all/).length).toBeGreaterThan(0);
      expect(screen.getByText('Rejected')).toBeTruthy();
    });

    it('shows how a finished answer was verified', () => {
      finished({ grounding: 'ok', verification: VERIFIED });
      answerState.text = 'It sorts [S1].';
      render(<CodeContextPage />);

      expect(screen.getByText('Verified')).toBeTruthy();
      expect(screen.getByText('citation coverage')).toBeTruthy();
    });

    it('links a cited handle while the answer is still arriving', () => {
      answerState.status = 'streaming';
      answerState.text = 'It sorts [S1] by score';
      (answerState as Record<string, unknown>).packet = PACKET;
      render(<CodeContextPage />);

      expect(screen.getByRole('button', { name: 'rank_memories' })).toBeTruthy();
    });

    it('links a cited handle once the server has resolved it', () => {
      finished({ grounding: 'ok' });
      answerState.text = 'It sorts [S1].';
      answerState.citations = [
        { handle: 'S1', kind: 'symbol', name: 'rank_memories', qualified_name: 'marm.recall.rank_memories', file_path: 'marm/recall.py', start_line: 10 },
      ];
      render(<CodeContextPage />);

      expect(screen.getByRole('button', { name: 'rank_memories' })).toBeTruthy();
    });

    it('lists a cited memory without pretending it is a file', () => {
      finished({ grounding: 'ok' });
      answerState.text = 'It ranks by PageRank [M1].';
      answerState.citations = [{ handle: 'M1', kind: 'memory', name: 'M1', memory_id: 'm1' }];
      (answerState as Record<string, unknown>).packet = PACKET;
      render(<CodeContextPage />);

      expect(screen.queryByText(/:undefined/)).toBeNull();
      // Linked inline and listed under the answer; never as a source file.
      expect(screen.getAllByRole('button', { name: /M1/ }).length).toBeGreaterThan(0);
      expect(screen.queryByText('Sources it used')).toBeNull();
    });

    it('jumps to the cited memory, not just to its tab', async () => {
      const user = userEvent.setup();
      const scrolled: Element[] = [];
      const original = Element.prototype.scrollIntoView;
      Element.prototype.scrollIntoView = function (this: Element) {
        scrolled.push(this);
      };
      try {
        buildState.data = SUCCESS;
        finished({ grounding: 'ok' });
        answerState.text = 'It ranks by PageRank [M1].';
        answerState.citations = [{ handle: 'M1', kind: 'memory', name: 'M1', memory_id: 'm1' }];
        (answerState as Record<string, unknown>).packet = PACKET;
        render(<CodeContextPage />);

        await user.click(screen.getAllByRole('button', { name: /M1/ })[0]);
        await waitFor(() =>
          expect(scrolled.some((el) => el.getAttribute('data-memory') === 'm1')).toBe(true),
        );
      } finally {
        Element.prototype.scrollIntoView = original;
      }
    });

    it('shows which model answered, how long it took, and from which packet', () => {
      finished({
        grounding: 'ok',
        verification: VERIFIED,
        packet: PACKET,
        modelInfo: { id: 'local-model', endpoint_source: 'discovery', max_tokens: 900, elapsed_ms: 2240, stopped: null },
      });
      answerState.text = 'It sorts [S1].';
      render(<CodeContextPage />);

      expect(screen.getByText(/pkt-7c1e/)).toBeTruthy();
      expect(screen.getByText(/2\.2 s/)).toBeTruthy();
    });

    it('says when the answer was cut off by its time budget', () => {
      finished({
        grounding: 'unverified',
        modelInfo: { id: 'm', endpoint_source: null, max_tokens: 900, elapsed_ms: 90000, stopped: 'deadline' },
      });
      answerState.text = 'It sorts';
      render(<CodeContextPage />);

      expect(screen.getByText(/time budget/i)).toBeTruthy();
    });

    it('shows each structured item with what verified it', () => {
      finished({
        grounding: 'unverified',
        items: [
          { id: 'F1', op: 'facts', text: 'claim_row marks the row applied', state: 'verified', support: 'quote', cites: ['S1'], quote: "SET status = 'applied'", failures: [] },
          { id: 'A1', op: 'summary', text: 'apply deletes every memory', state: 'uncertain', support: 'none', cites: ['S1'], failures: ['claim words not in the cited evidence: deletes, memory'] },
        ],
      });
      answerState.text = 'claim_row marks the row applied [S1]';
      render(<CodeContextPage />);

      expect(screen.getByText(/verified · verbatim quote/)).toBeTruthy();
      expect(screen.getByText(/claim words not in the cited evidence: deletes/)).toBeTruthy();
    });

    it('shows the profile and the token cap the model was held to', () => {
      finished({
        grounding: 'ok',
        verification: VERIFIED,
        modelInfo: { id: 'm', endpoint_source: null, profile: 'small', max_tokens: 1024, calls: 5, elapsed_ms: 3000, stopped: null },
      });
      answerState.text = 'It sorts [S1].';
      render(<CodeContextPage />);

      expect(screen.getByText(/small profile/)).toBeTruthy();
      expect(screen.getByText(/≤ 1,024 tokens/)).toBeTruthy();
      expect(screen.getByText(/5 calls/)).toBeTruthy();
    });

    it('defaults the analyst to read-only and sends that mode with an answer', async () => {
      const user = userEvent.setup();
      render(<CodeContextPage />);

      const mode = screen.getByRole('combobox', { name: /analyst/i }) as HTMLSelectElement;
      expect(mode.value).toBe('read_only');
      expect(mode.disabled).toBe(true);

      await user.click(screen.getByRole('checkbox', { name: /answer it too/i }));
      expect(mode.disabled).toBe(false);
      await user.selectOptions(mode, 'manual_review');
      await user.type(screen.getByLabelText('Task'), 'how does recall rank');
      await user.click(screen.getByRole('button', { name: /compose context/i }));

      await waitFor(() => expect(answerState.start).toHaveBeenCalledTimes(1));
      expect(answerState.start.mock.calls[0][0]).toMatchObject({ analyst_mode: 'manual_review' });
    });

    it('points to the Distill queue when verified results were staged', () => {
      finished({
        grounding: 'ok',
        analyst: { mode: 'manual_review', staged: ['a', 'b'], skipped: [], decisions: [] },
      });
      answerState.text = 'It sorts [S1].';
      render(<CodeContextPage />);

      const link = screen.getByRole('link', { name: /2 verified results staged for review/i });
      expect(link.getAttribute('href')).toContain('/distill');
    });

    it('says why guardrails left a result for review', () => {
      finished({
        grounding: 'ok',
        analyst: {
          mode: 'guardrails',
          staged: ['a'],
          skipped: [],
          decisions: [
            {
              proposal_id: 'a',
              applied: false,
              decision: {
                apply: false,
                status: 'review_required',
                checks: {},
                reason: 'review required: MARM cannot prove a paraphrase claim mechanically',
              },
            },
          ],
        },
      });
      answerState.text = 'It sorts [S1].';
      render(<CodeContextPage />);

      expect(screen.getByText(/cannot prove a paraphrase claim/)).toBeTruthy();
    });

    it('says when memory and the graph disagree', () => {
      finished({
        grounding: 'ok',
        disagreements: [{ memory: 'M1', from: 'S1', to: 'S2', memory_says: 'does not call', graph: 'edge', severity: 'contradicted' }],
      });
      answerState.text = 'It sorts [S1].';
      render(<CodeContextPage />);

      expect(screen.getByText('Memory and code disagree')).toBeTruthy();
      expect(screen.getByText(/contradicted/)).toBeTruthy();
    });
  });
});
