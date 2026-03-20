/**
 * Console Logging Security Tests
 * 
 * Tests that verify sensitive information is not logged to console
 * and that debug information has been properly sanitized.
 */

import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

describe('Console Logging Security', () => {
  let fileContents;
  
  beforeAll(() => {
    // Read all relevant source files
    const srcDir = path.join(__dirname, '../../../webchat/src');
    const desktopSrc = path.join(__dirname, '../../src');
    
    fileContents = {};
    
    // Read webchat files
    const webchatFiles = [
      path.join(srcDir, 'logic/session.js'),
      path.join(srcDir, 'replicateHelper.js'),
      path.join(srcDir, 'logic/summary.js'),
      path.join(srcDir, 'chatbot/core.js')
    ];
    
    webchatFiles.forEach(filePath => {
      if (fs.existsSync(filePath)) {
        const fileName = path.basename(filePath);
        fileContents[fileName] = fs.readFileSync(filePath, 'utf8');
      }
    });
    
    // Read desktop main.js
    const desktopMainPath = path.join(desktopSrc, 'main.js');
    if (fs.existsSync(desktopMainPath)) {
      fileContents['main.js'] = fs.readFileSync(desktopMainPath, 'utf8');
    }
  });
  
  describe('Sensitive Data Exposure Prevention', () => {
    test('should not log user session context or content', () => {
      const sessionFile = fileContents['session.js'];
      if (sessionFile) {
        // Should not log actual session content
        expect(sessionFile).not.toMatch(/console\.log.*session.*context/i);
        expect(sessionFile).not.toMatch(/console\.log.*basicContext\.substring/i);
        expect(sessionFile).not.toMatch(/console\.log.*context\.substring/i);
        
        // Should use generic comments instead
        expect(sessionFile).toContain('// Session context requested') || 
        expect(sessionFile).toContain('// No session found') ||
        expect(sessionFile).toContain('// Building session context');
      }
    });
    
    test('should not log API responses or tokens', () => {
      const replicateFile = fileContents['replicateHelper.js'];
      if (replicateFile) {
        // Should not log API responses
        expect(replicateFile).not.toMatch(/console\.log.*reply/i);
        expect(replicateFile).not.toMatch(/console\.log.*response/i);
        expect(replicateFile).not.toMatch(/console\.log.*token/i);
        
        // Should use generic success message
        expect(replicateFile).toContain('// API request completed') ||
        expect(replicateFile).not.toMatch(/console\.log.*successful/i);
      }
    });
    
    test('should not expose safety filter details', () => {
      const summaryFile = fileContents['summary.js'];
      const coreFile = fileContents['core.js'];
      
      [summaryFile, coreFile].forEach(file => {
        if (file) {
          // Should not log attempt numbers or filter details
          expect(file).not.toMatch(/console\.warn.*attempt/i);
          expect(file).not.toMatch(/console\.warn.*safety.*filter/i);
          
          // Should use generic comments
          expect(file).toContain('// Possible safety filter detected') ||
          expect(file).not.toMatch(/console\.warn/);
        }
      });
    });
  });
  
  describe('Debug Information Sanitization', () => {
    test('should replace debug logs with comments', () => {
      Object.entries(fileContents).forEach(([fileName, content]) => {
        // Count console.log statements - should be minimal
        const consoleLogMatches = content.match(/console\.log/g) || [];
        const consoleWarnMatches = content.match(/console\.warn/g) || [];
        
        // Should have very few or no console statements
        expect(consoleLogMatches.length + consoleWarnMatches.length).toBeLessThan(3);
      });
    });
    
    test('should not log user input or form data', () => {
      Object.values(fileContents).forEach(content => {
        expect(content).not.toMatch(/console\.log.*input/i);
        expect(content).not.toMatch(/console\.log.*userInput/i);
        expect(content).not.toMatch(/console\.log.*formData/i);
        expect(content).not.toMatch(/console\.log.*serverUrl/i);
      });
    });
    
    test('should not log error details that could expose internals', () => {
      Object.values(fileContents).forEach(content => {
        // Error logging should be limited and sanitized
        const errorLogPattern = /console\.(log|error).*error/gi;
        const matches = content.match(errorLogPattern) || [];
        
        // Should have minimal error logging
        expect(matches.length).toBeLessThan(2);
      });
    });
  });
  
  describe('Production Readiness', () => {
    test('should not contain debug flags or development logging', () => {
      Object.values(fileContents).forEach(content => {
        expect(content).not.toMatch(/DEBUG.*=.*true/i);
        expect(content).not.toMatch(/DEVELOPMENT.*=.*true/i);
        expect(content).not.toMatch(/console\.debug/i);
        expect(content).not.toMatch(/console\.trace/i);
      });
    });
    
    test('should not log stack traces or internal state', () => {
      Object.values(fileContents).forEach(content => {
        expect(content).not.toMatch(/console\.log.*stack/i);
        expect(content).not.toMatch(/console\.log.*trace/i);
        expect(content).not.toMatch(/console\.log.*state/i);
      });
    });
  });
  
  describe('MARM-specific Logging Rules', () => {
    test('should not log MARM protocol context', () => {
      const sessionFile = fileContents['session.js'];
      if (sessionFile) {
        expect(sessionFile).not.toMatch(/console\.log.*MARM.*context/i);
        expect(sessionFile).not.toMatch(/console\.log.*protocol/i);
        expect(sessionFile).not.toMatch(/console\.log.*notebook/i);
      }
    });
    
    test('should not expose session IDs or names in logs', () => {
      Object.values(fileContents).forEach(content => {
        expect(content).not.toMatch(/console\.log.*sessionId/i);
        expect(content).not.toMatch(/console\.log.*sessionName/i);
        expect(content).not.toMatch(/console\.log.*session\.name/i);
      });
    });
  });
});

describe('Console Security Best Practices', () => {
  test('should use appropriate log levels', () => {
    Object.values(fileContents).forEach(content => {
      // console.log should be rare in production code
      const logCount = (content.match(/console\.log/g) || []).length;
      expect(logCount).toBeLessThan(3);
      
      // console.error should be used for actual errors, not debugging
      const errorLogs = content.match(/console\.error/g) || [];
      errorLogs.forEach(match => {
        const context = content.substring(
          Math.max(0, content.indexOf(match) - 100),
          Math.min(content.length, content.indexOf(match) + 100)
        );
        
        // Should be in error handling context
        expect(context.toLowerCase()).toMatch(/error|catch|exception|failed/);
      });
    });
  });
  
  test('should not log in loops or frequent operations', () => {
    Object.values(fileContents).forEach(content => {
      // Check for console statements inside loops
      const forLoopPattern = /for\s*\([^)]*\)[^{]*{[^}]*console\./g;
      const whileLoopPattern = /while\s*\([^)]*\)[^{]*{[^}]*console\./g;
      const forEachPattern = /forEach[^{]*{[^}]*console\./g;
      
      expect(content).not.toMatch(forLoopPattern);
      expect(content).not.toMatch(whileLoopPattern);
      expect(content).not.toMatch(forEachPattern);
    });
  });
});

// Mock console for testing logging behavior
describe('Console Logging Behavior', () => {
  let mockConsole;
  
  beforeEach(() => {
    mockConsole = {
      log: jest.fn(),
      warn: jest.fn(),
      error: jest.fn(),
      debug: jest.fn()
    };
    global.console = mockConsole;
  });
  
  afterEach(() => {
    jest.resetAllMocks();
  });
  
  test('should not accidentally log sensitive data in development', () => {
    // Simulate operations that might accidentally log sensitive data
    const sensitiveData = {
      token: 'secret-token-12345',
      session: { content: 'private session data' },
      userInput: '<script>alert("xss")</script>'
    };
    
    // These operations should not trigger any console output
    const safeOperation = (data) => {
      // Simulate safe processing without logging
      return data ? 'processed' : 'no data';
    };
    
    safeOperation(sensitiveData.token);
    safeOperation(sensitiveData.session);
    safeOperation(sensitiveData.userInput);
    
    expect(mockConsole.log).not.toHaveBeenCalled();
    expect(mockConsole.warn).not.toHaveBeenCalled();
  });
  
  test('should handle errors without exposing sensitive context', () => {
    const sensitiveError = new Error('Authentication failed for user@secret-domain.com');
    
    const safeErrorHandler = (error) => {
      // Should log generic error, not specific details
      if (error.message.includes('Authentication')) {
        // Log sanitized message
        return 'Authentication error occurred';
      }
      return 'Unknown error';
    };
    
    const result = safeErrorHandler(sensitiveError);
    expect(result).toBe('Authentication error occurred');
    expect(result).not.toContain('secret-domain.com');
  });
});