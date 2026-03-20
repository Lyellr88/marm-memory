import React from 'react';
import { cn } from '@/lib/utils';

interface TokenCounterProps {
  inputTokens: number;
  outputTokens: number;
  maxTokens?: number;
}

export const TokenCounter: React.FC<TokenCounterProps> = ({ 
  inputTokens, 
  outputTokens, 
  maxTokens = 10000000 // LLaMA 4 Scout context limit (10M tokens)
}) => {
  const totalTokens = inputTokens + outputTokens;
  const usagePercentage = (totalTokens / maxTokens) * 100;
  
  // Color coding based on usage
  const getColorClass = () => {
    if (usagePercentage < 50) return 'text-success';
    if (usagePercentage < 75) return 'text-yellow-600';
    if (usagePercentage < 90) return 'text-orange-600';
    return 'text-destructive';
  };

  const getBgClass = () => {
    if (usagePercentage < 50) return 'bg-success/10';
    if (usagePercentage < 75) return 'bg-yellow-100';
    if (usagePercentage < 90) return 'bg-orange-100';
    return 'bg-destructive/10';
  };

  return (
    <div 
      className={cn(
        "flex items-center gap-2 px-3 py-1.5 rounded-lg text-xs font-mono transition-colors cursor-default",
        getBgClass()
      )}
      title="Token Counter"
    >
      {/* Token Count Display */}
      <div className={cn("flex items-center gap-1", getColorClass())}>
        <span className="font-semibold">
          {totalTokens.toLocaleString()}
        </span>
        <span className="opacity-50">/ 10M</span>
      </div>
      
      {/* Usage Bar */}
      <div className="w-16 h-1.5 bg-muted rounded-full overflow-hidden">
        <div 
          className={cn(
            "h-full transition-all duration-300",
            usagePercentage < 50 ? 'bg-success' :
            usagePercentage < 75 ? 'bg-yellow-500' :
            usagePercentage < 90 ? 'bg-orange-500' :
            'bg-destructive'
          )}
          style={{ width: `${Math.min(usagePercentage, 100)}%` }}
        />
      </div>
      
      {/* Percentage */}
      <span className={cn("text-xs opacity-70", getColorClass())}>
        {usagePercentage.toFixed(1)}%
      </span>
    </div>
  );
};