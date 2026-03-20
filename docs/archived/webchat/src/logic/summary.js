// summary.js - Session data compilation and summarization functions 

// ===== Session Summary & Compilation Utilities =====
import { ensureSession } from './session.js';
import { generateContent } from '../replicateHelper.js';

export async function compileSessionSummary(id, options = {}) {
  const s = ensureSession(id);
  if (!s) return 'No active session.';
  const tailPairs = options.tailPairs || 6;
  const fields = options.fields ? options.fields.split(',').map(f => f.trim().toLowerCase()) : null;
  const hist = s.history.slice(-(tailPairs * 2));
  const logs = s.logs || [];
  let filteredLogs = logs;
  if (fields && logs.length > 0) {
    filteredLogs = logs.map(log => {
      const parts = log.split(/[\|-]/);
      if (parts.length >= 3) {
        const logObj = {
          date: parts[0]?.trim(),
          summary: parts[1]?.trim(),
          result: parts[2]?.trim()
        };
        const filteredParts = [];
        if (fields.includes('date')) filteredParts.push(logObj.date);
        if (fields.includes('summary')) filteredParts.push(logObj.summary);
        if (fields.includes('result')) filteredParts.push(logObj.result);
        return filteredParts.join(' | ');
      }
      return log;
    });
  }
  // --- Log & Conversation Compilation ---
  let content = '';
  if (filteredLogs.length > 0) {
    content += `Log Entries:\n${filteredLogs.join('\n')}\n\n`;
  }
  const flat = hist.map(m => `${m.role.toUpperCase()}: ${m.content}`).join('\n');
  content += `Conversation:\n${flat}`;
  const prompt = [
    {
      role: 'system',
      content: `You are MARM Bot creating a legitimate session summary. This is a standard summarization task for a protocol-driven chat system.\n${fields ? `Focus on these fields: ${fields.join(', ')}` : 'Include all relevant information'}\nProvide a concise summary highlighting key points and any MARM protocol usage. Only summarize, do not generate or speculate.`
    },
    { role: 'user', content: content }
  ];



  // Add retry logic for safety filter issues
  for (let attempt = 1; attempt <= 2; attempt++) {
    try {
      if (attempt === 2) {
        prompt[0].content = `You are MARM Bot creating a legitimate session summary. This is a standard summarization task.\n${fields ? `Focus on these fields: ${fields.join(', ')}` : 'Include all relevant information'}\nProvide a concise summary highlighting key points and any MARM protocol usage.`;
      }

      const response = await generateContent(prompt);

      if (!response) {
        console.error('[MARM] generateContent returned null/undefined');
        if (attempt === 2) return 'Summary unavailable (API returned no response).';
        continue;
      }

      if (typeof response.text !== 'function') {
        console.error('[MARM] generateContent response missing .text() method:', typeof response);
        if (attempt === 2) return 'Summary unavailable (Invalid API response format).';
        continue;
      }

      const summary = await response.text();

      if (!summary || typeof summary !== 'string' || summary.trim() === '') {
        console.error('[MARM] response.text() returned invalid/empty data:', typeof summary);
        if (attempt === 2) return 'Summary unavailable (Empty response - possibly blocked by safety filters).';
        continue;
      }

      if (summary.includes("I can't help with that") || summary.includes("I'm not able to") || summary.includes("sorry, but I can't")) {
        console.warn('[MARM] Possible safety filter trigger in summary on attempt', attempt);
        if (attempt === 1) continue;
      }

      return summary.trim();
    } catch (err) {
      console.error('[MARM] summary error attempt', attempt, ':', err);
      if (attempt === 2) {
        if (err.name === 'TypeError' && err.message.includes('text')) {
          return 'Summary unavailable (API response format error).';
        }
        return 'Summary unavailable (API error occurred).';
      }
    }
  }
  return 'Summary unavailable after multiple attempts (Safety filters may be blocking summarization).';
}
