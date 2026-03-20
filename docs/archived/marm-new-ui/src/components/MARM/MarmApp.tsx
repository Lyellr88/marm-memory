import React, { useState, useEffect, useRef } from 'react';
import { AppHeader } from '@/components/Header/AppHeader';
import { ChatContainer, Message } from '@/components/Chat/ChatContainer';
import { ChatInput } from '@/components/Input/ChatInput';
import { HelpModal } from '@/components/Help/HelpModal';
import { SessionBrowser } from '@/components/Sessions/SessionBrowser';
import { useToast } from '@/hooks/use-toast';
import { useDarkMode } from '@/hooks/useDarkMode';

interface SessionData {
  id: string;
  title: string;
  messages: Message[];
  timestamp: Date;
  marmActive: boolean;
}

export const MarmApp: React.FC = () => {
  const [messages, setMessages] = useState<Message[]>([]);
  const [isTyping, setIsTyping] = useState(false);
  const [isMarmActive, setIsMarmActive] = useState(false);
  const [currentSession, setCurrentSession] = useState<SessionData | null>(null);
  const [showHelpModal, setShowHelpModal] = useState(false);
  const [showSessionBrowser, setShowSessionBrowser] = useState(false);
  const sessionIdRef = useRef<string | null>(null);
  const { toast } = useToast();
  const { isDarkMode, toggleDarkMode } = useDarkMode();

  // Real MARM Response Handler - connects to actual backend
  const generateMarmResponse = async (userInput: string): Promise<string> => {
    try {
      // Make API call to your Express server
      const sessionId = currentSession?.id || sessionIdRef.current || 'no-session';
      console.log('Sending to backend:', { 
        sessionId, 
        messageCount: messages.length,
        isMarmActive 
      });
      
      const response = await fetch('http://localhost:8082/api/chat', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ 
          message: userInput,
          isMarmActive: isMarmActive,
          sessionId: sessionId,
          conversationHistory: messages.slice(-6) // Send last 6 messages for context when MARM is disabled
        })
      });
      
      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`);
      }
      
      const data = await response.json();
      return data.response || 'No response received';
      
    } catch (error) {
      console.error('Error calling MARM API:', error);
      return `❌ Error connecting to MARM system: ${error.message}`;
    }
  };


  // Generate session title from first message
  const generateSessionTitle = (firstMessage: string): string => {
    const words = firstMessage.trim().split(' ').slice(0, 4);
    return words.join(' ') + (words.length >= 4 ? '...' : '') || 'New Conversation';
  };

  // Load session from localStorage on mount
  useEffect(() => {
    const savedSession = localStorage.getItem('marm-current-session');
    if (savedSession) {
      try {
        const session: SessionData = JSON.parse(savedSession);
        
        // Convert timestamp strings back to Date objects
        const messagesWithDates = session.messages.map(message => ({
          ...message,
          timestamp: new Date(message.timestamp)
        }));
        
        const sessionWithDates = {
          ...session,
          messages: messagesWithDates,
          timestamp: new Date(session.timestamp)
        };
        
        setCurrentSession(sessionWithDates);
        setMessages(messagesWithDates);
        setIsMarmActive(session.marmActive);
      } catch (error) {
        console.error('Failed to load session:', error);
      }
    }
  }, []);

  // Auto-save session when messages change
  useEffect(() => {
    if (messages.length > 0) {
      const sessionData: SessionData = {
        id: currentSession?.id || Date.now().toString(),
        title: currentSession?.title || generateSessionTitle(messages[0].content),
        messages,
        timestamp: new Date(),
        marmActive: isMarmActive
      };
      
      setCurrentSession(sessionData);
      localStorage.setItem('marm-current-session', JSON.stringify(sessionData));
      
      // Also save to sessions list
      const existingSessions = JSON.parse(localStorage.getItem('marm-sessions') || '[]');
      const sessionIndex = existingSessions.findIndex((s: SessionData) => s.id === sessionData.id);
      
      if (sessionIndex >= 0) {
        existingSessions[sessionIndex] = sessionData;
      } else {
        existingSessions.unshift(sessionData);
      }
      
      // Keep only last 20 sessions
      localStorage.setItem('marm-sessions', JSON.stringify(existingSessions.slice(0, 20)));
    }
  }, [messages, isMarmActive, currentSession]);

  const handleSendMessage = async (content: string, files?: File[]) => {
    // Add user message
    const userMessage: Message = {
      id: Date.now().toString(),
      content,
      type: 'user',
      timestamp: new Date(),
      files
    };

    setMessages(prev => [...prev, userMessage]);
    setIsTyping(true);

    // Check if this is a command
    if (content.startsWith('/')) {
      try {
        // Handle command processing via API
        const response = await fetch('http://localhost:8082/api/command', {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
          },
          body: JSON.stringify({ command: content })
        });
        
        const data = await response.json();
        const commandResponse: Message = {
          id: (Date.now() + 1).toString(),
          content: data.response || 'Command executed successfully',
          type: 'assistant',
          timestamp: new Date()
        };
        
        setMessages(prev => [...prev, commandResponse]);
        setIsTyping(false);
        return;
      } catch (error) {
        console.error('Error executing command:', error);
        const errorResponse: Message = {
          id: (Date.now() + 1).toString(),
          content: `❌ Error executing command: ${error.message}`,
          type: 'assistant',
          timestamp: new Date()
        };
        
        setMessages(prev => [...prev, errorResponse]);
        setIsTyping(false);
        return;
      }
    }

    // Real AI response from MARM backend
    const getMarmResponse = async () => {
      try {
        const responseContent = await generateMarmResponse(content);
        const aiResponse: Message = {
          id: (Date.now() + 1).toString(),
          content: responseContent,
          type: 'assistant',
          timestamp: new Date()
        };
        
        setMessages(prev => [...prev, aiResponse]);
        setIsTyping(false);
      } catch (error) {
        console.error('Error getting MARM response:', error);
        const errorResponse: Message = {
          id: (Date.now() + 1).toString(),
          content: '❌ Failed to get response from AI service',
          type: 'assistant',
          timestamp: new Date()
        };
        
        setMessages(prev => [...prev, errorResponse]);
        setIsTyping(false);
      }
    };

    getMarmResponse();
  };

  const handleCommandSelect = (command: string) => {
    // Commands are handled in the message processing
    toast({
      title: "Command Selected",
      description: `Selected: ${command}`,
    });
  };

  const handleNewChat = async () => {
    // Clear frontend state
    setMessages([]);
    setCurrentSession(null);
    setIsMarmActive(false);
    sessionIdRef.current = null;  // Reset session ID ref
    
    // Clear localStorage
    localStorage.removeItem('marm-current-session');
    
    // Clear backend session data by sending multiple clear commands
    try {
      const clearCommands = ['/notebook clear'];
      
      for (const command of clearCommands) {
        await fetch('http://localhost:8082/api/command', {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
          },
          body: JSON.stringify({ command })
        });
      }
      
      console.log('Backend session data cleared');
    } catch (error) {
      console.error('Error clearing backend session:', error);
    }
    
    toast({
      title: "New Chat Started",
      description: "Fresh conversation ready",
    });
  };

  const handleSaveSession = () => {
    if (messages.length === 0) {
      toast({
        title: "Nothing to Save",
        description: "Start a conversation first",
        variant: "destructive"
      });
      return;
    }

    toast({
      title: "Session Saved",
      description: "Conversation saved to browser storage",
    });
  };

  const handleLoadSession = () => {
    setShowSessionBrowser(true);
  };

  const handleSessionLoad = (session: SessionData) => {
    setCurrentSession(session);
    setMessages(session.messages);
    setIsMarmActive(session.marmActive);
    localStorage.setItem('marm-current-session', JSON.stringify(session));
    
    toast({
      title: "Session Loaded",
      description: `Loaded "${session.title}"`,
    });
  };

  // Listen for localStorage changes to update current session title when renamed
  useEffect(() => {
    const handleStorageChange = () => {
      if (currentSession) {
        const updatedSession = JSON.parse(localStorage.getItem('marm-current-session') || 'null');
        if (updatedSession && updatedSession.id === currentSession.id && updatedSession.title !== currentSession.title) {
          setCurrentSession(updatedSession);
        }
      }
    };

    window.addEventListener('storage', handleStorageChange);
    return () => window.removeEventListener('storage', handleStorageChange);
  }, [currentSession]);

  const handleToggleMarm = async () => {
    const newState = !isMarmActive;
    setIsMarmActive(newState);
    
    // If activating MARM, send the /start marm command automatically
    if (newState) {
      try {
        // Send the /start marm command to the backend
        const response = await fetch('http://localhost:8082/api/command', {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
          },
          body: JSON.stringify({ command: '/start marm' })
        });
        
        if (!response.ok) {
          throw new Error('Failed to send MARM activation command');
        }
        
        const data = await response.json();
        
        // Add the MARM activation response as a system message
        const systemMessage: Message = {
          id: Date.now().toString(),
          content: data.response,
          isUser: false,
          timestamp: new Date()
        };
        
        setMessages(prev => [...prev, systemMessage]);
        
        toast({
          title: "MARM Activated", 
          description: "Enhanced reasoning mode enabled",
        });
      } catch (error) {
        console.error('Error activating MARM:', error);
        // Revert the state if activation failed
        setIsMarmActive(false);
        toast({
          title: "MARM Activation Failed", 
          description: "Could not initialize MARM system",
          variant: "destructive"
        });
      }
    } else {
      toast({
        title: "MARM Deactivated", 
        description: "Standard mode restored",
      });
    }
  };

  const handleShowHelp = () => {
    setShowHelpModal(true);
  };

  const handleMessageAction = (action: 'copy' | 'speak', message: Message) => {
    if (action === 'copy') {
      toast({
        title: "Copied to Clipboard",
        description: "Message copied successfully",
      });
    } else if (action === 'speak') {
      toast({
        title: "Speaking Message",
        description: "Text-to-speech activated",
      });
    }
  };

  return (
    <div className="h-screen flex flex-col bg-background">
      <AppHeader
        sessionTitle={currentSession?.title || "New Conversation"}
        isMarmActive={isMarmActive}
        onNewChat={handleNewChat}
        onSaveSession={handleSaveSession}
        onLoadSession={handleLoadSession}
        onToggleMarm={handleToggleMarm}
        onShowHelp={handleShowHelp}
        onToggleTheme={toggleDarkMode}
        isDarkMode={isDarkMode}
      />
      
      <div className="flex-1 flex flex-col min-h-0 pt-16">
        <div className="flex-1">
          <ChatContainer
            messages={messages}
            isTyping={isTyping}
            onMessageAction={handleMessageAction}
          />
        </div>
        
        <ChatInput
          onSendMessage={handleSendMessage}
          onCommandSelect={handleCommandSelect}
          isLoading={isTyping}
          placeholder={
            isMarmActive 
              ? "MARM is active - Ask anything for enhanced analysis..."
              : "Type your message... (use / for commands)"
          }
        />
      </div>
      
      <HelpModal 
        open={showHelpModal} 
        onOpenChange={setShowHelpModal}
      />
      
      <SessionBrowser
        open={showSessionBrowser}
        onOpenChange={setShowSessionBrowser}
        onLoadSession={handleSessionLoad}
      />
    </div>
  );
};
