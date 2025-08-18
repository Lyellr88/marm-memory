// sessionUI.js - Session management UI functions //

import { appendMessage } from './ui.js';
import { sessions } from '../logic/session.js';
import { persistSessions } from '../logic/storage.js';
import { getState, updateState } from './state.js';
import { sanitizeHTML, sanitizeText } from '../security/xssProtection.js';

// ===== Memory Leak Prevention =====
const sessionEventListeners = new Map();

function trackableSessionEventListener(element, event, handler, options) {
  element.addEventListener(event, handler, options);
  
  if (!sessionEventListeners.has(element)) {
    sessionEventListeners.set(element, []);
  }
  sessionEventListeners.get(element).push({ event, handler, options });
}

export function cleanupSessionUI() {
  sessionEventListeners.forEach((listeners, element) => {
    listeners.forEach(({ event, handler, options }) => {
      try {
        element.removeEventListener(event, handler, options);
      } catch (e) {
      }
    });
  });
  sessionEventListeners.clear();
  
}

// ===== Session Management UI =====
export function loadChatsList() {
  const menuContent = document.getElementById('chats-menu-content');
  if (!menuContent) return;

  const savedSessions = Object.entries(sessions)
    .filter(([id, session]) => id.startsWith('saved_') && session.title)
    .sort((a, b) => (b[1].savedAt || 0) - (a[1].savedAt || 0));

  if (savedSessions.length === 0) {
    menuContent.innerHTML = '<div class="no-chats">No saved chats yet</div>';
    return;
  }

  menuContent.innerHTML = savedSessions.map(([id, session]) => {
    const date = session.savedAt ? new Date(session.savedAt).toLocaleDateString() : 'Unknown date';
    const time = session.savedAt ? new Date(session.savedAt).toLocaleTimeString([], {hour: '2-digit', minute:'2-digit'}) : '';
    const fullDateTime = time ? `${date} at ${time}` : date;
    const safeSessionId = sanitizeText(id);
    const safeTitle = sanitizeText(session.title);
    const safeDateTime = sanitizeText(fullDateTime);
    return `
      <div class="chat-item" data-session-id="${safeSessionId}" title="Created: ${safeDateTime}">
        <div class="chat-title">${safeTitle}</div>
        <button class="delete-chat-btn" data-session-id="${safeSessionId}" title="Delete this chat">×</button>
      </div>
    `;
  }).join('');

  menuContent.querySelectorAll('.chat-item').forEach(item => {
    trackableSessionEventListener(item, 'click', (e) => {
      if (e.target.classList.contains('delete-chat-btn')) return;
      
      const sessionId = item.getAttribute('data-session-id');
      loadSavedChat(sessionId);
      
      const chatsMenu = document.getElementById('chats-menu');
      if (chatsMenu) {
        chatsMenu.classList.remove('visible');
      }
    });
  });

  menuContent.querySelectorAll('.delete-chat-btn').forEach(deleteBtn => {
    trackableSessionEventListener(deleteBtn, 'click', (e) => {
      e.stopPropagation();
      
      const sessionId = deleteBtn.getAttribute('data-session-id');
      const chatTitle = deleteBtn.parentElement.querySelector('.chat-title').textContent;
      
      if (confirm(`Are you sure you want to delete "${chatTitle}"?`)) {
        deleteSavedChat(sessionId);
        loadChatsList();
        
        const chatsMenu = document.getElementById('chats-menu');
        const menuContent = document.getElementById('chats-menu-content');
        if (chatsMenu && menuContent && menuContent.innerHTML.includes('No saved chats yet')) {
          chatsMenu.classList.remove('visible');
        }
      }
    });
  });
}

// --- Delete Saved Chat ---
function deleteSavedChat(sessionId) {
  const sessionToDelete = sessions[sessionId];

  if (sessionToDelete) {
    const chatTitle = sessionToDelete.title || 'Untitled Chat';
    
    delete sessions[sessionId];
    persistSessions();
    
    appendMessage('bot', `🗑️ **Deleted chat:** "${sanitizeText(chatTitle)}"`);
  } else {
    console.warn(`Attempted to delete a non-existent session: ${sessionId}`);
    appendMessage('bot', `❌ Could not delete chat - session not found.`);
  }
}

// --- Load Saved Chat ---
function loadSavedChat(sessionId) {
  const savedSession = sessions[sessionId];
  if (!savedSession) {
    appendMessage('bot', '❌ Could not load saved chat - session not found.');
    return;
  }

  const chatMessages = document.getElementById('chat-log');
  if (chatMessages) {
    chatMessages.innerHTML = '';
  }

  updateState({
    isMarmActive: true,
    currentSessionId: sessionId
  });

  if (savedSession.history && savedSession.history.length > 0) {
    savedSession.history.forEach(msg => {
      if (msg.role === 'user') {
        appendMessage('user', msg.content);
      } else if (msg.role === 'bot') {
        appendMessage('bot', msg.content);
      }
    });
  }

  appendMessage('bot', `📂 **Loaded saved chat:** "${savedSession.title}"`);
}

// --- Save Session Button Setup ---
export function setupSaveSession() {
  const saveBtn = document.getElementById('saveSessionBtn');
  if (!saveBtn) return;

  saveBtn.innerHTML = '💾 Save Session';
  saveBtn.title = 'Save your current session with a custom title';

  trackableSessionEventListener(saveBtn, 'click', () => {
    const sessionTitle = prompt('Enter a title for this session:');
    
    if (sessionTitle && sessionTitle.trim()) {
      localStorage.setItem('marm-persistence-enabled', 'true');
      const currentState = getState();
      
      if (currentState.currentSessionId && sessions[currentState.currentSessionId]) {
        const savedSessionId = `saved_${Date.now()}`;
        sessions[savedSessionId] = {
          ...sessions[currentState.currentSessionId],
          title: sessionTitle.trim(),
          savedAt: Date.now()
        };
        
        persistSessions();
        
        appendMessage('bot', `✅ Session saved as "${sessionTitle.trim()}"`);
        
        const chatsMenu = document.getElementById('chats-menu');
        if (chatsMenu && chatsMenu.classList.contains('visible')) {
          loadChatsList();
        }
      }
    }
  });
}

// --- Restore Chat History ---
export function restoreChatHistory() {
  const currentState = getState();
  if (currentState.isMarmActive && currentState.currentSessionId && sessions[currentState.currentSessionId]) {
    const session = sessions[currentState.currentSessionId];
    
    if (session.history.length > 0) {
      const chatMessages = document.getElementById('chat-log');
      if (!chatMessages) return;
      
      chatMessages.innerHTML = '';
      
      session.history.forEach(msg => {
        if (msg.role === 'user') {
          appendMessage('user', msg.content);
        } else if (msg.role === 'bot') {
          appendMessage('bot', msg.content);
        }
      });
    }
  }
}
