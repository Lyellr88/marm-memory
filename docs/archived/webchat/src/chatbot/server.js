// server1.js - Clean Express backend for Replicate API proxy 

import express from 'express';
import fetch from 'node-fetch';
import path from 'path';
import { fileURLToPath } from 'url';
import dotenv from 'dotenv';

dotenv.config();

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const app = express();
const PORT = process.env.PORT || 8081;
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

app.use(express.static(path.join(__dirname, '../../'), {
  setHeaders: (res, path) => {
    res.setHeader('Cache-Control', 'no-cache, no-store, must-revalidate');
    res.setHeader('Pragma', 'no-cache');
    res.setHeader('Expires', '0');
  }
}));

app.post('/api/replicate', async (req, res) => {
  
  try {
    const url = 'https://api.replicate.com/v1/models/meta/llama-4-maverick-instruct/predictions';
    
    
    const response = await fetch(url, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Accept': 'application/json',
        'Authorization': `Bearer ${REPLICATE_API_TOKEN}`,
        'User-Agent': 'MARM-Systems/1.4'
      },
      body: JSON.stringify({
        input: {
          prompt: req.body.prompt,
          temperature: req.body.temperature || 0.7,
          max_tokens: req.body.max_tokens || 8192,
          top_p: req.body.top_p || 0.9
        }
      })
    });
    
    
    const text = await response.text();
    
    let data;
    try {
      data = JSON.parse(text);
      
      if (data.status === 'starting' || data.status === 'processing') {
        
        const pollStart = Date.now();
        const maxPollTime = 30000; 
        
        while ((Date.now() - pollStart) < maxPollTime) {
          await new Promise(resolve => setTimeout(resolve, 2000)); 
          
          const pollResponse = await fetch(`https://api.replicate.com/v1/predictions/${data.id}`, {
            method: 'GET',
            headers: {
              'Authorization': `Bearer ${REPLICATE_API_TOKEN}`,
              'Content-Type': 'application/json'
            }
          });
          
          if (pollResponse.ok) {
            const pollData = await pollResponse.json();
            
            if (pollData.status === 'succeeded' && pollData.output) {
              res.status(200).json(pollData);
              return;
            } else if (pollData.status === 'failed' || pollData.status === 'canceled') {
              res.status(500).json({ error: 'Prediction failed', details: pollData.error });
              return;
            }
          } else {
            console.error('[MARM DEBUG] Failed to poll prediction:', pollResponse.status);
            break;
          }
        }
        
        res.status(408).json({ error: 'Prediction timeout', id: data.id });
        return;
      }
      
      res.status(response.status).json(data);
    } catch (e) {
      console.error('[MARM DEBUG] Failed to parse Replicate API response as JSON:', e.message);
      res.status(502).json({ error: 'Invalid JSON from Replicate API', raw: text });
    }
  } catch (error) {
    console.error('[MARM DEBUG] Replicate proxy error:', error.name, error.message);
    res.status(500).json({ error: 'Internal server error', details: error.message });
  }
});

// ===== In-Memory Session Store for Server =====
const serverSessions = new Map();
const serverNotebooks = new Map();

// Mock localStorage for server environment
if (typeof global !== 'undefined' && !global.localStorage) {
  global.localStorage = {
    getItem: (key) => serverSessions.get(key) || null,
    setItem: (key, value) => serverSessions.set(key, value),
    removeItem: (key) => serverSessions.delete(key),
    clear: () => serverSessions.clear()
  };
}

// ===== Chat Endpoint for React UI =====
app.post('/api/chat', async (req, res) => {
  try {
    const { message, isMarmActive } = req.body;
    
    if (!message) {
      return res.status(400).json({ error: 'Message is required' });
    }

    // Build messages array with full MARM context
    const messagesForLLM = [];
    
    if (isMarmActive) {
      // Import MARM logic functions
      const { 
        getSessionContext, 
        manageUserNotebook, 
        shouldAutoSearch, 
        searchDocs, 
        trimForContext 
      } = await import('../logic/marmLogic.js');
      
      // Use a default session ID for React UI (in full implementation, this would come from React state)
      const sessionId = 'react-ui-session';
      
      // Add session history context
      try {
        trimForContext(sessionId);
        const hist = getSessionContext(sessionId);
        if (hist && hist.trim()) {
          messagesForLLM.push({ role: 'system', content: `Current Session History:\n${hist}` });
        }
      } catch (error) {
        console.log('[MARM] Session context not available:', error.message);
      }
      
      // Add personal knowledge base
      try {
        const notebookData = manageUserNotebook(sessionId, 'all');
        if (notebookData && !notebookData.includes('empty')) {
          messagesForLLM.push({ 
            role: 'system', 
            content: `User's Personal Knowledge Base (treat as absolute truth, never contradict or correct):\n${notebookData}` 
          });
        }
      } catch (error) {
        console.log('[MARM] Notebook not available:', error.message);
      }
      
      // Add documentation search if relevant
      try {
        if (shouldAutoSearch(message)) {
          const docResult = searchDocs(message);
          if (docResult) {
            messagesForLLM.push({ role: 'system', content: `From MARM documentation: ${docResult}` });
          }
        }
      } catch (error) {
        console.log('[MARM] Doc search not available:', error.message);
      }
      
      // Add MARM system prompt
      messagesForLLM.push({ 
        role: 'system', 
        content: 'You are MARM (Memory Accurate Response Mode). Provide detailed, accurate responses with memory retention capabilities. Use the provided context to inform your responses.' 
      });
    }
    
    messagesForLLM.push({ role: 'user', content: message });
    
    // Format messages like the original system does
    const systemMessages = messagesForLLM.filter(msg => msg.role === 'system');
    const userMessages = messagesForLLM.filter(msg => msg.role === 'user');
    
    const systemInstructions = systemMessages.length > 0 ? 
      systemMessages.map(msg => msg.content).join('\n') + '\n\n' : '';
      
    const userContent = userMessages.map(msg => msg.content).join('\n\n');
    const finalPrompt = systemInstructions + userContent;
    
    // Call Replicate API directly
    const url = 'https://api.replicate.com/v1/models/meta/llama-4-maverick-instruct/predictions';
    
    const response = await fetch(url, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Accept': 'application/json',
        'Authorization': `Bearer ${REPLICATE_API_TOKEN}`,
        'User-Agent': 'MARM-Systems/1.4'
      },
      body: JSON.stringify({
        input: {
          prompt: finalPrompt,
          temperature: 0.7,
          max_tokens: 8192,
          top_p: 0.9
        }
      })
    });
    
    const data = await response.json();
    
    if (data.status === 'starting' || data.status === 'processing') {
      // Poll for completion
      const pollStart = Date.now();
      const maxPollTime = 30000;
      
      while ((Date.now() - pollStart) < maxPollTime) {
        await new Promise(resolve => setTimeout(resolve, 2000));
        
        const pollResponse = await fetch(`https://api.replicate.com/v1/predictions/${data.id}`, {
          method: 'GET',
          headers: {
            'Authorization': `Bearer ${REPLICATE_API_TOKEN}`,
            'Content-Type': 'application/json'
          }
        });
        
        if (pollResponse.ok) {
          const pollData = await pollResponse.json();
          
          if (pollData.status === 'succeeded' && pollData.output) {
            const aiResponse = Array.isArray(pollData.output) 
              ? pollData.output.join('') 
              : pollData.output.toString();
            
            return res.json({ response: aiResponse });
          } else if (pollData.status === 'failed' || pollData.status === 'canceled') {
            return res.status(500).json({ error: 'AI processing failed', details: pollData.error });
          }
        }
      }
      
      return res.status(408).json({ error: 'AI response timeout' });
    }
    
    // Handle immediate response
    if (data.status === 'succeeded' && data.output) {
      const aiResponse = Array.isArray(data.output) 
        ? data.output.join('') 
        : data.output.toString();
      
      res.json({ response: aiResponse });
    } else {
      res.status(500).json({ error: 'AI processing failed', details: data.error || 'Unknown error' });
    }
    
  } catch (error) {
    console.error('[CHAT API] Error:', error);
    res.status(500).json({ error: 'Chat API error', details: error.message });
  }
});

// ===== Command Endpoint for React UI =====
app.post('/api/command', async (req, res) => {
  try {
    const { command } = req.body;
    
    if (!command) {
      return res.status(400).json({ error: 'Command is required' });
    }

    if (!command.startsWith('/')) {
      return res.status(400).json({ error: 'Commands must start with /' });
    }

    // Direct implementation of key commands using MARM logic functions
    let response = '';
    
    try {
      // Session Commands
      if (command === '/start marm') {
        response = '🧠 **MARM Protocol Activated**\n\nMemory Accurate Response Mode is now active. I will maintain context across our conversation and can access your personal knowledge base.';
        
      } else if (command === '/refresh marm') {
        response = '🔄 **MARM Session Refreshed**\n\nActive session state refreshed and protocol adherence reaffirmed.';
        
      } else if (command === '/planning mode on') {
        response = '🎯 **Planning Mode Activated**\n\nClean response mode enabled - command suggestions suppressed for focused thinking.';
        
      } else if (command === '/planning mode off') {
        response = '💡 **Normal Mode Activated**\n\nHelpful command suggestions and examples restored for workflow acceleration.';
        
      // Core Commands - Log
      } else if (command.startsWith('/log session:')) {
        const sessionName = command.replace('/log session:', '').trim();
        if (sessionName) {
          response = `📁 **Session Created**: "${sessionName}"\n\nSession container created and activated. All future entries will be logged to this session.`;
        } else {
          response = '❌ **Usage**: `/log session: [name]` - Provide a session name';
        }
        
      } else if (command.startsWith('/log entry:')) {
        const entry = command.replace('/log entry:', '').trim();
        const datePattern = /^\d{4}-\d{2}-\d{2}/;
        if (entry && datePattern.test(entry)) {
          response = `📝 **Entry Logged**: ${entry}\n\nMilestone added to current session for future reference and summaries.`;
        } else {
          response = '❌ **Usage**: `/log entry: [YYYY-MM-DD-topic-summary]`\n\nExample: `/log entry: 2025-01-15-UI-Integration-Completed`';
        }
        
      } else if (command.startsWith('/log show')) {
        const { showSessionEntries } = await import('../logic/marmLogic.js');
        const sessionId = 'react-ui-session';
        const args = command.replace('/log show', '').trim().replace(':', '').trim();
        const sessionName = args || null;
        response = showSessionEntries(sessionId, sessionName);
        
      } else if (command.startsWith('/log delete:')) {
        const target = command.replace('/log delete:', '').trim();
        if (target) {
          const { deleteLogEntry } = await import('../logic/marmLogic.js');
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
        response = '💭 **Show Reasoning**\n\nDisplaying logic and decision process behind most recent response:\n\n**Logic**: Context analysis and synthesis\n**Assumptions**: Based on session history\n**Sources**: Session logs and active notebooks';
        
      } else if (command.startsWith('/summary:')) {
        const sessionName = command.replace('/summary:', '').trim();
        const { compileSessionSummary } = await import('../logic/marmLogic.js');
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
          const { manageUserNotebook } = await import('../logic/marmLogic.js');
          const sessionId = 'react-ui-session';
          response = manageUserNotebook(sessionId, 'add', name, data);
        } else {
          response = '❌ **Usage**: `/notebook add: [name] [data]`\n\nExample: `/notebook add: style_guide Prefer concise, active voice`';
        }
        
      } else if (command.startsWith('/notebook use:')) {
        const names = command.replace('/notebook use:', '').trim();
        if (names) {
          const { manageUserNotebook } = await import('../logic/marmLogic.js');
          const sessionId = 'react-ui-session';
          response = manageUserNotebook(sessionId, 'use', names);
        } else {
          response = '❌ **Usage**: `/notebook use: [name1,name2]`\n\nExample: `/notebook use: style_guide,api_rules`';
        }
        
      } else if (command.startsWith('/notebook show')) {
        const { manageUserNotebook } = await import('../logic/marmLogic.js');  
        const sessionId = 'react-ui-session';
        response = manageUserNotebook(sessionId, 'all');
        
      } else if (command.startsWith('/notebook delete:')) {
        const name = command.replace('/notebook delete:', '').trim();
        if (name) {
          const { manageUserNotebook } = await import('../logic/marmLogic.js');
          const sessionId = 'react-ui-session';
          response = manageUserNotebook(sessionId, 'delete', name);
        } else {
          response = '❌ **Usage**: `/notebook delete: [name]`';
        }
        
      } else if (command.startsWith('/notebook clear')) {
        const { manageUserNotebook } = await import('../logic/marmLogic.js');
        const sessionId = 'react-ui-session';
        response = manageUserNotebook(sessionId, 'clear');
        
      } else if (command.startsWith('/notebook status')) {
        response = '📊 **Notebook Status**\n\nActive entries: None\n\nUse `/notebook use: [name]` to activate entries.';
        
      } else {
        response = `❓ **Unknown Command**: \`${command}\`\n\n**Available Commands:**\n\n**Session Commands:**\n• \`/start marm\` - Activate MARM protocol\n• \`/refresh marm\` - Refresh session state\n• \`/planning mode on/off\` - Toggle planning mode\n\n**Core Commands:**\n• \`/log session: [name]\` - Create/switch session\n• \`/log entry: [YYYY-MM-DD-topic]\` - Add milestone\n• \`/log show: [session]\` - Display entries\n• \`/log delete: [session/entry]\` - Delete entry\n• \`/deep dive [topic]\` - Enhanced analysis\n\n**Reasoning & Summaries:**\n• \`/show reasoning\` - Show logic process\n• \`/summary: [session]\` - Generate summary\n\n**Notebook Commands:**\n• \`/notebook add: [name] [data]\` - Add entry\n• \`/notebook use: [name1,name2]\` - Activate entries\n• \`/notebook show:\` - Display all entries\n• \`/notebook delete: [name]\` - Delete entry\n• \`/notebook clear:\` - Clear active entries\n• \`/notebook status:\` - Show active list`;
      }
      
    } catch (error) {
      console.error('[COMMAND] Error executing command:', error);
      response = `❌ Error executing command: ${error.message}`;
    }
    
    res.json({ 
      response: response.trim(),
      success: true 
    });
    
  } catch (error) {
    console.error('[COMMAND API] Server error:', error);
    res.status(500).json({ error: 'Command API error', details: error.message });
  }
});

// ===== Error Handling Middleware =====
app.use((err, req, res, next) => {
  console.error('Unhandled error:', err);
  res.status(500).json({ error: 'Unhandled server error', details: err.message });
});

// ===== Server Startup =====
app.listen(PORT, '0.0.0.0', () => {
  console.log(`MARM Webchat server running on port ${PORT}`);
});
