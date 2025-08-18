// state.js - Centralized state management for MARM chatbot

// ===== Centralized State Management for MARM Chatbot =====
const STATE_KEY = 'marm-current-state';

// --- Application State (Private) ---
const state = { 
  isMarmActive: false, 
  currentSessionId: null 
};

// --- State Getter ---
export function getState() {
  return { ...state };
}

// --- State Persistence ---
function persistState() {
  try {
    localStorage.setItem(STATE_KEY, JSON.stringify(state));
  } catch (e) {
    console.warn('Failed to persist state:', e);
  }
}

// --- State Restoration ---
export function restoreState() {
  try {
    const saved = localStorage.getItem(STATE_KEY);
    if (saved) {
      const parsedState = JSON.parse(saved);
      try {
        validateState(parsedState);
        Object.assign(state, parsedState);
      } catch (validationError) {
        console.warn('Saved state failed validation, resetting to defaults:', validationError);
        resetToDefaults();
      }
    }
  } catch (e) {
    console.warn('Failed to restore state, using defaults:', e);
    resetToDefaults();
  }
}

// --- State Reset ---
function resetToDefaults() {
  state.isMarmActive = false;
  state.currentSessionId = null;
  persistState(); 
}

restoreState();

// --- State Validation ---
export function validateState(newState) {
  if (typeof newState.isMarmActive !== 'boolean') {
    throw new Error('isMarmActive must be boolean');
  }
  if (newState.currentSessionId && typeof newState.currentSessionId !== 'string') {
    throw new Error('currentSessionId must be string or null');
  }
  return true;
}

// ===== State Management Functions =====
export function updateState(updates) {
  const newState = { ...state, ...updates };
  validateState(newState);
  
  Object.assign(state, newState);
  
  persistState();
  return { ...state };
}

export function resetState() {
  return updateState({
    isMarmActive: false,
    currentSessionId: null
  });
} 
