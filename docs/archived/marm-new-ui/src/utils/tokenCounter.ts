// Simple token estimation for LLaMA models
// More accurate than character count, less complex than tiktoken

export const estimateTokens = (text: string): number => {
  if (!text) return 0;
  
  // LLaMA tokenizer approximation:
  // - Average ~4 characters per token for English
  // - Adjust for whitespace, punctuation, and special characters
  
  // Remove extra whitespace and normalize
  const normalizedText = text.trim().replace(/\s+/g, ' ');
  
  // Count different types of content
  const words = normalizedText.split(' ').filter(word => word.length > 0);
  const punctuation = (normalizedText.match(/[.,!?;:(){}[\]"'-]/g) || []).length;
  const numbers = (normalizedText.match(/\d+/g) || []).length;
  
  // Estimation formula based on LLaMA tokenization patterns
  let tokenCount = 0;
  
  // Words (average 1.3 tokens per word for English)
  tokenCount += words.length * 1.3;
  
  // Punctuation (usually 1 token each)
  tokenCount += punctuation * 1;
  
  // Numbers (can be multiple tokens for large numbers)
  tokenCount += numbers * 1.5;
  
  // Add buffer for special tokens and encoding overhead
  tokenCount = Math.ceil(tokenCount * 1.1);
  
  return Math.max(1, tokenCount);
};

export const estimateTokensFromMessages = (messages: Array<{content: string}>): number => {
  return messages.reduce((total, message) => {
    return total + estimateTokens(message.content);
  }, 0);
};