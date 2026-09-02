import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/core';

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

const GROUPED = SHORTCUTS.reduce<Record<string, Shortcut[]>>((acc, shortcut) => {
  (acc[shortcut.category] ??= []).push(shortcut);
  return acc;
}, {});

export function KeyboardShortcutsDialog({ open, onOpenChange }: KeyboardShortcutsDialogProps) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="flex max-h-[calc(100vh-4rem)] max-w-3xl flex-col overflow-hidden">
        <DialogHeader>
          <DialogTitle>Keyboard Shortcuts</DialogTitle>
        </DialogHeader>
        <div className="min-h-0 flex-1 space-y-5 overflow-y-auto py-1 pr-1">
          {Object.entries(GROUPED).map(([category, shortcuts]) => (
            <div key={category} className="space-y-2">
              <h3 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">{CATEGORY_NAMES[category as Shortcut['category']]}</h3>
              <div className="columns-2 gap-3">
                {shortcuts.map((shortcut) => (
                  <div
                    key={shortcut.keys + shortcut.description}
                    className="mb-2.5 flex w-full break-inside-avoid flex-col gap-1 rounded-lg border border-border/70 bg-background/35 p-3"
                  >
                    <kbd className="w-fit rounded bg-primary/10 px-1.5 py-0.5 font-mono text-[11px] text-primary">{shortcut.keys}</kbd>
                    <span className="text-sm text-muted-foreground">{shortcut.description}</span>
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>
      </DialogContent>
    </Dialog>
  );
}
