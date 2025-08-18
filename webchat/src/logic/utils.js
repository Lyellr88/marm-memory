// utils.js - General utility functions for MARM logic

// ===== Utility Functions for MARM Logic =====
export function stripHTML(input) {
  if (!input || typeof input !== 'string' || input.length > 10000) {
    return ''; 
  }
  
  return input.replace(/<[^<>]*>/g, '');
}

export function validateNotebookEntry(key, value) {
  if (!key || typeof key !== 'string' || key.length === 0 || key.length > 64) return false;
  if (!value || typeof value !== 'string' || value.length === 0 || value.length > 2048) return false;
  
  for (let i = 0; i < key.length; i++) {
    const char = key[i];
    if (!/[\w\- ]/.test(char)) {
      return false;
    }
  }
  
  return true;
}

// --- Log Entry Validation ---
export function validateLogEntry(entry) {
  if (!entry || typeof entry !== 'string' || entry.length > 500) {
    return false; 
  }
  
  return /^\s*\d{4}-\d{2}-\d{2}\s*[-|]\s*[^-|]{1,100}\s*[-|]\s*[^-|]{1,100}\s*$/.test(entry);
}

export function checkProtocolCompliance(type, data) {
  if (type === 'log') return validateLogEntry(data);
  if (type === 'notebook') return validateNotebookEntry(data.key, data.value);
  return true;
}

export function estimateTokens(str) {
  return Math.ceil((str || '').length / 3.5);
} 
