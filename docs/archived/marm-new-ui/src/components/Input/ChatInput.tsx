import React, { useState, useRef } from 'react';
import { Button } from '@/components/ui/button';
import { Textarea } from '@/components/ui/textarea';
import { 
  Send, 
  Paperclip, 
  Zap
} from 'lucide-react';
import { cn } from '@/lib/utils';
import { CommandMenu } from './CommandMenu';
import { FileUpload } from './FileUpload';

interface ChatInputProps {
  onSendMessage: (message: string, files?: File[]) => void;
  onCommandSelect: (command: string) => void;
  isLoading?: boolean;
  disabled?: boolean;
  placeholder?: string;
}

export const ChatInput: React.FC<ChatInputProps> = ({
  onSendMessage,
  onCommandSelect,
  isLoading = false,
  disabled = false,
  placeholder = "Type your message here... (use / for commands)"
}) => {
  const [input, setInput] = useState('');
  const [files, setFiles] = useState<File[]>([]);
  const [showCommandMenu, setShowCommandMenu] = useState(false);
  const [showFileUpload, setShowFileUpload] = useState(false);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!input.trim() && files.length === 0) return;
    
    onSendMessage(input.trim(), files.length > 0 ? files : undefined);
    setInput('');
    setFiles([]);
    
    // Reset textarea height
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto';
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSubmit(e);
    }
    
    // Show command menu when typing /
    if (e.key === '/' && input.length === 0) {
      setShowCommandMenu(true);
    }
  };

  const handleInputChange = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    setInput(e.target.value);
    
    // Auto-resize textarea
    const textarea = e.target;
    textarea.style.height = 'auto';
    textarea.style.height = Math.min(textarea.scrollHeight, 120) + 'px';
    
    // Hide command menu if not starting with /
    if (!e.target.value.startsWith('/')) {
      setShowCommandMenu(false);
    }
  };

  const handleCommandSelect = (command: string) => {
    setInput(command + ' ');
    setShowCommandMenu(false);
    onCommandSelect(command);
    textareaRef.current?.focus();
  };

  const handleFileSelect = (selectedFiles: File[]) => {
    setFiles(prev => [...prev, ...selectedFiles]);
    setShowFileUpload(false);
  };

  const removeFile = (index: number) => {
    setFiles(prev => prev.filter((_, i) => i !== index));
  };


  const canSend = (input.trim().length > 0 || files.length > 0) && !isLoading;

  return (
    <div className="sticky bottom-0 z-40 bg-background/80 backdrop-blur-md border-t border-glass-border">
      {/* File Upload Preview */}
      {files.length > 0 && (
        <div className="px-4 py-2 border-b border-glass-border">
          <div className="max-w-4xl mx-auto">
            <div className="flex flex-wrap gap-2">
              {files.map((file, index) => (
                <div
                  key={index}
                  className="flex items-center gap-2 bg-muted rounded-lg px-3 py-1 text-sm"
                >
                  <Paperclip className="w-3 h-3" />
                  <span className="truncate max-w-32">{file.name}</span>
                  <Button
                    onClick={() => removeFile(index)}
                    size="sm"
                    variant="ghost"
                    className="w-4 h-4 p-0 hover:bg-destructive hover:text-destructive-foreground"
                  >
                    ×
                  </Button>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      {/* Main Input Area */}
      <div className="px-4 py-4">
        <div className="max-w-4xl mx-auto relative">
          <form onSubmit={handleSubmit} className="relative">
            
            {/* Input Container */}
            <div className={cn(
              "relative flex items-end gap-2 p-3 rounded-xl",
              "bg-glass/50 backdrop-blur-sm border border-glass-border",
              "shadow-sm focus-within:shadow-md transition-all duration-normal",
              disabled && "opacity-50 cursor-not-allowed"
            )}>
              
              {/* Command Menu Button */}
              <div className="relative">
                <Button
                  type="button"
                  onClick={() => setShowCommandMenu(!showCommandMenu)}
                  size="sm"
                  variant="ghost"
                  className={cn(
                    "w-8 h-8 p-0 shrink-0",
                    showCommandMenu && "bg-primary text-primary-foreground"
                  )}
                  disabled={disabled}
                >
                  <Zap className="w-4 h-4" />
                </Button>
                
                {showCommandMenu && (
                  <CommandMenu
                    onSelect={handleCommandSelect}
                    onClose={() => setShowCommandMenu(false)}
                    filter={input.startsWith('/') ? input.slice(1) : ''}
                  />
                )}
              </div>

              {/* Text Input */}
              <Textarea
                ref={textareaRef}
                value={input}
                onChange={handleInputChange}
                onKeyDown={handleKeyDown}
                placeholder={placeholder}
                disabled={disabled}
                className={cn(
                  "min-h-[20px] max-h-[120px] resize-none border-0 bg-transparent",
                  "focus-visible:ring-0 focus-visible:ring-offset-0 p-0",
                  "placeholder:text-muted-foreground"
                )}
                rows={1}
              />

              {/* Action Buttons */}
              <div className="flex items-center gap-1 shrink-0">
                
                {/* File Upload */}
                <div className="relative">
                  <Button
                    type="button"
                    onClick={() => setShowFileUpload(!showFileUpload)}
                    size="sm"
                    variant="ghost"
                    className="w-8 h-8 p-0"
                    disabled={disabled}
                  >
                    <Paperclip className="w-4 h-4" />
                  </Button>
                  
                  {showFileUpload && (
                    <FileUpload
                      onFileSelect={handleFileSelect}
                      onClose={() => setShowFileUpload(false)}
                    />
                  )}
                </div>


                {/* Send Button */}
                <Button
                  type="submit"
                  size="sm"
                  disabled={!canSend || disabled}
                  className={cn(
                    "w-8 h-8 p-0 transition-all duration-normal",
                    canSend 
                      ? "bg-gradient-primary shadow-glow hover:shadow-lg" 
                      : "bg-muted"
                  )}
                >
                  <Send className="w-4 h-4" />
                </Button>
              </div>
            </div>

            {/* Character/Token Counter */}
            <div className="flex justify-between items-center mt-2 px-2">
              <div className="text-xs text-muted-foreground">
                {input.length > 0 && `${input.length} characters`}
              </div>
              <div className="text-xs text-muted-foreground">
                {isLoading && "AI is thinking..."}
              </div>
            </div>
          </form>
        </div>
      </div>
    </div>
  );
};