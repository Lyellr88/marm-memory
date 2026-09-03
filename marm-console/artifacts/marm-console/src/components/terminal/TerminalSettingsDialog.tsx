import { useEffect, useState } from 'react';
import { Button, Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle, Input, Label, Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/core';
import { cn } from '@/components/ui/core';
import { DEFAULT_TERMINAL_SETTINGS, type TerminalSettings } from './types';

interface TerminalSettingsDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  settings: TerminalSettings;
  onSave: (settings: TerminalSettings) => void;
}

function playBellPreview(sound: 'chime' | 'bell' | 'pulse', volume: 'low' | 'medium' | 'high') {
  try {
    const context = new AudioContext();
    const volumeSettings = { low: 0.15, medium: 0.3, high: 0.5 };
    const masterVolume = volumeSettings[volume];
    const now = context.currentTime;

    const playTone = (frequency: number, startTime: number, duration: number, volumeMultiplier = 1) => {
      const osc = context.createOscillator();
      const gain = context.createGain();
      osc.connect(gain);
      gain.connect(context.destination);
      osc.frequency.value = frequency;
      osc.type = 'sine';
      gain.gain.setValueAtTime(0, startTime);
      gain.gain.linearRampToValueAtTime(masterVolume * volumeMultiplier, startTime + 0.03);
      gain.gain.exponentialRampToValueAtTime(0.01, startTime + duration);
      osc.start(startTime);
      osc.stop(startTime + duration);
    };

    if (sound === 'chime') {
      playTone(523, now, 0.3, 1.0);
      playTone(659, now + 0.1, 0.25, 0.8);
    } else if (sound === 'bell') {
      playTone(800, now, 0.15);
      playTone(600, now + 0.15, 0.15);
    } else {
      playTone(700, now, 0.08);
      playTone(700, now + 0.1, 0.08);
      playTone(700, now + 0.2, 0.08);
    }
  } catch {
    // Preview is best-effort; a silent failure just means no preview sound.
  }
}

function Pill({ active, onClick, children }: { active: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        'rounded-md border px-3 py-1.5 text-xs font-medium transition-colors',
        active ? 'border-primary/55 bg-primary/15 text-primary' : 'border-border/70 bg-background/40 text-muted-foreground hover:border-border hover:text-foreground'
      )}
    >
      {children}
    </button>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="mb-4 break-inside-avoid space-y-3 rounded-lg border border-border/70 bg-background/35 p-4">
      <h3 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">{title}</h3>
      {children}
    </div>
  );
}

export function TerminalSettingsDialog({ open, onOpenChange, settings: initialSettings, onSave }: TerminalSettingsDialogProps) {
  const [settings, setSettings] = useState<TerminalSettings>(initialSettings);

  useEffect(() => {
    if (open) setSettings(initialSettings);
  }, [open, initialSettings]);

  const handleSave = () => {
    onSave(settings);
    onOpenChange(false);
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[calc(100vh-4rem)] max-w-3xl overflow-y-auto">
        <DialogHeader>
          <DialogTitle>Terminal Settings</DialogTitle>
        </DialogHeader>

        <div className="columns-1 py-1 sm:columns-2 sm:gap-4">
          {/* Notifications is intentionally outside this container -- it renders
              full-width below, since its pill rows need more room than one column gives. */}
          <Section title="Profile & Startup">
            <label className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={settings.profile.useProfile}
                onChange={(event) => setSettings({ ...settings, profile: { ...settings.profile, useProfile: event.target.checked } })}
              />
              Use shell profile
            </label>
            <div className="space-y-1.5">
              <Label className="text-xs text-muted-foreground">Starting directory</Label>
              <Input
                placeholder="Defaults to the server's home directory"
                value={settings.profile.customPath ?? ''}
                onChange={(event) => setSettings({ ...settings, profile: { ...settings.profile, customPath: event.target.value } })}
              />
            </div>
          </Section>

          <Section title="Appearance">
            <div className="grid grid-cols-3 gap-3">
              <div className="space-y-1.5">
                <Label className="text-xs text-muted-foreground">Font size</Label>
                <Input
                  type="number"
                  min={10}
                  max={20}
                  value={settings.appearance.fontSize}
                  onChange={(event) => setSettings({ ...settings, appearance: { ...settings.appearance, fontSize: Number(event.target.value) || 13 } })}
                />
              </div>
              <div className="space-y-1.5">
                <Label className="text-xs text-muted-foreground">Opacity</Label>
                <Input
                  type="number"
                  min={0}
                  max={100}
                  value={settings.appearance.opacity}
                  onChange={(event) => setSettings({ ...settings, appearance: { ...settings.appearance, opacity: Number(event.target.value) || 100 } })}
                />
              </div>
              <div className="space-y-1.5">
                <Label className="text-xs text-muted-foreground">Padding</Label>
                <Input
                  type="number"
                  min={0}
                  max={20}
                  value={settings.appearance.padding}
                  onChange={(event) => setSettings({ ...settings, appearance: { ...settings.appearance, padding: Number(event.target.value) || 0 } })}
                />
              </div>
            </div>
            <div className="space-y-1.5">
              <Label className="text-xs text-muted-foreground">Cursor style</Label>
              <div className="flex gap-2">
                {(['block', 'bar', 'underline'] as const).map((style) => (
                  <Pill key={style} active={settings.appearance.cursorStyle === style} onClick={() => setSettings({ ...settings, appearance: { ...settings.appearance, cursorStyle: style } })}>
                    {style[0].toUpperCase() + style.slice(1)}
                  </Pill>
                ))}
              </div>
            </div>
            <label className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={settings.appearance.cursorBlink}
                onChange={(event) => setSettings({ ...settings, appearance: { ...settings.appearance, cursorBlink: event.target.checked } })}
              />
              Blink cursor
            </label>
          </Section>

          <Section title="Clipboard & Selection">
            <label className="flex items-center gap-2 text-sm" title="Automatically copy text when selected (like Linux terminals)">
              <input
                type="checkbox"
                checked={settings.clipboard.copyOnSelection}
                onChange={(event) => setSettings({ ...settings, clipboard: { ...settings.clipboard, copyOnSelection: event.target.checked } })}
              />
              Copy on selection
            </label>
            <label className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={settings.clipboard.tripleClickSelectsLine}
                onChange={(event) => setSettings({ ...settings, clipboard: { ...settings.clipboard, tripleClickSelectsLine: event.target.checked } })}
              />
              Triple-click selects line
            </label>
            <div className="space-y-1.5">
              <Label className="text-xs text-muted-foreground">Word separators</Label>
              <Input
                value={settings.clipboard.wordSeparators}
                onChange={(event) => setSettings({ ...settings, clipboard: { ...settings.clipboard, wordSeparators: event.target.value } })}
              />
            </div>
          </Section>

          <Section title="Scrollback & Tab Titles">
            <div className="space-y-1.5">
              <Label className="text-xs text-muted-foreground">Buffer size</Label>
              <Select
                value={String(settings.scrollback.scrollbackSize)}
                onValueChange={(value) => setSettings({ ...settings, scrollback: { ...settings.scrollback, scrollbackSize: Number(value) as TerminalSettings['scrollback']['scrollbackSize'] } })}
              >
                <SelectTrigger><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="1000">1,000 lines</SelectItem>
                  <SelectItem value="5000">5,000 lines</SelectItem>
                  <SelectItem value="10000">10,000 lines</SelectItem>
                  <SelectItem value="50000">50,000 lines</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-1.5">
              <Label className="text-xs text-muted-foreground">Tab title format</Label>
              <Input
                placeholder="Use {n} for the session number"
                value={settings.scrollback.customTitleFormat}
                onChange={(event) => setSettings({ ...settings, scrollback: { ...settings.scrollback, customTitleFormat: event.target.value } })}
              />
            </div>
          </Section>

        </div>

        <Section title="Notifications">
          <div className="space-y-1.5">
            <Label className="text-xs text-muted-foreground">Bell style</Label>
            <div className="flex flex-wrap gap-2">
              {(['none', 'visual', 'audio', 'both'] as const).map((style) => (
                <Pill key={style} active={settings.notifications.bellStyle === style} onClick={() => setSettings({ ...settings, notifications: { ...settings.notifications, bellStyle: style } })}>
                  {style[0].toUpperCase() + style.slice(1)}
                </Pill>
              ))}
            </div>
          </div>
          {(settings.notifications.bellStyle === 'audio' || settings.notifications.bellStyle === 'both') && (
            <div className="grid grid-cols-2 gap-6">
              <div className="space-y-1.5">
                <Label className="text-xs text-muted-foreground">Volume</Label>
                <div className="flex gap-2">
                  {(['low', 'medium', 'high'] as const).map((volume) => (
                    <Pill key={volume} active={settings.notifications.bellVolume === volume} onClick={() => setSettings({ ...settings, notifications: { ...settings.notifications, bellVolume: volume } })}>
                      {volume[0].toUpperCase() + volume.slice(1)}
                    </Pill>
                  ))}
                </div>
              </div>
              <div className="space-y-1.5">
                <Label className="text-xs text-muted-foreground">Sound</Label>
                <div className="flex gap-2">
                  {(['chime', 'bell', 'pulse'] as const).map((sound) => (
                    <Pill
                      key={sound}
                      active={settings.notifications.bellSound === sound}
                      onClick={() => {
                        setSettings({ ...settings, notifications: { ...settings.notifications, bellSound: sound } });
                        playBellPreview(sound, settings.notifications.bellVolume);
                      }}
                    >
                      {sound[0].toUpperCase() + sound.slice(1)}
                    </Pill>
                  ))}
                </div>
              </div>
            </div>
          )}
        </Section>

        <DialogFooter className="gap-2">
          <Button variant="outline" onClick={() => setSettings(DEFAULT_TERMINAL_SETTINGS)}>Reset to Defaults</Button>
          <Button variant="outline" onClick={() => onOpenChange(false)}>Cancel</Button>
          <Button onClick={handleSave}>Save Settings</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
