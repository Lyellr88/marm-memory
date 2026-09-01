import { useEffect, useState } from 'react';
import { KeyRound, Network, ServerCog } from 'lucide-react';
import { useConnection } from '@/lib/marm-connection';
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle, Button, Input, Label } from '@/components/ui/core';

export function SettingsDialog({ open, onOpenChange }: { open: boolean, onOpenChange: (open: boolean) => void }) {
  const { baseUrl, apiKey, clearApiKey, setBaseUrl, setApiKey } = useConnection();
  const [localUrl, setLocalUrl] = useState(baseUrl);
  const [localKey, setLocalKey] = useState(apiKey || '');

  useEffect(() => {
    if (open) {
      setLocalUrl(baseUrl);
      setLocalKey(apiKey || '');
    }
  }, [open, baseUrl, apiKey]);

  const handleSave = () => {
    setBaseUrl(localUrl);
    setApiKey(localKey || null);
    onOpenChange(false);
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="settings-dialog !max-w-2xl !gap-0 !p-0">
        <DialogHeader className="settings-dialog-header border-b border-border/70 px-6 py-5 pr-16">
          <div className="flex items-start gap-3">
            <div className="settings-dialog-mark"><ServerCog className="h-4 w-4" /></div>
            <div>
              <p className="text-[10px] font-semibold uppercase tracking-[0.16em] text-primary/80">Local control plane</p>
              <DialogTitle className="mt-1">Connection</DialogTitle>
              <DialogDescription className="mt-1">Where this browser reaches your local MARM Console. Runtime health and automation live in System.</DialogDescription>
            </div>
          </div>
        </DialogHeader>

        <div className="grid gap-4 p-6">
          <div className="grid gap-2">
            <Label htmlFor="base-url">Console base URL</Label>
            <Input id="base-url" value={localUrl} onChange={(event) => setLocalUrl(event.target.value)} placeholder="http://127.0.0.1:8002" className="font-mono text-xs" />
            <p className="text-xs text-muted-foreground">Saved locally in this browser. The Console then securely talks to the MCP runtime.</p>
          </div>
          <div className="grid gap-2">
            <Label htmlFor="api-key">API key (Bearer token)</Label>
            <Input id="api-key" type="password" value={localKey} onChange={(event) => setLocalKey(event.target.value)} placeholder="Optional" className="font-mono text-xs" />
            <div className="flex items-center justify-between gap-3 text-xs text-muted-foreground">
              <span>{apiKey ? 'A token is held only in this browser tab.' : 'No token is held in this browser tab.'}</span>
              {apiKey && <Button size="sm" variant="ghost" onClick={() => { clearApiKey(); setLocalKey(''); }}>Clear token</Button>}
            </div>
          </div>
          <p className="flex items-center gap-2 rounded-lg border border-border/70 bg-background/35 p-3 text-xs text-muted-foreground"><Network className="h-3.5 w-3.5 shrink-0 text-primary" />Runtime health, automation, storage, and watch health moved to the System tab.</p>
        </div>

        <DialogFooter className="border-t border-border/70 px-6 py-4">
          <Button variant="outline" onClick={() => onOpenChange(false)}>Close</Button>
          <Button onClick={handleSave}><KeyRound className="mr-2 h-4 w-4" />Save connection</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
