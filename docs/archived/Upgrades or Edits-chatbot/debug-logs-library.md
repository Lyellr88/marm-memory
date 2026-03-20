# Debug Logs Library - MARM Systems

This library contains all detailed debug logs that were helpful during development but removed from production for cleaner code. Use these patterns when troubleshooting specific issues.

## Purpose

- **Preserve debugging knowledge** from bug-solving sessions
- **Quick reference** for adding targeted debug logs when issues arise
- **Contributor guidance** for debugging specific components
- **Clean production code** while maintaining debugging capability

---

## Usage Instructions

1. **Identify the problem area** (e.g., session management, command parsing)
2. **Find the relevant section** below 
3. **Temporarily add specific logs** to your local development
4. **Remove logs** before committing

---

## File Sections

### 📂 Core Logic Files

#### [`webchat/src/logic/session.js`](#sessionjs)
#### [`webchat/src/logic/notebook.js`](#notebookjs)
#### [`webchat/src/logic/marmLogic.js`](#marmlogicjs)
#### [`webchat/src/logic/storage.js`](#storagejs)

### 📂 Chatbot Core Files

#### [`webchat/src/chatbot/core.js`](#corejs)
#### [`webchat/src/chatbot/chatbot.js`](#chatbotjs)
#### [`webchat/src/chatbot/commands.js`](#commandsjs)
#### [`webchat/src/chatbot/ui.js`](#uijs)

### 📂 Server & API Files

#### [`webchat/src/chatbot/server.js`](#serverjs)
#### [`webchat/src/replicateHelper.js`](#replicatehelperjs)

---

## Debug Log Sections

*Each section will be populated as we review the files*

### constants.js

**Debug Category:** Protocol & Configuration Debugging  
**Location:** `webchat/src/logic/constants.js`

#### Keywords Loading Debug (Lines 12-16)
```javascript
// Debug function to check if keywords might trigger safety filters
export function debugMarmKeywords() {
  console.log('[MARM DEBUG] MARM_KEYWORDS loaded:', MARM_KEYWORDS.length, 'keywords');
  console.log('[MARM DEBUG] Keywords:', MARM_KEYWORDS.join(', '));
  return MARM_KEYWORDS;
}
```
**Purpose:** Verify MARM keywords array loads correctly and check for potential safety filter triggers.

#### Protocol Text Validation Debug (Lines 19-36)
```javascript
// Debug function to check protocol text for potential safety triggers
export function debugProtocolText() {
  console.log('[MARM DEBUG] MARM_PROTOCOL_TEXT length:', MARM_PROTOCOL_TEXT.length, 'characters');
  console.log('[MARM DEBUG] Protocol preview:', MARM_PROTOCOL_TEXT.substring(0, 200) + '...');
  
  // Check for potentially problematic words
  const potentialTriggers = ['control', 'override', 'strict', 'guardrails', 'priority', 'directive'];
  const foundTriggers = potentialTriggers.filter(trigger => 
    MARM_PROTOCOL_TEXT.toLowerCase().includes(trigger.toLowerCase())
  );
  
  if (foundTriggers.length > 0) {
    console.warn('[MARM DEBUG] Potential safety trigger words found:', foundTriggers); // KEEP THIS WARNING
  } else {
    console.log('[MARM DEBUG] No obvious trigger words detected - protocol text sanitized');
  }
  
  return MARM_PROTOCOL_TEXT;
}
```
**Purpose:** Validate protocol text loads correctly and detect potential AI safety trigger words.
**Note:** Keep the console.warn for production - useful for debugging protocol issues.

---

### session.js

**Debug Category:** Session Management & Context Building  
**Location:** `webchat/src/logic/session.js`

#### Context Building Debug (Lines 104-143)
```javascript
export function getSessionContext(id) {
  console.log('[MARM DEBUG] getSessionContext called for session ID:', id);
  
  // Debug the protocol text that might trigger safety filters
  debugProtocolText(); // This calls the removed constants.js function
  debugMarmKeywords(); // This calls the removed constants.js function
  
  const s = sessions[id];
  if (!s) {
    const basicContext = `MARM v${PROTOCOL_VERSION}\n\n` + MARM_PROTOCOL_TEXT;
    console.log('[MARM DEBUG] No session found, returning basic context length:', basicContext.length);
    console.log('[MARM DEBUG] Basic context preview:', basicContext.substring(0, 200) + '...');
    return basicContext;
  }
  
  // ... context building logic ...
  
  console.log('[MARM DEBUG] Session found, building context...');
  
  // ... after building context ...
  
  console.log('[MARM DEBUG] Final context length:', context.length, 'characters');
  console.log('[MARM DEBUG] Final context preview:', context.substring(0, 300) + '...');
  
  return context;
}
```
**Purpose:** Track session context building process, monitor context size, and debug protocol text issues.
**Note:** Also calls debugProtocolText() and debugMarmKeywords() which were removed from constants.js

#### Session Logging Error (Line 191) - KEEP
```javascript
console.error('MARM: Failed to log session entry:', e); // KEEP - useful for production
```
**Purpose:** Production error logging for session entry failures - KEEP THIS ONE

### notebook.js

**Debug Category:** Notebook Operations & Storage
- Entry addition logs
- Retrieval logs
- Validation logs

### marmLogic.js

**Debug Category:** MARM Protocol Logic
- Protocol activation logs
- Logic flow logs
- Session history logs

### storage.js

**Debug Category:** LocalStorage Operations
- Storage save/load logs
- Multi-tab sync logs
- Storage validation logs

### core.js

**Debug Category:** Main Chat Flow & Message Processing  
**Location:** `webchat/src/chatbot/core.js`

#### Message Processing Debug (Lines 25, 49)
```javascript
console.log('[DEEP DIVE DEBUG] processMessage called with:', userInput);
// ... and later in command detection ...
console.log('[DEEP DIVE DEBUG] Command detected:', userInput);
```
**Purpose:** Track message processing flow and command detection.

#### Error Logs to KEEP (Production)
```javascript
// Line 55 - General processing errors
console.error('Error processing message:', error);

// Lines 101, 111, 123 - API response errors
console.error('[MARM] generateContent returned null/undefined in core.js');
console.error('[MARM] generateContent response missing .text() method in core.js:', typeof replicateResponse);
console.error('[MARM] replicateResponse.text() returned invalid/empty data in core.js:', typeof botAnswer);

// Line 136 - Safety filter warning
console.warn('[MARM] Possible safety filter trigger on attempt', attempt);

// Line 146 - Retry attempt errors
console.error('[MARM] Error in message processing attempt', attempt, ':', error);
```
**Purpose:** Production error and warning logging for message processing failures - KEEP ALL

### chatbot.js

**Debug Category:** UI Initialization & Setup
- Module loading logs
- Event setup logs
- DOM manipulation logs

### commands.js

**Debug Category:** Command Processing & Execution  
**Location:** `webchat/src/chatbot/commands.js`

#### Conversation Import Debug (Line 71)
```javascript
console.log(`[MARM DEBUG] Imported ${conversationHistory.length} messages to session ${sessionId}`);
```
**Purpose:** Track conversation history import when activating MARM mid-session.

#### Command Execution Context Debug (Lines 76-90)
```javascript
async function executeWithContext(sessionId, systemPrompt, userCommand) {
  console.log('[MARM DEBUG] executeWithContext called');
  console.log('[MARM DEBUG] sessionId:', sessionId);
  console.log('[MARM DEBUG] userCommand:', userCommand);
  console.log('[MARM DEBUG] systemPrompt preview:', systemPrompt.substring(0, 100) + '...');
  
  // ... setup code ...
  
  console.log('[MARM DEBUG] Added session history, length:', hist.length);
  console.log('[MARM DEBUG] Total messages for LLM:', messagesForLLM.length);
}
```
**Purpose:** Debug command execution context setup and message preparation.

#### API Response Debug (Lines 93-121)
```javascript
console.log('[MARM DEBUG] Calling generateContent for command...');
// ... after API call ...
console.log('[MARM DEBUG] Response received, type:', typeof response);
console.log('[MARM DEBUG] Response has text method:', typeof response.text === 'function');
console.log('[MARM DEBUG] Calling response.text()...');
console.log('[MARM DEBUG] Result type:', typeof result);
console.log('[MARM DEBUG] Result length:', result?.length || 0);
console.log('[MARM DEBUG] Result preview:', result?.substring(0, 100) + '...');
console.log('[MARM DEBUG] Command execution successful, returning result');
```
**Purpose:** Track API response processing and validate response format.

#### Command Parsing Debug (Lines 136-150)
```javascript
console.log('[MARM DEBUG] handleCommand called with input:', userInput);
console.log('[MARM DEBUG] Parsed command:', command);
console.log('[MARM DEBUG] Command args:', args);
console.log('[MARM DEBUG] Normalized command:', normalizedCommand);
// Deep dive specific logs:
console.log('[DEEP DIVE DEBUG] Full /deep dive command detected:', userInput);
console.log('[DEEP DIVE DEBUG] Calling handleDeepDiveCommand with args:', fullArgs);
```
**Purpose:** Debug command parsing and argument extraction.

#### Deep Dive Command Debug (Lines 331-335)
```javascript
console.log('[DEEP DIVE DEBUG] handleDeepDiveCommand called with args:', args);
console.log('[DEEP DIVE DEBUG] Current MARM state:', currentState.isMarmActive);
console.log('[DEEP DIVE DEBUG] MARM not active, returning error');
```
**Purpose:** Debug deep dive command execution and MARM state validation.

#### Error Logs to KEEP (Production)
```javascript
// Lines 97, 105, 117, 125, 129 - API errors
console.error('[MARM DEBUG] generateContent returned null/undefined in commands.js');
console.error('[MARM DEBUG] generateContent response missing .text() method in commands.js:', typeof response);
console.error('[MARM DEBUG] response.text() returned invalid data in commands.js:', typeof result);
console.error('[MARM DEBUG] Commands execution error:', error.name, error.message);
console.error('[MARM DEBUG] Unexpected error in executeWithContext:', error);

// Lines 213, 219, 227, 235 - Start command errors  
console.error('[MARM] generateContent returned null/undefined in start command');
console.error('[MARM] generateContent response missing .text() method in start command:', typeof replicateResponse);
console.error('[MARM] replicateResponse.text() returned invalid data in start command:', typeof botResponse);
console.error('[MARM] Start command error:', error);

// Lines 358, 364, 372 - Show command errors
console.error('[MARM] generateContent returned null/undefined in show command');
console.error('[MARM] generateContent response missing .text() method in show command:', typeof replicateResponse);
console.error('[MARM] replicateResponse.text() returned invalid data in show command:', typeof botAnswer);
```
**Purpose:** Production error logging for API failures and command execution errors - KEEP ALL ERROR LOGS

### ui.js

**Debug Category:** UI Operations & Interactions
- DOM manipulation logs
- Event handling logs
- Animation logs

### server.js

**Debug Category:** Server Operations & Replicate API Integration  
**Location:** `webchat/src/chatbot/server.js`

#### API Request Debug (Lines 44-50)
```javascript
console.log('[MARM DEBUG] Received POST /api/replicate');
console.log('[MARM DEBUG] Request body prompt length:', req.body?.prompt?.length || 0);
console.log('[MARM DEBUG] Sending request to Replicate API...');
```
**Purpose:** Track incoming API requests and request body validation.

#### API Response Debug (Lines 70-79)
```javascript
console.log('[MARM DEBUG] Response received - Status:', response.status, 'OK:', response.ok);
console.log('[MARM DEBUG] Response text length:', text?.length || 0, 'characters');
console.log('[MARM DEBUG] Successfully parsed JSON, checking status');
console.log('[MARM DEBUG] Response status:', data.status, 'ID:', data.id);
```
**Purpose:** Track Replicate API response processing and validation.

#### Polling System Debug (Lines 82-117)
```javascript
console.log('[MARM DEBUG] Prediction still', data.status, '- polling until completion...');
console.log('[MARM DEBUG] Poll result:', pollData.status, pollData.id);
console.log('[MARM DEBUG] Prediction completed successfully!');
console.log('[MARM DEBUG] Prediction failed or canceled:', pollData.error);
console.log('[MARM DEBUG] Polling timeout reached');
```
**Purpose:** Debug the prediction polling system for async Replicate responses.

#### Server Startup Log (Line 141) - KEEP
```javascript
console.log(`MARM Webchat server running on port ${PORT}`); // KEEP - useful server info
```
**Purpose:** Server startup confirmation - KEEP THIS ONE

#### Error Logs to KEEP (Production)
```javascript
// Line 28 - Environment setup error
console.error('Error: REPLICATE_API_TOKEN environment variable not set.');

// Lines 112, 124, 128 - API and parsing errors  
console.error('[MARM DEBUG] Failed to poll prediction:', pollResponse.status);
console.error('[MARM DEBUG] Failed to parse Replicate API response as JSON:', e.message);
console.error('[MARM DEBUG] Replicate proxy error:', error.name, error.message);

// Line 135 - Unhandled errors
console.error('Unhandled error:', err);
```
**Purpose:** Production error logging for server and API failures - KEEP ALL ERROR LOGS

### voice.js

**Debug Category:** Voice Synthesis & Speech Processing  
**Location:** `webchat/src/chatbot/voice.js`

#### Speech Cancellation Debug (Line 67)
```javascript
console.log('[VOICE DEBUG] Cancelling existing speech');
```
**Purpose:** Track speech interruption and cancellation.

#### Text Processing Debug (Lines 87-95)
```javascript
console.log('[VOICE DEBUG] Original text length:', text.length);
console.log('[VOICE DEBUG] Clean text length:', cleanText.length);
console.log('[VOICE DEBUG] Clean text preview:', cleanText.substring(0, 100) + '...');
console.log('[VOICE DEBUG] Text too long, truncating from', cleanText.length, 'to', MAX_SPEECH_LENGTH);
```
**Purpose:** Debug text cleaning and truncation for speech synthesis.

#### Speech Synthesis Debug (Lines 108-124)
```javascript
console.log('[VOICE DEBUG] Creating utterance with final text length:', cleanText.length);
console.log('[VOICE DEBUG] Speech started successfully');
console.log('[VOICE DEBUG] Speech ended successfully');
```
**Purpose:** Track speech synthesis creation and lifecycle events.

#### Speech API Debug (Lines 149-156)
```javascript
console.log('[VOICE DEBUG] About to call speechSynthesis.speak()');
console.log('[VOICE DEBUG] speechSynthesis.speaking:', speechSynthesis.speaking);
console.log('[VOICE DEBUG] speechSynthesis.pending:', speechSynthesis.pending);
console.log('[VOICE DEBUG] Available voices:', speechSynthesis.getVoices().length);
console.log('[VOICE DEBUG] speechSynthesis.speak() called');
```
**Purpose:** Debug browser speech synthesis API state and voice availability.

#### Error/Warning Logs to KEEP (Production)
```javascript
// Line 21 - Voice loading warning
console.warn('Could not load voices:', e);

// Line 120 - Speech synthesis errors
console.error('[VOICE DEBUG] Speech error:', event.error, event);

// Line 168 - Template warning
console.warn('Voice settings template not found in HTML');

// Line 263 - Speech unavailable error
console.error("Speech synthesis unavailable");
```
**Purpose:** Production error and warning logging for voice feature failures - KEEP ALL

---

### replicateHelper.js

**Debug Category:** Replicate API Integration & Message Processing  
**Location:** `webchat/src/replicateHelper.js`

#### Connection Debug (Line 9)
```javascript
console.log('[MARM DEBUG] Connection warming skipped (using backend proxy)');
```
**Purpose:** Track connection warming behavior.

#### Message Processing Debug (Lines 65-80)
```javascript
console.log('[MARM DEBUG] generateContent called with messages:', messages.length, 'messages');
console.log('[MARM DEBUG] First message preview:', messages[0]?.content?.substring(0, 100) + '...');
console.log('[MARM DEBUG] Converted to prompt format, length:', prompt.length, 'characters');
```
**Purpose:** Debug message array to prompt conversion.

#### Request Attempt Debug (Lines 87-98)
```javascript
console.log(`[MARM DEBUG] Starting attempt ${attempt}/${maxAttempts}`);
console.log('[MARM DEBUG] Request timeout triggered');
console.log('[MARM DEBUG] Sending request to backend proxy...');
console.log('[MARM DEBUG] Request body size:', JSON.stringify(requestBody).length, 'characters');
```
**Purpose:** Track retry attempts and request body preparation.

#### Response Processing Debug (Lines 113-173)
```javascript
console.log(`[MARM DEBUG] Response received - Status: ${res.status}, OK: ${res.ok}`);
console.log('[MARM DEBUG] Response text length:', text?.length || 0, 'characters');
console.log('[MARM DEBUG] Response preview:', text?.substring(0, 200) + '...');
console.log('[MARM DEBUG] Successfully parsed JSON response');
console.log('[MARM DEBUG] Response data structure:', { /* data info */ });
console.log(`[MARM DEBUG] Prediction ${data.id} still ${data.status}, polling again (attempt ${attempt})`);
```
**Purpose:** Debug API response processing and polling logic.

#### Final Response Debug (Lines 185-195)
```javascript
console.log('[MARM DEBUG] Reply text length:', reply?.length || 0, 'characters');
console.log('[MARM DEBUG] Reply preview:', reply?.substring(0, 100) + '...');
console.log('[MARM DEBUG] Successful response, returning reply');
```
**Purpose:** Debug final response text extraction and validation.

#### Production Logs to KEEP
```javascript
// Line 175 - API Success Status (ADDED)
console.log('[MARM] API request successful');

// Lines 117, 143, 153, 189, 201 - API and parsing errors
console.error(`[MARM DEBUG] Replicate API Error (Attempt ${attempt}):`, res.status, errText);
console.error('[MARM DEBUG] Empty response from Replicate API');
console.error('[MARM DEBUG] Failed to parse Replicate API response as JSON:', text);
console.error('[MARM DEBUG] Empty reply text:', reply);
console.error(`[MARM DEBUG] Request error (Attempt ${attempt}):`, error.name, error.message);
```
**Purpose:** API status visibility (success/failure) and detailed error logging - KEEP ALL

---

## Notes

- **Keep essential logs:** Errors, warnings, critical state changes
- **Archive detailed logs:** Flow tracking, success confirmations, debug counters
- **Preserve context:** Include line numbers and function names where logs were removed
- **Document purpose:** Why each log was helpful for debugging specific issues

Last Updated: [Date when logs are moved]