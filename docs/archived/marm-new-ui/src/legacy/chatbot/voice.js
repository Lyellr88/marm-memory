// voice.js - Web Speech API and voice synthesis functionality

// Import XSS protection
import { sanitizeHTML } from '../../security/xssProtection.js';

// ===== VOICE CONFIGURATION =====
export const voiceConfig = {
  enabled: false,
  rate: 1.10,
  pitch: 1.0,
  voice: null
};

let availableVoices = [];

// ===== VOICE LOADING =====
export function loadVoices() {
  try {
    availableVoices = speechSynthesis.getVoices();
  } catch (e) {
    console.warn('Could not load voices:', e);
    availableVoices = [];
  }
  
  const preferredVoices = [
    'Google UK English Female',
    'Google UK English Male', 
    'Google US English',
    'Microsoft Zira Desktop',
    'Microsoft David Desktop',
    'Samantha',
    'Alex',
    'Karen',
    'Microsoft Zira',
    'Microsoft David',
    'Google UK English Female',
    'Google US English'
  ];
  
  let selectedVoice = null;
  for (const preferred of preferredVoices) {
    selectedVoice = availableVoices.find(v => v.name.includes(preferred));
    if (selectedVoice) break;
  }
  
  if (!selectedVoice) {
    selectedVoice = availableVoices.find(v => 
      v.lang.startsWith('en') && !v.default
    ) || availableVoices.find(v => v.lang.startsWith('en')) || availableVoices[0];
  }
  
  if (selectedVoice && !voiceConfig.voice) {
    voiceConfig.voice = selectedVoice.name;
  }
}

// ===== TEXT-TO-SPEECH =====
export function speakText(text, isBot = true) {
  if (!isBot) return;
  
  document.querySelectorAll('.bot-message.speaking').forEach(msg => {
    msg.classList.remove('speaking');
  });
  
  if (speechSynthesis.speaking || speechSynthesis.pending) {
    speechSynthesis.cancel();
  }
  
  let cleanText = text
    .replace(/\*\*(.*?)\*\*/g, '$1')
    .replace(/\*(.*?)\*/g, '$1')
    .replace(/```[\s\S]*?```/g, ' [code block removed] ')
    .replace(/`(.*?)`/g, '$1')
    .replace(/^[-*]\s/gm, '')
    .replace(/\[.*?\]\(.*?\)/g, '')
    .replace(/^#+\s/gm, '')
    .replace(/([.!?])\s*\n/g, '$1 ')
    .replace(/\n{2,}/g, '. ')
    .replace(/:/g, ',')
    .replace(/\s+/g, ' ')
    .trim();
  
  if (!cleanText) return;
  
  const MAX_SPEECH_LENGTH = 10000; 
  if (cleanText.length > MAX_SPEECH_LENGTH) {
    cleanText = cleanText.substring(0, MAX_SPEECH_LENGTH) + "... Response truncated for voice playback.";
  }
  
  cleanText = cleanText
    .replace(/\. /g, '. ... ')
    .replace(/, /g, ', .. ')
    .replace(/\? /g, '? ... ')
    .replace(/! /g, '! ... ');
  
  const utterance = new SpeechSynthesisUtterance(cleanText);
  
  
  utterance.rate = voiceConfig.rate;
  utterance.pitch = voiceConfig.pitch;
  utterance.volume = 0.9;
  
  utterance.onstart = () => {
  };
  
  utterance.onerror = (event) => {
    console.error('[VOICE DEBUG] Speech error:', event.error, event);
  };
  
  utterance.onend = () => {
  };
  
  if (voiceConfig.voice) {
    const selectedVoice = availableVoices.find(v => v.name === voiceConfig.voice);
    if (selectedVoice) {
      utterance.voice = selectedVoice;
      if (selectedVoice.name.includes('Google')) {
        utterance.rate = voiceConfig.rate * 0.95;
      }
    }
  }
  
  utterance.onstart = () => {
    document.querySelectorAll('.bot-message').forEach(msg => {
      msg.classList.remove('speaking');
    });
  };
  
  utterance.onend = () => {
    document.querySelectorAll('.bot-message').forEach(msg => {
      msg.classList.remove('speaking');
    });
  };
  
  
  speechSynthesis.speak(utterance);
  
}

// ===== VOICE UI INTEGRATION =====
export function addVoiceToggleToHelp() {
  const voiceSettings = document.getElementById('voice-settings');
  const autoToggle = document.getElementById('auto-voice-toggle');
  const voiceOptionsBtn = document.getElementById('voice-options-btn');
  const speedSlider = document.getElementById('voice-speed-slider');
  const speedValue = document.getElementById('voice-speed-value');
  
  if (!voiceSettings || !autoToggle || !voiceOptionsBtn || !speedSlider || !speedValue) {
    console.warn('Voice settings template not found in HTML');
    return;
  }
  
  autoToggle.checked = voiceConfig.enabled;
  speedSlider.value = voiceConfig.rate;
  speedValue.textContent = voiceConfig.rate + 'x';
  
  autoToggle.onchange = (e) => {
    voiceConfig.enabled = e.target.checked;
    localStorage.setItem('marmVoiceEnabled', voiceConfig.enabled);
  };
  
  speedSlider.oninput = (e) => {
    voiceConfig.rate = parseFloat(e.target.value);
    speedValue.textContent = voiceConfig.rate + 'x';
    localStorage.setItem('marmVoiceSpeed', voiceConfig.rate);
  };
  
  voiceOptionsBtn.onclick = showVoiceOptions;
  
  voiceSettings.style.display = 'block';
}

export function showVoiceOptions() {
  const overlay = document.createElement('div');
  overlay.style.cssText = `
    position: fixed; top: 0; left: 0; width: 100%; height: 100%; 
    background: rgba(0,0,0,0.5); z-index: 9999; display: flex; 
    align-items: center; justify-content: center;
  `;
  
  const modal = document.createElement('div');
  modal.style.cssText = `
    background: white; border-radius: 8px; padding: 20px; 
    max-width: 400px; max-height: 500px; width: 90%;
    box-shadow: 0 8px 32px rgba(0,0,0,0.3);
  `;
  
  const currentVoice = voiceConfig.voice || 'Default';
  modal.innerHTML = `
    <h3 style="margin: 0 0 15px 0; color: #3d5a80;">Voice Selection</h3>
    <p style="margin: 0 0 10px 0; color: #666;">Current: ${currentVoice}</p>
    <div id="voice-list" style="max-height: 300px; overflow-y: auto; border: 1px solid #ddd; border-radius: 4px;"></div>
    <div style="margin-top: 15px; text-align: right;">
      <button id="voice-cancel" style="padding: 8px 16px; margin-right: 10px; border: 1px solid #ddd; background: white; border-radius: 4px; cursor: pointer;">Cancel</button>
    </div>
  `;
  
  const voiceList = modal.querySelector('#voice-list');
  availableVoices.forEach(voice => {
    const voiceItem = document.createElement('div');
    const isSelected = voice.name === voiceConfig.voice;
    voiceItem.style.cssText = `
      padding: 10px; cursor: pointer; border-bottom: 1px solid #eee;
      background: ${isSelected ? '#e3f2fd' : 'white'};
      font-weight: ${isSelected ? 'bold' : 'normal'};
    `;
    voiceItem.innerHTML = `${voice.name} <span style="color: #666; font-size: 0.9em;">(${voice.lang})</span>`;
    
    voiceItem.onmouseover = () => voiceItem.style.background = isSelected ? '#e3f2fd' : '#f5f5f5';
    voiceItem.onmouseout = () => voiceItem.style.background = isSelected ? '#e3f2fd' : 'white';
    
    voiceItem.onclick = () => {
      voiceConfig.voice = voice.name;
      localStorage.setItem('marmVoiceSelected', voice.name);
      document.body.removeChild(overlay);
    };
    
    voiceList.appendChild(voiceItem);
  });
  
  modal.querySelector('#voice-cancel').onclick = () => {
    document.body.removeChild(overlay);
  };
  
  overlay.onclick = (e) => {
    if (e.target === overlay) document.body.removeChild(overlay);
  };
  
  overlay.appendChild(modal);
  document.body.appendChild(overlay);
}

// ===== VOICE INITIALIZATION =====
export function initializeVoice() {
  if (!window.speechSynthesis) {
    console.error("Speech synthesis unavailable");
    voiceConfig.enabled = false;
    document.querySelectorAll('.voice-btn').forEach(btn => btn.style.display = 'none');
    return;
  }
  
  speechSynthesis.onvoiceschanged = loadVoices;
  loadVoices();
  
  try {
    voiceConfig.enabled = localStorage.getItem('marmVoiceEnabled') === 'true';
    const savedSpeed = localStorage.getItem('marmVoiceSpeed');
    if (savedSpeed) {
      voiceConfig.rate = parseFloat(savedSpeed);
    }
  } catch (e) {
    voiceConfig.enabled = false;
  }
  
  trackableVoiceEventListener(document, 'keydown', (e) => {
    if (e.key === 'Escape') {
      speechSynthesis.cancel();
      document.querySelectorAll('.bot-message').forEach(msg => {
        msg.classList.remove('speaking');
      });
    }
  });
  
    // ===== INLINE SELF-TESTS FOR DEVELOPMENT/TEST ENVIRONMENTS =====
    if (typeof process !== 'undefined' && process.env?.NODE_ENV === 'test') {
      // Mock speechSynthesis for testing
      global.speechSynthesis = global.speechSynthesis || {
        getVoices: () => [{ name: 'TestVoice', lang: 'en-US', default: true }],
        speak: jest.fn ? jest.fn() : () => {},
        cancel: jest.fn ? jest.fn() : () => {},
        speaking: false,
        pending: false,
        onvoiceschanged: null,
      };
    
      // Test loadVoices
      loadVoices();
      if (voiceConfig.voice !== 'TestVoice') {
        throw new Error('loadVoices did not select the correct voice');
      }
    
      // Test speakText
      let speakCalled = false;
      global.speechSynthesis.speak = () => { speakCalled = true; };
      speakText('Hello world', true);
      if (!speakCalled) {
        throw new Error('speakText did not call speechSynthesis.speak for valid input');
      }
      speakCalled = false;
      speakText('Hello world', false);
      if (speakCalled) {
        throw new Error('speakText should not call speechSynthesis.speak when isBot is false');
      }
    
      // Test utility exports
      if (!(voiceTimers instanceof Set)) {
        throw new Error('voiceTimers is not a Set');
      }
      if (!(voiceListeners instanceof Map)) {
        throw new Error('voiceListeners is not a Map');
      }
    }
}

function trackableVoiceEventListener(element, event, handler, options) {
  element.addEventListener(event, handler, options);
  
  if (!voiceListeners.has(element)) {
    voiceListeners.set(element, []);
  }
  voiceListeners.get(element).push({ event, handler, options });
}

// ===== UTILITY FUNCTIONS =====
export const voiceTimers = new Set();
export const voiceListeners = new Map();

function debounce(fn, delay) {
  let timer = null;
  return function (...args) {
    if (timer) {
      clearTimeout(timer);
      voiceTimers.delete(timer);
    }
    timer = setTimeout(() => {
      voiceTimers.delete(timer);
      fn.apply(this, args);
    }, delay);
    voiceTimers.add(timer);
  };
}

export function cleanupVoice() {
  if (window.speechSynthesis) {
    window.speechSynthesis.cancel();
  }
  
  document.querySelectorAll('.bot-message.speaking').forEach(msg => {
    msg.classList.remove('speaking');
  });
  
  voiceTimers.forEach(timer => clearTimeout(timer));
  voiceTimers.clear();
  
  voiceListeners.forEach((listeners, element) => {
    listeners.forEach(({ event, handler, options }) => {
      try {
        element.removeEventListener(event, handler, options);
      } catch (e) {
      }
    });
  });
  voiceListeners.clear();
} 
