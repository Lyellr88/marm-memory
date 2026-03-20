// Jest setup for MARM Desktop tests
import { TextEncoder, TextDecoder } from 'util';

// Mock browser APIs
global.TextEncoder = TextEncoder;
global.TextDecoder = TextDecoder;

// Mock localStorage
const localStorageMock = {
  getItem: jest.fn(),
  setItem: jest.fn(),
  removeItem: jest.fn(),
  clear: jest.fn(),
};
global.localStorage = localStorageMock;

// Mock Tauri API
global.__TAURI__ = {
  core: {
    invoke: jest.fn()
  }
};

// Mock URL constructor
global.URL = URL;

// Mock DOM methods
global.document = {
  createElement: jest.fn(() => ({
    style: {},
    classList: { add: jest.fn(), remove: jest.fn() },
    appendChild: jest.fn(),
    removeChild: jest.fn(),
    addEventListener: jest.fn(),
    textContent: '',
    innerHTML: ''
  })),
  getElementById: jest.fn(),
  querySelectorAll: jest.fn(() => []),
  querySelector: jest.fn(),
  body: {
    appendChild: jest.fn(),
    removeChild: jest.fn()
  }
};

global.window = {
  localStorage: localStorageMock,
  location: {
    hostname: 'localhost',
    protocol: 'file:'
  },
  matchMedia: jest.fn(() => ({
    matches: false,
    addListener: jest.fn(),
    removeListener: jest.fn()
  })),
  __TAURI__: global.__TAURI__
};

// Mock console to prevent noise in tests
global.console = {
  ...console,
  log: jest.fn(),
  warn: jest.fn(),
  error: jest.fn()
};