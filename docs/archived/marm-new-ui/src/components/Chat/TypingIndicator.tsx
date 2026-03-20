import React from 'react';
import { Bot } from 'lucide-react';
import { cn } from '@/lib/utils';

export const TypingIndicator: React.FC = () => {
  return (
    <div className="flex gap-3">
      {/* Avatar */}
      <div className="flex-shrink-0 w-8 h-8 rounded-full flex items-center justify-center bg-glass border border-glass-border">
        <Bot className="w-4 h-4 text-foreground" />
      </div>

      {/* Typing Animation */}
      <div className="bg-chat-bot text-chat-bot-foreground border border-glass-border rounded-xl px-4 py-3 shadow-sm">
        <div className="flex items-center gap-1">
          <span className="text-muted-foreground text-sm">MARM is thinking</span>
          <div className="flex gap-1 ml-2">
            {[0, 1, 2].map((i) => (
              <div
                key={i}
                className={cn(
                  "w-1.5 h-1.5 bg-primary rounded-full animate-typing",
                )}
                style={{
                  animationDelay: `${i * 0.2}s`
                }}
              />
            ))}
          </div>
        </div>
      </div>
    </div>
  );
};