// storage.js - Centralized localStorage operations and multi-tab synchronization //
// ===== Storage & Synchronization Utilities =====

export const LS_KEY = 'marm-sessions-v1';
export const CURRENT_SESSION_KEY = 'marm-current-session';
export const REPLICATE_API_KEY = 'marm-replicate-api-key';

let hasDataChanged = false;
let sessionsRef = null;

export function setSessionsReference(sessions) {
  sessionsRef = sessions;
}

if (typeof window !== 'undefined') {
  window.addEventListener('storage', (event) => {
    if (event.key === LS_KEY || event.key === CURRENT_SESSION_KEY) {
      hasDataChanged = true;
    }
  });

  window.addEventListener('focus', () => {
    if (hasDataChanged && sessionsRef) {
      restoreSessions();
      hasDataChanged = false;
      }
  });
}

// ===== Session Persistence & Restoration =====
export function persistSessions() {
  if (!sessionsRef) {
    console.error('MARM: Sessions reference not set');
    return false;
  }

  const isPersistenceEnabled = localStorage.getItem('marm-persistence-enabled') === 'true';
  if (!isPersistenceEnabled) {
    return false;
  }

  try { 
    localStorage.setItem(LS_KEY, JSON.stringify(sessionsRef)); 
    return true; 
  } catch (e) {
    if (e.name === 'QuotaExceededError') {
      console.error('MARM: localStorage quota exceeded. Cannot save sessions.', e);
      try {
        localStorage.setItem(LS_KEY, JSON.stringify(sessionsRef));
        return true; 
      } catch (retryError) {
        console.error('MARM: Failed to save sessions even after cleanup.', retryError);
        return false; 
      }
    } else {
      console.error('MARM: Failed to persist sessions:', e);
      return false; 
    }
  }
}

// --- Current Session Persistence ---
export function persistCurrentSession() {
  if (!sessionsRef) {
    console.error('MARM: Sessions reference not set');
    return false;
  }

  try { 
    localStorage.setItem(CURRENT_SESSION_KEY, JSON.stringify(sessionsRef)); 
    return true; 
  } catch (e) {
    if (e.name === 'QuotaExceededError') {
      console.error('MARM: localStorage quota exceeded. Cannot save current session.', e);
    } else {
      console.error('MARM: Failed to persist current session:', e);
    }
    return false; 
  }
}

export function restoreSessions() {
  if (!sessionsRef) {
    console.error('MARM: Sessions reference not set');
    return;
  }

  try {
    const currentRaw = localStorage.getItem(CURRENT_SESSION_KEY);
    if (currentRaw) {
      const restored = JSON.parse(currentRaw);
      Object.keys(sessionsRef).forEach(key => delete sessionsRef[key]);
      Object.assign(sessionsRef, restored);
    }
  } catch (e) {
    console.error('MARM: Failed to restore current session:', e);
    Object.keys(sessionsRef).forEach(key => delete sessionsRef[key]);
  }
  
  const isPersistenceEnabled = localStorage.getItem('marm-persistence-enabled') === 'true';
  if (isPersistenceEnabled) {
    try {
      const savedRaw = localStorage.getItem(LS_KEY);
      if (savedRaw) {
        const savedSessions = JSON.parse(savedRaw);
        Object.assign(sessionsRef, { ...savedSessions, ...sessionsRef });
      }
    } catch (e) {
      console.error('MARM: Failed to restore saved sessions:', e);
    }
  }
}

// ===== API KEY MANAGEMENT =====
export function saveReplicateApiKey(apiKey) {
  try {
    if (apiKey && apiKey.trim()) {
      localStorage.setItem(REPLICATE_API_KEY, apiKey.trim());
      return true;
    } else {
      localStorage.removeItem(REPLICATE_API_KEY);
      return true;
    }
  } catch (error) {
    console.error('Error saving Replicate API key:', error);
    return false;
  }
}

export function getReplicateApiKey() {
  try {
    return localStorage.getItem(REPLICATE_API_KEY);
  } catch (error) {
    console.error('Error retrieving Replicate API key:', error);
    return null;
  }
}

export function hasReplicateApiKey() {
  const apiKey = getReplicateApiKey();
  return apiKey && apiKey.length > 0;
}
