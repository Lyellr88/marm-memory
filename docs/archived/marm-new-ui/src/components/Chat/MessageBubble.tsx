import React, { useState, useEffect, useRef } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { Button } from '@/components/ui/button';
import { Copy, Volume2, User, Bot, Check } from 'lucide-react';
import { cn } from '@/lib/utils';
import { Message } from './ChatContainer';

interface MessageBubbleProps {
  message: Message;
  isFirst?: boolean;
  onAction?: (action: 'copy' | 'speak', message: Message) => void;
}

export const MessageBubble: React.FC<MessageBubbleProps> = ({
  message,
  isFirst = false,
  onAction
}) => {
  const isUser = message.type === 'user';
  const [isCopied, setIsCopied] = useState(false);
  const [isSpeaking, setIsSpeaking] = useState(false);
  const messageContentRef = useRef<HTMLDivElement>(null);
  
  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(message.content);
      setIsCopied(true);
      onAction?.('copy', message);
      
      // Reset the state after animation
      setTimeout(() => {
        setIsCopied(false);
      }, 2000);
    } catch (err) {
      console.error('Failed to copy text: ', err);
    }
  };


  // Post-process code blocks to add copy buttons (like old webchat system)
  useEffect(() => {
    if (!messageContentRef.current || isUser) return;
    
    const codeBlocks = messageContentRef.current.querySelectorAll('pre');
    codeBlocks.forEach((preElement) => {
      // Skip if already has copy button
      if (preElement.querySelector('.code-copy-btn')) return;
      
      // Create copy button
      const copyBtn = document.createElement('button');
      copyBtn.className = 'code-copy-btn absolute top-2 right-2 w-8 h-8 p-0 opacity-0 group-hover:opacity-100 bg-glass/90 backdrop-blur-sm hover:bg-glass transition-all duration-200 rounded flex items-center justify-center';
      copyBtn.innerHTML = '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect width="14" height="14" x="8" y="8" rx="2" ry="2"/><path d="m4 16c-1.1 0-2-.9-2-2V4c0-1.1.9-2 2-2h10c1.1 0 2 .9 2 2"/></svg>';
      
      // Add click handler
      copyBtn.addEventListener('click', (e) => {
        e.preventDefault();
        const codeElement = preElement.querySelector('code');
        const codeText = codeElement?.textContent || '';
        
        navigator.clipboard.writeText(codeText).then(() => {
          copyBtn.innerHTML = '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" class="text-green-500"><polyline points="20,6 9,17 4,12"/></svg>';
          copyBtn.classList.add('bg-green-500/20', 'hover:bg-green-500/30');
          
          setTimeout(() => {
            copyBtn.innerHTML = '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect width="14" height="14" x="8" y="8" rx="2" ry="2"/><path d="m4 16c-1.1 0-2-.9-2V4c0-1.1.9-2 2-2h10c1.1 0 2 .9 2 2"/></svg>';
            copyBtn.classList.remove('bg-green-500/20', 'hover:bg-green-500/30');
          }, 2000);
        }).catch(err => {
          console.error('Failed to copy code:', err);
        });
      });
      
      // Make pre element relative and add group class for hover
      preElement.style.position = 'relative';
      preElement.classList.add('group');
      
      // Append button to pre element
      preElement.appendChild(copyBtn);
    });
  }, [message.content, isUser]);

  const handleSpeak = () => {
    // If currently speaking, cancel it
    if (isSpeaking) {
      speechSynthesis.cancel();
      setIsSpeaking(false);
      return;
    }
    
    // Start speaking
    const utterance = new SpeechSynthesisUtterance(message.content);
    
    // Load voice settings from localStorage
    const voiceSpeed = localStorage.getItem('marm-voice-speed');
    const selectedVoiceName = localStorage.getItem('marm-selected-voice');
    
    // Apply voice speed
    if (voiceSpeed) {
      utterance.rate = parseFloat(voiceSpeed);
    } else {
      utterance.rate = 1.1; // Default speed
    }
    
    // Apply selected voice - ensure voices are loaded
    if (selectedVoiceName) {
      const applyVoice = () => {
        const voices = speechSynthesis.getVoices();
        const selectedVoice = voices.find(voice => voice.name === selectedVoiceName);
        if (selectedVoice) {
          utterance.voice = selectedVoice;
          console.log('Applied voice:', selectedVoice.name, selectedVoice.lang);
        } else {
          console.log('Voice not found:', selectedVoiceName, 'Available:', voices.map(v => v.name));
        }
      };
      
      // Try to apply voice immediately
      applyVoice();
      
      // If voices aren't loaded yet, wait for them
      if (speechSynthesis.getVoices().length === 0) {
        speechSynthesis.onvoiceschanged = () => {
          applyVoice();
          speechSynthesis.onvoiceschanged = null;
        };
      }
    }
    
    setIsSpeaking(true);
    onAction?.('speak', message);
    
    // Handle speech events
    utterance.onend = () => {
      setIsSpeaking(false);
    };
    
    utterance.onerror = () => {
      setIsSpeaking(false);
    };
    
    speechSynthesis.speak(utterance);
  };

  return (
    <div 
      className={cn(
        "group flex gap-3 animate-fade-in",
        isUser ? "flex-row-reverse" : "flex-row",
        isFirst && "mt-6"
      )}
    >
      {/* Avatar */}
      <div className={cn(
        "flex-shrink-0 w-8 h-8 rounded-full flex items-center justify-center",
        isUser 
          ? "bg-gradient-primary shadow-glow" 
          : "bg-glass border border-glass-border"
      )}>
        {isUser ? (
          <User className="w-4 h-4 text-primary-foreground" />
        ) : (
          <Bot className="w-4 h-4 text-foreground" />
        )}
      </div>

      {/* Message Container */}
      <div className={cn(
        "flex-1 max-w-[85%] space-y-1",
        isUser ? "items-end" : "items-start"
      )}>
        {/* Message Content */}
        <div className={cn(
          "relative",
          isUser 
            ? "bg-chat-user text-chat-user-foreground px-4 py-2.5 rounded-2xl shadow-sm max-w-fit ml-auto" 
            : "text-chat-bot-foreground"
        )}>
          {/* Message Content */}
          <div className="whitespace-pre-wrap break-words">
            {isUser ? (
              message.content
            ) : (
              <div 
                ref={messageContentRef}
                className="text-sm leading-normal font-medium [&>p]:mb-2 [&>h1]:font-semibold [&>h1]:mb-2 [&>h2]:font-semibold [&>h2]:mb-2 [&>h3]:font-semibold [&>h3]:mb-2 [&>ul]:mb-2 [&>ul]:leading-normal [&>li]:mb-0 [&>ol]:mb-2 [&>ol]:leading-normal [&>pre]:bg-muted [&>pre]:p-3 [&>pre]:pr-12 [&>pre]:rounded-lg [&>pre]:mb-3 [&>pre]:overflow-x-auto [&>pre]:whitespace-pre-wrap [&>pre]:break-words [&_code]:bg-muted [&_code]:px-1 [&_code]:py-0.5 [&_code]:rounded [&_code]:text-sm [&>table]:border-collapse [&>table]:border [&>table]:border-muted [&>table]:mb-3 [&>table]:w-full [&_th]:border [&_th]:border-muted [&_th]:px-3 [&_th]:py-2 [&_th]:bg-muted/30 [&_th]:font-semibold [&_td]:border [&_td]:border-muted [&_td]:px-3 [&_td]:py-2"
              >
<ReactMarkdown remarkPlugins={[remarkGfm]}>
                  {message.content}
                </ReactMarkdown>
              </div>
            )}
          </div>

          {/* File Attachments */}
          {message.files && message.files.length > 0 && (
            <div className="mt-2 pt-2 border-t border-current/10">
              <div className="flex flex-wrap gap-2">
                {message.files.map((file, index) => (
                  <div
                    key={index}
                    className="text-xs bg-current/10 rounded px-2 py-1"
                  >
                    📎 {file.name}
                  </div>
                ))}
              </div>
            </div>
          )}
          
          {/* Message Action Buttons - Hidden by default, shown on hover */}
          <div className={cn(
            "absolute top-0 flex gap-1 opacity-0 group-hover:opacity-100",
            "transition-opacity duration-normal",
            isUser ? "-left-16" : "-right-16"
          )}>
            <Button
              onClick={handleCopy}
              size="sm"
              variant="ghost"
              className={cn(
                "w-8 h-8 p-0 bg-glass/80 backdrop-blur-sm hover:bg-glass transition-all duration-300",
                isCopied && "bg-green-500/20 hover:bg-green-500/30 scale-110"
              )}
              title="Copy entire message"
            >
              {isCopied ? (
                <Check className="w-3 h-3 text-green-500 animate-pulse" />
              ) : (
                <Copy className="w-3 h-3" />
              )}
            </Button>
            <Button
              onClick={handleSpeak}
              size="sm"
              variant="ghost"
              className={cn(
                "w-8 h-8 p-0 bg-glass/80 backdrop-blur-sm hover:bg-glass transition-all duration-300 relative",
                isSpeaking && "bg-blue-500/20 hover:bg-blue-500/30"
              )}
              title="Read message aloud"
            >
              {isSpeaking && (
                <div className="absolute inset-0 rounded-md">
                  <div className="absolute inset-0 bg-blue-500/30 rounded-md animate-pulse"></div>
                  <div className="absolute -inset-1 bg-blue-500/20 rounded-lg animate-ping"></div>
                  <div className="absolute -inset-2 bg-blue-500/10 rounded-xl animate-pulse" style={{ animationDelay: '0.15s' }}></div>
                </div>
              )}
              <Volume2 className={cn(
                "w-3 h-3 relative z-10 transition-colors duration-300",
                isSpeaking && "text-blue-500"
              )} />
            </Button>
          </div>
        </div>

        {/* Timestamp */}
        <div className={cn(
          "text-xs text-muted-foreground px-1",
          isUser ? "text-right" : "text-left"
        )}>
          {(() => {
            // Ensure timestamp is a Date object
            const timestamp = message.timestamp instanceof Date 
              ? message.timestamp 
              : new Date(message.timestamp);
            
            return timestamp.toLocaleTimeString([], { 
              hour: '2-digit', 
              minute: '2-digit' 
            });
          })()}
        </div>
      </div>
    </div>
  );
};