import React, { useState, useEffect } from 'react';
import { Card } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { 
  Play, 
  RotateCcw, 
  FileText, 
  BookOpen, 
  Search, 
  Zap,
  Brain,
  Archive,
  Plus,
  Eye,
  Trash2,
  BarChart3
} from 'lucide-react';
import { cn } from '@/lib/utils';

interface Command {
  id: string;
  command: string;
  description: string;
  icon: React.ReactNode;
  category: 'protocol' | 'memory' | 'response' | 'notebook';
}

const COMMANDS: Command[] = [
  // Protocol Control
  { 
    id: 'start-marm', 
    command: '/start marm', 
    description: 'Initialize MARM protocol', 
    icon: <Play className="w-4 h-4" />,
    category: 'protocol'
  },
  { 
    id: 'refresh', 
    command: '/refresh', 
    description: 'Refresh session context', 
    icon: <RotateCcw className="w-4 h-4" />,
    category: 'protocol'
  },
  
  // Memory Management - Log Commands
  { 
    id: 'log-session', 
    command: '/log session:', 
    description: 'Name current session (/log session:Name)', 
    icon: <FileText className="w-4 h-4" />,
    category: 'memory'
  },
  { 
    id: 'log-entry', 
    command: '/log entry: ', 
    description: 'Add log entry (/log entry: Date-Summary-Result)', 
    icon: <FileText className="w-4 h-4" />,
    category: 'memory'
  },
  { 
    id: 'log-show', 
    command: '/log show: ', 
    description: 'Show session entries (/log show: [session])', 
    icon: <Eye className="w-4 h-4" />,
    category: 'memory'
  },
  { 
    id: 'log-delete', 
    command: '/log delete: ', 
    description: 'Delete log entry (/log delete: [session/entry])', 
    icon: <Trash2 className="w-4 h-4" />,
    category: 'memory'
  },
  { 
    id: 'summary', 
    command: '/summary', 
    description: 'Generate conversation summary', 
    icon: <BarChart3 className="w-4 h-4" />,
    category: 'memory'
  },
  
  // Response Control
  { 
    id: 'deep-dive', 
    command: '/deep dive: ', 
    description: 'Provide detailed analysis (/deep dive: topic)', 
    icon: <Search className="w-4 h-4" />,
    category: 'response'
  },
  { 
    id: 'show-reasoning', 
    command: '/show reasoning', 
    description: 'Display thought process from /deep dive', 
    icon: <Brain className="w-4 h-4" />,
    category: 'response'
  },
  
  // Notebook Commands
  { 
    id: 'notebook-add', 
    command: '/notebook add:', 
    description: 'Add entry (/notebook add:name your data here)', 
    icon: <Plus className="w-4 h-4" />,
    category: 'notebook'
  },
  { 
    id: 'notebook-show', 
    command: '/notebook show:', 
    description: 'Display notebook contents (/notebook show:)', 
    icon: <Eye className="w-4 h-4" />,
    category: 'notebook'
  },
  { 
    id: 'notebook-use', 
    command: '/notebook use:', 
    description: 'Reference notebook (/notebook use:SessionName)', 
    icon: <BookOpen className="w-4 h-4" />,
    category: 'notebook'
  },
  { 
    id: 'notebook-clear', 
    command: '/notebook clear:', 
    description: 'Clear notebook (/notebook clear:SessionName)', 
    icon: <Trash2 className="w-4 h-4" />,
    category: 'notebook'
  },
  { 
    id: 'notebook-status', 
    command: '/notebook status:', 
    description: 'Show notebook status (/notebook status:SessionName)', 
    icon: <Archive className="w-4 h-4" />,
    category: 'notebook'
  },
  { 
    id: 'notebook-delete', 
    command: '/notebook delete: ', 
    description: 'Delete notebook entry (/notebook delete: name)', 
    icon: <Trash2 className="w-4 h-4" />,
    category: 'notebook'
  }
];

const CATEGORY_NAMES = {
  protocol: 'Protocol Control',
  memory: 'Memory Management',
  response: 'Response Control',
  notebook: 'Notebook'
};

interface CommandMenuProps {
  onSelect: (command: string) => void;
  onClose: () => void;
  filter?: string;
}

export const CommandMenu: React.FC<CommandMenuProps> = ({
  onSelect,
  onClose,
  filter = ''
}) => {
  const [searchTerm, setSearchTerm] = useState(filter);
  const [selectedIndex, setSelectedIndex] = useState(0);

  // Filter commands based on search term
  const filteredCommands = COMMANDS.filter(cmd => 
    cmd.command.toLowerCase().includes(searchTerm.toLowerCase()) ||
    cmd.description.toLowerCase().includes(searchTerm.toLowerCase())
  );

  // Group commands by category
  const groupedCommands = filteredCommands.reduce((acc, cmd) => {
    if (!acc[cmd.category]) acc[cmd.category] = [];
    acc[cmd.category].push(cmd);
    return acc;
  }, {} as Record<string, Command[]>);

  useEffect(() => {
    setSearchTerm(filter);
  }, [filter]);

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        onClose();
      } else if (e.key === 'ArrowDown') {
        e.preventDefault();
        setSelectedIndex(prev => 
          prev < filteredCommands.length - 1 ? prev + 1 : 0
        );
      } else if (e.key === 'ArrowUp') {
        e.preventDefault();
        setSelectedIndex(prev => 
          prev > 0 ? prev - 1 : filteredCommands.length - 1
        );
      } else if (e.key === 'Enter') {
        e.preventDefault();
        if (filteredCommands[selectedIndex]) {
          onSelect(filteredCommands[selectedIndex].command);
        }
      }
    };

    document.addEventListener('keydown', handleKeyDown);
    return () => document.removeEventListener('keydown', handleKeyDown);
  }, [selectedIndex, filteredCommands, onSelect, onClose]);

  return (
    <Card className={cn(
      "absolute bottom-full left-0 mb-2 w-80 max-h-96 overflow-hidden",
      "bg-glass/95 backdrop-blur-md border-glass-border shadow-lg",
      "animate-scale-in z-50"
    )}>
      {/* Header with Search */}
      <div className="p-3 border-b border-glass-border">
        <div className="flex items-center gap-2">
          <Zap className="w-4 h-4 text-primary" />
          <span className="font-medium text-sm">MARM Commands</span>
        </div>
        <Input
          placeholder="Search commands..."
          value={searchTerm}
          onChange={(e) => setSearchTerm(e.target.value)}
          className="mt-2 h-8 text-sm"
          autoFocus
        />
      </div>

      {/* Commands List */}
      <div className="max-h-64 overflow-y-auto">
        {Object.entries(groupedCommands).length === 0 ? (
          <div className="p-4 text-center text-muted-foreground text-sm">
            No commands found
          </div>
        ) : (
          Object.entries(groupedCommands).map(([category, commands]) => (
            <div key={category} className="p-2">
              <div className="text-xs font-medium text-muted-foreground uppercase tracking-wide px-2 py-1">
                {CATEGORY_NAMES[category as keyof typeof CATEGORY_NAMES]}
              </div>
              
              {commands.map((command, index) => {
                const globalIndex = filteredCommands.findIndex(c => c.id === command.id);
                return (
                  <Button
                    key={command.id}
                    onClick={() => onSelect(command.command)}
                    variant="ghost"
                    className={cn(
                      "w-full justify-start gap-3 h-auto p-2 text-left",
                      "hover:bg-muted/50 transition-colors",
                      globalIndex === selectedIndex && "bg-muted"
                    )}
                  >
                    <div className="text-primary">{command.icon}</div>
                    <div className="flex-1 min-w-0">
                      <div className="font-mono text-sm font-medium truncate">
                        {command.command}
                      </div>
                      <div className="text-xs text-muted-foreground truncate">
                        {command.description}
                      </div>
                    </div>
                  </Button>
                );
              })}
            </div>
          ))
        )}
      </div>

      {/* Footer */}
      <div className="p-2 border-t border-glass-border text-xs text-muted-foreground">
        <div className="flex justify-between">
          <span>↑↓ Navigate</span>
          <span>↵ Select</span>
          <span>Esc Close</span>
        </div>
      </div>
    </Card>
  );
};