// notebook.js - User knowledge library management and storage functions

import { ensureSession, trimSessionSize, updateNotebookSize } from './session.js';
import { persistSessions } from './storage.js';
import { stripHTML, validateNotebookEntry } from './utils.js';

// ===== NOTEBOOK SAFETY LIMITS =====
const NOTEBOOK_LIMITS = {
  MAX_ENTRIES: 30,          
  MAX_TOTAL_SIZE: 30000,   
  RATE_LIMIT_MS: 300,    
  MAX_ENTRY_SIZE: 2048       
};

let lastNotebookSave = 0;

function rateLimitedAddEntry(id, key, value) {
  const now = Date.now();
  if (now - lastNotebookSave < NOTEBOOK_LIMITS.RATE_LIMIT_MS) {
    return '⚠️ Please wait before saving another notebook entry.';
  }
  lastNotebookSave = now;
  return addNotebookEntry(id, key, value);
}

function addNotebookEntry(id, key, value) {
  const s = ensureSession(id);
  key = stripHTML(key);
  value = stripHTML(value);
  
  if (!validateNotebookEntry(key, value)) {
    return 'Invalid notebook entry. Key must be 1-64 chars (letters, numbers, dash, space). Value must be 1-2048 chars.';
  }
  
  const currentEntries = Object.keys(s.notebook).length;
  const isNewEntry = !s.notebook.hasOwnProperty(key);
  if (isNewEntry && currentEntries >= NOTEBOOK_LIMITS.MAX_ENTRIES) {
    return `⚠️ Notebook is full (${NOTEBOOK_LIMITS.MAX_ENTRIES} entries max). Delete some entries first.`;
  }
  

  // --- Notebook Entry Size & Storage Limit Check ---
  const newEntrySize = JSON.stringify({ [key]: value }).length;
  const oldEntrySize = s.notebook[key] ? JSON.stringify({ [key]: s.notebook[key] }).length : 0;
  const sizeDelta = newEntrySize - oldEntrySize;
  
  if (s.notebookSize + sizeDelta > NOTEBOOK_LIMITS.MAX_TOTAL_SIZE) {
    return `⚠️ Notebook storage limit reached (${NOTEBOOK_LIMITS.MAX_TOTAL_SIZE} chars max). Delete some entries first.`;
  }
  
  s.notebook[key] = value;
  updateNotebookSize(id, sizeDelta);
  trimSessionSize(s);
  persistSessions();
  return `Stored "${key}" → "${value}"`;
}

// --- Notebook Entry Retrieval & Listing ---
function getNotebookEntry(id, key) {
  const s = ensureSession(id);
  if (!key) return 'Usage: /notebook add:[name] [data] | /notebook use:[name] | /notebook show:';
  return s.notebook[key] ? `"${key}": ${s.notebook[key]}` : `No entry for "${key}"`;
}

function listNotebookEntries(id) {
  const s = ensureSession(id);
  const keys = Object.keys(s.notebook);
  if (!keys.length) return 'Notebook is empty.';
  
  const usage = `📊 Usage: ${keys.length}/${NOTEBOOK_LIMITS.MAX_ENTRIES} entries, ${s.notebookSize}/${NOTEBOOK_LIMITS.MAX_TOTAL_SIZE} chars`;
  
  const entries = keys.map(k => `• ${k}: ${s.notebook[k]}`).join('\n');
  return `${usage}\n\nNotebook entries:\n${entries}`;
}

// --- Notebook Entry Deletion ---
function deleteNotebookEntry(id, key) {
  const s = ensureSession(id);
  if (!key) return 'Usage: /notebook delete:[name]';
  
  if (!s.notebook[key]) {
    return `No entry found for "${key}"`;
  }
  
  const deletedEntrySize = JSON.stringify({ [key]: s.notebook[key] }).length;
  delete s.notebook[key];
  updateNotebookSize(id, -deletedEntrySize);
  persistSessions();
  return `Deleted "${key}" from notebook`;
}

// --- Clear All Notebook Entries ---
function clearNotebook(id) {
  const s = ensureSession(id);
  const entryCount = Object.keys(s.notebook).length;
  
  if (entryCount === 0) {
    return 'Notebook is already empty.';
  }
  
  s.notebook = {};
  s.notebookSize = 0;
  persistSessions();
  return `Cleared all ${entryCount} entries from notebook.`;
}

export function manageUserNotebook(id, action, key = '', value = '') {
  switch (action) {
    case 'add':
      return rateLimitedAddEntry(id, key, value);
    case 'all':
      return listNotebookEntries(id);
    case 'clear':
      return clearNotebook(id);
    default:
      return 'Usage: /notebook add:[name] [data] | /notebook use:[name] | /notebook show: | /notebook clear: | /notebook status:';
  }
} 
