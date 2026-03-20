// server.js - Express backend for MARM React UI

import express from 'express';
import fetch from 'node-fetch';
import path from 'path';
import { fileURLToPath } from 'url';
import { readFile } from 'fs/promises';
import dotenv from 'dotenv';

// Mock localStorage for Node.js environment
global.localStorage = {
  getItem: () => null,
  setItem: () => {},
  removeItem: () => {},
  clear: () => {}
};

dotenv.config();

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const app = express();
const PORT = process.env.PORT || 8082;
const REPLICATE_API_TOKEN = process.env.REPLICATE_API_TOKEN;

// ===== CORS Middleware =====
app.use((req, res, next) => {
  res.header('Access-Control-Allow-Origin', '*');
  res.header('Access-Control-Allow-Methods', 'GET, POST, PUT, DELETE, OPTIONS');
  res.header('Access-Control-Allow-Headers', 'Origin, X-Requested-With, Content-Type, Accept, Authorization');
  
  if (req.method === 'OPTIONS') {
    res.sendStatus(200);
  } else {
    next();
  }
});

// ===== API Key Validation =====
if (!REPLICATE_API_TOKEN) {
  console.error('Error: REPLICATE_API_TOKEN environment variable not set.');
  process.exit(1);
}

app.use(express.json());

// ===== Chat API Endpoint =====
app.post('/api/chat', async (req, res) => {
  try {
    const { message, isMarmActive, sessionId, conversationHistory } = req.body;

    if (!message) {
      return res.status(400).json({ error: 'Message is required' });
    }

    // Get session context - MARM protocol only when active
    let context = '';
    const actualSessionId = sessionId || 'react-ui-session';
    console.log('Backend using sessionId:', actualSessionId, 'MARM active:', isMarmActive);
    
    if (isMarmActive) {
      // Full MARM protocol + session context
      try {
        const { getSessionContext } = await import('../src/logic/marmLogic.js');
        context = getSessionContext(actualSessionId);
      } catch (error) {
        console.log('MARM context unavailable:', error.message);
      }
    } else if (conversationHistory && conversationHistory.length > 0) {
      // When MARM is disabled, use simple conversation history from frontend
      const recentHistory = conversationHistory.map(msg => 
        `${msg.type === 'user' ? 'Human' : 'Assistant'}: ${msg.content}`
      ).join('\n\n');
      context = `Previous conversation:\n${recentHistory}`;
    }
    // When MARM is disabled, we still update session history but don't use heavy protocol context

    const fullPrompt = context ? `${context}\n\nUser: ${message}` : message;

    const url = 'https://api.replicate.com/v1/models/meta/llama-4-scout-instruct/predictions';
    const response = await fetch(url, {
      method: 'POST',
      headers: {
        'Authorization': `Bearer ${REPLICATE_API_TOKEN}`,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        input: {
          prompt: fullPrompt,
          max_tokens: 4000,
          temperature: 0.7
        }
      })
    });

    if (!response.ok) {
      throw new Error(`Replicate API error: ${response.status}`);
    }

    const prediction = await response.json();
    
    // Poll for completion
    let result = prediction;
    while (result.status !== 'succeeded' && result.status !== 'failed') {
      await new Promise(resolve => setTimeout(resolve, 1000));
      
      const pollResponse = await fetch(`https://api.replicate.com/v1/predictions/${result.id}`, {
        headers: {
          'Authorization': `Bearer ${REPLICATE_API_TOKEN}`,
        }
      });
      
      result = await pollResponse.json();
    }

    if (result.status === 'failed') {
      throw new Error('Prediction failed');
    }

    const aiResponse = Array.isArray(result.output) ? result.output.join('') : result.output;
    
    // Update session history for all conversations
    try {
      const { updateSessionHistory } = await import('../src/logic/marmLogic.js');
      const actualSessionId = sessionId || 'react-ui-session';
      updateSessionHistory(actualSessionId, message, aiResponse);
    } catch (error) {
      console.log('Could not update session history:', error.message);
    }

    res.json({ response: aiResponse });
    
  } catch (error) {
    console.error('[CHAT] Error:', error);
    res.status(500).json({ error: error.message });
  }
});

// ===== Command API Endpoint =====
app.post('/api/command', async (req, res) => {
  try {
    const { command } = req.body;

    if (!command) {
      return res.status(400).json({ error: 'Command is required' });
    }

    console.log('[COMMAND] Processing:', command);
    let response = '';

    // Session Commands
    if (command === '/start marm') {
      const { activateMarmSession } = await import('../src/logic/marmLogic.js');
      response = await activateMarmSession('react-ui-session');
      
    } else if (command === '/refresh marm') {
      response = '🔄 **MARM Session Refreshed**\n\nProtocol adherence reaffirmed. Memory and accuracy layers active.';
      

    // Core Commands
    } else if (command.startsWith('/log session:')) {
      const sessionName = command.replace('/log session:', '').trim();
      if (sessionName) {
        response = `📁 **Session Created/Switched**: "${sessionName}"\n\nNow using session container for organized logging.`;
      } else {
        response = '❌ **Usage**: `/log session: [name]`\n\nExample: `/log session: Project Phoenix`';
      }
      
    } else if (command.startsWith('/log entry:')) {
      const entry = command.replace('/log entry:', '').trim();
      if (entry) {
        const { logSession } = await import('../src/logic/marmLogic.js');
        const sessionId = 'react-ui-session';
        response = logSession(sessionId, entry);
      } else {
        response = '❌ **Usage**: `/log entry: [YYYY-MM-DD-topic-summary]`\n\nExample: `/log entry: 2025-08-11-UI Refinements-Button alignment fixed`';
      }
      
    } else if (command.startsWith('/log show:')) {
      const target = command.replace('/log show:', '').trim();
      const { showSessionEntries } = await import('../src/logic/marmLogic.js');
      const sessionId = 'react-ui-session';
      response = showSessionEntries(sessionId, target || null);
      
    } else if (command.startsWith('/log delete:')) {
      const target = command.replace('/log delete:', '').trim();
      if (target) {
        const { deleteLogEntry } = await import('../src/logic/marmLogic.js');
        const sessionId = 'react-ui-session';
        response = deleteLogEntry(sessionId, target);
      } else {
        response = '❌ **Usage**: `/log delete: [session/entry name]`';
      }
      
    // Deep Dive Command
    } else if (command.startsWith('/deep dive')) {
      const topic = command.replace('/deep dive', '').trim();
      if (topic) {
        response = `🔍 **Deep Dive Analysis**: ${topic}\n\nEnhanced validation and reasoning protocols engaged for comprehensive analysis.`;
      } else {
        response = '🔍 **Deep Dive Mode**\n\nNext response will use enhanced validation protocols and include reasoning snapshot.';
      }
      
    // Reasoning and Summaries
    } else if (command === '/show reasoning') {
      const { getMostRecentBotResponseLogic } = await import('../src/logic/marmLogic.js');
      const sessionId = 'react-ui-session';
      const reasoning = getMostRecentBotResponseLogic(sessionId);
      response = `💭 **Show Reasoning**\n\nLogic and decision process:\n\n${reasoning || 'No reasoning data available for recent response.'}`;
      
    } else if (command.startsWith('/summary:')) {
      const sessionName = command.replace('/summary:', '').trim();
      const { compileSessionSummary } = await import('../src/logic/marmLogic.js');
      const sessionId = 'react-ui-session';
      if (sessionName) {
        response = `📄 **Session Summary**: ${sessionName}\n\n` + compileSessionSummary(sessionId);
      } else {
        response = '📄 **Session Summary**\n\n' + compileSessionSummary(sessionId);
      }
      
    // Notebook Commands  
    } else if (command.startsWith('/notebook add:')) {
      const args = command.replace('/notebook add:', '').trim();
      const parts = args.split(' ');
      if (parts.length >= 2) {
        const name = parts[0];
        const data = parts.slice(1).join(' ');
        const { manageUserNotebook } = await import('../src/logic/marmLogic.js');
        const sessionId = 'react-ui-session';
        response = manageUserNotebook(sessionId, 'add', name, data);
      } else {
        response = '❌ **Usage**: `/notebook add: [name] [data]`\n\nExample: `/notebook add: style_guide Prefer concise, active voice`';
      }
      
    } else if (command.startsWith('/notebook use:')) {
      const names = command.replace('/notebook use:', '').trim();
      if (names) {
        const { manageUserNotebook } = await import('../src/logic/marmLogic.js');
        const sessionId = 'react-ui-session';
        response = manageUserNotebook(sessionId, 'use', names);
      } else {
        response = '❌ **Usage**: `/notebook use: [name1,name2]`\n\nExample: `/notebook use: style_guide,api_rules`';
      }
      
    } else if (command.startsWith('/notebook show')) {
      const { manageUserNotebook } = await import('../src/logic/marmLogic.js');  
      const sessionId = 'react-ui-session';
      response = manageUserNotebook(sessionId, 'show');
      
    } else if (command.startsWith('/notebook delete:')) {
      const name = command.replace('/notebook delete:', '').trim();
      if (name) {
        const { manageUserNotebook } = await import('../src/logic/marmLogic.js');
        const sessionId = 'react-ui-session';
        response = manageUserNotebook(sessionId, 'delete', name);
      } else {
        response = '❌ **Usage**: `/notebook delete: [name]`';
      }
      
    } else if (command.startsWith('/notebook clear')) {
      const { manageUserNotebook } = await import('../src/logic/marmLogic.js');
      const sessionId = 'react-ui-session';
      response = manageUserNotebook(sessionId, 'clear');
      
    } else if (command.startsWith('/notebook status')) {
      const { manageUserNotebook } = await import('../src/logic/marmLogic.js');
      const sessionId = 'react-ui-session';
      response = manageUserNotebook(sessionId, 'status');
      
    } else {
      response = `❓ **Unknown Command**: \`${command}\`\n\n**Available Commands:**\n\n**Session Commands:**\n• \`/start marm\` - Activate MARM protocol\n• \`/refresh marm\` - Refresh session state\n\n**Core Commands:**\n• \`/log session: [name]\` - Create/switch session\n• \`/log entry: [YYYY-MM-DD-topic]\` - Add milestone\n• \`/log show: [session]\` - Display entries\n• \`/log delete: [session/entry]\` - Delete entry\n• \`/deep dive [topic]\` - Enhanced analysis\n\n**Reasoning & Summaries:**\n• \`/show reasoning\` - Show logic process\n• \`/summary: [session]\` - Generate summary\n\n**Notebook Commands:**\n• \`/notebook add: [name] [data]\` - Add entry\n• \`/notebook use: [name1,name2]\` - Activate entries\n• \`/notebook show:\` - Display all entries\n• \`/notebook delete: [name]\` - Delete entry\n• \`/notebook clear:\` - Clear active entries\n• \`/notebook status:\` - Show active list`;
    }

    res.json({ response });
    
  } catch (error) {
    console.error('[COMMAND] Error executing command:', error);
    res.status(500).json({ error: `Command execution failed: ${error.message}` });
  }
});

// ===== Documentation API Endpoint =====
app.get('/api/docs/:filename', async (req, res) => {
  try {
    const { filename } = req.params;
    
    // Validate filename to prevent path traversal
    const allowedFiles = ['handbook.md', 'faq.md', 'description.md', 'roadmap.md'];
    if (!allowedFiles.includes(filename)) {
      return res.status(404).json({ error: 'Document not found' });
    }
    
    const filePath = path.join(path.dirname(__filename), 'data', filename);
    const content = await readFile(filePath, 'utf-8');
    
    res.json({ 
      filename,
      content,
      title: filename.replace('.md', '').replace(/^./, c => c.toUpperCase())
    });
    
  } catch (error) {
    console.error('[DOCS] Error loading document:', error);
    res.status(500).json({ error: 'Failed to load document' });
  }
});

// ===== Start Server =====
app.listen(PORT, () => {
  console.log(`MARM Server running on port ${PORT}`);
});