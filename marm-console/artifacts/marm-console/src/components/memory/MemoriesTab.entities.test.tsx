import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { Memory } from '@/lib/marm-types';
import { MemoriesTab } from './MemoriesTab';

// A memory whose real text contains the literal characters `&lt;` -- an author
// quoting an entity. The server stores that with the `&` escaped.
//
// This content is chosen deliberately: decoding it TWICE differs from decoding
// it once. Something like `&#x27;` would not catch the defect at all, because
// decoding an apostrophe again is a no-op and the second decode leaves no
// trace. A test written on that content passes against the broken code.
const STORED = 'compare a &amp;lt; b';
const DECODED = 'compare a &lt; b';
const DECODED_TWICE = 'compare a < b';

const memory: Memory = {
  id: 'm1',
  content: STORED,
  session_name: 'session-a',
  project: 'MARM-Stack',
  platform: null,
  context_type: 'general',
  metadata: null,
  content_hash: 'abcdef0123456789',
  created_at: '2026-09-19T12:00:00+00:00',
  compaction_role: 'none',
  chunk_count: 0,
  has_embedding: true,
  concept_link_count: 0,
};

// PUT returns the stored row, so the server re-escapes what the editor sent.
const update = vi.fn(
  (_vars: unknown, opts?: { onSuccess?: (m: Memory) => void }) => {
    opts?.onSuccess?.({ ...memory, content: STORED, project: 'Other' });
  },
);

vi.mock('@/hooks/use-marm-queries', () => ({
  useMemories: () => ({
    data: { items: [memory], total: 1, offset: 0 },
    isLoading: false,
    isFetching: false,
  }),
  useFilters: () => ({
    data: { sessions: [], projects: [], platforms: [], context_types: [] },
  }),
  // No projects above, so the scope notice has nothing to report; this is
  // only here because the component reads it unconditionally.
  useOverview: () => ({ data: { memory: { active_memories: 1 } } }),
  useCreateMemory: () => ({ isPending: false, mutate: vi.fn() }),
  useUpdateMemory: () => ({ isPending: false, mutate: update, error: null }),
  useDeleteMemory: () => ({ isPending: false, mutate: vi.fn(), error: null }),
  useBulkDeleteMemories: () => ({ isPending: false, mutate: vi.fn(), error: null }),
}));

afterEach(() => {
  cleanup();
  update.mockClear();
});

// The dialog holds three Inputs beside the Textarea, and the page holds a
// search box, so the editor has to be addressed by tag rather than by role.
const editorValue = () => {
  const editor = screen
    .getByRole('dialog')
    .querySelector('textarea') as HTMLTextAreaElement | null;
  if (!editor) throw new Error('the memory editor is not open');
  return editor.value;
};

async function openEditor(user: ReturnType<typeof userEvent.setup>) {
  await user.click(await screen.findByRole('button', { name: /^edit$/i }));
}

describe('MemoriesTab editing', () => {
  it('sends the decoded text, so the server escapes it exactly once', async () => {
    const user = userEvent.setup();
    render(<MemoriesTab />);

    await user.click(screen.getAllByText(DECODED)[0]);
    await openEditor(user);
    expect(editorValue()).toBe(DECODED);

    await user.click(screen.getByRole('button', { name: 'Save' }));
    expect(update).toHaveBeenCalledWith(
      expect.objectContaining({
        data: expect.objectContaining({ content: DECODED }),
      }),
      expect.anything(),
    );
  });

  it('keeps the server representation after a save, not the editor text', async () => {
    // Writing `editContent` back into `selectedMemory` left the component
    // holding the DECODED text where it believes it holds the stored one.
    // The detail view decodes whatever it is given, so re-opening the editor
    // decoded a second time -- turning a memory that really contains `&lt;`
    // into one that appears to contain `<`, which the next save would then
    // make true. Re-opening must show exactly one decode, not two.
    const user = userEvent.setup();
    render(<MemoriesTab />);

    await user.click(screen.getAllByText(DECODED)[0]);
    await openEditor(user);
    await user.click(screen.getByRole('button', { name: 'Save' }));
    await waitFor(() => expect(screen.getByText('Memory updated.')).toBeTruthy());

    await openEditor(user);
    expect(editorValue()).toBe(DECODED);
    expect(editorValue()).not.toBe(DECODED_TWICE);
  });
});
