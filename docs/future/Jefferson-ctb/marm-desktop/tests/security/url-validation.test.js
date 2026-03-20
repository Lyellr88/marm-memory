/**
 * URL Validation Security Tests
 * 
 * Tests for the comprehensive URL validation system that prevents:
 * - HTTP cleartext transmission
 * - Local file access attempts
 * - Script injection via URLs
 * - Malformed URL attacks
 */

import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

// Read the main.js file to extract validation functions
const mainJsPath = path.join(__dirname, '../../src/main.js');
const mainJsContent = fs.readFileSync(mainJsPath, 'utf8');

// Extract and evaluate the validation functions in a safe context
const createValidationContext = () => {
  const context = {};
  
  // Mock browser APIs
  context.localStorage = {
    getItem: jest.fn(),
    setItem: jest.fn()
  };
  
  context.document = {
    getElementById: jest.fn(() => ({
      value: '',
      style: {},
      textContent: ''
    }))
  };
  
  // Extract isValidUrl function
  const isValidUrlMatch = mainJsContent.match(/isValidUrl\(url\)\s*\{([\s\S]*?)\n\s*\}/);
  if (isValidUrlMatch) {
    const funcBody = isValidUrlMatch[1];
    context.isValidUrl = new Function('url', funcBody);
  }
  
  return context;
};

describe('URL Validation Security', () => {
  let validationContext;
  
  beforeEach(() => {
    validationContext = createValidationContext();
  });
  
  describe('HTTPS Enforcement', () => {
    test('should reject HTTP URLs to prevent cleartext transmission', () => {
      const httpUrls = [
        'http://example.com',
        'http://fastmcp.app',
        'http://api.example.com/path',
        'http://127.0.0.1:8080'
      ];
      
      httpUrls.forEach(url => {
        expect(validationContext.isValidUrl(url)).toBe(false);
      });
    });
    
    test('should accept valid HTTPS URLs', () => {
      const httpsUrls = [
        'https://example.com',
        'https://fastmcp.app',
        'https://api.example.com/path',
        'https://subdomain.example.co.uk'
      ];
      
      httpsUrls.forEach(url => {
        expect(validationContext.isValidUrl(url)).toBe(true);
      });
    });
  });
  
  describe('Local Access Prevention', () => {
    test('should block localhost access attempts', () => {
      const localUrls = [
        'https://localhost',
        'https://localhost:8080',
        'https://127.0.0.1',
        'https://127.0.0.1:3000',
        'https://0.0.0.0',
        'https://::1'
      ];
      
      localUrls.forEach(url => {
        expect(validationContext.isValidUrl(url)).toBe(false);
      });
    });
    
    test('should block file protocol attempts', () => {
      const fileUrls = [
        'file:///etc/passwd',
        'file://localhost/etc/passwd', 
        'file:///C:/Windows/System32/',
        'https://example.com/file://'
      ];
      
      fileUrls.forEach(url => {
        expect(validationContext.isValidUrl(url)).toBe(false);
      });
    });
  });
  
  describe('Script Injection Prevention', () => {
    test('should block javascript protocol injection', () => {
      const jsUrls = [
        'javascript:alert(1)',
        'https://example.com/javascript:',
        'JAVASCRIPT:alert(document.domain)',
        'https://example.com/path?param=javascript:alert(1)'
      ];
      
      jsUrls.forEach(url => {
        expect(validationContext.isValidUrl(url)).toBe(false);
      });
    });
    
    test('should block data protocol injection', () => {
      const dataUrls = [
        'data:text/html,<script>alert(1)</script>',
        'https://example.com/data:',
        'DATA:image/svg+xml;base64,PHN2Zz4='
      ];
      
      dataUrls.forEach(url => {
        expect(validationContext.isValidUrl(url)).toBe(false);
      });
    });
    
    test('should block HTML injection attempts in URLs', () => {
      const htmlUrls = [
        'https://example.com/<script>',
        'https://example.com/eval(',
        'https://example.com/onclick=',
        'https://example.com/<script>alert(1)</script>'
      ];
      
      htmlUrls.forEach(url => {
        expect(validationContext.isValidUrl(url)).toBe(false);
      });
    });
  });
  
  describe('Input Sanitization', () => {
    test('should handle null and undefined inputs safely', () => {
      expect(validationContext.isValidUrl(null)).toBe(false);
      expect(validationContext.isValidUrl(undefined)).toBe(false);
      expect(validationContext.isValidUrl('')).toBe(false);
    });
    
    test('should handle non-string inputs safely', () => {
      expect(validationContext.isValidUrl(123)).toBe(false);
      expect(validationContext.isValidUrl({})).toBe(false);
      expect(validationContext.isValidUrl([])).toBe(false);
    });
    
    test('should trim whitespace from URLs', () => {
      expect(validationContext.isValidUrl('  https://example.com  ')).toBe(true);
      expect(validationContext.isValidUrl('\n\thttps://example.com\r\n')).toBe(true);
    });
  });
  
  describe('Domain Validation', () => {
    test('should require valid domain format', () => {
      const invalidDomains = [
        'https://.',
        'https://.com',
        'https://a',
        'https://a.b', // Too short TLD
        'https://-example.com',
        'https://example-.com'
      ];
      
      invalidDomains.forEach(url => {
        expect(validationContext.isValidUrl(url)).toBe(false);
      });
    });
    
    test('should accept valid domain formats', () => {
      const validDomains = [
        'https://example.com',
        'https://sub.example.com',
        'https://example.co.uk',
        'https://api-v2.example-site.org'
      ];
      
      validDomains.forEach(url => {
        expect(validationContext.isValidUrl(url)).toBe(true);
      });
    });
    
    test('should validate IP addresses correctly', () => {
      // Valid public IP addresses should be allowed
      expect(validationContext.isValidUrl('https://8.8.8.8')).toBe(true);
      expect(validationContext.isValidUrl('https://192.0.2.1')).toBe(true);
      
      // Invalid IP formats should be rejected
      expect(validationContext.isValidUrl('https://256.1.1.1')).toBe(false);
      expect(validationContext.isValidUrl('https://1.1.1')).toBe(false);
    });
  });
  
  describe('Edge Cases and Bypass Attempts', () => {
    test('should prevent URL encoding bypass attempts', () => {
      const encodedUrls = [
        'https://example.com/%6A%61%76%61%73%63%72%69%70%74%3A', // javascript:
        'https://example.com/%66%69%6C%65%3A%2F%2F', // file://
        'https://example.com/\u006A\u0061\u0076\u0061\u0073\u0063\u0072\u0069\u0070\u0074\u003A' // Unicode
      ];
      
      encodedUrls.forEach(url => {
        expect(validationContext.isValidUrl(url)).toBe(false);
      });
    });
    
    test('should handle malformed URL constructions gracefully', () => {
      const malformedUrls = [
        'https://[invalid-ipv6',
        'https://example.com:99999',
        'https://example.com/path?param=value&',
        'https://example.com/../../../etc/passwd'
      ];
      
      // These should either be rejected or handled safely without throwing
      malformedUrls.forEach(url => {
        expect(() => {
          const result = validationContext.isValidUrl(url);
          expect(typeof result).toBe('boolean');
        }).not.toThrow();
      });
    });
  });
});

describe('URL Validation Integration', () => {
  test('should exist in main.js file', () => {
    expect(mainJsContent).toContain('isValidUrl(url)');
    expect(mainJsContent).toContain('validateServerUrl()');
  });
  
  test('should enforce HTTPS requirement', () => {
    expect(mainJsContent).toContain('https:');
    expect(mainJsContent).toContain("protocol !== 'https:'");
  });
  
  test('should contain security blocklist patterns', () => {
    const securityPatterns = [
      'localhost',
      '127.0.0.1', 
      'javascript:',
      'file://',
      '<script',
      'eval(',
      'onclick='
    ];
    
    securityPatterns.forEach(pattern => {
      expect(mainJsContent).toContain(pattern);
    });
  });
});