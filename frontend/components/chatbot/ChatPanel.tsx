import React, { useState, useCallback, useEffect } from 'react';
import { X, HardHat } from 'lucide-react';
import { ChatMessage, ChatBlock } from '../../types';
import { sendChatMessage } from '../../services/api';
import ChatContainer from './ChatContainer';
import ChatInput from './ChatInput';

// ---------------------------------------------------------------------------
// localStorage helpers
// ---------------------------------------------------------------------------
const LS_MESSAGES_KEY = 'imos_chat_messages';
const LS_SESSION_KEY  = 'imos_chat_session_id';
const MAX_MESSAGES    = 50;
const TTL_MS          = 7 * 24 * 60 * 60 * 1000; // 7 days

/** Generate a UUID without any external package.
 *  Uses crypto.randomUUID() in secure contexts (HTTPS / localhost),
 *  falls back to crypto.getRandomValues() on plain HTTP. */
const genId = (): string => {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID();
  }
  // Fallback: RFC-4122 v4 UUID via getRandomValues
  const bytes = new Uint8Array(16);
  crypto.getRandomValues(bytes);
  bytes[6] = (bytes[6] & 0x0f) | 0x40; // version 4
  bytes[8] = (bytes[8] & 0x3f) | 0x80; // variant 1
  const hex = Array.from(bytes, (b) => b.toString(16).padStart(2, '0')).join('');
  return `${hex.slice(0,8)}-${hex.slice(8,12)}-${hex.slice(12,16)}-${hex.slice(16,20)}-${hex.slice(20)}`;
};

function loadMessages(): ChatMessage[] {
  try {
    const raw = localStorage.getItem(LS_MESSAGES_KEY);
    if (!raw) return [];
    const all: ChatMessage[] = JSON.parse(raw);
    // Prune messages older than TTL
    const cutoff = Date.now() - TTL_MS;
    return all.filter((m) => m.timestamp >= cutoff);
  } catch {
    return [];
  }
}

function saveMessages(msgs: ChatMessage[]): void {
  try {
    // Keep only the most recent MAX_MESSAGES
    const trimmed = msgs.length > MAX_MESSAGES ? msgs.slice(-MAX_MESSAGES) : msgs;
    localStorage.setItem(LS_MESSAGES_KEY, JSON.stringify(trimmed));
  } catch {
    // Storage full or unavailable — silently ignore
  }
}

function loadSessionId(): string {
  try {
    const stored = localStorage.getItem(LS_SESSION_KEY);
    if (stored) return stored;
    const id = genId();
    localStorage.setItem(LS_SESSION_KEY, id);
    return id;
  } catch {
    return genId();
  }
}

function newSessionId(): string {
  const id = genId();
  try { localStorage.setItem(LS_SESSION_KEY, id); } catch { /* ignore */ }
  return id;
}

// ---------------------------------------------------------------------------
// Build plain-text history for backend (last 10 messages)
// ---------------------------------------------------------------------------
function buildHistory(messages: ChatMessage[]): { role: string; content: string }[] {
  return messages.slice(-10).map((m) => ({
    role: m.role,
    // Describe every block type so GPT never sees "[structured response]"
    // which it interprets as a previous formatting failure and apologises.
    content: m.blocks.map((b) => {
      if (b.type === 'text' && b.content) return b.content;
      if (b.type === 'table') return `[Table shown: columns — ${(b.headers || []).join(', ')}]`;
      if (b.type === 'chart') return `[${b.chart_type || 'Chart'} chart displayed: ${b.title || 'data chart'}]`;
      return '';
    }).filter(Boolean).join('\n') || '[Response shown]',
  }));
}

// ---------------------------------------------------------------------------
// ChatPanel
// ---------------------------------------------------------------------------

interface Props {
  onClose: () => void;
}

const ChatPanel: React.FC<Props> = ({ onClose }) => {
  const [messages,  setMessages]  = useState<ChatMessage[]>(loadMessages);
  const [inputText, setInputText] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [sessionId, setSessionId] = useState<string>(loadSessionId);

  // Persist messages to localStorage whenever they change
  useEffect(() => {
    saveMessages(messages);
  }, [messages]);

  const handleSend = useCallback(async () => {
    const text = inputText.trim();
    if (!text || isLoading) return;

    setInputText('');
    setIsLoading(true);

    // Show user message immediately in UI
    const userMsg: ChatMessage = {
      id       : genId(),
      role     : 'user',
      blocks   : [{ type: 'text', content: text }],
      timestamp: Date.now(),
    };
    setMessages((prev) => [...prev, userMsg]);

    try {
      const response = await sendChatMessage({
        message   : text,
        session_id: sessionId,
        history   : buildHistory(messages),
      });

      const assistantMsg: ChatMessage = {
        id       : genId(),
        role     : 'assistant',
        blocks   : response.blocks as ChatBlock[],
        timestamp: Date.now(),
      };
      setMessages((prev) => [...prev, assistantMsg]);

    } catch (err) {
      // Log actual error so it's visible in browser DevTools (F12 → Console).
      // Common causes: network timeout, backend 500, or CORS issue.
      console.error('[ChatPanel] sendChatMessage failed:', err);

      // Determine a user-facing message based on error type
      const isTimeout = err instanceof Error && (
        err.message.includes('timeout') || err.message.includes('ECONNABORTED')
      );
      const userContent = isTimeout
        ? "⏱️ The request took too long to complete. Complex analytical queries can take up to 2 minutes. Please try again, or ask a more specific question (e.g. 'Show total ROM for January')."
        : "Sorry, I couldn't get a response right now. Please check your connection and try again.";

      const errorMsg: ChatMessage = {
        id       : genId(),
        role     : 'assistant',
        blocks   : [{ type: 'text', content: userContent }],
        timestamp: Date.now(),
      };
      setMessages((prev) => [...prev, errorMsg]);
    } finally {
      setIsLoading(false);
    }
  }, [inputText, isLoading, messages, sessionId]);

  const handleClear = useCallback(() => {
    setMessages([]);
    const newId = newSessionId();
    setSessionId(newId);
    try { localStorage.removeItem(LS_MESSAGES_KEY); } catch { /* ignore */ }
  }, []);

  return (
    <div
      className="flex flex-col bg-white rounded-2xl shadow-2xl overflow-hidden"
      style={{
        width:  window.innerWidth < 480 ? 'calc(100vw - 32px)' : 380,
        height: window.innerWidth < 480 ? 'calc(100dvh - 140px)' : 560,
      }}
    >
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 bg-gradient-to-r from-blue-700 to-blue-600 shrink-0">
        <div className="flex items-center gap-3">
          {/* Mining hard-hat logo badge */}
          <div className="w-9 h-9 rounded-full bg-gradient-to-br from-yellow-300 to-yellow-500
                          flex items-center justify-center shadow-md ring-2 ring-yellow-200/40">
            <HardHat size={18} className="text-yellow-900" strokeWidth={2} />
          </div>
          <div>
            <p className="text-sm font-bold text-white leading-tight tracking-wide">Mines Assistant</p>
            <p className="text-[10px] text-blue-200 leading-tight">Kaliapani Mines · Balasore Alloys</p>
          </div>
        </div>
        <button
          onClick={onClose}
          className="w-7 h-7 rounded-full hover:bg-white/20 flex items-center justify-center transition-colors"
          title="Close chat"
        >
          <X size={16} className="text-white" />
        </button>
      </div>

      {/* Message list */}
      <ChatContainer messages={messages} isLoading={isLoading} />

      {/* Text input */}
      <ChatInput
        value={inputText}
        onChange={setInputText}
        onSend={handleSend}
        onClear={handleClear}
        isLoading={isLoading}
      />
    </div>
  );
};

export default ChatPanel;
