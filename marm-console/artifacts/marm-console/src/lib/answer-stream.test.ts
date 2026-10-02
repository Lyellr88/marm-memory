import { describe, expect, it } from 'vitest';
import { IDLE_ANSWER, applyAnswerEvent, applyStreamEnd, type AnswerStreamState } from './answer-stream';

const streaming: AnswerStreamState = { ...IDLE_ANSWER, status: 'streaming' };

describe('applyAnswerEvent', () => {
  it('records the composition the answer is written from', () => {
    const context = { status: 'success', task: 't' };
    expect(applyAnswerEvent(streaming, 'context', context).context).toEqual(context);
  });

  it('appends deltas', () => {
    const one = applyAnswerEvent(streaming, 'delta', { text: 'The ' });
    expect(applyAnswerEvent(one, 'delta', { text: 'apply' }).text).toBe('The apply');
  });

  it('withdraws the cut-off text on restart, so two answers are never spliced', () => {
    const cut = applyAnswerEvent(streaming, 'delta', { text: 'The `apply`' });
    const restarted = applyAnswerEvent(cut, 'restart', { reason: 'length' });
    expect(restarted.text).toBe('');
    expect(restarted.status).toBe('streaming');
    expect(applyAnswerEvent(restarted, 'delta', { text: 'Full answer' }).text).toBe('Full answer');
  });

  it('keeps the composition across a restart', () => {
    const withContext = applyAnswerEvent(streaming, 'context', { status: 'success' });
    expect(applyAnswerEvent(withContext, 'restart', {}).context).toEqual({ status: 'success' });
  });

  it('takes the verdict from done', () => {
    const done = applyAnswerEvent(streaming, 'done', {
      citations: [],
      status: 'unverified',
      unresolved: ['x_y'],
      hint: 'why',
      truncated: true,
    });
    expect(done).toMatchObject({
      status: 'done',
      grounding: 'unverified',
      unresolved: ['x_y'],
      hint: 'why',
      truncated: true,
    });
  });

  it('treats a done without a verdict as unverified', () => {
    expect(applyAnswerEvent(streaming, 'done', { citations: [] }).grounding).toBe('unverified');
  });

  it('records an error', () => {
    const failed = applyAnswerEvent(streaming, 'error', { message: 'no model', hint: 'h' });
    expect(failed).toMatchObject({ status: 'error', message: 'no model', hint: 'h' });
  });

  it('turns a stream that closed mid-answer into an error, so it never hangs', () => {
    const cut = applyAnswerEvent(streaming, 'delta', { text: 'The `apply`' });
    const ended = applyStreamEnd(cut);
    expect(ended.status).toBe('error');
    expect(ended.message).toMatch(/ended before/i);
    expect(ended.text).toBe('The `apply`');
  });

  it('leaves a stream that already reached a terminal event alone', () => {
    const done = applyAnswerEvent(streaming, 'done', { citations: [], status: 'ok' });
    expect(applyStreamEnd(done)).toBe(done);
    const failed = applyAnswerEvent(streaming, 'error', { message: 'no model' });
    expect(applyStreamEnd(failed)).toBe(failed);
  });
});

describe('the analyst fields', () => {
  const packet = {
    packet_id: 'p1',
    project: 'demo',
    task: 'how',
    symbols: [{ handle: 'S1', qualified_name: 'pkg.apply', name: 'apply', file_path: 'a.py', start_line: 1, end_line: 9 }],
    memories: [],
  };
  const verification = {
    state: 'verified', score: 1, citation_coverage: 1, source_span_support: 1,
    graph_memory_consistency: 1, claims: 1, cited_claims: 1, failures: [], hard_failures: [], abstained: false,
  };

  it('records the evidence packet', () => {
    expect(applyAnswerEvent(streaming, 'packet', packet).packet?.packet_id).toBe('p1');
  });

  it('records the profile the operator chose from start', () => {
    const profile = { name: 'small', max_tokens: 1024 };
    expect(applyAnswerEvent(streaming, 'start', { model: 'm', profile }).profile?.name).toBe('small');
  });

  it('collects each operation as it finishes', () => {
    const one = applyAnswerEvent(streaming, 'operation', { op: 'summary', status: 'ok', items: [] });
    const two = applyAnswerEvent(one, 'operation', { op: 'facts', status: 'malformed', items: [] });
    expect(two.operations?.map((o) => o.op)).toEqual(['summary', 'facts']);
  });

  it('takes the verification, model, items and disagreements from done', () => {
    const item = { id: 'F1', op: 'facts', text: 'apply claims', state: 'verified', support: 'quote', cites: ['S1'], failures: [] };
    const done = applyAnswerEvent(streaming, 'done', {
      citations: [], status: 'ok', verification, packet_id: 'p1',
      model_info: { id: 'm', endpoint_source: 'discovery', max_tokens: 900, elapsed_ms: 12, stopped: null },
      items: [item],
      disagreements: [{ memory: 'M1', from: 'S1', to: 'S2', severity: 'contradicted' }],
    });
    expect(done.verification?.state).toBe('verified');
    expect(done.modelInfo?.id).toBe('m');
    expect(done.items?.[0].support).toBe('quote');
    expect(done.disagreements?.[0].severity).toBe('contradicted');
  });

  it('takes the analyst result from done', () => {
    const analyst = { mode: 'manual_review', staged: ['x'], skipped: [], decisions: [] };
    expect(applyAnswerEvent(streaming, 'done', { citations: [], status: 'ok', analyst }).analyst).toEqual(analyst);
  });

  it('keeps a rejection a rejection', () => {
    expect(applyAnswerEvent(streaming, 'done', { citations: [], status: 'rejected' }).grounding).toBe('rejected');
  });
});
