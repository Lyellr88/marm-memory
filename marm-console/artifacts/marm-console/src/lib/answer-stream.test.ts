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
