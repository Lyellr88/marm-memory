// session.js - Session storage, persistence, and lifecycle management for MARM

// ===== Session Storage & Lifecycle Management =====
import { PROTOCOL_VERSION, MARM_PROTOCOL_TEXT, } from './constants.js';
import { validateLogEntry, estimateTokens } from './utils.js';
import { loadDocs } from './docs.js';
import { 
  persistSessions, 
  persistCurrentSession, 
  restoreSessions, 
  setSessionsReference,
  LS_KEY,
  CURRENT_SESSION_KEY 
} from './storage.js';

let sessions = {};
const MAX_SESSIONS = 50;
const SESSION_EXPIRY_DAYS = 30;
const MAX_SESSION_SIZE = 35000;
const PRUNING_THRESHOLD = 5000; 

setSessionsReference(sessions); 

export function ensureSession(id) {
  if (!sessions[id]) {
    const currentSessionCount = Object.keys(sessions).length;
    if (currentSessionCount >= MAX_SESSIONS) {
            const persistenceEnabled = localStorage.getItem('marm-persistence-enabled') === 'true';
      if (persistenceEnabled) {
        pruneOldSessions();
      }
      const remainingSessions = Object.keys(sessions);
      if (remainingSessions.length >= MAX_SESSIONS) {
        const oldestSession = remainingSessions.sort((a, b) => 
          (sessions[a].created || 0) - (sessions[b].created || 0))[0];
        delete sessions[oldestSession];
      }
    }
    
    sessions[id] = {
      history: [],
      logs: [],
      notebook: {},
      notebookSize: 0,  
      lastReasoning: '',
      created: Date.now()
    };
  } else if (sessions[id].notebookSize === undefined) {
    sessions[id].notebookSize = JSON.stringify(sessions[id].notebook).length;
  }
  return sessions[id];
}

// --- Session Object Management & Pruning ---
export function updateNotebookSize(sessionId, sizeDelta) {
  const s = sessions[sessionId];
  if (s) {
    s.notebookSize = (s.notebookSize || 0) + sizeDelta;
  }
}

export function pruneOldSessions() {
  const now = Date.now();
  const ids = Object.keys(sessions);
  ids.forEach(id => {
    const s = sessions[id];
    if (s.created && (now - s.created) > SESSION_EXPIRY_DAYS * 86400000) {
      delete sessions[id];
    }
  });
  let remaining = Object.keys(sessions);
  if (remaining.length > MAX_SESSIONS) {
    remaining.sort((a, b) => (sessions[a].created || 0) - (sessions[b].created || 0));
    remaining.slice(0, remaining.length - MAX_SESSIONS).forEach(id => delete sessions[id]);
  }
}

export function trimSessionSize(s) {
  let total = (JSON.stringify(s.history).length + JSON.stringify(s.logs).length);
  while (total > PRUNING_THRESHOLD && s.history.length > 0) {
    s.history.shift();
    total = (JSON.stringify(s.history).length + JSON.stringify(s.logs).length);
  }
  while (total > MAX_SESSION_SIZE && s.logs.length > 0) {
    s.logs.shift();
    total = (JSON.stringify(s.history).length + JSON.stringify(s.logs).length);
  }
}

restoreSessions();

export {
  sessions,
  LS_KEY,
  CURRENT_SESSION_KEY,
  MAX_SESSIONS,
  SESSION_EXPIRY_DAYS,
  MAX_SESSION_SIZE,
  PRUNING_THRESHOLD
};

// ===== CORE API FUNCTIONS =====
export function getSessionContext(id) {
  console.log('[MARM DEBUG] getSessionContext called for session ID:', id);
  
  // Debug functions removed - they were causing undefined errors
  // debugProtocolText();
  // debugMarmKeywords();
  
  const s = sessions[id];
  if (!s) {
    const basicContext = `MARM v${PROTOCOL_VERSION}\n\n` + MARM_PROTOCOL_TEXT;
    console.log('[MARM DEBUG] No session found, returning basic context length:', basicContext.length);
    console.log('[MARM DEBUG] Basic context preview:', basicContext.substring(0, 200) + '...');
    return basicContext;
  }
  
  let context = `You are operating under MARM v${PROTOCOL_VERSION} protocol:\n\n${MARM_PROTOCOL_TEXT}\n\n`;
  context += `Current Session ID: ${id}\n\n`;
  
  console.log('[MARM DEBUG] Session found, building context...');
  const notebookKeys = Object.keys(s.notebook || {});
  if (notebookKeys.length > 0) {
    context += `Current Notebook Contents:\n`;
    notebookKeys.forEach(key => {
      context += `- ${key}: ${s.notebook[key]}\n`;
    });
    context += '\n';
  }
  if (s.logs && s.logs.length > 0) {
    context += `Recent Log Entries:\n`;
    s.logs.slice(-5).forEach(log => {
      context += `- ${log}\n`;
    });
    context += '\n';
  }
  const tail = s.history.slice(-20).map(m => `${m.role}: ${m.content}`).join('\n');
  if (tail) {
    context += `Conversation History:\n${tail}`;
  }
  
  console.log('[MARM DEBUG] Final context length:', context.length, 'characters');
  console.log('[MARM DEBUG] Final context preview:', context.substring(0, 300) + '...');
  
  return context;
}

// ===== Session Context & Activation =====
export async function activateMarmSession(id = 'default_session') {
  const persistenceEnabled = localStorage.getItem('marm-persistence-enabled') === 'true';
  if (persistenceEnabled) {
    pruneOldSessions();
  }  
  await loadDocs();
  ensureSession(id);
  persistCurrentSession();
  persistSessions(); 
  return `MARM session activated (v${PROTOCOL_VERSION}). Docs loaded.`;
}

export function updateSessionHistory(id, userText, botText, reasoning = '') {
  const s = ensureSession(id);
  s.history.push({ role: 'user', content: userText, ts: Date.now() });
  s.history.push({ role: 'bot', content: botText, ts: Date.now() });
  if (reasoning) s.lastReasoning = reasoning;
  trimSessionSize(s);
  persistCurrentSession(); 
  persistSessions(); 
}

export function setSessionReasoning(id, reasoning) {
  const s = ensureSession(id);
  s.lastReasoning = reasoning;
  persistCurrentSession(); 
  persistSessions(); 
}

export function logSession(id, logLine) {
  if (!validateLogEntry(logLine)) {
    return 'Invalid log entry format. Use: [YYYY-MM-DD-topic-summary]';
  }
  const s = ensureSession(id);
  
  try {
    s.logs.push(logLine);
    trimSessionSize(s);
    persistCurrentSession(); 
    persistSessions(); 
    return `Logged: ${logLine}`;
  } catch (e) {
    console.error('MARM: Failed to log session entry:', e);
    return 'Failed to log entry due to internal error';
  }
}

export function trimForContext(id, maxTokens = 8000) {
  const s = sessions[id];
  if (!s) return false;
  
  const estTokens = arr => arr.reduce((t, m) => t + estimateTokens(m.content), 0);
  let trimmed = false;
  
  while (estTokens(s.history) > maxTokens) {
    s.history.shift();
    trimmed = true;
  }
  
  return trimmed;
}

export function resetSession(id) {
  delete sessions[id];
  persistCurrentSession();
  persistSessions();
  return 'Session reset. Starting fresh.';
}

export function getAllSessions() {
  return Object.keys(sessions);
}

export function getMostRecentBotResponseLogic(id) {
  const s = sessions[id];
  return s?.lastReasoning || '';
} 
