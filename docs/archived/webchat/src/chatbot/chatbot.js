// chatbot.js - Main entry point and initializer for MARM chatbot //

// ===== Imports & Dependencies =====
// --- XSS Protection ---
import { sanitizeHTML } from '../security/xssProtection.js';

export * from './core.js';
export * from './ui.js';
export * from './voice.js';
export * from './commands.js';

import { handleUserInput } from './core.js';
import { 
  createCommandMenu, 
  setupHelpModal, 
  setupDarkMode, 
  setupAutoExpandingTextarea,
  setupKeyboardShortcuts
} from './ui.js';
import { 
  setupSaveSession,
  restoreChatHistory,
  loadChatsList
} from './sessionUI.js';
import { initializeVoice } from './voice.js';
import { cleanupConnections } from '../replicateHelper.js';
import { cleanupUI } from './ui.js';
import { cleanupVoice } from './voice.js';
import { cleanupSessionUI } from './sessionUI.js';
import { resetState, getState, updateState, restoreState } from './state.js';
import { CURRENT_SESSION_KEY } from '../logic/session.js';
import { appendMessage } from './ui.js';

// ===== Initialization =====
// --- Chatbot Initialization ---
function initializeChatbot() {
  restoreState(); // Restore MARM state from localStorage
  
  setupHelpModal();
  setupDarkMode();
  setupAutoExpandingTextarea();
  setupKeyboardShortcuts();
  setupSaveSession();
  
  initializeVoice();
  
  restoreChatHistory();
  
  const chatForm = document.getElementById('chat-form');
  if (chatForm) {
    chatForm.addEventListener('submit', e => {
      e.preventDefault();
      const input = document.getElementById('user-input');
      if (!input) return;
      const userMessage = input.value.trim();
      if (userMessage) {
        handleUserInput(userMessage);
        input.value = '';
      }
    });
  }
  
  
  initializeMobileFAB();
  setupFileUpload();
  setupCommandButton();
  updateMarmButtonState();
  
  window.addEventListener('beforeunload', cleanup);
  window.addEventListener('pagehide', cleanup);
}

// *** Event Handlers ***
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', initializeChatbot);
} else {
  initializeChatbot();
}

// ===== FAB Button Actions =====
// --- Dark Mode Toggle ---
function toggleDarkMode() {
  document.body.classList.toggle('dark-mode');
  
  if (document.body.classList.contains('dark-mode')) {
    localStorage.setItem('darkMode', '1');
  } else {
    localStorage.setItem('darkMode', '0');
  }
}

// --- Chats Menu Toggle ---
function toggleChatsMenu() {
  const chatsMenu = document.getElementById('chats-menu');
  
  if (!chatsMenu) {
    console.warn('Chats menu template not found in HTML');
    return;
  }
  
  const refreshBtn = document.getElementById('refresh-chats-btn');
  if (refreshBtn && !refreshBtn.hasAttribute('data-listener-added')) {
    refreshBtn.addEventListener('click', (e) => {
      e.stopPropagation(); 
      loadChatsList();
    });
    refreshBtn.setAttribute('data-listener-added', 'true');
  }
  
  const closeBtn = document.getElementById('close-chats-btn');
  if (closeBtn && !closeBtn.hasAttribute('data-listener-added')) {
    closeBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      chatsMenu.classList.remove('visible');
      chatsMenu.style.display = 'none';
      document.removeEventListener('click', handleClickOutside);
    });
    closeBtn.setAttribute('data-listener-added', 'true');
  }
  
  const isVisible = chatsMenu.classList.contains('visible');
  
  if (isVisible) {
    chatsMenu.classList.remove('visible');
    chatsMenu.style.display = 'none';
    document.removeEventListener('click', handleClickOutside);
  } else {
    chatsMenu.style.display = 'block';
    chatsMenu.classList.add('visible');
    setTimeout(() => {
      document.addEventListener('click', handleClickOutside);
    }, 0);
    
    const menuContent = document.getElementById('chats-menu-content');
    if (menuContent && menuContent.innerHTML.includes('No saved chats yet')) {
      loadChatsList();
    }
  }
}

// --- Click Outside Handler ---
function handleClickOutside(event) {
  const chatsMenu = document.getElementById('chats-menu');
  const fabContainer = document.getElementById('fab-container');
  
  if (!chatsMenu || !chatsMenu.classList.contains('visible')) return;
  
  const isClickOutsideMenu = !chatsMenu.contains(event.target);
  const isClickOnFAB = fabContainer && fabContainer.contains(event.target);
  
  if (isClickOutsideMenu && !isClickOnFAB) {
    chatsMenu.classList.remove('visible');
    document.removeEventListener('click', handleClickOutside);
  }
}

// --- Start New Chat ---
function startNewChat() {
  const chatsMenu = document.getElementById('chats-menu');
  if (chatsMenu) chatsMenu.classList.remove('visible');
  
  try {
    localStorage.removeItem(CURRENT_SESSION_KEY);
  } catch (e) {
    console.warn('Failed to clear current session:', e);
  }
  
  resetState();
  
  const chatMessages = document.getElementById('chat-log');
  if (chatMessages) {
    while (chatMessages.firstChild) {
      chatMessages.removeChild(chatMessages.firstChild);
    }
    
    const welcomeDiv = document.createElement('div');
    welcomeDiv.id = 'welcome-message';
    welcomeDiv.className = 'welcome-message-chat';
    
    const contentDiv = document.createElement('div');
    contentDiv.className = 'welcome-content';
    
    const heading = document.createElement('h3');
    heading.innerHTML = 'Sick of re-explaining yourself every few minutes? <span class="wave">👋</span>';
    
    const paragraph = document.createElement('p');
    paragraph.innerHTML = 'Try MARM now. Use the command button on the left to unlock session control.';
    
    contentDiv.appendChild(heading);
    contentDiv.appendChild(paragraph);
    welcomeDiv.appendChild(contentDiv);
    chatMessages.appendChild(welcomeDiv);
  }
}

// --- MARM Protocol Toggle ---
function toggleMarmProtocol() {
  const currentState = getState();
  const newMarmState = !currentState.isMarmActive;
  
  updateState({ 
    isMarmActive: newMarmState 
  });
  
const statusMessage = newMarmState
  ? '<span class="pulse-brain">🧠</span> **MARM Protocol activated** - Memory Accurate Response Mode is now active'
  : '<span class="shake-no">🚫</span> **MARM Protocol deactivated** - Now using Llama 4 Maverick Free mode';

appendMessage('system', statusMessage);

updateMarmButtonState();
}

// --- Update MARM Button State ---
function updateMarmButtonState() {
  const currentState = getState();
  const marmButton = document.getElementById('fab-marm-toggle');
  if (marmButton) {
    const isActive = currentState.isMarmActive;
    marmButton.style.backgroundColor = isActive ? '#22c55e' : '';
    marmButton.style.color = isActive ? 'white' : '';
    marmButton.title = isActive 
      ? 'MARM Protocol Active - Click to disable' 
      : 'MARM Protocol Inactive - Click to enable';
  }
}

// --- Token Counter ---
function toggleTokenCounter() {
  window.open('https://platform.openai.com/tokenizer', '_blank');
}

// ===== Mobile FAB Initialization =====
// --- FAB Event Listeners ---
function initializeMobileFAB() {
  const fabContainer = document.getElementById('fab-container');
  const fabMain = document.getElementById('fab-main');
  
  if (!fabContainer || !fabMain) return;
  
  fabMain.addEventListener('click', () => {
    fabContainer.classList.toggle('fab-expanded');
  });
  
  document.getElementById('fab-dark-mode')?.addEventListener('click', () => {
    toggleDarkMode();
    fabContainer.classList.remove('fab-expanded');
  });
  
  document.getElementById('fab-chats')?.addEventListener('click', () => {
    toggleChatsMenu();
    fabContainer.classList.remove('fab-expanded');
  });
  
  document.getElementById('fab-new-chat')?.addEventListener('click', () => {
    startNewChat();
    fabContainer.classList.remove('fab-expanded');
  });
  
  document.getElementById('fab-marm-toggle')?.addEventListener('click', () => {
    toggleMarmProtocol();
    fabContainer.classList.remove('fab-expanded');
  });
  
  document.getElementById('fab-token-counter')?.addEventListener('click', () => {
    toggleTokenCounter();
    fabContainer.classList.remove('fab-expanded');
  });
  
  document.addEventListener('click', (e) => {
    if (!fabContainer.contains(e.target)) {
      fabContainer.classList.remove('fab-expanded');
    }
  });
}

// ===== Command Button Setup =====
function setupCommandButton() {
  const commandBtn = document.getElementById('command-menu-btn');
  const commandMenu = document.getElementById('command-menu');
  const inputContainer = document.querySelector('.input-container');
  
  if (!commandBtn || !commandMenu || !inputContainer) return;
  
  inputContainer.appendChild(commandMenu);
  
  commandBtn.addEventListener('click', (e) => {
    e.stopPropagation();
    toggleCommandMenu();
  });
  
  commandMenu.addEventListener('click', handleCommandClick);
  
  document.addEventListener('click', (e) => {
    if (!inputContainer.contains(e.target)) {
      hideCommandMenu();
    }
  });
}

function toggleCommandMenu() {
  const commandMenu = document.getElementById('command-menu');
  if (commandMenu) {
    const isVisible = commandMenu.classList.contains('visible');
    if (isVisible) {
      hideCommandMenu();
    } else {
      showCommandMenu();
    }
  }
}

function showCommandMenu() {
  const commandMenu = document.getElementById('command-menu');
  if (commandMenu) {
    commandMenu.classList.add('visible');
    commandMenu.style.display = 'flex';
  }
}

function hideCommandMenu() {
  const commandMenu = document.getElementById('command-menu');
  if (commandMenu) {
    commandMenu.classList.remove('visible');
    commandMenu.style.display = 'none';
  }
}

function handleCommandClick(e) {
  const commandItem = e.target.closest('[data-command]');
  const notebookItem = e.target.closest('.notebook-item');
  const logItem = e.target.closest('.log-item');
  
  if (commandItem && commandItem.dataset.command) {
    const command = commandItem.dataset.command;
    insertCommand(command);
    hideCommandMenu();
    return;
  }
  
  if (notebookItem && !e.target.closest('.notebook-submenu')) {
    e.stopPropagation();
    toggleSubmenu('notebook-submenu');
  }
  
  if (logItem && !e.target.closest('.log-submenu')) {
    e.stopPropagation();
    toggleSubmenu('log-submenu');
  }
}

function insertCommand(command) {
  const userInput = document.getElementById('user-input');
  if (userInput) {
    userInput.value = command;
    userInput.focus();
    userInput.setSelectionRange(command.length, command.length);
  }
}

function toggleSubmenu(submenuId) {
  const submenu = document.getElementById(submenuId);
  if (submenu) {
    const isVisible = submenu.style.display !== 'none';
    submenu.style.display = isVisible ? 'none' : 'block';
  }
}

// ===== File Upload =====
function setupFileUpload() {
  const fileUploadBtn = document.getElementById('file-upload-btn');
  const fileInput = document.getElementById('file-input');
  
  if (!fileUploadBtn || !fileInput) return;
  
  fileUploadBtn.addEventListener('click', () => {
    fileInput.click();
  });
  
  fileInput.addEventListener('change', handleFileUpload);
}

async function handleFileUpload(event) {
  const file = event.target.files[0];
  if (!file) return;
  
  try {
    const content = await readFileContent(file);
    const fileExtension = file.name.split('.').pop().toLowerCase();
    const fileName = file.name;
    
    let formattedMessage = `📁 **File uploaded:** \`${fileName}\`\n\n`;
    
    if (['js', 'html', 'css', 'json', 'py', 'java', 'cpp', 'c', 'h', 'xml', 'yaml', 'yml'].includes(fileExtension)) {
      formattedMessage += `\`\`\`${fileExtension}\n${content}\n\`\`\``;
    } else {
      formattedMessage += `\`\`\`\n${content}\n\`\`\``;
    }
    
    const aiMessage = `Analyze this ${fileExtension} file: ${fileName}\n\n${formattedMessage}`;
    
    handleUserInput(aiMessage);
    
  } catch (error) {
    console.error('Error reading file:', error);
    appendMessage('system', '❌ Error reading file. Please make sure it\'s a valid text file.');
  }
  
  event.target.value = '';
}

function readFileContent(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    
    reader.onload = (e) => {
      resolve(e.target.result);
    };
    
    reader.onerror = () => {
      reject(new Error('Failed to read file'));
    };
    
    reader.readAsText(file);
  });
}

// ===== Cleanup =====
export function cleanup() {
  if (window.speechSynthesis) {
    window.speechSynthesis.cancel();
  }
  
  cleanupConnections();
  cleanupUI();
  cleanupVoice();
  cleanupSessionUI();
}
