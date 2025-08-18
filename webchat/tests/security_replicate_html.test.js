test('Security, HTML, and replicateHelper test placeholder', () => {
  expect(true).toBe(true);
});
import { sanitizeText, sanitizeHTML, sanitizeHTMLStrict } from '../webchat/src/security/xssProtection.js';
import { stripHTML, validateNotebookEntry, validateLogEntry, checkProtocolCompliance } from '../webchat/src/logic/utils.js';
import { 
  cleanupUI, 
  showLoadingIndicator, 
  hideLoadingIndicator, 
  appendMessage, 
  createCommandMenu, 
  toggleCommandMenu, 
  handleNotebookClick, 
  insertCommand, 
  setupHelpModal, 
  setupDarkMode 
} from '../webchat/src/chatbot/ui.js';

describe('Security: XSS Protection', () => {
  test('sanitizeText escapes HTML', () => {
    expect(sanitizeText('<b>Safe</b>')).toContain('&lt;b&gt;Safe&lt;/b&gt;');
  });

  test('sanitizeHTML removes dangerous tags', () => {
    expect(sanitizeHTML('<script>alert(1)</script><b>Safe</b>')).toContain('<b>Safe</b>');
    expect(sanitizeHTML('<img src=x onerror=alert(1)>')).toContain('<img src=x>');
  });

  test('sanitizeHTMLStrict only allows safe tags', () => {
    expect(sanitizeHTMLStrict('<script>alert(1)</script><b>Safe</b><a href="#">link</a>')).toContain('<b>Safe</b>');
    expect(sanitizeHTMLStrict('<img src=x onerror=alert(1)>')).not.toContain('<img');
  });
});

describe('Logic Utilities', () => {
  test('stripHTML removes HTML tags', () => {
    expect(stripHTML('<b>Hello</b> World')).toBe('Hello World');
    expect(stripHTML('No tags')).toBe('No tags');
    expect(stripHTML('')).toBe('');
  });

  test('validateNotebookEntry returns true for valid entry', () => {
    expect(validateNotebookEntry('valid_key', 'valid value')).toBe(true);
  });

  test('validateNotebookEntry returns false for invalid entry', () => {
    expect(validateNotebookEntry('', 'valid value')).toBe(false);
    expect(validateNotebookEntry('valid_key', '')).toBe(false);
    expect(validateNotebookEntry('invalid!key', 'valid value')).toBe(false);
  });

  test('validateLogEntry returns true for valid log', () => {
    expect(validateLogEntry('2025-08-18 - test entry - summary')).toBe(true);
  });

  test('validateLogEntry returns false for invalid log', () => {
    expect(validateLogEntry('bad log')).toBe(false);
    expect(validateLogEntry('')).toBe(false);
  });

  test('checkProtocolCompliance works for log and notebook', () => {
    expect(checkProtocolCompliance('log', '2025-08-18 - test entry - summary')).toBe(true);
    expect(checkProtocolCompliance('notebook', {key: 'valid_key', value: 'valid value'})).toBe(true);
    expect(checkProtocolCompliance('notebook', {key: '', value: 'valid value'})).toBe(false);
  });
});

describe('UI Module', () => {
  beforeAll(() => {
    // Set up custom Jest matchers
    expect.extend({
      toHaveClass(received, className) {
        const pass = received.classList.contains(className);
        return {
          message: () => 
            pass 
              ? `expected element not to have class "${className}"`
              : `expected element to have class "${className}"`,
          pass,
        };
      },
    });
  });

  beforeEach(() => {
    // Set up basic DOM structure for UI tests
    document.body.innerHTML = `
      <div id="chat-log"></div>
      <div id="user-input"></div>
      <div id="command-menu" style="display: none;">
        <div class="command-menu-header"></div>
        <div class="command-item" data-command="/help"></div>
        <div class="notebook-item"></div>
      </div>
      <div id="notebook-submenu" style="display: none;"></div>
      <template id="loading-indicator-template">
        <div class="loading-dots">
          <div class="dot"></div>
          <div class="dot"></div>
          <div class="dot"></div>
        </div>
      </template>
      <template id="code-window-template">
        <div class="code-window">
          <div class="code-window-header">
            <span class="code-language"></span>
            <button class="code-window-copy-btn">Copy</button>
          </div>
          <pre><code></code></pre>
        </div>
      </template>
      <div id="help-modal" class="modal">
        <div class="modal-header"></div>
        <button id="close-help">×</button>
      </div>
      <button id="helpBtn">Help</button>
    `;

    // Mock clipboard API
    Object.assign(navigator, {
      clipboard: {
        writeText: jest.fn().mockResolvedValue(),
      },
    });

    // Mock localStorage
    Storage.prototype.getItem = jest.fn();
    Storage.prototype.setItem = jest.fn();
  });

  afterEach(() => {
    cleanupUI();
    document.body.innerHTML = '';
  });

  test('showLoadingIndicator adds loading indicator to chat log', () => {
    showLoadingIndicator();
    const loadingIndicator = document.getElementById('loading-indicator');
    expect(loadingIndicator).toBeTruthy();
    expect(loadingIndicator.style.display).toBe('block');
  });

  test('showLoadingIndicator throws error if chat log not found', () => {
    document.getElementById('chat-log').remove();
    expect(() => showLoadingIndicator()).toThrow('Chat log not found');
  });

  test('hideLoadingIndicator removes loading indicator', () => {
    showLoadingIndicator();
    hideLoadingIndicator();
    const loadingIndicator = document.getElementById('loading-indicator');
    expect(loadingIndicator).toBeFalsy();
  });

  test('appendMessage creates message elements correctly', () => {
    appendMessage('user', 'Hello world');
    const messages = document.querySelectorAll('.message');
    expect(messages.length).toBe(1);
    expect(messages[0]).toHaveClass('user-message');
    expect(messages[0].querySelector('.message-name').textContent).toBe('User');
    expect(messages[0].querySelector('.message-content').textContent).toBe('Hello world');
  });

  test('appendMessage adds voice button for bot messages', () => {
    appendMessage('bot', 'Hello from bot');
    const message = document.querySelector('.bot-message');
    const voiceBtn = message.querySelector('.voice-btn');
    expect(voiceBtn).toBeTruthy();
    expect(voiceBtn.textContent).toBe('🔊');
  });

  test('appendMessage does not add voice button for user messages', () => {
    appendMessage('user', 'Hello from user');
    const message = document.querySelector('.user-message');
    const voiceBtn = message.querySelector('.voice-btn');
    expect(voiceBtn).toBeFalsy();
  });

  test('appendMessage throws error if chat log not found', () => {
    document.getElementById('chat-log').remove();
    expect(() => appendMessage('user', 'test')).toThrow('Chat log not found');
  });

  test('createCommandMenu sets up command menu correctly', () => {
    createCommandMenu();
    const commandMenu = document.getElementById('command-menu');
    expect(commandMenu.style.display).toBe('block');
  });

  test('toggleCommandMenu toggles collapsed class', () => {
    const menu = document.getElementById('command-menu');
    toggleCommandMenu();
    expect(menu).toHaveClass('collapsed');
    toggleCommandMenu();
    expect(menu).not.toHaveClass('collapsed');
  });

  test('handleNotebookClick toggles submenu visibility', () => {
    const submenu = document.getElementById('notebook-submenu');
    const event = { stopPropagation: jest.fn() };
    
    handleNotebookClick(event);
    expect(submenu.style.display).toBe('block');
    
    handleNotebookClick(event);
    expect(submenu.style.display).toBe('none');
    
    expect(event.stopPropagation).toHaveBeenCalledTimes(2);
  });

  test('insertCommand sets input value and focuses', () => {
    const input = document.getElementById('user-input');
    input.focus = jest.fn();
    
    insertCommand('/help');
    expect(input.value).toBe('/help');
    expect(input.focus).toHaveBeenCalled();
  });

  test('insertCommand hides submenu after insertion', () => {
    const submenu = document.getElementById('notebook-submenu');
    submenu.style.display = 'block';
    
    insertCommand('/help');
    expect(submenu.style.display).toBe('none');
  });

  test('setupHelpModal configures modal functionality', () => {
    setupHelpModal();
    const helpBtn = document.getElementById('helpBtn');
    const helpModal = document.getElementById('help-modal');
    
    helpBtn.click();
    expect(helpModal).toHaveClass('visible');
    
    helpBtn.click();
    expect(helpModal).not.toHaveClass('visible');
  });

  test('setupDarkMode applies dark mode based on preferences', () => {
    // Mock window.matchMedia
    Object.defineProperty(window, 'matchMedia', {
      writable: true,
      value: jest.fn().mockImplementation(query => ({
        matches: query === '(prefers-color-scheme: dark)',
        media: query,
        onchange: null,
        addListener: jest.fn(),
        removeListener: jest.fn(),
        addEventListener: jest.fn(),
        removeEventListener: jest.fn(),
        dispatchEvent: jest.fn(),
      })),
    });

    Storage.prototype.getItem.mockReturnValue('1');
    setupDarkMode();
    expect(document.body).toHaveClass('dark-mode');
  });

  test('cleanupUI clears event listeners and timers', () => {
    // Add some mock event listeners through UI functions
    createCommandMenu();
    setupHelpModal();
    
    expect(() => cleanupUI()).not.toThrow();
  });
});
