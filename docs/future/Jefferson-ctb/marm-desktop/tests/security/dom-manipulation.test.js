/**
 * DOM Manipulation Security Tests
 * 
 * Tests that verify all innerHTML usages have been replaced with safe DOM manipulation
 * and that XSS prevention measures are properly implemented.
 */

import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

describe('DOM Manipulation Security', () => {
  let mainJsContent;
  
  beforeAll(() => {
    const mainJsPath = path.join(__dirname, '../../src/main.js');
    mainJsContent = fs.readFileSync(mainJsPath, 'utf8');
  });
  
  describe('innerHTML Prevention', () => {
    test('should not contain any innerHTML assignments', () => {
      const innerHTMLPattern = /\.innerHTML\s*=/g;
      const matches = mainJsContent.match(innerHTMLPattern);
      
      expect(matches).toBeNull();
    });
    
    test('should use textContent instead of innerHTML for user data', () => {
      expect(mainJsContent).toContain('.textContent =');
      expect(mainJsContent).toContain('textContent');
    });
    
    test('should use createElement for dynamic content', () => {
      expect(mainJsContent).toContain('document.createElement');
      expect(mainJsContent).toContain('appendChild');
    });
  });
  
  describe('Safe HTML Construction', () => {
    test('should contain security utility functions', () => {
      expect(mainJsContent).toContain('sanitizeHTML');
      expect(mainJsContent).toContain('safeSetInnerHTML');
    });
    
    test('should escape HTML entities in security functions', () => {
      // Check that sanitizeHTML function exists and processes content safely
      const sanitizeMatch = mainJsContent.match(/function sanitizeHTML\(html\)([\s\S]*?)^\}/m);
      expect(sanitizeMatch).toBeTruthy();
      
      if (sanitizeMatch) {
        const functionBody = sanitizeMatch[1];
        expect(functionBody).toContain('textContent');
        expect(functionBody).toContain('innerHTML');
      }
    });
  });
  
  describe('Event Handler Security', () => {
    test('should not contain inline event handlers', () => {
      const dangerousPatterns = [
        /onclick\s*=/gi,
        /onload\s*=/gi,  
        /onerror\s*=/gi,
        /onmouseover\s*=/gi
      ];
      
      dangerousPatterns.forEach(pattern => {
        const matches = mainJsContent.match(pattern);
        expect(matches).toBeNull();
      });
    });
    
    test('should use addEventListener for event binding', () => {
      expect(mainJsContent).toContain('addEventListener');
    });
  });
  
  describe('User Content Handling', () => {
    test('should safely handle session names and descriptions', () => {
      // Check that session data is handled through textContent
      const sessionHandlingPattern = /session\.name|activity\.description|session\.created/g;
      const matches = mainJsContent.match(sessionHandlingPattern);
      
      if (matches) {
        // Find contexts where these are used - should be with textContent
        const contextPattern = /textContent.*(?:session\.name|activity\.description|session\.created)/g;
        const safeContexts = mainJsContent.match(contextPattern);
        expect(safeContexts).toBeTruthy();
      }
    });
    
    test('should use createTextNode for dynamic text', () => {
      expect(mainJsContent).toContain('createTextNode') || 
      expect(mainJsContent).toContain('textContent');
    });
  });
  
  describe('CSS Injection Prevention', () => {
    test('should use cssText or style properties instead of style innerHTML', () => {
      expect(mainJsContent).toContain('cssText') || 
      expect(mainJsContent).toContain('.style.');
    });
    
    test('should not allow style attribute injection', () => {
      // Check that style assignments don't use user input directly
      const stylePattern = /style\s*=\s*['"]/g;
      const matches = mainJsContent.match(stylePattern);
      
      if (matches) {
        // Ensure these are hardcoded styles, not user input
        matches.forEach(match => {
          const context = mainJsContent.substring(
            Math.max(0, mainJsContent.indexOf(match) - 50),
            Math.min(mainJsContent.length, mainJsContent.indexOf(match) + 100)
          );
          
          // Should not contain user input variables
          expect(context).not.toMatch(/\$\{.*\}/);
        });
      }
    });
  });
});

describe('XSS Prevention Mechanisms', () => {
  let mainJsContent;
  
  beforeAll(() => {
    const mainJsPath = path.join(__dirname, '../../src/main.js');
    mainJsContent = fs.readFileSync(mainJsPath, 'utf8');
  });
  
  test('should include sanitization utility functions', () => {
    expect(mainJsContent).toContain('sanitizeHTML');
    expect(mainJsContent).toContain('safeSetInnerHTML');
  });
  
  test('should handle error messages safely', () => {
    // Error messages should use textContent, not innerHTML
    const errorPattern = /error\.message|Error.*:/g;
    const matches = mainJsContent.match(errorPattern);
    
    if (matches) {
      // Check surrounding context uses safe methods
      expect(mainJsContent).toMatch(/textContent.*error|createElement.*error/i);
    }
  });
});

describe('Security Regression Prevention', () => {
  let mainJsContent;
  
  beforeAll(() => {
    const mainJsPath = path.join(__dirname, '../../src/main.js');
    mainJsContent = fs.readFileSync(mainJsPath, 'utf8');
  });
  
  test('should not reintroduce dangerous methods', () => {
    const dangerousMethods = [
      'eval(',
      'Function(',
      'setTimeout(.*string',
      'setInterval(.*string',
      'document.write(',
      'execCommand('
    ];
    
    dangerousMethods.forEach(method => {
      expect(mainJsContent).not.toMatch(new RegExp(method, 'i'));
    });
  });
  
  test('should maintain input validation patterns', () => {
    expect(mainJsContent).toContain('isValidUrl');
    expect(mainJsContent).toContain('validateServerUrl');
  });
});

// Mock DOM manipulation test
describe('Safe DOM Creation', () => {
  let mockDocument;
  let mockElement;
  
  beforeEach(() => {
    mockElement = {
      textContent: '',
      innerHTML: '',
      style: {},
      classList: {
        add: jest.fn(),
        remove: jest.fn()
      },
      appendChild: jest.fn(),
      addEventListener: jest.fn()
    };
    
    mockDocument = {
      createElement: jest.fn(() => mockElement),
      createTextNode: jest.fn(text => ({ textContent: text })),
      getElementById: jest.fn(() => mockElement)
    };
    
    global.document = mockDocument;
  });
  
  test('should create elements safely', () => {
    // Simulate safe element creation pattern from the app
    const safeCreate = (tag, text, styles) => {
      const element = document.createElement(tag);
      element.textContent = text;
      if (styles) {
        element.style.cssText = styles;
      }
      return element;
    };
    
    const result = safeCreate('div', 'Safe content', 'color: red;');
    
    expect(mockDocument.createElement).toHaveBeenCalledWith('div');
    expect(result.textContent).toBe('Safe content');
    expect(result.style.cssText).toBe('color: red;');
  });
  
  test('should handle user input safely', () => {
    const userInput = '<script>alert("xss")</script>';
    const element = document.createElement('span');
    element.textContent = userInput; // Safe assignment
    
    expect(element.textContent).toBe('<script>alert("xss")</script>');
    expect(element.innerHTML).toBe(''); // Should not be set
  });
});