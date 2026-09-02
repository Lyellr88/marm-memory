export type AgentType = 'claude' | 'codex' | 'antigravity';

export type Platform = 'windows' | 'macos' | 'linux';

export interface AgentCommandSet {
  install: string;
  launch: string;
  verify: string;
}

export interface AgentConfig {
  id: AgentType;
  name: string;
  description: string;
  commands: Record<Platform, AgentCommandSet>;
}

export interface DependencyCheck {
  name: string;
  command: string;
  installCommand: string;
}

export type OnboardingPhase =
  | 'os-selection'
  | 'agent-selection'
  | 'dependency-check'
  | 'install-agent'
  | 'launch-agent';

export interface TerminalSettings {
  profile: ProfileSettings;
  appearance: AppearanceSettings;
  clipboard: ClipboardSettings;
  scrollback: ScrollbackSettings;
  notifications: NotificationSettings;
}

export interface ProfileSettings {
  useProfile: boolean;
  customPath?: string;
}

export interface AppearanceSettings {
  fontSize: number;
  padding: number;
  cursorStyle: 'block' | 'bar' | 'underline';
  cursorBlink: boolean;
  opacity: number;
}

export interface ClipboardSettings {
  copyOnSelection: boolean;
  wordSeparators: string;
  tripleClickSelectsLine: boolean;
}

export interface ScrollbackSettings {
  scrollbackSize: 1000 | 5000 | 10000 | 50000;
  customTitleFormat: string;
}

export interface NotificationSettings {
  bellStyle: 'none' | 'visual' | 'audio' | 'both';
  bellVolume: 'low' | 'medium' | 'high';
  bellSound: 'chime' | 'bell' | 'pulse';
}

export const DEFAULT_TERMINAL_SETTINGS: TerminalSettings = {
  profile: {
    useProfile: true,
    customPath: '',
  },
  appearance: {
    fontSize: 13,
    padding: 8,
    cursorStyle: 'block',
    cursorBlink: true,
    opacity: 100,
  },
  clipboard: {
    copyOnSelection: false,
    wordSeparators: ' ()[]{}\'",`',
    tripleClickSelectsLine: true,
  },
  scrollback: {
    scrollbackSize: 10000,
    customTitleFormat: 'Terminal {n}',
  },
  notifications: {
    bellStyle: 'none',
    bellVolume: 'medium',
    bellSound: 'chime',
  },
};
