import { describe, expect, it } from 'vitest';
import { decodeEntities } from './entities';

describe('decodeEntities', () => {
  it('decodes what sanitize_content escaped on the way in', () => {
    expect(decodeEntities('the target&#x27;s write')).toBe("the target's write");
    expect(decodeEntities('said &quot;no&quot;')).toBe('said "no"');
    expect(decodeEntities('a &lt;tag&gt; and &amp; an ampersand')).toBe(
      'a <tag> and & an ampersand',
    );
  });

  it('is a single pass, so a nested escape survives as literal text', () => {
    expect(decodeEntities('&amp;lt;')).toBe('&lt;');
  });

  it('makes the edit round-trip stable, which is the corruption this fixes', () => {
    const stored = 'the target&#x27;s write';
    const escape = (s: string) =>
      s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
       .replace(/"/g, '&quot;').replace(/'/g, '&#x27;');
    expect(escape(decodeEntities(stored))).toBe(stored);
    expect(escape(stored)).not.toBe(stored);   // the bug, for contrast
  });

  it('handles null and empty without throwing', () => {
    expect(decodeEntities(null)).toBe('');
    expect(decodeEntities(undefined)).toBe('');
    expect(decodeEntities('')).toBe('');
  });
});
