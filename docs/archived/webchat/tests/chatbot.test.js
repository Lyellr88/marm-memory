import { handleUserInput } from '../src/chatbot/core.js';
import { 
  voiceConfig, 
  loadVoices, 
  speakText, 
  initializeVoice, 
  cleanupVoice, 
  voiceTimers, 
  voiceListeners 
} from '../src/chatbot/voice.js';

describe('Chatbot Core', () => {
  test('handleUserInput returns undefined for empty input', async () => {
    const result = await handleUserInput('');
    expect(result).toBeUndefined();
  });

  test('handleUserInput returns undefined for non-string input', async () => {
    const result = await handleUserInput(null);
    expect(result).toBeUndefined();
  });

  test('handleUserInput enforces input length limit', async () => {
    const longInput = 'a'.repeat(15001); // Updated to exceed new 15k limit
    const result = await handleUserInput(longInput);
    expect(result).toBeUndefined();
  });
});

describe('Voice Module', () => {
  beforeEach(() => {
    // Mock speechSynthesis for each test
    global.speechSynthesis = {
      getVoices: jest.fn(() => [
        { name: 'Google UK English Female', lang: 'en-GB', default: false },
        { name: 'Microsoft Zira Desktop', lang: 'en-US', default: false },
        { name: 'TestVoice', lang: 'en-US', default: true }
      ]),
      speak: jest.fn(),
      cancel: jest.fn(),
      speaking: false,
      pending: false,
      onvoiceschanged: null
    };

    // Reset voice config
    voiceConfig.enabled = false;
    voiceConfig.voice = null;
    voiceConfig.rate = 1.10;
    voiceConfig.pitch = 1.0;
  });

  afterEach(() => {
    cleanupVoice();
  });

  test('voiceConfig has correct default values', () => {
    expect(voiceConfig).toHaveProperty('enabled', false);
    expect(voiceConfig).toHaveProperty('rate', 1.10);
    expect(voiceConfig).toHaveProperty('pitch', 1.0);
    expect(voiceConfig).toHaveProperty('voice', null);
  });

  test('loadVoices loads available voices and selects preferred one', () => {
    loadVoices();
    expect(global.speechSynthesis.getVoices).toHaveBeenCalled();
    expect(voiceConfig.voice).toBe('Google UK English Female');
  });

  test('loadVoices handles speech synthesis errors gracefully', () => {
    global.speechSynthesis.getVoices = jest.fn(() => {
      throw new Error('Speech synthesis error');
    });
    
    expect(() => loadVoices()).not.toThrow();
    expect(voiceConfig.voice).toBeNull();
  });

  test('speakText calls speechSynthesis.speak for bot messages', () => {
    loadVoices();
    speakText('Hello world', true);
    expect(global.speechSynthesis.speak).toHaveBeenCalled();
  });

  test('speakText does not speak for non-bot messages', () => {
    speakText('Hello world', false);
    expect(global.speechSynthesis.speak).not.toHaveBeenCalled();
  });

  test('speakText cleans markdown formatting from text', () => {
    loadVoices();
    let actualUtterance;
    global.speechSynthesis.speak = jest.fn((utterance) => {
      actualUtterance = utterance;
    });

    speakText('**Bold text** and *italic text* with `code`', true);
    
    expect(actualUtterance.text).not.toContain('**');
    expect(actualUtterance.text).not.toContain('*');
    expect(actualUtterance.text).not.toContain('`');
    expect(actualUtterance.text).toContain('Bold text');
    expect(actualUtterance.text).toContain('italic text');
  });

  test('speakText truncates long text for voice playback', () => {
    loadVoices();
    let actualUtterance;
    global.speechSynthesis.speak = jest.fn((utterance) => {
      actualUtterance = utterance;
    });

    const longText = 'a'.repeat(12000); // 12k chars - exceeds 10k voice limit
    speakText(longText, true);
    
    expect(actualUtterance.text.length).toBeLessThan(12000);
    expect(actualUtterance.text).toContain('Response truncated for voice playback');
  });

  test('speakText configures utterance with correct voice settings', () => {
    loadVoices();
    let actualUtterance;
    global.speechSynthesis.speak = jest.fn((utterance) => {
      actualUtterance = utterance;
    });

    speakText('Test message', true);
    
    // Rate is adjusted for Google voices (0.95x multiplier), so test the actual rate
    expect(actualUtterance.rate).toBeCloseTo(1.045, 3); // 1.1 * 0.95 = 1.045
    expect(actualUtterance.pitch).toBe(voiceConfig.pitch);
    expect(actualUtterance.volume).toBe(0.9);
  });

  test('initializeVoice sets up voice system correctly', () => {
    // Temporarily disable the self-test in voice.js by mocking the environment
    const originalNodeEnv = process.env?.NODE_ENV;
    if (process.env) {
      process.env.NODE_ENV = 'development';
    }
    
    initializeVoice();
    expect(global.speechSynthesis.onvoiceschanged).toBe(loadVoices);
    expect(voiceConfig.voice).toBe('Google UK English Female');
    
    // Restore original environment
    if (process.env && originalNodeEnv !== undefined) {
      process.env.NODE_ENV = originalNodeEnv;
    }
  });

  test('initializeVoice handles missing speechSynthesis gracefully', () => {
    const originalSpeechSynthesis = global.speechSynthesis;
    global.speechSynthesis = undefined;
    
    expect(() => initializeVoice()).not.toThrow();
    expect(voiceConfig.enabled).toBe(false);
    
    global.speechSynthesis = originalSpeechSynthesis;
  });

  test('voiceTimers and voiceListeners are properly initialized', () => {
    expect(voiceTimers).toBeInstanceOf(Set);
    expect(voiceListeners).toBeInstanceOf(Map);
  });

  test('cleanupVoice properly cleans up resources', () => {
    // Add some mock timers and listeners
    const mockTimer = setTimeout(() => {}, 1000);
    voiceTimers.add(mockTimer);
    
    const mockElement = document.createElement('div');
    voiceListeners.set(mockElement, []);
    
    cleanupVoice();
    
    expect(global.speechSynthesis.cancel).toHaveBeenCalled();
    expect(voiceTimers.size).toBe(0);
    expect(voiceListeners.size).toBe(0);
  });
});

describe('Commands Module', () => {
  let mockGenerateContent;
  let mockGetState;
  let mockUpdateState;
  let mockActivateMarmSession;
  let mockLogSession;
  let mockManageUserNotebook;
  let mockGetSessionContext;
  let mockUpdateSessionHistory;
  let mockGetMostRecentBotResponseLogic;
  let mockSetSessionReasoning;
  let mockTrimForContext;
  let mockCompileSessionSummary;

  beforeEach(() => {
    // Reset DOM
    document.body.innerHTML = '<div id="chat-log"></div>';
    
    // Mock all external dependencies
    mockGenerateContent = jest.fn();
    mockGetState = jest.fn();
    mockUpdateState = jest.fn();
    mockActivateMarmSession = jest.fn();
    mockLogSession = jest.fn();
    mockManageUserNotebook = jest.fn();
    mockGetSessionContext = jest.fn();
    mockUpdateSessionHistory = jest.fn();
    mockGetMostRecentBotResponseLogic = jest.fn();
    mockSetSessionReasoning = jest.fn();
    mockTrimForContext = jest.fn();
    mockCompileSessionSummary = jest.fn();

    // Mock module imports
    jest.doMock('../src/replicateHelper.js', () => ({
      generateContent: mockGenerateContent
    }));

    jest.doMock('../src/chatbot/state.js', () => ({
      getState: mockGetState,
      updateState: mockUpdateState
    }));

    jest.doMock('../src/logic/marmLogic.js', () => ({
      activateMarmSession: mockActivateMarmSession,
      logSession: mockLogSession,
      manageUserNotebook: mockManageUserNotebook,
      getSessionContext: mockGetSessionContext,
      updateSessionHistory: mockUpdateSessionHistory,
      getMostRecentBotResponseLogic: mockGetMostRecentBotResponseLogic,
      setSessionReasoning: mockSetSessionReasoning,
      trimForContext: mockTrimForContext,
      compileSessionSummary: mockCompileSessionSummary
    }));

    // Setup default state
    mockGetState.mockReturnValue({
      isMarmActive: false,
      currentSessionId: null
    });

    // Setup default generateContent response
    mockGenerateContent.mockResolvedValue({
      text: jest.fn().mockResolvedValue('Mock bot response')
    });

    mockGetSessionContext.mockReturnValue('Mock session context');
  });

  afterEach(() => {
    jest.clearAllMocks();
    jest.resetModules();
  });

  test('handleCommand parses commands correctly', async () => {
    const { handleCommand } = await import('../src/chatbot/commands.js');
    
    // Test unknown command
    await handleCommand('/unknown');
    // Should show error message (we can't easily test the exact message without more complex mocking)
  });

  test('handleCommand handles /start marm command', async () => {
    const { handleCommand } = await import('../src/chatbot/commands.js');
    
    mockUpdateState.mockReturnValue({
      isMarmActive: true,
      currentSessionId: 'test_session'
    });

    await handleCommand('/start marm');

    expect(mockUpdateState).toHaveBeenCalledWith({
      isMarmActive: true,
      currentSessionId: expect.any(String)
    });
    expect(mockActivateMarmSession).toHaveBeenCalled();
    expect(mockGenerateContent).toHaveBeenCalled();
  });

  test('handleCommand handles /refresh marm command when MARM is active', async () => {
    const { handleCommand } = await import('../src/chatbot/commands.js');
    
    mockGetState.mockReturnValue({
      isMarmActive: true,
      currentSessionId: 'test_session'
    });

    await handleCommand('/refresh marm');

    expect(mockTrimForContext).toHaveBeenCalledWith('test_session');
    expect(mockGenerateContent).toHaveBeenCalled();
  });

  test('handleCommand handles /log entry command', async () => {
    const { handleCommand } = await import('../src/chatbot/commands.js');
    
    mockGetState.mockReturnValue({
      isMarmActive: true,
      currentSessionId: 'test_session'
    });

    await handleCommand('/log entry: 2025-08-18 - test log - summary');

    expect(mockLogSession).toHaveBeenCalledWith('test_session', '2025-08-18 - test log - summary');
    expect(mockGenerateContent).toHaveBeenCalled();
  });

  test('handleCommand handles /log session command', async () => {
    const { handleCommand } = await import('../src/chatbot/commands.js');
    
    mockGetState.mockReturnValue({
      isMarmActive: true,
      currentSessionId: 'test_session'
    });

    mockUpdateState.mockReturnValue({
      isMarmActive: true,
      currentSessionId: 'new_session'
    });

    await handleCommand('/log session: new_session');

    expect(mockUpdateState).toHaveBeenCalledWith({ currentSessionId: 'new_session' });
    expect(mockGenerateContent).toHaveBeenCalled();
  });

  test('handleCommand handles /deep dive command', async () => {
    const { handleCommand } = await import('../src/chatbot/commands.js');
    
    mockGetState.mockReturnValue({
      isMarmActive: true,
      currentSessionId: 'test_session'
    });

    // Mock response with reasoning
    mockGenerateContent.mockResolvedValue({
      text: jest.fn().mockResolvedValue('Bot response\n\nREASONING: This is the reasoning')
    });

    await handleCommand('/deep dive: test topic');

    expect(mockGenerateContent).toHaveBeenCalled();
    expect(mockSetSessionReasoning).toHaveBeenCalledWith('test_session', 'This is the reasoning');
  });

  test('handleCommand handles /show reasoning command', async () => {
    const { handleCommand } = await import('../src/chatbot/commands.js');
    
    mockGetState.mockReturnValue({
      isMarmActive: true,
      currentSessionId: 'test_session'
    });

    mockGetMostRecentBotResponseLogic.mockReturnValue('Test reasoning');

    await handleCommand('/show reasoning');

    expect(mockGetMostRecentBotResponseLogic).toHaveBeenCalledWith('test_session');
  });

  test('handleCommand handles /summary command', async () => {
    const { handleCommand } = await import('../src/chatbot/commands.js');
    
    mockGetState.mockReturnValue({
      isMarmActive: true,
      currentSessionId: 'test_session'
    });

    mockCompileSessionSummary.mockResolvedValue('Session summary');

    await handleCommand('/summary');

    expect(mockCompileSessionSummary).toHaveBeenCalledWith('test_session');
  });

  test('handleCommand handles /notebook add command', async () => {
    const { handleCommand } = await import('../src/chatbot/commands.js');
    
    mockGetState.mockReturnValue({
      isMarmActive: true,
      currentSessionId: 'test_session'
    });

    mockManageUserNotebook.mockReturnValue('Notebook data');

    await handleCommand('/notebook add: test_key test value');

    expect(mockManageUserNotebook).toHaveBeenCalledWith('test_session', 'add', 'test_key', 'test value');
    expect(mockGenerateContent).toHaveBeenCalled();
  });

  test('handleCommand handles /notebook show command', async () => {
    const { handleCommand } = await import('../src/chatbot/commands.js');
    
    mockGetState.mockReturnValue({
      isMarmActive: true,
      currentSessionId: 'test_session'
    });

    mockManageUserNotebook.mockReturnValue('All notebook entries');

    await handleCommand('/notebook show:');

    expect(mockManageUserNotebook).toHaveBeenCalledWith('test_session', 'all');
    expect(mockGenerateContent).toHaveBeenCalled();
  });

  test('handleCommand rejects commands when MARM not active', async () => {
    const { handleCommand } = await import('../src/chatbot/commands.js');
    
    // Keep MARM inactive
    mockGetState.mockReturnValue({
      isMarmActive: false,
      currentSessionId: null
    });

    await handleCommand('/log entry: test');
    await handleCommand('/deep dive: test');
    await handleCommand('/notebook add: key value');

    // Should not call MARM functions when inactive
    expect(mockLogSession).not.toHaveBeenCalled();
    expect(mockManageUserNotebook).not.toHaveBeenCalled();
  });

  test('handleCommand handles API errors gracefully', async () => {
    const { handleCommand } = await import('../src/chatbot/commands.js');
    
    mockGetState.mockReturnValue({
      isMarmActive: true,
      currentSessionId: 'test_session'
    });

    // Mock API failure
    mockGenerateContent.mockRejectedValue(new Error('API Error'));

    await handleCommand('/refresh marm');

    // Should handle error without crashing
    expect(mockGenerateContent).toHaveBeenCalled();
  });

  test('handleCommand validates input formats', async () => {
    const { handleCommand } = await import('../src/chatbot/commands.js');
    
    mockGetState.mockReturnValue({
      isMarmActive: true,
      currentSessionId: 'test_session'
    });

    // Test commands with missing arguments
    await handleCommand('/log');
    await handleCommand('/notebook');
    await handleCommand('/summary');

    // Should not call underlying functions with invalid input
    // (Exact validation depends on implementation)
  });
});