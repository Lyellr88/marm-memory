import { useState } from 'react';
import { Dialog, DialogContent, DialogHeader, DialogTitle, Input } from '@/components/ui/core';

interface KeyboardShortcutsDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

interface Shortcut {
  keys: string;
  description: string;
  category: 'editing' | 'navigation' | 'selection' | 'search' | 'shell';
}

const SHORTCUTS: Shortcut[] = [
  { keys: 'Ctrl+C', description: 'Copy selection (or interrupt if no selection)', category: 'editing' },
  { keys: 'Ctrl+Shift+C', description: 'Copy selection', category: 'editing' },
  { keys: 'Ctrl+V', description: 'Paste from clipboard', category: 'editing' },
  { keys: 'Shift+Insert', description: 'Paste from clipboard', category: 'editing' },
  { keys: 'Ctrl+Enter', description: 'Insert newline', category: 'editing' },
  { keys: 'Ctrl+Shift+A', description: 'Select all terminal output', category: 'selection' },
  { keys: 'Double-click', description: 'Select word', category: 'selection' },
  { keys: 'Triple-click', description: 'Select line (if enabled)', category: 'selection' },
  { keys: 'Right-click', description: 'Copy if selection, otherwise paste', category: 'selection' },
  { keys: 'Ctrl+F', description: 'Open search', category: 'search' },
  { keys: 'Enter', description: 'Find next match (in search)', category: 'search' },
  { keys: 'Shift+Enter', description: 'Find previous match (in search)', category: 'search' },
  { keys: 'Esc', description: 'Close search', category: 'search' },
  { keys: 'Up/Down', description: 'Command history', category: 'navigation' },
  { keys: 'Ctrl+Left/Right', description: 'Move by word', category: 'navigation' },
  { keys: 'Home/End', description: 'Move to line start/end', category: 'navigation' },
  { keys: 'Tab', description: 'Auto-complete', category: 'navigation' },
  { keys: 'Ctrl+L', description: 'Clear screen', category: 'shell' },
  { keys: 'Ctrl+R', description: 'Reverse history search', category: 'shell' },
  { keys: 'Ctrl+D', description: 'Exit shell / EOF', category: 'shell' },
  { keys: 'Ctrl+`', description: 'Toggle the terminal dock', category: 'shell' },
];

const CATEGORY_NAMES: Record<Shortcut['category'], string> = {
  editing: 'Editing',
  selection: 'Selection',
  search: 'Search',
  navigation: 'Navigation',
  shell: 'Shell',
};

export function KeyboardShortcutsDialog({ open, onOpenChange }: KeyboardShortcutsDialogProps) {
  const [query, setQuery] = useState('');

  const filtered = SHORTCUTS.filter(
    (shortcut) => shortcut.keys.toLowerCase().includes(query.toLowerCase()) || shortcut.description.toLowerCase().includes(query.toLowerCase())
  );
  const grouped = filtered.reduce<Record<string, Shortcut[]>>((acc, shortcut) => {
    (acc[shortcut.category] ??= []).push(shortcut);
    return acc;
  }, {});

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[calc(100vh-4rem)] max-w-md overflow-y-auto">
        <DialogHeader>
          <DialogTitle>Keyboard Shortcuts</DialogTitle>
        </DialogHeader>
        <Input placeholder="Search shortcuts..." value={query} onChange={(event) => setQuery(event.target.value)} autoFocus />
        <div className="space-y-4 py-1">
          {Object.keys(grouped).length === 0 ? (
            <p className="py-6 text-center text-sm text-muted-foreground">No shortcuts found.</p>
          ) : (
            Object.entries(grouped).map(([category, shortcuts]) => (
              <div key={category} className="space-y-2">
                <h3 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">{CATEGORY_NAMES[category as Shortcut['category']]}</h3>
                <div className="space-y-1.5">
                  {shortcuts.map((shortcut) => (
                    <div key={shortcut.keys + shortcut.description} className="flex items-center justify-between gap-3 text-sm">
                      <kbd className="rounded border border-border/70 bg-muted/40 px-2 py-0.5 font-mono text-xs">{shortcut.keys}</kbd>
                      <span className="flex-1 text-right text-muted-foreground">{shortcut.description}</span>
                    </div>
                  ))}
                </div>
              </div>
            ))
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}
