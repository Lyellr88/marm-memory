import React, { useState, useEffect } from 'react';
import { 
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { 
  MessageSquare, 
  Calendar,
  Trash2,
  Edit3,
  Check,
  X
} from 'lucide-react';
import { cn } from '@/lib/utils';

interface SessionData {
  id: string;
  title: string;
  messages: Array<{
    id: string;
    content: string;
    isUser: boolean;
    timestamp: Date;
  }>;
  timestamp: Date;
  marmActive: boolean;
}

interface SessionBrowserProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onLoadSession: (session: SessionData) => void;
}

export const SessionBrowser: React.FC<SessionBrowserProps> = ({ 
  open, 
  onOpenChange, 
  onLoadSession 
}) => {
  const [sessions, setSessions] = useState<SessionData[]>([]);
  const [editingSessionId, setEditingSessionId] = useState<string | null>(null);
  const [editingTitle, setEditingTitle] = useState<string>('');

  useEffect(() => {
    if (open) {
      loadSessions();
    }
  }, [open]);

  const loadSessions = () => {
    const savedSessions = JSON.parse(localStorage.getItem('marm-sessions') || '[]');
    const sessionsWithDates = savedSessions.map((session: any) => ({
      ...session,
      timestamp: new Date(session.timestamp),
      messages: session.messages.map((msg: any) => ({
        ...msg,
        timestamp: new Date(msg.timestamp)
      }))
    }));
    setSessions(sessionsWithDates);
  };

  const handleLoadSession = (session: SessionData) => {
    onLoadSession(session);
    onOpenChange(false);
  };

  const handleRenameSession = (sessionId: string, event: React.MouseEvent) => {
    event.stopPropagation();
    
    const session = sessions.find(s => s.id === sessionId);
    if (!session) return;
    
    setEditingSessionId(sessionId);
    setEditingTitle(session.title);
  };

  const handleSaveRename = (sessionId: string) => {
    if (!editingTitle.trim() || editingTitle.trim() === sessions.find(s => s.id === sessionId)?.title) {
      setEditingSessionId(null);
      setEditingTitle('');
      return;
    }

    const updatedSessions = sessions.map(s => 
      s.id === sessionId ? { ...s, title: editingTitle.trim() } : s
    );
    setSessions(updatedSessions);
    localStorage.setItem('marm-sessions', JSON.stringify(updatedSessions));

    // Update current session if it's the one being renamed
    const currentSession = JSON.parse(localStorage.getItem('marm-current-session') || 'null');
    if (currentSession && currentSession.id === sessionId) {
      const updatedCurrentSession = { ...currentSession, title: editingTitle.trim() };
      localStorage.setItem('marm-current-session', JSON.stringify(updatedCurrentSession));
    }

    setEditingSessionId(null);
    setEditingTitle('');
  };

  const handleCancelRename = () => {
    setEditingSessionId(null);
    setEditingTitle('');
  };

  const handleDeleteSession = (sessionId: string, event: React.MouseEvent) => {
    event.stopPropagation();
    
    if (!confirm('Delete this conversation? This cannot be undone.')) {
      return;
    }

    const updatedSessions = sessions.filter(s => s.id !== sessionId);
    setSessions(updatedSessions);
    localStorage.setItem('marm-sessions', JSON.stringify(updatedSessions));

    // If deleting current session, clear it
    const currentSession = JSON.parse(localStorage.getItem('marm-current-session') || 'null');
    if (currentSession && currentSession.id === sessionId) {
      localStorage.removeItem('marm-current-session');
    }
  };

  const formatDate = (date: Date) => {
    const now = new Date();
    const diffInDays = Math.floor((now.getTime() - date.getTime()) / (1000 * 60 * 60 * 24));
    
    if (diffInDays === 0) {
      return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    } else if (diffInDays === 1) {
      return 'Yesterday';
    } else if (diffInDays < 7) {
      return `${diffInDays} days ago`;
    } else {
      return date.toLocaleDateString();
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl h-[70vh] overflow-hidden flex flex-col">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <MessageSquare className="w-5 h-5" />
            Browse Conversations
          </DialogTitle>
        </DialogHeader>

        <div className="flex-1 overflow-y-auto space-y-2 pr-2">
          {sessions.length === 0 ? (
            <div className="text-center text-muted-foreground py-8">
              <MessageSquare className="w-12 h-12 mx-auto mb-3 opacity-50" />
              <p>No saved conversations yet</p>
              <p className="text-sm">Start chatting to create your first conversation</p>
            </div>
          ) : (
            sessions.map((session) => (
              <div
                key={session.id}
                onClick={() => handleLoadSession(session)}
                className={cn(
                  "p-4 border border-border rounded-lg cursor-pointer",
                  "hover:bg-muted/50 transition-colors group",
                  "flex items-start justify-between"
                )}
              >
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 mb-1">
                    {editingSessionId === session.id ? (
                      <input
                        type="text"
                        value={editingTitle}
                        onChange={(e) => setEditingTitle(e.target.value)}
                        onKeyDown={(e) => {
                          if (e.key === 'Enter') {
                            handleSaveRename(session.id);
                          } else if (e.key === 'Escape') {
                            handleCancelRename();
                          }
                        }}
                        onClick={(e) => e.stopPropagation()}
                        className="font-medium bg-background border border-border rounded px-2 py-1 text-sm flex-1 focus:outline-none focus:ring-2 focus:ring-primary"
                        autoFocus
                      />
                    ) : (
                      <h3 className="font-medium truncate">{session.title}</h3>
                    )}
                    {session.marmActive && (
                      <div className="flex items-center gap-1 px-2 py-0.5 bg-success/10 text-success text-xs rounded-full">
                        <div className="w-1.5 h-1.5 rounded-full bg-success" />
                        MARM
                      </div>
                    )}
                  </div>
                  <div className="flex items-center gap-3 text-sm text-muted-foreground">
                    <div className="flex items-center gap-1">
                      <Calendar className="w-3 h-3" />
                      {formatDate(session.timestamp)}
                    </div>
                    <span>{session.messages.length} messages</span>
                  </div>
                </div>
                
                <div className="flex gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                  {editingSessionId === session.id ? (
                    <>
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={(e) => {
                          e.stopPropagation();
                          handleSaveRename(session.id);
                        }}
                        className="text-green-600 hover:text-green-700"
                      >
                        <Check className="w-4 h-4" />
                      </Button>
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={(e) => {
                          e.stopPropagation();
                          handleCancelRename();
                        }}
                        className="text-muted-foreground hover:text-foreground"
                      >
                        <X className="w-4 h-4" />
                      </Button>
                    </>
                  ) : (
                    <>
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={(e) => handleRenameSession(session.id, e)}
                        className="text-muted-foreground hover:text-foreground"
                      >
                        <Edit3 className="w-4 h-4" />
                      </Button>
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={(e) => handleDeleteSession(session.id, e)}
                        className="text-destructive hover:text-destructive"
                      >
                        <Trash2 className="w-4 h-4" />
                      </Button>
                    </>
                  )}
                </div>
              </div>
            ))
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
};