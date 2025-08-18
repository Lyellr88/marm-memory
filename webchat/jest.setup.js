// Jest setup file for browser environment mocks

// Mock localStorage for Node.js environment
Object.defineProperty(window, 'localStorage', {
  value: {
    getItem: jest.fn(() => null),
    setItem: jest.fn(() => null),
    removeItem: jest.fn(() => null),
    clear: jest.fn(() => null),
  },
  writable: true,
});

// Mock sessionStorage for Node.js environment
Object.defineProperty(window, 'sessionStorage', {
  value: {
    getItem: jest.fn(() => null),
    setItem: jest.fn(() => null),
    removeItem: jest.fn(() => null),
    clear: jest.fn(() => null),
  },
  writable: true,
});

// Mock console methods to avoid noise in tests
global.console = {
  ...console,
  log: jest.fn(),
  warn: jest.fn(),
  error: jest.fn(),
  debug: jest.fn(),
};

// Mock speechSynthesis for Node.js environment
global.speechSynthesis = {
  getVoices: jest.fn(() => []),
  speak: jest.fn(),
  cancel: jest.fn(),
  speaking: false,
  pending: false,
  onvoiceschanged: null,
};

// Mock SpeechSynthesisUtterance constructor
global.SpeechSynthesisUtterance = jest.fn().mockImplementation((text) => ({
  text: text,
  rate: 1,
  pitch: 1,
  volume: 1,
  voice: null,
  onstart: null,
  onend: null,
  onerror: null,
}));

// Add Jest DOM matchers - will be available after Jest initializes
global.setupJestMatchers = () => {
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
};

// Mock global debug functions that session.js calls
global.debugProtocolText = jest.fn();
global.debugMarmKeywords = jest.fn();

// Create basic DOM structure that tests expect
document.body.innerHTML = '<div id="chat-log"></div>';
