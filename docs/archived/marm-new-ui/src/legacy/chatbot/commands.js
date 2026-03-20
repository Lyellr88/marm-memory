// commands.js - Command handling and specific command logic for MARM chatbot //

import {
  activateMarmSession,
  logSession,
  compileSessionSummary,
  manageUserNotebook,
  getSessionContext,
  updateSessionHistory,
  getMostRecentBotResponseLogic,
  setSessionReasoning,
  trimForContext,
  showSessionEntries,
  deleteLogEntry
} from '../logic/marmLogic.js';

import { generateContent } from '../replicateHelper.js';
import { appendMessage, hideLoadingIndicator } from './ui.js';
import { getState, updateState } from './state.js';

// ===== Helper Functions =====
function commandResponse(message) {
  hideLoadingIndicator();
  appendMessage('bot', message);
}

function importCurrentConversationToMarm(sessionId) {
  const chatLog = document.getElementById('chat-log');
  if (!chatLog) return;
  
  const messages = chatLog.querySelectorAll('.message');
  const conversationHistory = [];
  
  messages.forEach(messageDiv => {
    const isUser = messageDiv.classList.contains('user-message');
    const isBot = messageDiv.classList.contains('bot-message');
    
    if (isUser || isBot) {
      const contentDiv = messageDiv.querySelector('.message-content');
      if (contentDiv) {
        const role = isUser ? 'user' : 'bot';
        const content = contentDiv.textContent || contentDiv.innerText || '';
        
        if (!content.includes('MARM activated') && 
            !content.includes('MARM Protocol') && 
            content.trim()) {
          conversationHistory.push({ role, content: content.trim() });
        }
      }
    }
  });
  
  if (conversationHistory.length > 0) {
    let i = 0;
    while (i < conversationHistory.length) {
      const currentMsg = conversationHistory[i];
      
      if (currentMsg.role === 'user') {
        const nextMsg = i + 1 < conversationHistory.length ? conversationHistory[i + 1] : null;
        const botResponse = (nextMsg && nextMsg.role === 'bot') ? nextMsg.content : '[No response recorded]';
        
        updateSessionHistory(sessionId, currentMsg.content, botResponse);
        i += (nextMsg && nextMsg.role === 'bot') ? 2 : 1; 
      } else {
        updateSessionHistory(sessionId, '[System interaction]', currentMsg.content);
        i++;
      }
    }
  }
}

async function executeWithContext(sessionId, systemPrompt, userCommand) {
  
  const messagesForLLM = [];
  const hist = getSessionContext(sessionId);
  if (hist?.trim()) {
    messagesForLLM.push({ role: 'system', content: `Current Session History:\n${hist}` });
  }
  messagesForLLM.push({ role: 'system', content: systemPrompt });
  messagesForLLM.push({ role: 'user', content: userCommand });
  
  
  try {
    const response = await generateContent(messagesForLLM);
    
    if (!response) {
      console.error('[MARM DEBUG] generateContent returned null/undefined in commands.js');
      throw new Error('❌ Command execution failed (No response from AI service).');
    }
    
    
    if (typeof response.text !== 'function') {
      console.error('[MARM DEBUG] generateContent response missing .text() method in commands.js:', typeof response);
      throw new Error('❌ Command execution failed (Invalid response format).');
    }
    
    const result = await response.text();
    
    
    if (!result || typeof result !== 'string') {
      console.error('[MARM DEBUG] response.text() returned invalid data in commands.js:', typeof result);
      throw new Error('❌ Command execution failed (Empty response).');
    }
    
    return result;
    
  } catch (error) {
    console.error('[MARM DEBUG] Commands execution error:', error.name, error.message);
    if (error.message.startsWith('❌')) {
      throw error;
    }
    console.error('[MARM DEBUG] Unexpected error in executeWithContext:', error);
    throw new Error('❌ Command execution failed. Please try again.');
  }
}

// ===== Main Command Handler =====
export async function handleCommand(userInput) {
  const [command, ...rest] = userInput.split(' ');
  const args = rest.join(' ').trim();
  
  
  const normalizedCommand = command.replace(/[:]*$/, '');
  
  if (userInput.startsWith('/deep dive')) {
    const fullArgs = userInput.replace('/deep dive', '').trim();
    await handleDeepDiveCommand(fullArgs);
    return;
  }
  
  switch (normalizedCommand) {
    case '/start':
      await handleStartCommand(args);
      break;
    case '/refresh':
      await handleRefreshCommand(args);
      break;
    case '/log':
      await handleLogCommand(args);
      break;
    case '/deep': {
      const deepDiveMatch = args.match(/^dive\s*:?\s*(.*)$/i);
      if (deepDiveMatch) {
        await handleDeepDiveCommand(deepDiveMatch[1].trim());
      } else {
        await handleDeepDiveCommand(args);
      }
      break;
    }
    case '/show':
      await handleShowCommand(args);
      break;
    case '/summary':
      await handleSummaryCommand(args);
      break;
    case '/notebook':
      await handleNotebookCommand(args);
      break;
    default:
      commandResponse('Unknown command. Use /start marm to begin.');
  }
}

// --- Start Command ---
async function handleStartCommand(args) {
  if (args === 'marm') {
    const currentState = getState();
    const sessionId = currentState.currentSessionId || Date.now().toString(36);
    const newState = updateState({
      isMarmActive: true,
      currentSessionId: sessionId
    });
    await activateMarmSession(newState.currentSessionId);
    
    importCurrentConversationToMarm(newState.currentSessionId);
    
    const messagesForLLM = [];
    messagesForLLM.push({ 
      role: 'system', 
      content: 'You are MARM Bot. The user just activated Memory Accurate Response Mode v1.4 (MARM) Acknowledge activation with: 1) Confirm "MARM activated. Ready to log context." 2) Brief 2-line explanation of what MARM is and why useful.' 
    });
    messagesForLLM.push({ role: 'user', content: '/start marm' });
    
    try {
      const replicateResponse = await generateContent(messagesForLLM);
      
      if (!replicateResponse) {
        console.error('[MARM] generateContent returned null/undefined in start command');
        commandResponse( '❌ Failed to activate MARM (No response from AI service).');
        return;
      }
      
      if (typeof replicateResponse.text !== 'function') {
        console.error('[MARM] generateContent response missing .text() method in start command:', typeof replicateResponse);
        commandResponse( '❌ Failed to activate MARM (Invalid response format).');
        return;
      }
      
      const botResponse = await replicateResponse.text();
      
      if (!botResponse || typeof botResponse !== 'string') {
        console.error('[MARM] replicateResponse.text() returned invalid data in start command:', typeof botResponse);
        commandResponse( '❌ Failed to activate MARM (Empty response).');
        return;
      }
      
      updateSessionHistory(newState.currentSessionId, '/start marm', botResponse);
      commandResponse( botResponse);
    } catch (error) {
      console.error('[MARM] Start command error:', error);
      commandResponse( '❌ Failed to activate MARM. Please try again.');
      return;
    }
  } else {
    commandResponse('Usage: /start marm');
  }
}

// --- Refresh Command ---
async function handleRefreshCommand(args) {
  const currentState = getState();
  if (args === 'marm' && currentState.isMarmActive) {
    trimForContext(currentState.currentSessionId);
    
    try {
      const botResponse = await executeWithContext(
        currentState.currentSessionId,
        'The user just refreshed MARM. Acknowledge that session state has been updated and protocol reaffirmed. Keep response brief.',
        '/refresh marm'
      );
      
      updateSessionHistory(currentState.currentSessionId, '/refresh marm', botResponse);
      commandResponse( botResponse);
    } catch (error) {
      commandResponse( error.message);
      return;
    }
  } else {
    const botResponse = currentState.isMarmActive ? 'Usage: /refresh marm' : 'MARM not active. Use /start marm first.';
    commandResponse( botResponse);
  }
}

// --- Log Command ---
async function handleLogCommand(args) {
  const currentState = getState();
  if (!currentState.isMarmActive) {
    commandResponse( 'MARM not active. Use /start marm first.');
    return;
  }
  
  if (!args) {
    commandResponse( 'Usage: /log session:Name or /log entry: [Date-Summary-Result]');
    return;
  }
  
  const sessionMatch = args.match(/^session\s*:?\s*(.*)$/i);
  if (sessionMatch) {
    const sessionName = sessionMatch[1].trim();
    if (sessionName) {
      const newState = updateState({ currentSessionId: sessionName });
      try {
        const botResponse = await executeWithContext(
          newState.currentSessionId,
          `The user just named this session "${sessionName}". Acknowledge this briefly and suggest what they might log next.`,
          `/log session:${sessionName}`
        );
        updateSessionHistory(newState.currentSessionId, `/log session:${sessionName}`, botResponse);
        commandResponse( botResponse);
      } catch (error) {
        commandResponse( error.message);
        return;
      }
    } else {
      commandResponse( 'Usage: /log session:Name');
    }
    return;
  }
  const entryMatch = args.match(/^entry\s*:?\s*(.*)$/i);
  if (entryMatch) {
    const entryData = entryMatch[1].trim();
    if (entryData) {
      logSession(currentState.currentSessionId, entryData);
      try {
        const botResponse = await executeWithContext(
          currentState.currentSessionId,
          `The user just logged: "${entryData}". Acknowledge this log entry: briefly and show you understand its context.`,
          `/log entry: ${entryData}`
        );
        updateSessionHistory(currentState.currentSessionId, `/log entry: ${entryData}`, botResponse);
        commandResponse( botResponse);
      } catch (error) {
        commandResponse( error.message);
        return;
      }
    } else {
      commandResponse( 'Usage: /log entry: [Date-Summary-Result]');
    }
    return;
  }

  const showMatch = args.match(/^show\s*:?\s*(.*)$/i);
  if (showMatch) {
    const sessionName = showMatch[1].trim() || null;
    const result = showSessionEntries(currentState.currentSessionId, sessionName);
    commandResponse(result);
    return;
  }

  const deleteMatch = args.match(/^delete\s*:?\s*(.*)$/i);
  if (deleteMatch) {
    const target = deleteMatch[1].trim();
    if (target) {
      const result = deleteLogEntry(currentState.currentSessionId, target);
      commandResponse(result);
    } else {
      commandResponse('Usage: /log delete: [session/entry name]');
    }
    return;
  }

  commandResponse( 'Usage: /log session:Name or /log entry: [Date-Summary-Result] or /log show: [session] or /log delete: [session/entry]');
}

// --- Deep Dive Command ---
async function handleDeepDiveCommand(args) {
  const currentState = getState();
  if (!currentState.isMarmActive) {
    commandResponse( 'MARM not active. Use /start marm first.');
    return;
  }

  const messagesForLLM = [];
  
  const hist = getSessionContext(currentState.currentSessionId);
  if (hist && hist.trim()) {
    messagesForLLM.push({ role: 'system', content: `Current Session History:\n${hist}` });
  }
  
  messagesForLLM.push({
    role: 'system',
    content: 'Provide your response. Then, on a new line, add a "REASONING:" section explaining your logic.'
  });
  
  messagesForLLM.push({ role: 'user', content: args || 'Please provide a deep dive response' });
  
  try {
    const replicateResponse = await generateContent(messagesForLLM);
    
    if (!replicateResponse) {
      console.error('[MARM] generateContent returned null/undefined in show command');
      commandResponse( '❌ Failed to generate response (No response from AI service).');
      return;
    }
    
    if (typeof replicateResponse.text !== 'function') {
      console.error('[MARM] generateContent response missing .text() method in show command:', typeof replicateResponse);
      commandResponse( '❌ Failed to generate response (Invalid response format).');
      return;
    }
    
    const botAnswer = await replicateResponse.text();
    
    if (!botAnswer || typeof botAnswer !== 'string') {
      console.error('[MARM] replicateResponse.text() returned invalid data in show command:', typeof botAnswer);
      commandResponse( '❌ Failed to generate response (Empty response).');
      return;
    }
    
    const reasoningMatch = botAnswer.match(/REASONING:\s*(.*)/is);
    
    let botResponse;
    if (reasoningMatch) {
      botResponse = botAnswer.substring(0, reasoningMatch.index).trim();
      setSessionReasoning(currentState.currentSessionId, reasoningMatch[1].trim());
    } else {
      botResponse = botAnswer;
      setSessionReasoning(currentState.currentSessionId, 'Contextual response provided, but no explicit reasoning section found.');
    }
    
    commandResponse( botResponse);
  } catch (error) {
    commandResponse( '❌ Failed to generate deep dive response. Please try again.');
    return;
  }
}

// --- Show Command ---
async function handleShowCommand(args) {
  const currentState = getState();
  if (args === 'reasoning' && currentState.isMarmActive) {
    const reasoning = getMostRecentBotResponseLogic(currentState.currentSessionId);
    const botResponse = reasoning 
      ? reasoning 
      : 'No reasoning trail available. Use **/deep dive** first to generate a response with reasoning, then use **/show reasoning** to see the logic behind it.';
    commandResponse( botResponse);
  } else {
    commandResponse( 'Use **/show reasoning** to see the logic behind the most recent response. Note: You must use **/deep dive** first to generate reasoning.');
  }
}

// --- Summary Command ---
async function handleSummaryCommand(args) {
  const currentState = getState();
  if (!currentState.isMarmActive) {
    commandResponse( 'MARM not active. Use /start marm first.');
    return;
  }
  
  const summaryArgs = args.split('--');
  const sessionName = summaryArgs[0].trim() || currentState.currentSessionId;
  const hasSummary = args.includes('--summary');
  const fieldsMatch = args.match(/--fields=([^\s]+)/);
  
  let botResponse;
  if (fieldsMatch) {
    const fields = fieldsMatch[1].split(',').map(f => f.trim());
    botResponse = await compileSessionSummary(sessionName, { fields });
  } else {
    botResponse = await compileSessionSummary(sessionName);
  }
  
  if (hasSummary) {
    botResponse = `Summary for ${sessionName}:\n${botResponse}`;
  }
  
  commandResponse( botResponse);
}

// --- Notebook Command ---
async function handleNotebookCommand(args) {
  const currentState = getState();
  if (!currentState.isMarmActive) {
    commandResponse( 'MARM not active. Use /start marm first.');
    return;
  }
  
  const addMatch = args.match(/^add\s*:?\s*(.*)$/i);
  if (addMatch) {
    const keyData = addMatch[1];
    const spaceIndex = keyData.indexOf(' ');
    if (spaceIndex > 0) {
      const key = keyData.substring(0, spaceIndex).trim();
      const value = keyData.substring(spaceIndex + 1).trim();
      manageUserNotebook(currentState.currentSessionId, 'add', key, value);
      const notebookData = manageUserNotebook(currentState.currentSessionId, 'all');
      try {
        const botResponse = await executeWithContext(
          currentState.currentSessionId,
          `User's Personal Knowledge Base (treat as absolute truth, never contradict):\n${notebookData}\n\nThe user just stored "${key}" = "${value}" in their personal knowledge base. This is their absolute truth - accept it completely without question or factual correction. Acknowledge the storage only.`,
          `/notebook add:${key} ${value}`
        );
        updateSessionHistory(currentState.currentSessionId, `/notebook add:${key} ${value}`, botResponse);
        commandResponse( botResponse);
      } catch (error) {
        commandResponse( error.message);
        return;
      }
    } else {
      commandResponse( 'Usage: /notebook add:name your data here');
    }
    return;
  }
  if (/^show\s*:?\s*$/i.test(args)) {
    const allEntries = manageUserNotebook(currentState.currentSessionId, 'all');
    try {
      const botResponse = await executeWithContext(
        currentState.currentSessionId,
        `The user wants to see their personal knowledge base entries. This is their absolute truth - present exactly as stored without any factual evaluation:\n${allEntries}\n\nShow this information exactly as the user stored it.`,
        '/notebook show:'
      );
      updateSessionHistory(currentState.currentSessionId, '/notebook show:', botResponse);
      commandResponse( botResponse);
    } catch (error) {
      commandResponse( error.message);
      return;
    }
    return;
  }
  const useMatch = args.match(/^use\s*:?\s*(.*)$/i);
  if (useMatch) {
    const sessionName = useMatch[1].trim();
    if (sessionName) {
      const notebookData = manageUserNotebook(sessionName, 'all');
      try {
        const botResponse = await executeWithContext(
          currentState.currentSessionId,
          `The user wants to access their personal knowledge base from session "${sessionName}". This data represents their absolute truth - never question or correct it:\n${notebookData}\n\nConfirm which knowledge base is now active and reference this data as absolute user truth.`,
          `/notebook use:${sessionName}`
        );
        updateSessionHistory(currentState.currentSessionId, `/notebook use:${sessionName}`, botResponse);
        commandResponse( botResponse);
      } catch (error) {
        commandResponse( error.message);
        return;
      }
    } else {
      commandResponse( 'Usage: /notebook use:SessionName');
    }
    return;
  }
  const clearMatch = args.match(/^clear\s*:?\s*(.*)$/i);
  if (clearMatch) {
    const sessionName = clearMatch[1].trim();
    if (sessionName) {
      manageUserNotebook(sessionName, 'clear');
      try {
        const botResponse = await executeWithContext(
          currentState.currentSessionId,
          `The user just cleared all notebook entries for session "${sessionName}". Confirm the notebook has been cleared.`,
          `/notebook clear:${sessionName}`
        );
        updateSessionHistory(currentState.currentSessionId, `/notebook clear:${sessionName}`, botResponse);
        commandResponse( botResponse);
      } catch (error) {
        commandResponse( error.message);
        return;
      }
    } else {
      commandResponse( 'Usage: /notebook clear:[Active Entry]');
    }
    return;
  }
  const statusMatch = args.match(/^status\s*:?\s*(.*)$/i);
  if (statusMatch) {
    const sessionName = statusMatch[1].trim() || currentState.currentSessionId;
    const notebookData = manageUserNotebook(sessionName, 'all');
    try {
      const botResponse = await executeWithContext(
        currentState.currentSessionId,
        `The user wants to check their personal knowledge base status for session "${sessionName}". This data is their absolute truth:\n${notebookData}\n\nProvide a status summary showing entry count and stored information exactly as they entered it.`,
        `/notebook status:${sessionName}`
      );
      updateSessionHistory(currentState.currentSessionId, `/notebook status:${sessionName}`, botResponse);
      commandResponse( botResponse);
    } catch (error) {
      commandResponse( error.message);
      return;
    }
    return;
  }

  const deleteMatch = args.match(/^delete\s*:?\s*(.*)$/i);
  if (deleteMatch) {
    const entryName = deleteMatch[1].trim();
    if (entryName) {
      const result = manageUserNotebook(currentState.currentSessionId, 'delete', entryName);
      commandResponse(result);
    } else {
      commandResponse('Usage: /notebook delete: [name]');
    }
    return;
  }

  commandResponse( 'Usage: /notebook add:name data | /notebook use:SessionName | /notebook show: | /notebook clear:SessionName | /notebook delete:name | /notebook status:SessionName');
} 
