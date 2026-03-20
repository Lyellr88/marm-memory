import React, { useState } from 'react';
import { Button } from '@/components/ui/button';
import { 
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
  DropdownMenuSeparator
} from '@/components/ui/dropdown-menu';
import { 
  Menu, 
  HelpCircle, 
  Plus, 
  MessageSquare, 
  Moon,
  Sun,
  Zap
} from 'lucide-react';
import { cn } from '@/lib/utils';

interface AppHeaderProps {
  sessionTitle: string;
  isMarmActive: boolean;
  onNewChat: () => void;
  onSaveSession: () => void;
  onLoadSession: () => void;
  onToggleMarm: () => void;
  onShowHelp: () => void;
  onToggleTheme?: () => void;
  isDarkMode?: boolean;
}

export const AppHeader: React.FC<AppHeaderProps> = ({
  sessionTitle,
  isMarmActive,
  onNewChat,
  onSaveSession,
  onLoadSession,
  onToggleMarm,
  onShowHelp,
  onToggleTheme,
  isDarkMode = false
}) => {
  return (
    <header className="fixed top-0 z-50 w-full border-b border-glass-border bg-glass/80 backdrop-blur-md">
      <div className="flex h-16 items-center justify-between px-4">
        
        {/* Left Side - Logo & Session */}
        <div className="flex items-center gap-4">
          <div className="flex items-center gap-3">
            <div className="w-8 h-8 bg-gradient-primary rounded-lg flex items-center justify-center shadow-glow">
              <span className="text-sm font-bold text-primary-foreground">M</span>
            </div>
            <div>
              <h1 className="font-semibold text-foreground">MARM</h1>
              <p className="text-xs text-muted-foreground truncate max-w-48">
                {sessionTitle || "New Conversation"}
              </p>
            </div>
          </div>
          
          {/* MARM Status Indicator */}
          <div className={cn(
            "flex items-center gap-2 px-3 py-1 rounded-full text-xs",
            "border transition-all duration-normal",
            isMarmActive 
              ? "bg-success/10 text-success border-success/20" 
              : "bg-muted text-muted-foreground border-border"
          )}>
            <div className={cn(
              "w-2 h-2 rounded-full",
              isMarmActive ? "bg-success animate-pulse-glow" : "bg-muted-foreground"
            )} />
            {isMarmActive ? "MARM Active" : "Standard Mode"}
          </div>
        </div>

        {/* Right Side - Actions */}
        <div className="flex items-center gap-2">
          
          {/* Quick Actions */}
          <Button
            onClick={onToggleMarm}
            size="sm"
            variant={isMarmActive ? "default" : "outline"}
            className="gap-2"
          >
            <Zap className="w-4 h-4" />
            {isMarmActive ? "Disable MARM" : "Enable MARM"}
          </Button>


          {/* Main Menu */}
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button size="sm" variant="outline">
                <Menu className="w-4 h-4" />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="w-56">
              <DropdownMenuItem onClick={onNewChat} className="gap-2">
                <Plus className="w-4 h-4" />
                New Chat
              </DropdownMenuItem>
              <DropdownMenuItem onClick={onLoadSession} className="gap-2">
                <MessageSquare className="w-4 h-4" />
                Browse Chats
              </DropdownMenuItem>
              <DropdownMenuSeparator />
              {onToggleTheme && (
                <>
                  <DropdownMenuItem onClick={onToggleTheme} className="gap-2">
                    {isDarkMode ? <Sun className="w-4 h-4" /> : <Moon className="w-4 h-4" />}
                    {isDarkMode ? "Light Mode" : "Dark Mode"}
                  </DropdownMenuItem>
                  <DropdownMenuSeparator />
                </>
              )}
              <DropdownMenuItem onClick={onShowHelp} className="gap-2">
                <HelpCircle className="w-4 h-4" />
                Help & Guide
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      </div>
    </header>
  );
};