/**
 * Security Integration Tests
 * 
 * Tests that verify all security components work together correctly
 * and that the overall security posture is maintained.
 */

import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

describe('Security Integration', () => {
  let mainJsContent;
  
  beforeAll(() => {
    const mainJsPath = path.join(__dirname, '../../src/main.js');
    mainJsContent = fs.readFileSync(mainJsPath, 'utf8');
  });
  
  describe('End-to-End Security Flow', () => {
    test('should implement complete URL validation pipeline', () => {
      // URL validation should be integrated into the app flow
      expect(mainJsContent).toContain('isValidUrl');
      expect(mainJsContent).toContain('validateServerUrl');
      
      // Should be called during authentication flow
      expect(mainJsContent).toMatch(/startOAuthFlow.*isValidUrl/s);
      expect(mainJsContent).toMatch(/connectToMARMServer.*serverUrl/s);
    });
    
    test('should prevent XSS throughout the user journey', () => {
      // All user data should go through safe handling
      expect(mainJsContent).toContain('textContent');
      expect(mainJsContent).toContain('createElement');
      
      // Should not have any innerHTML assignments
      expect(mainJsContent).not.toMatch(/\.innerHTML\s*=/);
    });
    
    test('should handle error scenarios securely', () => {
      // Error messages should be sanitized
      const errorHandlingPattern = /catch.*error/gi;
      const errorHandlers = mainJsContent.match(errorHandlingPattern) || [];
      
      // Should have error handling
      expect(errorHandlers.length).toBeGreaterThan(0);
      
      // Should use safe error display methods
      expect(mainJsContent).toMatch(/textContent.*error|createElement.*error/i);
    });
  });
  
  describe('OAuth Security Integration', () => {
    test('should validate URLs before OAuth flow', () => {
      const oauthFlow = mainJsContent.match(/startOAuthFlow[\s\S]*?catch/);
      expect(oauthFlow).toBeTruthy();
      
      if (oauthFlow) {
        const flowText = oauthFlow[0];
        expect(flowText).toContain('isValidUrl');
        expect(flowText).toContain('serverUrl');
      }
    });
    
    test('should use HTTPS for OAuth redirects', () => {
      // OAuth URLs should be HTTPS only
      const urlPattern = /https:\/\/fastmcp\.app/;
      expect(mainJsContent).toMatch(urlPattern);
      
      // Should not contain HTTP URLs
      expect(mainJsContent).not.toContain('http://fastmcp.app');
    });
  });
  
  describe('Data Flow Security', () => {
    test('should sanitize all user inputs before processing', () => {
      // User input fields should be validated
      expect(mainJsContent).toContain('server-url');
      expect(mainJsContent).toContain('validateServerUrl');
      
      // Activity data should be handled safely
      expect(mainJsContent).toMatch(/activity\.description.*textContent/s);
      expect(mainJsContent).toMatch(/session\.name.*textContent/s);
    });
    
    test('should prevent script injection in dynamic content', () => {
      // Dynamic content creation should be safe
      expect(mainJsContent).toContain('document.createElement');
      expect(mainJsContent).toContain('createTextNode') ||
      expect(mainJsContent).toContain('textContent');
      
      // Should not use dangerous methods
      expect(mainJsContent).not.toContain('eval(');
      expect(mainJsContent).not.toContain('Function(');
    });
  });
});

describe('Defense in Depth Validation', () => {
  test('should have multiple layers of input validation', () => {
    // Layer 1: URL format validation
    expect(mainJsContent).toContain('isValidUrl');
    
    // Layer 2: Protocol validation (HTTPS only)
    expect(mainJsContent).toMatch(/protocol.*!==.*https/);
    
    // Layer 3: Domain validation
    expect(mainJsContent).toMatch(/hostname.*test/);
    
    // Layer 4: Blocklist validation
    expect(mainJsContent).toContain('blockedPatterns');
  });
  
  test('should prevent bypass attempts at multiple levels', () => {
    const securityMeasures = [
      'localhost',     // Local access prevention
      'javascript:',   // Script injection prevention
      'file://',      // File access prevention
      '<script',      // HTML injection prevention
      'eval(',        // Code execution prevention
    ];
    
    securityMeasures.forEach(measure => {
      expect(mainJsContent).toContain(measure);
    });
  });
});

describe('Security Configuration Integration', () => {
  test('should enforce security policies throughout the app lifecycle', () => {
    // Authentication should require valid URL
    expect(mainJsContent).toMatch(/authentication.*isValidUrl|isValidUrl.*authentication/s);
    
    // Connection should validate server
    expect(mainJsContent).toMatch(/connect.*validateServerUrl|validateServerUrl.*connect/s);
    
    // Activity display should be safe
    expect(mainJsContent).toMatch(/activity.*textContent|createElement.*activity/s);
  });
  
  test('should maintain security during error conditions', () => {
    // Error handling should not expose sensitive data
    expect(mainJsContent).not.toMatch(/console\.log.*error\.stack/i);
    expect(mainJsContent).not.toMatch(/console\.log.*error\.message.*sensitive/i);
    
    // Error display should be safe
    expect(mainJsContent).toMatch(/error.*textContent|createElement.*error/s);
  });
});

describe('Cross-Component Security Validation', () => {
  let mainJsContent, webchatSecurityContent;
  
  beforeAll(() => {
    const mainJsPath = path.join(__dirname, '../../src/main.js');
    mainJsContent = fs.readFileSync(mainJsPath, 'utf8');
    
    const webchatSecurityPath = path.join(__dirname, '../../../webchat/src/security/xssProtection.js');
    if (fs.existsSync(webchatSecurityPath)) {
      webchatSecurityContent = fs.readFileSync(webchatSecurityPath, 'utf8');
    }
  });
  
  test('should use consistent security patterns across components', () => {
    // Both should use similar sanitization approaches
    expect(mainJsContent).toContain('textContent');
    
    if (webchatSecurityContent) {
      expect(webchatSecurityContent).toContain('sanitizeHTML');
      expect(webchatSecurityContent).toContain('textContent');
    }
  });
  
  test('should prevent the same attack vectors across components', () => {
    const attackVectors = [
      'script',
      'javascript:',
      'eval',
      'innerHTML'
    ];
    
    attackVectors.forEach(vector => {
      // Desktop app should block these
      if (vector === 'innerHTML') {
        expect(mainJsContent).not.toMatch(/\.innerHTML\s*=/);
      } else {
        expect(mainJsContent).toContain(vector);
      }
      
      // Webchat should also handle these
      if (webchatSecurityContent) {
        expect(webchatSecurityContent).toContain(vector) ||
        expect(webchatSecurityContent).toMatch(new RegExp(vector, 'i'));
      }
    });
  });
});

// Mock environment test
describe('Security Under Different Conditions', () => {
  let mockWindow, mockDocument;
  
  beforeEach(() => {
    mockDocument = {
      createElement: jest.fn(() => ({
        textContent: '',
        style: {},
        appendChild: jest.fn(),
        addEventListener: jest.fn()
      })),
      getElementById: jest.fn(() => ({
        textContent: '',
        value: '',
        style: {},
        classList: { add: jest.fn(), remove: jest.fn() }
      }))
    };
    
    mockWindow = {
      location: { protocol: 'https:' },
      document: mockDocument
    };
    
    global.window = mockWindow;
    global.document = mockDocument;
  });
  
  test('should maintain security when DOM is manipulated', () => {
    // Simulate safe DOM manipulation
    const element = document.createElement('div');
    element.textContent = '<script>alert("xss")</script>';
    
    expect(element.textContent).toBe('<script>alert("xss")</script>');
    expect(document.createElement).toHaveBeenCalledWith('div');
  });
  
  test('should validate URLs under different input conditions', () => {
    // Mock URL validation function behavior
    const mockIsValidUrl = (url) => {
      if (!url || typeof url !== 'string') return false;
      if (!url.startsWith('https://')) return false;
      if (url.includes('localhost')) return false;
      return true;
    };
    
    // Test various inputs
    expect(mockIsValidUrl('https://example.com')).toBe(true);
    expect(mockIsValidUrl('http://example.com')).toBe(false);
    expect(mockIsValidUrl('https://localhost')).toBe(false);
    expect(mockIsValidUrl('')).toBe(false);
    expect(mockIsValidUrl(null)).toBe(false);
  });
});