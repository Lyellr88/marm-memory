// replicateHelper.js - Replicate API integration and request handling

// ===== CONNECTION OPTIMIZATION =====
let connectionsWarmed = 0;
const targetWarmConnections = 3;
let activeControllers = new Set();

async function warmConnections() {
  return;
}

async function warmSingleConnection(connectionId) {
  return;
}

export function cleanupConnections() {
  activeControllers.forEach(controller => {
    controller.abort();
  });
  activeControllers.clear();
  connectionsWarmed = 0;
}

export { warmConnections };

// ===== UTILITY FUNCTIONS =====
function delay(ms) {
  return new Promise(resolve => setTimeout(resolve, ms));
}

function createRequestBody(prompt) {
  return {
    prompt: prompt,
    temperature: 0.7,
    max_tokens: 8192,
    top_p: 0.9
  };
}

function getErrorMessage(status, attempt, maxAttempts) {
  const isRetrying = attempt < maxAttempts;
  const retryText = isRetrying ? ` (Attempt ${attempt}/${maxAttempts}, retrying...)` : '';
  
  switch (status) {
    case 429:
      return `🚫 Rate limit reached${retryText}`;
    case 500:
    case 502:
    case 503:
    case 504:
      return `🌐 Replicate servers are busy${retryText}`;
    case 401:
    case 403:
      return `🔑 API authentication issue. Please check your API key.`;
    case 400:
      return `⚠️ Invalid request format. Please try a different message.`;
    default:
      return `❌ Connection issue${retryText}`;
  }
}

// ===== MAIN API FUNCTION =====
export async function generateContent(messages) {
  
  const url = 'http://localhost:8080/api/replicate';
  const maxAttempts = 5;
  
  const systemMessages = messages.filter(msg => msg.role === 'system');
  const userMessages = messages.filter(msg => msg.role === 'user');

  const systemInstructions = systemMessages.length > 0 ? 
    systemMessages.map(msg => msg.content).join('\n') + '\n\n' : '';
    
  const userContent = userMessages.map(msg => msg.content).join('\n\n');
  const prompt = systemInstructions + userContent;


  const requestBody = createRequestBody(prompt);

 for (let attempt = 1; attempt <= maxAttempts; attempt++) {
  let controller;
  try {
    controller = new AbortController();
    activeControllers.add(controller);
      
      const timeoutId = setTimeout(() => {
        controller.abort();
        activeControllers.delete(controller);
      }, 45000);
      
      
      const res = await fetch(url, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Accept': 'application/json',
        },
        body: JSON.stringify(requestBody),
        signal: controller.signal
      });
      
      clearTimeout(timeoutId);
      activeControllers.delete(controller);
      
      
      if (!res.ok) {
        const errText = await res.text();
        console.error(`[MARM DEBUG] Replicate API Error (Attempt ${attempt}):`, res.status, errText);
        
        if (res.status === 401 || res.status === 403 || res.status === 400) {
          return {
            text: () => getErrorMessage(res.status, attempt, maxAttempts)
          };
        }
        
        if (attempt < maxAttempts) {
          const base = Math.pow(2, attempt - 1) * 500;
          const jitter = Math.floor(Math.random() * 250);
          const delayMs = Math.min(base + jitter, 2250);
          await delay(delayMs);
          continue;
        }
        
        return {
          text: () => getErrorMessage(res.status, attempt, maxAttempts)
        };
      }
      
      const text = await res.text();
      
      if (!text) {
        console.error('[MARM DEBUG] Empty response from Replicate API');
        return {
          text: () => '❌ Empty response from Replicate API. Please try again later.'
        };
      }
      let data;
      try {
        data = JSON.parse(text);
      } catch (e) {
        console.error('[MARM DEBUG] Failed to parse Replicate API response as JSON:', text);
        return {
          text: () => '❌ Invalid response from Replicate API. Please try again later.'
        };
      }

      // ===== RESPONSE VALIDATION =====
      
      let reply = null;
      if (data.output) {
        reply = Array.isArray(data.output) ? data.output.join('') : data.output;
      } else if (data.status === 'completed' && data.result) {
        reply = Array.isArray(data.result) ? data.result.join('') : data.result;
      } else if (data.status === 'processing' || data.status === 'starting') {
        if (attempt < maxAttempts) {
       
          const delayMs = 4000; 
          await delay(delayMs);
          continue; 
          
        } else {
          return {
            text: () => '⏱️ Response is taking longer than expected. Please try again.'
          };
        }
      }
      
      if (!reply || reply.trim() === '') {
        console.error('[MARM DEBUG] Empty reply text:', reply);
        return {
          text: () => '🤔 Received an empty response. Please try asking your question differently.'
        };
      }
      
      console.log('[MARM] API request successful');
      return {
        text: () => reply
      };
      
 } catch (error) {
    console.error(`[MARM DEBUG] Request error (Attempt ${attempt}):`, error.name, error.message);
    if (controller) activeControllers.delete(controller);
      
      if (error.name === 'AbortError') {
        if (attempt < maxAttempts) {
          const base = Math.pow(2, attempt - 1) * 500;
          const jitter = Math.floor(Math.random() * 250);
          const delayMs = Math.min(base + jitter, 2250);
          await delay(delayMs);
          continue;
        }
        return {
          text: () => '⏱️ Request timed out. Please check your connection and try again.'
        };
      }
      
      if (attempt < maxAttempts) {
        const base = Math.pow(2, attempt - 1) * 500;
        const jitter = Math.floor(Math.random() * 250);
        const delayMs = Math.min(base + jitter, 2250);
        await delay(delayMs);
        continue;
      }
      
      return {
        text: () => '🌐 Network error. Please check your internet connection and try again.'
      };
    }
  }
}
