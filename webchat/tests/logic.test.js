import {
  stripHTML,
  validateNotebookEntry,
  validateLogEntry,
  checkProtocolCompliance
} from '../webchat/src/logic/utils.js';

import {
  ensureSession,
  updateNotebookSize,
  trimSessionSize,
  getSessionContext,
  updateSessionHistory,
  setSessionReasoning,
  logSession,
  trimForContext,
  resetSession,
  getAllSessions,
  getMostRecentBotResponseLogic
} from '../webchat/src/logic/session.js';

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

describe('Session Logic', () => {
  test('ensureSession creates and returns a session object', () => {
    const session = ensureSession('test_session');
    expect(session).toHaveProperty('history');
    expect(session).toHaveProperty('logs');
    expect(session).toHaveProperty('notebook');
  });

  test('updateNotebookSize updates notebookSize', () => {
    const sessionId = 'size_session';
    ensureSession(sessionId);
    updateNotebookSize(sessionId, 10);
    expect(ensureSession(sessionId).notebookSize).toBeGreaterThanOrEqual(10);
  });

  test('trimSessionSize prunes history/logs if too large', () => {
    const session = ensureSession('prune_session');
    session.history = Array(100).fill({role: 'user', content: 'test'});
    session.logs = Array(100).fill('log');
    trimSessionSize(session);
    expect(session.history.length).toBeLessThanOrEqual(100);
    expect(session.logs.length).toBeLessThanOrEqual(100);
  });

  test('resetSession deletes a session', () => {
    ensureSession('reset_session');
    resetSession('reset_session');
    expect(getAllSessions()).not.toContain('reset_session');
  });

  test('getSessionContext returns basic context for new session', () => {
    const context = getSessionContext('nonexistent_session');
    expect(context).toContain('MARM v');
    expect(context).toContain('MEMORY ACCURATE RESPONSE MODE');
  });

  test('getSessionContext includes notebook and logs', () => {
    const sessionId = 'context_session';
    const session = ensureSession(sessionId);
    session.notebook = { 'test_key': 'test_value' };
    session.logs = ['2025-08-18 - test log - summary'];
    
    const context = getSessionContext(sessionId);
    expect(context).toContain('Current Notebook Contents');
    expect(context).toContain('test_key: test_value');
    expect(context).toContain('Recent Log Entries');
    expect(context).toContain('2025-08-18 - test log - summary');
  });

  test('updateSessionHistory adds user and bot messages', () => {
    const sessionId = 'history_session';
    updateSessionHistory(sessionId, 'User question', 'Bot response', 'Bot reasoning');
    
    const session = ensureSession(sessionId);
    expect(session.history).toHaveLength(2);
    expect(session.history[0].role).toBe('user');
    expect(session.history[0].content).toBe('User question');
    expect(session.history[1].role).toBe('bot');
    expect(session.history[1].content).toBe('Bot response');
    expect(session.lastReasoning).toBe('Bot reasoning');
  });

  test('setSessionReasoning updates reasoning', () => {
    const sessionId = 'reasoning_session';
    ensureSession(sessionId);
    setSessionReasoning(sessionId, 'New reasoning');
    
    expect(ensureSession(sessionId).lastReasoning).toBe('New reasoning');
  });

  test('logSession validates log entry format', () => {
    const sessionId = 'log_session';
    const result = logSession(sessionId, 'invalid log');
    expect(result).toContain('Invalid log entry format');
  });

  test('logSession adds valid log entries', () => {
    const sessionId = 'log_session';
    const validLog = '2025-08-18 - test topic - test summary';
    const result = logSession(sessionId, validLog);
    
    expect(result).toContain('Logged:');
    expect(ensureSession(sessionId).logs).toContain(validLog);
  });

  test('trimForContext removes old history when exceeding token limit', () => {
    const sessionId = 'trim_session';
    const session = ensureSession(sessionId);
    
    // Add many messages to exceed token limit
    for (let i = 0; i < 50; i++) {
      session.history.push({
        role: 'user',
        content: 'A very long message that contains many tokens and should trigger trimming when the total exceeds the maximum allowed tokens for context management'.repeat(10)
      });
    }
    
    const originalLength = session.history.length;
    const wasTrimmed = trimForContext(sessionId, 1000); // Low token limit to force trimming
    
    expect(wasTrimmed).toBe(true);
    expect(session.history.length).toBeLessThan(originalLength);
  });

  test('getMostRecentBotResponseLogic returns reasoning', () => {
    const sessionId = 'reasoning_session';
    const session = ensureSession(sessionId);
    session.lastReasoning = 'Test reasoning';
    
    expect(getMostRecentBotResponseLogic(sessionId)).toBe('Test reasoning');
  });

  test('getMostRecentBotResponseLogic returns empty string for nonexistent session', () => {
    expect(getMostRecentBotResponseLogic('nonexistent')).toBe('');
  });

  test('ensureSession enforces max session limit', () => {
    // Clear existing sessions
    getAllSessions().forEach(id => resetSession(id));
    
    // Create maximum number of sessions
    for (let i = 0; i < 50; i++) {
      ensureSession(`session_${i}`);
    }
    
    // Creating one more should trigger cleanup
    ensureSession('overflow_session');
    const sessionCount = getAllSessions().length;
    expect(sessionCount).toBeLessThanOrEqual(50);
  });

  test('updateNotebookSize tracks notebook size changes', () => {
    const sessionId = 'size_session';
    ensureSession(sessionId);
    
    updateNotebookSize(sessionId, 100);
    expect(ensureSession(sessionId).notebookSize).toBe(100);
    
    updateNotebookSize(sessionId, 50);
    expect(ensureSession(sessionId).notebookSize).toBe(150);
  });
});
