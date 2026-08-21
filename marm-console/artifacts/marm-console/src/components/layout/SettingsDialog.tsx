import { useState, useEffect } from 'react';
import { useConnection } from '@/lib/marm-connection';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter, Button, Input, Label } from '@/components/ui/core';

export function SettingsDialog({ open, onOpenChange }: { open: boolean, onOpenChange: (open: boolean) => void }) {
  const { baseUrl, apiKey, setBaseUrl, setApiKey } = useConnection();
  
  const [localUrl, setLocalUrl] = useState(baseUrl);
  const [localKey, setLocalKey] = useState(apiKey || '');

  // Reset inputs when opened
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
      <DialogContent className="border-t-primary/35">
        <DialogHeader>
          <div className="mb-1 text-[10px] font-semibold uppercase tracking-[0.16em] text-primary/80">Local runtime</div>
          <DialogTitle>Connection settings</DialogTitle>
          <DialogDescription>
            Configure your local MARM backend connection.
          </DialogDescription>
        </DialogHeader>
        <div className="grid gap-4 py-4">
          <div className="grid gap-2">
            <Label htmlFor="base-url">Base URL</Label>
            <Input
              id="base-url"
              value={localUrl}
              onChange={(e) => setLocalUrl(e.target.value)}
              placeholder="http://127.0.0.1:8002"
              className="font-mono text-xs"
            />
          </div>
          <div className="grid gap-2">
            <Label htmlFor="api-key">API Key (Bearer Token)</Label>
            <Input
              id="api-key"
              type="password"
              value={localKey}
              onChange={(e) => setLocalKey(e.target.value)}
              placeholder="Optional"
              className="font-mono text-xs"
            />
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>Cancel</Button>
          <Button onClick={handleSave}>Save Changes</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
