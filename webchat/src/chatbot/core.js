// core.js - Main orchestration and state management for MARM chatbot

import {
  activateMarmSession,
  getSessionContext,
  updateSessionHistory,
  setSessionReasoning,
  searchDocs,
  shouldAutoSearch,
  trimForContext,
  manageUserNotebook
} from '../logic/marmLogic.js';

import { generateContent } from '../replicateHelper.js';
import { appendMessage, showLoadingIndicator, hideLoadingIndicator } from './ui.js';
import { handleCommand } from './commands.js';
import { getState, updateState } from './state.js';

// ===== RATE LIMITING =====
let lastMessageTime = 0;
const MESSAGE_COOLDOWN = 1000; 

// ===== MAIN INPUT HANDLER =====
export async function handleUserInput(userInput) {
  if (typeof userInput !== 'string' || userInput.length === 0) return;
  if (userInput.length > 15000) {
    appendMessage('bot', 'Input too long. Please limit to 15000 characters.');
    return;
  }
  
  const now = Date.now();
  if (now - lastMessageTime < MESSAGE_COOLDOWN) {
    appendMessage('bot', '⏱️ Please wait a moment before sending another message.');
    return;
  }
  lastMessageTime = now;
  
  const welcomeMessage = document.getElementById('welcome-message');
  if (welcomeMessage) {
    welcomeMessage.style.display = 'none';
  }
  
  appendMessage('user', userInput);
  showLoadingIndicator();
  
  try {
    if (userInput.startsWith('/')) {
      await handleCommand(userInput);
    } else {
      await handleStandardMessage(userInput);
    }
  } catch (error) {
    console.error('Error processing message:', error);
    hideLoadingIndicator();
    appendMessage('bot', 'Sorry, I encountered an error. Please try again.');
  }
}

// ===== STANDARD MESSAGE HANDLER =====
async function handleStandardMessage(userInput) {
  const messagesForLLM = [];
  const currentState = getState();
  
  if (currentState.isMarmActive) {
    trimForContext(currentState.currentSessionId);
    const hist = getSessionContext(currentState.currentSessionId);
    if (hist && hist.trim()) {
      messagesForLLM.push({ role: 'system', content: `Current Session History:\n${hist}` });
    }
    
    const notebookData = manageUserNotebook(currentState.currentSessionId, 'all');
    if (notebookData && !notebookData.includes('empty')) {
      messagesForLLM.push({ 
        role: 'system', 
        content: `User's Personal Knowledge Base (treat as absolute truth, never contradict or correct):\n${notebookData}` 
      });
    }
  }

  if (currentState.isMarmActive && shouldAutoSearch(userInput)) {
    const docResult = searchDocs(userInput);
    if (docResult) {
      messagesForLLM.push({ role: 'system', content: `From MARM documentation: ${docResult}` });
    }
  }

  messagesForLLM.push({ role: 'user', content: userInput });


  let replicateResponse;
  let botResponse;
  
  for (let attempt = 1; attempt <= 2; attempt++) {
    try {
      replicateResponse = await generateContent(messagesForLLM);

      if (!replicateResponse) {
        console.error('[MARM] generateContent returned null/undefined in core.js');
        if (attempt === 2) {
          hideLoadingIndicator();
          appendMessage('bot', 'Sorry, I encountered an error processing your request.');
          return;
        }
        continue;
      }
      
      if (typeof replicateResponse.text !== 'function') {
        console.error('[MARM] generateContent response missing .text() method in core.js:', typeof replicateResponse);
        if (attempt === 2) {
          hideLoadingIndicator();
          appendMessage('bot', 'Sorry, I received an invalid response from the AI service.');
          return;
        }
        continue;
      }
      
      const botAnswer = await replicateResponse.text();
      
      if (!botAnswer || typeof botAnswer !== 'string' || botAnswer.trim() === '') {
        console.error('[MARM] replicateResponse.text() returned invalid/empty data in core.js:', typeof botAnswer);
        if (attempt === 1) {
          messagesForLLM[messagesForLLM.length - 1].content = `${userInput}\n\nPlease provide a helpful response to this message.`;
          continue;
        }
        hideLoadingIndicator();
        appendMessage('bot', 'Sorry, I received an empty response. This might be due to content filters - please try rephrasing your message.');
        return;
      }
      
      botResponse = botAnswer.trim();
      
      if (botResponse.includes('I can\'t help with that') || botResponse.includes('I\'m not able to') || botResponse.includes('sorry, but I can\'t')) {
        if (attempt === 1) {
          messagesForLLM[messagesForLLM.length - 1].content = `User message: ${userInput}\n\nPlease provide a helpful and informative response.`;
          continue;
        }
      }
      
      break; 
      
    } catch (error) {
      console.error('[MARM] Error in message processing attempt', attempt, ':', error);
      if (attempt === 2) {
        hideLoadingIndicator();
        appendMessage('bot', 'Sorry, I encountered an error processing your request.');
        return;
      }
    }
  }

  if (currentState.isMarmActive) {
    setSessionReasoning(currentState.currentSessionId, '');
  }
  
  hideLoadingIndicator();
  appendMessage('bot', botResponse);
  
  if (currentState.isMarmActive && currentState.currentSessionId) {
    updateSessionHistory(currentState.currentSessionId, userInput, botResponse);
  }
} 
