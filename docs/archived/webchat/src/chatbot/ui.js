// ui.js - DOM manipulation and UI display functions for MARM chatbot

// ===== UI Functions for MARM Chatbot =====
import { speakText, voiceConfig, addVoiceToggleToHelp } from './voice.js';
import { sanitizeHTML, sanitizeText } from '../security/xssProtection.js';

// ===== MEMORY LEAK PREVENTION =====
const eventListeners = new Map();
const timeouts = new Set();
const intervals = new Set();

function trackableTimeout(callback, delay) {
  const timeoutId = setTimeout(() => {
    timeouts.delete(timeoutId);
    callback();
  }, delay);
  timeouts.add(timeoutId);
  return timeoutId;
}

function trackableInterval(callback, delay) {
  const intervalId = setInterval(callback, delay);
  intervals.add(intervalId);
  return intervalId;
}

function trackableEventListener(element, event, handler, options) {
  element.addEventListener(event, handler, options);
  
  if (!eventListeners.has(element)) {
    eventListeners.set(element, []);
  }
  eventListeners.get(element).push({ event, handler, options });
}

export function cleanupUI() {
  timeouts.forEach(timeoutId => clearTimeout(timeoutId));
  timeouts.clear();
  
  intervals.forEach(intervalId => clearInterval(intervalId));
  intervals.clear();
  
  eventListeners.forEach((listeners, element) => {
    listeners.forEach(({ event, handler, options }) => {
      try {
        element.removeEventListener(event, handler, options);
      } catch (e) {
      }
    });
  });
  eventListeners.clear();
  
}

// ===== SECURITY FUNCTIONS =====
function sanitizeHtml(html) {
  return html
    .replace(/<script\b[^<]*(?:(?!<\/script>)<[^<]*)*<\/script>/gi, '') 
    .replace(/on\w+\s*=\s*["'][^"']*["']/gi, '') 
    .replace(/javascript:/gi, '') 
    .replace(/<iframe\b[^<]*(?:(?!<\/iframe>)<[^<]*)*<\/iframe>/gi, '')
    .replace(/<object\b[^<]*(?:(?!<\/object>)<[^<]*)*<\/object>/gi, '') 
    .replace(/<embed\b[^<]*(?:(?!<\/embed>)<[^<]*)*<\/embed>/gi, '');
}

// ===== LOADING INDICATORS =====
export function showLoadingIndicator() {
  const chatMessages = document.getElementById('chat-log');
  if (!chatMessages) throw new Error('Chat log not found');
  
  const template = document.getElementById('loading-indicator-template');
  if (!template) {
    console.warn('Loading indicator template not found in HTML');
    return;
  }
  
  const loadingDiv = template.cloneNode(true);
  loadingDiv.id = 'loading-indicator';  
  loadingDiv.style.display = 'block';  
  
  chatMessages.appendChild(loadingDiv);
  chatMessages.scrollTop = chatMessages.scrollHeight;
}

export function hideLoadingIndicator() {
  const loadingDiv = document.getElementById('loading-indicator');
  if (loadingDiv) {
    loadingDiv.remove();
  }
}

// ===== MARKDOWN PROCESSING =====
function processMarkdownWithCodeWindows(text) {
  if (!window.marked) return text;
  
  let html = marked.parse(text);
  
  html = sanitizeHTML(html);
  
  const codeBlockRegex = /<pre><code[^>]*>([\s\S]*?)<\/code><\/pre>/g;
  
  html = html.replace(codeBlockRegex, (match, codeContent) => {
    const langMatch = match.match(/class="language-(\w+)"/);
    const language = langMatch ? langMatch[1] : 'markdown';
    
    const cleanCode = codeContent
      .replace(/&lt;/g, '<')
      .replace(/&gt;/g, '>')
      .replace(/&amp;/g, '&')
      .replace(/&quot;/g, '"')
      .replace(/&#39;/g, "'");
    
    const template = document.getElementById('code-window-template');
    if (!template) {
      console.warn('Code window template not found, falling back to simple code block');
      return `<pre><code>${cleanCode}</code></pre>`;
    }
    
    const codeWindow = template.cloneNode(true);
    codeWindow.removeAttribute('id'); 
    codeWindow.style.display = 'block'; 
    
    const languageSpan = codeWindow.querySelector('.code-language');
    const codeElement = codeWindow.querySelector('code');
    
    if (languageSpan) languageSpan.textContent = language;
    if (codeElement) codeElement.textContent = cleanCode;
    
    return codeWindow.outerHTML;
  });
  
  return html;
}

// ===== CODE WINDOW COPY FUNCTION =====
function copyCodeWindow(button) {
  const codeWindow = button.closest('.code-window');
  const codeElement = codeWindow.querySelector('code');
  const codeText = codeElement.textContent;
  
  navigator.clipboard.writeText(codeText).then(() => {
    button.textContent = 'Copied!';
    button.classList.add('copied');
    
    trackableTimeout(() => {
      button.textContent = 'Copy';
      button.classList.remove('copied');
    }, 2000);
  }).catch(err => {
    console.error('Failed to copy code: ', err);
  });
}

// ===== EVENT DELEGATION FOR CODE COPY BUTTONS =====
trackableEventListener(document, 'click', (e) => {
  if (e.target.classList.contains('code-window-copy-btn')) {
    copyCodeWindow(e.target);
  }
});

// ===== MESSAGE DISPLAY =====
export function appendMessage(sender, text) {
  const chatMessages = document.getElementById('chat-log');
  if (!chatMessages) throw new Error('Chat log not found');
  
  const messageDiv = document.createElement('div');
  messageDiv.className = `message ${sender}-message`;
  
  const nameTag = document.createElement('div');
  nameTag.className = 'message-name';
  nameTag.textContent = sender === 'user' ? 'User' : 'MARM bot';
  messageDiv.appendChild(nameTag);
  
  const contentDiv = document.createElement('div');
  contentDiv.className = 'message-content';
  contentDiv.setAttribute('aria-live', 'polite');
  
  if (sender === 'bot') {
    try {
      const processedContent = processMarkdownWithCodeWindows(text);
      contentDiv.innerHTML = sanitizeHTML(processedContent);
    } catch (e) {
      contentDiv.textContent = text;
    }
  } else {
    try {
      const processedContent = processMarkdownWithCodeWindows(text);
      contentDiv.innerHTML = sanitizeHTML(processedContent);
    } catch (e) {
      contentDiv.textContent = text;
    }
  }
  messageDiv.appendChild(contentDiv);

  const copyBtn = document.createElement('button');
  copyBtn.className = 'copy-btn';
  copyBtn.textContent = 'Copy';
  copyBtn.title = 'Copy text';
  
  trackableEventListener(copyBtn, 'click', () => {
    navigator.clipboard.writeText(contentDiv.textContent).then(() => {
      copyBtn.textContent = 'Copied!';
      copyBtn.classList.add('copied');
      
      trackableTimeout(() => {
        copyBtn.textContent = 'Copy';
        copyBtn.classList.remove('copied');
      }, 2000);
    }).catch(err => {
      console.error('Failed to copy text: ', err);
    });
  });
  messageDiv.appendChild(copyBtn);
  
  if (sender === 'bot') {
    const voiceBtn = document.createElement('button');
    voiceBtn.className = 'voice-btn';
    voiceBtn.textContent = '🔊';
    voiceBtn.title = 'Read aloud';
    
    trackableEventListener(voiceBtn, 'click', () => {
      if (speechSynthesis.speaking) {
        speechSynthesis.cancel();
        document.querySelectorAll('.bot-message').forEach(msg => {
          msg.classList.remove('speaking');
        });
      } else {
        if (typeof speakText === 'function') {
          speakText(text, true);
          messageDiv.classList.add('speaking');
        }
      }
    });
    messageDiv.appendChild(voiceBtn);
  }
  
  chatMessages.appendChild(messageDiv);
  chatMessages.scrollTop = chatMessages.scrollHeight;
  
  if (sender === 'bot' && voiceConfig && voiceConfig.enabled) {
    trackableTimeout(() => {
      speakText(text, true);
      messageDiv.classList.add('speaking');
    }, 100);
  }
}

// ===== COMMAND MENU SYSTEM =====
export function createCommandMenu() {
  const commandMenu = document.getElementById('command-menu');
  
  if (!commandMenu) {
    console.warn('Command menu template not found in HTML');
    return;
  }
  
  let commandMenuCollapsed = false;
  try {
    commandMenuCollapsed = localStorage.getItem('commandMenuCollapsed') === 'true';
  } catch (e) {
    commandMenuCollapsed = false;
  }
  
  if (commandMenuCollapsed) {
    commandMenu.classList.add('collapsed');
  }
  
  commandMenu.setAttribute('aria-expanded', 'false');
  
  commandMenu.style.display = 'block';
  
  commandMenu.addEventListener('click', (e) => {
    if (e.target.closest('.command-menu-header')) {
      toggleCommandMenu();
    } else if (e.target.closest('.submenu-item')) {
      const command = e.target.closest('.submenu-item').getAttribute('data-command');
      if (command) insertCommand(command);
    } else if (e.target.closest('.notebook-item')) {
      handleNotebookClick(e);
      return;
    } else if (e.target.closest('.command-item')) {
      const command = e.target.closest('.command-item').getAttribute('data-command');
      if (command) insertCommand(command);
    }
  });
}

export function toggleCommandMenu() {
  const menu = document.getElementById('command-menu');
  if (!menu) return;
  menu.classList.toggle('collapsed');
  
  localStorage.setItem('commandMenuCollapsed', menu.classList.contains('collapsed'));
}

export function handleNotebookClick(event) {
  event.stopPropagation();
  const submenu = document.getElementById('notebook-submenu');
  if (!submenu) return;
  const isVisible = submenu.style.display === 'block';
  
  document.querySelectorAll('.notebook-submenu').forEach(menu => {
    menu.style.display = 'none';
  });
  
  submenu.style.display = isVisible ? 'none' : 'block';
}

export function insertCommand(command) {
  const input = document.getElementById('user-input');
  if (!input) return;
  input.value = command;
  input.focus();
  
  const submenu = document.getElementById('notebook-submenu');
  if (submenu) {
    submenu.style.display = 'none';
  }
  
  const commandMenu = document.getElementById('command-menu');
  if (commandMenu && window.innerWidth <= 600) {
    commandMenu.classList.add('collapsed');
    localStorage.setItem('commandMenuCollapsed', 'true');
  }
  
  if (command.endsWith(' ')) {
    input.setSelectionRange(input.value.length, input.value.length);
  }
}

// ===== MODAL SETUP =====
export function setupHelpModal() {
  const helpBtn = document.getElementById('helpBtn');
  const helpModal = document.getElementById('help-modal');
  const closeHelp = document.getElementById('close-help');
  const markdownModal = document.getElementById('markdown-modal');
  const closeMarkdown = document.getElementById('close-markdown');
  const markdownContent = document.getElementById('markdown-content');
  const markdownTitle = document.getElementById('markdown-title');

  if (helpBtn && helpModal && closeHelp) {
    helpBtn.addEventListener('click', () => {
      if (helpModal.classList.contains('visible')) {
        helpModal.classList.remove('visible');
      } else {
        helpModal.classList.add('visible');
        helpModal.style.position = 'fixed'; 
        
        addVoiceToggleToHelp();
      }
    });
    trackableEventListener(closeHelp, 'click', () => helpModal.classList.remove('visible'));
    trackableEventListener(document, 'click', (e) => {
      if (e.target === helpModal) helpModal.classList.remove('visible');
    });

    const header = helpModal.querySelector('.modal-header');
    let isDragging = false, startX = 0, startY = 0, startLeft = 0, startTop = 0;
    if (header) {
      header.addEventListener('mousedown', (e) => {
        isDragging = true;
        startX = e.clientX;
        startY = e.clientY;
        const rect = helpModal.getBoundingClientRect();
        startLeft = rect.left;
        startTop = rect.top;
        document.body.style.userSelect = 'none';
      });
      document.addEventListener('mousemove', (e) => {
        if (!isDragging) return;
        const dx = e.clientX - startX;
        const dy = e.clientY - startY;
        helpModal.style.left = `${startLeft + dx}px`;
        helpModal.style.top = `${startTop + dy}px`;
        helpModal.style.margin = '0';
      });
      document.addEventListener('mouseup', () => {
        isDragging = false;
        document.body.style.userSelect = '';
      });
    }
  }

  if (markdownModal && closeMarkdown) {
    trackableEventListener(closeMarkdown, 'click', () => markdownModal.classList.remove('visible'));
    trackableEventListener(document, 'click', (e) => {
      if (e.target === markdownModal) markdownModal.classList.remove('visible');
    });
  }

  trackableEventListener(document, 'click', async (e) => {
    if (e.target.closest('.doc-link')) {
      e.preventDefault();
      const docLink = e.target.closest('.doc-link');
      const docFile = docLink.getAttribute('data-doc');
      
      if (docFile && markdownModal && markdownContent && markdownTitle) {
        markdownModal.classList.add('visible');
        markdownContent.innerHTML = '<div class="loading-spinner">Loading...</div>';
        
        const titles = {
          'handbook.md': '📘 MARM Handbook',
          'faq.md': '❓ Frequently Asked Questions',
          'description.md': '📄 Project Description',
          'roadmap.md': '🗺️ Development Roadmap'
        };
        markdownTitle.textContent = titles[docFile] || 'Documentation';
        
        try {
          const response = await fetch(`data/${docFile}`);
          if (!response.ok) throw new Error('Failed to load document');
          
          const markdownText = await response.text();
          const htmlContent = marked.parse(markdownText);
          markdownContent.innerHTML = sanitizeHTML(htmlContent);
        } catch (error) {
          markdownContent.innerHTML = sanitizeHTML(`
            <div class="error-message">
              <h3>❌ Failed to load document</h3>
              <p>Sorry, we couldn't load the ${docFile} file. Please try again later.</p>
              <p><small>Error: ${sanitizeText(error.message)}</small></p>
            </div>
          `);
        }
      }
    }
  });
  
}

// ===== UI SETUP FUNCTIONS =====
export function setupDarkMode() {
  const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
  
  let userPreference = null;
  try {
    userPreference = localStorage.getItem('darkMode');
  } catch (e) {
    userPreference = null;
  }
  
  let shouldBeDark = false;
  if (userPreference !== null) {
    shouldBeDark = userPreference === '1';
  } else {
    shouldBeDark = prefersDark;
  }
  
  if (shouldBeDark) {
    document.body.classList.add('dark-mode');
  }
  
  trackableEventListener(window.matchMedia('(prefers-color-scheme: dark)'), 'change', (e) => {
    if (userPreference === null) {
      if (e.matches) {
        document.body.classList.add('dark-mode');
      } else {
        document.body.classList.remove('dark-mode');
      }
    }
  });
}

export function setupKeyboardShortcuts() {
  trackableEventListener(document, 'keydown', (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key === '/') {
      e.preventDefault();
      toggleCommandMenu();
    }
  });
}

export function setupAutoExpandingTextarea() {
  const userInput = document.getElementById('user-input');
  if (!userInput) return;

  trackableEventListener(userInput, 'input', () => {
    userInput.style.height = 'auto';
    userInput.style.height = userInput.scrollHeight + 'px';
  });

  trackableEventListener(userInput, 'keydown', (event) => {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault();
      document.getElementById('chat-form').requestSubmit();
    }
  });
}

export function setupTokenCounter() {
} 
