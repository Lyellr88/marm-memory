import React, { useState, useEffect } from 'react';
import { 
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { 
  Target, 
  Zap, 
  BookOpen, 
  HelpCircle, 
  FileText, 
  Map, 
  Volume2,
  Settings,
  ExternalLink
} from 'lucide-react';
import { cn } from '@/lib/utils';
import ReactMarkdown from 'react-markdown';

interface HelpModalProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

interface Command {
  command: string;
  description: string;
  category: string;
}

interface DocItem {
  id: string;
  title: string;
  description: string;
  icon: React.ReactNode;
  filename: string;
}

const commands: Command[] = [
  { command: '/start marm', description: 'Activates MARM protocol for the session', category: 'Session' },
  { command: '/refresh marm', description: 'Reaffirms protocol adherence mid-session', category: 'Session' },
  
  { command: '/log session: [name]', description: 'Create or switch to named session', category: 'Logging' },
  { command: '/log entry: [date-topic]', description: 'Log milestone entry', category: 'Logging' },
  { command: '/log show: [session]', description: 'Display session entries', category: 'Logging' },
  { command: '/log delete: [target]', description: 'Delete session or entry', category: 'Logging' },
  
  { command: '/notebook add: [name] [data]', description: 'Add knowledge entry', category: 'Notebook' },
  { command: '/notebook use: [name]', description: 'Activate entry as instruction', category: 'Notebook' },
  { command: '/notebook show', description: 'Display all entries', category: 'Notebook' },
  { command: '/notebook delete: [name]', description: 'Remove entry', category: 'Notebook' },
  { command: '/notebook clear', description: 'Clear active list', category: 'Notebook' },
  { command: '/notebook status', description: 'Show active entries', category: 'Notebook' },
  
  { command: '/deep dive [topic]', description: 'Enhanced analysis with reasoning', category: 'Analysis' },
  { command: '/show reasoning', description: 'Display logic behind last response', category: 'Analysis' },
  { command: '/summary: [session]', description: 'Generate session summary', category: 'Analysis' }
];

const docs: DocItem[] = [
  {
    id: 'handbook',
    title: 'Full Handbook',
    description: 'Complete guide to MARM usage and commands',
    icon: <BookOpen className="w-5 h-5" />,
    filename: 'handbook.md'
  },
  {
    id: 'faq',
    title: 'FAQ',
    description: 'Frequently asked questions and answers',
    icon: <HelpCircle className="w-5 h-5" />,
    filename: 'faq.md'
  },
  {
    id: 'description',
    title: 'Project Description',
    description: 'Overview of MARM protocol and vision',
    icon: <FileText className="w-5 h-5" />,
    filename: 'description.md'
  },
  {
    id: 'roadmap',
    title: 'Roadmap',
    description: 'Planned features and enhancements',
    icon: <Map className="w-5 h-5" />,
    filename: 'roadmap.md'
  }
];

export const HelpModal: React.FC<HelpModalProps> = ({ open, onOpenChange }) => {
  const [activeTab, setActiveTab] = useState<'commands' | 'docs' | 'settings'>('commands');
  const [selectedCategory, setSelectedCategory] = useState<string>('All');
  
  // Voice settings state
  const [autoRead, setAutoRead] = useState(false);
  const [voiceSpeed, setVoiceSpeed] = useState(1.1);
  const [availableVoices, setAvailableVoices] = useState<SpeechSynthesisVoice[]>([]);
  const [selectedVoice, setSelectedVoice] = useState<string>('');

  // Load voice settings from localStorage on mount
  useEffect(() => {
    const savedSpeed = localStorage.getItem('marm-voice-speed');
    const savedVoice = localStorage.getItem('marm-selected-voice');
    const savedAutoRead = localStorage.getItem('marm-auto-read');
    
    if (savedSpeed) {
      setVoiceSpeed(parseFloat(savedSpeed));
    }
    if (savedVoice) {
      setSelectedVoice(savedVoice);
    }
    if (savedAutoRead) {
      setAutoRead(savedAutoRead === 'true');
    }
  }, []);
  
  // Documentation modal state
  const [showDocModal, setShowDocModal] = useState(false);
  const [docContent, setDocContent] = useState<{title: string, content: string} | null>(null);
  const [loadingDoc, setLoadingDoc] = useState(false);

  const categories = ['All', ...Array.from(new Set(commands.map(cmd => cmd.category)))];
  
  const filteredCommands = selectedCategory === 'All' 
    ? commands 
    : commands.filter(cmd => cmd.category === selectedCategory);

  // Load available voices
  useEffect(() => {
    const loadVoices = () => {
      const voices = speechSynthesis.getVoices();
      setAvailableVoices(voices);
      if (voices.length > 0 && !selectedVoice) {
        setSelectedVoice(voices[0].name);
      }
    };

    loadVoices();
    speechSynthesis.onvoiceschanged = loadVoices;

    return () => {
      speechSynthesis.onvoiceschanged = null;
    };
  }, [selectedVoice]);

  const handleDocClick = async (doc: DocItem) => {
    setLoadingDoc(true);
    try {
      const response = await fetch(`http://localhost:8082/api/docs/${doc.filename}`);
      if (!response.ok) {
        throw new Error(`Failed to load ${doc.filename}`);
      }
      
      const data = await response.json();
      setDocContent({
        title: data.title || doc.title,
        content: data.content
      });
      setShowDocModal(true);
    } catch (error) {
      console.error('Error loading document:', error);
      alert('Failed to load document. Please try again.');
    } finally {
      setLoadingDoc(false);
    }
  };

  const handleVoiceSpeedChange = (event: React.ChangeEvent<HTMLInputElement>) => {
    const speed = parseFloat(event.target.value);
    setVoiceSpeed(speed);
    localStorage.setItem('marm-voice-speed', speed.toString());
  };

  const handleAdvancedVoiceOptions = () => {
    // Open voice selection modal
    if (availableVoices.length === 0) {
      alert('No voices available. Please check your browser settings.');
      return;
    }
    
    const voiceList = availableVoices
      .map((voice, index) => `${index}: ${voice.name} (${voice.lang})`)
      .join('\n');
    
    const selection = prompt(
      `Available voices:\n${voiceList}\n\nEnter the number of the voice you want to use:`,
      '0'
    );
    
    if (selection !== null) {
      const voiceIndex = parseInt(selection);
      if (voiceIndex >= 0 && voiceIndex < availableVoices.length) {
        const voice = availableVoices[voiceIndex].name;
        setSelectedVoice(voice);
        localStorage.setItem('marm-selected-voice', voice);
      }
    }
  };

  const testVoice = () => {
    const utterance = new SpeechSynthesisUtterance('Hello! This is a test of the voice settings.');
    utterance.rate = voiceSpeed;
    
    if (selectedVoice) {
      const voice = availableVoices.find(v => v.name === selectedVoice);
      if (voice) {
        utterance.voice = voice;
      }
    }
    
    speechSynthesis.speak(utterance);
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-4xl h-[85vh] overflow-hidden flex flex-col">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2 text-xl">
            <Target className="w-6 h-6 text-primary" />
            MARM Protocol Help & Guide
            <Badge variant="secondary">v2.0</Badge>
          </DialogTitle>
        </DialogHeader>

        <div className="flex flex-col flex-1 min-h-0">
          {/* Tabs */}
          <div className="flex border-b border-border flex-shrink-0">
            <Button
              variant={activeTab === 'commands' ? 'default' : 'ghost'}
              size="sm"
              onClick={() => setActiveTab('commands')}
              className="flex items-center gap-2 rounded-none border-b-2 border-transparent data-[state=active]:border-primary"
            >
              <Zap className="w-4 h-4" />
              Commands
            </Button>
            <Button
              variant={activeTab === 'docs' ? 'default' : 'ghost'}
              size="sm"
              onClick={() => setActiveTab('docs')}
              className="flex items-center gap-2 rounded-none border-b-2 border-transparent data-[state=active]:border-primary"
            >
              <BookOpen className="w-4 h-4" />
              Documentation
            </Button>
            <Button
              variant={activeTab === 'settings' ? 'default' : 'ghost'}
              size="sm"
              onClick={() => setActiveTab('settings')}
              className="flex items-center gap-2 rounded-none border-b-2 border-transparent data-[state=active]:border-primary"
            >
              <Settings className="w-4 h-4" />
              Settings
            </Button>
          </div>

          {/* Content */}
          <div className="flex-1 overflow-y-scroll p-6 min-h-0">
            <div className="min-h-[1200px]">
            {/* Commands Tab */}
            {activeTab === 'commands' && (
              <div className="space-y-6">
                <div>
                  <h3 className="text-lg font-semibold mb-4">MARM Commands Reference</h3>
                  <p className="text-muted-foreground mb-6">
                    Use these commands to interact with the MARM protocol and manage your sessions.
                  </p>
                  
                  {/* Category Filter */}
                  <div className="flex flex-wrap gap-2 mb-6">
                    {categories.map(category => (
                      <Badge
                        key={category}
                        variant={selectedCategory === category ? 'default' : 'outline'}
                        className="cursor-pointer"
                        onClick={() => setSelectedCategory(category)}
                      >
                        {category}
                      </Badge>
                    ))}
                  </div>
                </div>

                {/* Commands List */}
                <div className="grid gap-3">
                  {filteredCommands.map((cmd, index) => (
                    <div
                      key={index}
                      className="flex items-start justify-between p-4 border border-border rounded-lg hover:bg-muted/50 transition-colors"
                    >
                      <div className="flex-1">
                        <code className="text-sm font-mono bg-muted px-2 py-1 rounded">
                          {cmd.command}
                        </code>
                        <p className="text-sm text-muted-foreground mt-2">
                          {cmd.description}
                        </p>
                      </div>
                      <Badge variant="outline" className="text-xs">
                        {cmd.category}
                      </Badge>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Documentation Tab */}
            {activeTab === 'docs' && (
              <div className="space-y-6">
                <div>
                  <h3 className="text-lg font-semibold mb-4">Documentation & Resources</h3>
                  <p className="text-muted-foreground mb-6">
                    Access comprehensive guides and documentation for MARM.
                  </p>
                </div>

                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  {docs.map((doc) => (
                    <Button
                      key={doc.id}
                      variant="outline"
                      className="h-auto p-6 flex flex-col items-start text-left hover:bg-muted/50"
                      onClick={() => handleDocClick(doc)}
                      disabled={loadingDoc}
                    >
                      <div className="flex items-center gap-3 mb-2">
                        <div className="text-primary">
                          {doc.icon}
                        </div>
                        <h4 className="font-semibold">{doc.title}</h4>
                        <ExternalLink className="w-4 h-4 ml-auto text-muted-foreground" />
                      </div>
                      <p className="text-sm text-muted-foreground">
                        {doc.description}
                      </p>
                    </Button>
                  ))}
                </div>

                <div className="mt-8 p-4 bg-muted/30 rounded-lg">
                  <h4 className="font-semibold mb-2">Quick Start</h4>
                  <ol className="text-sm text-muted-foreground space-y-1 list-decimal list-inside">
                    <li>Type <code className="bg-muted px-1 rounded">/start marm</code> to activate MARM protocol</li>
                    <li>Use <code className="bg-muted px-1 rounded">/log session: project-name</code> to create a named session</li>
                    <li>Add knowledge with <code className="bg-muted px-1 rounded">/notebook add: key data</code></li>
                    <li>Get enhanced analysis with <code className="bg-muted px-1 rounded">/deep dive topic</code></li>
                  </ol>
                </div>
              </div>
            )}

            {/* Settings Tab */}
            {activeTab === 'settings' && (
              <div className="space-y-6">
                <div>
                  <h3 className="text-lg font-semibold mb-4">Voice & Interface Settings</h3>
                  <p className="text-muted-foreground mb-6">
                    Configure text-to-speech and interface preferences.
                  </p>
                </div>

                <div className="space-y-6">
                  {/* Voice Settings */}
                  <div className="space-y-4">
                    <div className="flex items-center gap-3">
                      <Volume2 className="w-5 h-5 text-primary" />
                      <h4 className="font-semibold">Voice Settings</h4>
                    </div>
                    
                    <div className="pl-8 space-y-4">
                      <label className="flex items-center gap-3 cursor-pointer">
                        <input 
                          type="checkbox" 
                          className="rounded" 
                          checked={autoRead}
                          onChange={(e) => {
                            const checked = e.target.checked;
                            setAutoRead(checked);
                            localStorage.setItem('marm-auto-read', checked.toString());
                          }}
                        />
                        <span>Auto-read bot responses</span>
                      </label>
                      
                      <div className="space-y-2">
                        <label className="flex items-center gap-3">
                          <span className="min-w-20">Speed:</span>
                          <input 
                            type="range" 
                            min="0.5" 
                            max="2.0" 
                            step="0.1" 
                            value={voiceSpeed}
                            onChange={handleVoiceSpeedChange}
                            className="flex-1"
                          />
                          <span className="min-w-12 text-sm text-muted-foreground">{voiceSpeed}x</span>
                        </label>
                      </div>
                      
                      <div className="flex gap-2">
                        <Button variant="outline" size="sm" onClick={handleAdvancedVoiceOptions}>
                          Choose Voice ({availableVoices.length} available)
                        </Button>
                        <Button variant="outline" size="sm" onClick={testVoice}>
                          Test Voice
                        </Button>
                      </div>
                      
                      {selectedVoice && (
                        <div className="text-sm text-muted-foreground">
                          Current voice: {selectedVoice}
                        </div>
                      )}
                    </div>
                  </div>

                  {/* Interface Settings */}
                  <div className="space-y-4 pt-6 border-t">
                    <h4 className="font-semibold">Interface Preferences</h4>
                    
                    <div className="space-y-3">
                      <label className="flex items-center gap-3 cursor-pointer">
                        <input type="checkbox" className="rounded" defaultChecked />
                        <span>Show command suggestions</span>
                      </label>
                      
                      <label className="flex items-center gap-3 cursor-pointer">
                        <input type="checkbox" className="rounded" defaultChecked />
                        <span>Enable markdown rendering</span>
                      </label>
                      
                      <label className="flex items-center gap-3 cursor-pointer">
                        <input type="checkbox" className="rounded" />
                        <span>Compact message layout</span>
                      </label>
                    </div>
                  </div>
                </div>
              </div>
            )}
            </div>
          </div>
        </div>
      </DialogContent>
      
      {/* Document Modal */}
      <Dialog open={showDocModal} onOpenChange={setShowDocModal}>
        <DialogContent className="max-w-4xl max-h-[90vh] overflow-hidden flex flex-col">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <FileText className="w-5 h-5" />
              {docContent?.title || 'Documentation'}
            </DialogTitle>
          </DialogHeader>
          <div className="flex-1 overflow-y-auto p-6 prose prose-sm max-w-none dark:prose-invert">
            {docContent ? (
              <ReactMarkdown>{docContent.content}</ReactMarkdown>
            ) : (
              <div className="text-center text-muted-foreground">Loading...</div>
            )}
          </div>
        </DialogContent>
      </Dialog>
    </Dialog>
  );
};