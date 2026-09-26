import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';
import type { CodeContextMemory } from '@/lib/marm-types';
import { MemoryPane } from './MemoryPane';

afterEach(cleanup);

describe('MemoryPane', () => {
  it('decodes recalled content once, as the Memories page does', () => {
    const memory = {
      content: 'the target&#x27;s write compares a &amp;lt; b',
      context_type: 'general',
    } as CodeContextMemory;
    render(<MemoryPane memories={[memory]} links={[]} recallUnavailable={false} />);
    expect(screen.getByText("the target's write compares a &lt; b")).toBeTruthy();
  });
});
