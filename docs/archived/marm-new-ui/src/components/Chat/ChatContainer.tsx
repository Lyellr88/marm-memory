import React, { useRef, useEffect, useMemo } from 'react';
import { MessageBubble } from './MessageBubble';
import { TypingIndicator } from './TypingIndicator';
import { TokenCounter } from './TokenCounter';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Button } from '@/components/ui/button';
import { ArrowDown } from 'lucide-react';
import { cn } from '@/lib/utils';
import { estimateTokensFromMessages } from '../../utils/tokenCounter';

export interface Message {
  id: string;
  content: string;
  type: 'user' | 'assistant';
  timestamp: Date;
  files?: File[];
}

interface ChatContainerProps {
  messages: Message[];
  isTyping?: boolean;
  onMessageAction?: (action: 'copy' | 'speak', message: Message) => void;
}

export const ChatContainer: React.FC<ChatContainerProps> = ({
  messages,
  isTyping = false,
  onMessageAction
}) => {
  const scrollAreaRef = useRef<HTMLDivElement>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const [showScrollButton, setShowScrollButton] = React.useState(false);

  // Calculate token usage
  const { inputTokens, outputTokens } = useMemo(() => {
    const userMessages = messages.filter(m => m.type === 'user');
    const assistantMessages = messages.filter(m => m.type === 'assistant');
    
    return {
      inputTokens: estimateTokensFromMessages(userMessages),
      outputTokens: estimateTokensFromMessages(assistantMessages)
    };
  }, [messages]);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages, isTyping]);

  const handleScroll = (event: React.UIEvent<HTMLDivElement>) => {
    const { scrollTop, scrollHeight, clientHeight } = event.currentTarget;
    const isAtBottom = scrollHeight - scrollTop - clientHeight < 50;
    setShowScrollButton(!isAtBottom);
  };

  return (
    <div className="relative h-full bg-gradient-chat">
      {/* Token Counter - Bottom Right */}
      {messages.length > 0 && (
        <div className="absolute bottom-4 right-4 z-10">
          <TokenCounter 
            inputTokens={inputTokens} 
            outputTokens={outputTokens}
          />
        </div>
      )}
      
      <ScrollArea 
        ref={scrollAreaRef}
        className="h-full px-4 py-6"
        onScrollCapture={handleScroll}
      >
        <div className="max-w-4xl mx-auto space-y-6">
          {messages.length === 0 ? (
            <div className="flex items-center justify-center h-96">
              <div className="text-center space-y-4 animate-fade-in">
                <div className="w-20 h-20 mx-auto bg-gradient-primary rounded-full flex items-center justify-center shadow-glow">
                  <span className="text-2xl font-bold text-primary-foreground">M</span>
                </div>
                <div>
                  <h3 className="text-xl font-semibold text-foreground mb-2">
                    Welcome to MARM
                  </h3>
                  <p className="text-muted-foreground max-w-md">
                    Your intelligent AI assistant is ready to help. Try using commands like 
                    <span className="font-mono text-primary"> /start marm</span> to begin.
                  </p>
                </div>
              </div>
            </div>
          ) : (
            <>
              {messages.map((message, index) => (
                <MessageBubble
                  key={message.id}
                  message={message}
                  isFirst={index === 0}
                  onAction={onMessageAction}
                />
              ))}
              
              {isTyping && (
                <div className="animate-slide-up">
                  <TypingIndicator />
                </div>
              )}
            </>
          )}
          <div ref={messagesEndRef} />
        </div>
      </ScrollArea>

      {/* Scroll to bottom button */}
      {showScrollButton && (
        <Button
          onClick={scrollToBottom}
          size="sm"
          className={cn(
            "fixed bottom-24 right-6 z-10 rounded-full w-10 h-10 p-0",
            "bg-glass/80 backdrop-blur-md border border-glass-border",
            "hover:bg-glass shadow-md hover:shadow-lg transition-all"
          )}
        >
          <ArrowDown className="w-4 h-4" />
        </Button>
      )}
    </div>
  );
};