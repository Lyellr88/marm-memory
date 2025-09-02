// server1.js - Clean Express backend for Replicate API proxy 

import express from 'express';
import fetch from 'node-fetch';
import path from 'path';
import { fileURLToPath } from 'url';
import dotenv from 'dotenv';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

dotenv.config();

const app = express();
const PORT = process.env.PORT || 8080;
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
    
    // Use API key from request body if provided, otherwise use environment variable
    const apiKey = req.body.apiKey || REPLICATE_API_TOKEN;
    
    if (!apiKey) {
      return res.status(401).json({ 
        error: 'API key required', 
        message: 'Please provide an API key or use /setupreplicate command to configure one.' 
      });
    }
    
    const response = await fetch(url, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Accept': 'application/json',
        'Authorization': `Bearer ${apiKey}`,
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
      
      // Handle payment required error with friendly message
      if (response.status === 402) {
        res.status(402).json({ 
          error: 'Payment Required', 
          message: 'Your Replicate account needs credit to use this AI model. Please visit https://replicate.com/account/billing to add funds and try again.',
          friendly: true,
          details: data.detail || 'Insufficient credit'
        });
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

// ===== Error Handling Middleware =====
app.use((err, req, res, next) => {
  console.error('Unhandled error:', err);
  res.status(500).json({ error: 'Unhandled server error', details: err.message });
});

// ===== Server Startup =====
app.listen(PORT, '0.0.0.0', () => {
  console.log(`MARM Webchat server running on port ${PORT}`);
});
