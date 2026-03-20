// docs.js - Documentation loading and search functionality for MARM system

import { MARM_KEYWORDS } from './constants.js';

let docsCache = null;
export const docSnippets = {};
const DOC_NAMES = ['marmreadme', 'description', 'faq', 'handbook', 'roadmap'];
const DOC_BASE_PATH = './data/';

export async function loadDocs() {
  if (docsCache && Object.keys(docsCache).length) return docsCache;
  const newDocsCache = {};
  const newDocSnippets = {};
  await Promise.all(
    DOC_NAMES.map(async name => {
      try {
        const res = await fetch(`${DOC_BASE_PATH}${name}.md`);
        if (!res.ok) throw new Error(`${name}.md not found (status ${res.status})`);
        const text = await res.text();
        newDocsCache[name] = text;
        newDocSnippets[name] = text
          .split(/[.!?]/)
          .map(s => s.trim())
          .filter(s => s.length > 20 && !s.startsWith('#'));
      } catch (err) {
        console.error(`[MARM] Error loading ${name}.md →`, err.message);
        newDocsCache[name] = '';
        newDocSnippets[name] = [];
      }
    })
  );
  docsCache = newDocsCache;
  Object.assign(docSnippets, newDocSnippets);
  return docsCache;
}

// --- Documentation Search Logic ---
export function searchDocs(query) {
  if (!docsCache) return '';
  const q = query.toLowerCase();
  const isMarmQuery = MARM_KEYWORDS.some(keyword => q.includes(keyword));
  if (isMarmQuery) {
    const results = [];
    for (const key in docsCache) {
      const lines = docsCache[key].split('\n');
      const relevantLines = lines.filter(l =>
        MARM_KEYWORDS.some(kw => l.toLowerCase().includes(kw))
      );
      if (relevantLines.length > 0) {
        results.push(...relevantLines.slice(0, 3).map(l => `[${key}] ${l.trim()}`));
      }
    }
    if (results.length > 0) {
      return `MARM Documentation:\n${results.slice(0, 5).join('\n')}`;
    }
  }
  for (const key in docsCache) {
    const line = docsCache[key].split('\n').find(l => l.toLowerCase().includes(q));
    if (line) return `Found in ${key}.md → ${line.trim()}`;
  }
  return '';
}

export function shouldAutoSearch(userInput) {
  const q = userInput.toLowerCase();
  if (MARM_KEYWORDS.some(kw => q.includes(kw))) return true;
  const keyword = /(what|who|how|when|why)\b.*\?/i.test(userInput) ||
    /^\s*(define|describe|explain|give me|tell me about)\b/i.test(q);
  return keyword;
} 
