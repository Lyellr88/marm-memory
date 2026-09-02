import { forwardRef, useEffect, useImperativeHandle, useRef, useState } from 'react';
import { Terminal as XTerm } from '@xterm/xterm';
import { FitAddon } from '@xterm/addon-fit';
import { SearchAddon } from '@xterm/addon-search';
import { WebLinksAddon } from '@xterm/addon-web-links';
import { WebglAddon } from '@xterm/addon-webgl';
import '@xterm/xterm/css/xterm.css';
import { cn } from '@/components/ui/core';
import { useClipboard } from './hooks/useClipboard';
import { useTerminalHotkeys } from './hooks/useTerminalHotkeys';
import type { TerminalSettings } from './types';

export type ConnectionState = 'idle' | 'connecting' | 'open' | 'closed';

export interface TerminalSessionHandle {
  sendInput: (data: string) => void;
  sendClear: () => void;
  focus: () => void;
}

interface TerminalSessionViewProps {
  active: boolean;
  baseUrl: string;
  cwd?: string;
  shellHint: string | null;
  settings: TerminalSettings;
  resumeSessionId?: string;
  onConnectionStateChange: (state: ConnectionState) => void;
  onSessionIdChange: (sessionId: string) => void;
}

function playBell(sound: TerminalSettings['notifications']['bellSound'], volume: TerminalSettings['notifications']['bellVolume']) {
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
    // Bell sound is best-effort.
  }
}

function notifyBell() {
  if (typeof Notification === 'undefined') return;
  if (Notification.permission === 'granted') {
    new Notification('Terminal', { body: 'Terminal bell triggered' });
  } else if (Notification.permission !== 'denied') {
    void Notification.requestPermission().then((permission) => {
      if (permission === 'granted') new Notification('Terminal', { body: 'Terminal bell triggered' });
    });
  }
}

export const TerminalSessionView = forwardRef<TerminalSessionHandle, TerminalSessionViewProps>(
  ({ active, baseUrl, cwd, shellHint, settings, resumeSessionId, onConnectionStateChange, onSessionIdChange }, ref) => {
    const containerRef = useRef<HTMLDivElement>(null);
    const termRef = useRef<XTerm | null>(null);
    const socketRef = useRef<WebSocket | null>(null);
    const searchAddonRef = useRef<SearchAddon | null>(null);
    const settingsRef = useRef(settings);
    const onSessionIdChangeRef = useRef(onSessionIdChange);
    const [searchOpen, setSearchOpen] = useState(false);

    const { copySelection, pasteClipboard } = useClipboard();
    const { handleKeyEvent } = useTerminalHotkeys({
      onData: (data) => {
        if (socketRef.current?.readyState === WebSocket.OPEN) socketRef.current.send(JSON.stringify({ type: 'input', data }));
      },
      copySelection: (term) => copySelection(term),
      pasteClipboard: (onData) => pasteClipboard(onData),
      onOpenSearch: () => setSearchOpen(true),
    });

    useEffect(() => {
      settingsRef.current = settings;
    }, [settings]);

    useEffect(() => {
      onSessionIdChangeRef.current = onSessionIdChange;
    }, [onSessionIdChange]);

    useImperativeHandle(ref, () => ({
      sendInput: (data: string) => {
        if (socketRef.current?.readyState === WebSocket.OPEN) socketRef.current.send(JSON.stringify({ type: 'input', data }));
      },
      sendClear: () => {
        const command = /pwsh|powershell/i.test(shellHint ?? '') ? 'Clear-Host\r' : 'clear\r';
        if (socketRef.current?.readyState === WebSocket.OPEN) socketRef.current.send(JSON.stringify({ type: 'input', data: command }));
      },
      focus: () => termRef.current?.focus(),
    }));

    useEffect(() => {
      if (!containerRef.current) return;

      const term = new XTerm({
        cursorBlink: settingsRef.current.appearance.cursorBlink,
        cursorStyle: settingsRef.current.appearance.cursorStyle,
        fontSize: settingsRef.current.appearance.fontSize,
        scrollback: settingsRef.current.scrollback.scrollbackSize,
        wordSeparator: settingsRef.current.clipboard.wordSeparators,
        convertEol: true,
      });
      term.attachCustomKeyEventHandler(handleKeyEvent(term));

      const fitAddon = new FitAddon();
      term.loadAddon(fitAddon);
      const webLinksAddon = new WebLinksAddon((_event, uri) => {
        window.open(uri, '_blank', 'noopener,noreferrer');
      });
      term.loadAddon(webLinksAddon);
      const searchAddon = new SearchAddon();
      term.loadAddon(searchAddon);
      searchAddonRef.current = searchAddon;
      term.open(containerRef.current);

      try {
        const webgl = new WebglAddon();
        webgl.onContextLoss(() => webgl.dispose());
        term.loadAddon(webgl);
      } catch {
        // WebGL isn't available everywhere; the canvas renderer still works.
      }

      fitAddon.fit();
      termRef.current = term;

      const wsUrl = `${baseUrl.replace(/^http/, 'ws')}/api/terminal/ws`;
      const socket = new WebSocket(wsUrl);
      socketRef.current = socket;
      onConnectionStateChange('connecting');

      const sendSpawn = () => {
        socket.send(JSON.stringify({ type: 'spawn', cols: term.cols, rows: term.rows, cwd, useProfile: settingsRef.current.profile.useProfile }));
      };
      let attaching = Boolean(resumeSessionId);
      let sawReplay = false;
      let suppressEcho = false;

      socket.onopen = () => {
        onConnectionStateChange('open');
        if (resumeSessionId) socket.send(JSON.stringify({ type: 'attach', sessionId: resumeSessionId }));
        else sendSpawn();
      };
      socket.onmessage = (event) => {
        const message = JSON.parse(event.data as string);
        if (message.type === 'data') {
          if (attaching && !sawReplay) {
            // The replayed scrollback can end mid-query (e.g. a shell's device-attributes
            // probe sent right before the connection dropped). xterm auto-answers that
            // through onData same as real keystrokes, which would otherwise get typed
            // into the live shell as garbage. Swallow onData until the replay write settles.
            sawReplay = true;
            suppressEcho = true;
            term.write(message.data, () => {
              setTimeout(() => {
                suppressEcho = false;
              }, 0);
            });
          } else {
            term.write(message.data);
          }
        }
        else if (message.type === 'exit') term.write(`\r\n[process exited: ${message.exitCode ?? 'unknown'}]\r\n`);
        else if (message.type === 'status' && message.state === 'running') {
          attaching = false;
          if (message.sessionId) onSessionIdChangeRef.current(message.sessionId);
        } else if (message.type === 'status' && message.state === 'error') {
          if (attaching) {
            // The session this pane was pointed at is gone (expired, or the
            // server restarted) -- fall back to a fresh spawn on the same
            // connection rather than leaving the pane dead.
            attaching = false;
            sendSpawn();
          } else {
            term.write(`\r\n[terminal error: ${message.message}]\r\n`);
          }
        }
      };
      socket.onclose = () => onConnectionStateChange('closed');
      socket.onerror = () => onConnectionStateChange('closed');

      const onData = term.onData((data) => {
        if (suppressEcho) return;
        if (socket.readyState === WebSocket.OPEN) socket.send(JSON.stringify({ type: 'input', data }));
      });

      const onBell = term.onBell(() => {
        const style = settingsRef.current.notifications.bellStyle;
        if (style === 'visual' || style === 'both') notifyBell();
        if (style === 'audio' || style === 'both') playBell(settingsRef.current.notifications.bellSound, settingsRef.current.notifications.bellVolume);
      });

      let suppressSelectionCopy = false;
      const onSelectionChange = term.onSelectionChange(() => {
        if (suppressSelectionCopy) {
          suppressSelectionCopy = false;
          return;
        }
        if (settingsRef.current.clipboard.copyOnSelection && term.hasSelection()) void copySelection(term, false);
      });

      const resizeObserver = new ResizeObserver(() => {
        const rect = containerRef.current?.getBoundingClientRect();
        if (!rect || rect.width < 50 || rect.height < 50) return;
        fitAddon.fit();
        if (socket.readyState === WebSocket.OPEN) socket.send(JSON.stringify({ type: 'resize', cols: term.cols, rows: term.rows }));
      });
      resizeObserver.observe(containerRef.current);

      return () => {
        onData.dispose();
        onBell.dispose();
        onSelectionChange.dispose();
        resizeObserver.disconnect();
        socket.close();
        term.dispose();
        termRef.current = null;
        socketRef.current = null;
        searchAddonRef.current = null;
      };
      // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [baseUrl, cwd]);

    useEffect(() => {
      const term = termRef.current;
      if (!term) return;
      term.options.cursorBlink = settings.appearance.cursorBlink;
      term.options.cursorStyle = settings.appearance.cursorStyle;
      term.options.fontSize = settings.appearance.fontSize;
      term.options.scrollback = settings.scrollback.scrollbackSize;
      term.options.wordSeparator = settings.clipboard.wordSeparators;
    }, [settings.appearance, settings.scrollback, settings.clipboard]);

    const handleClick: React.MouseEventHandler<HTMLDivElement> = (event) => {
      termRef.current?.focus();
      if (event.detail === 3 && settings.clipboard.tripleClickSelectsLine) {
        const term = termRef.current;
        if (term) {
          const cursorY = term.buffer.active.cursorY;
          term.selectLines(cursorY, cursorY);
        }
      }
    };

    const handleContextMenu: React.MouseEventHandler<HTMLDivElement> = (event) => {
      event.preventDefault();
      const term = termRef.current;
      if (term?.hasSelection()) void copySelection(term);
      else void pasteClipboard((data) => socketRef.current?.readyState === WebSocket.OPEN && socketRef.current.send(JSON.stringify({ type: 'input', data })));
    };

    return (
      <div className={cn('absolute inset-0', active ? 'block' : 'hidden')}>
        {searchOpen && (
          <TerminalSearchBar
            onClose={() => {
              setSearchOpen(false);
              searchAddonRef.current?.clearDecorations();
              termRef.current?.focus();
            }}
            onFind={(query, direction) => {
              const addon = searchAddonRef.current;
              if (!addon || !query) return;
              if (direction === 'next') addon.findNext(query);
              else addon.findPrevious(query);
            }}
          />
        )}
        <div
          ref={containerRef}
          onClick={handleClick}
          onContextMenu={handleContextMenu}
          style={{ padding: settings.appearance.padding, opacity: settings.appearance.opacity / 100 }}
          className="h-full"
        />
      </div>
    );
  }
);

TerminalSessionView.displayName = 'TerminalSessionView';

function TerminalSearchBar({ onClose, onFind }: { onClose: () => void; onFind: (query: string, direction: 'next' | 'previous') => void }) {
  const [query, setQuery] = useState('');

  return (
    <div className="absolute right-3 top-3 z-10 flex items-center gap-1 rounded-md border border-border/70 bg-card/95 px-2 py-1 text-xs shadow-lg">
      <input
        autoFocus
        placeholder="Search..."
        value={query}
        onChange={(event) => {
          setQuery(event.target.value);
          onFind(event.target.value, 'next');
        }}
        onKeyDown={(event) => {
          if (event.key === 'Escape') onClose();
          else if (event.key === 'Enter') onFind(query, event.shiftKey ? 'previous' : 'next');
        }}
        className="w-32 bg-transparent text-xs outline-none placeholder:text-muted-foreground"
      />
      <button type="button" onClick={onClose} className="text-muted-foreground hover:text-foreground">×</button>
    </div>
  );
}
