import React, { useEffect, useRef } from 'react';
import { HardHat } from 'lucide-react';
import { ChatMessage } from '../../types';
import MessageBubble, { TypingIndicator } from './MessageBubble';

interface Props {
  messages: ChatMessage[];
  isLoading: boolean;
}

const WELCOME_TEXT =
  'Hello! I\'m Mines Assistant ⛏️\n\n' +
  'I can help you with:\n' +
  '• Production data — ROM, OB, Cr2O3 trends\n' +
  '• Quality tracking — excavation to plant\n' +
  '• Equipment — fuel efficiency, fleet status\n' +
  '• Planning — plan vs actual analysis\n' +
  '• General mining knowledge\n\n' +
  'Ask me anything! For data queries, mention the date (e.g. "last week", "January 2026") or I\'ll use the previous month.';

const ChatContainer: React.FC<Props> = ({ messages, isLoading }) => {
  const bottomRef = useRef<HTMLDivElement>(null);

  // Auto-scroll to bottom whenever messages or loading state changes
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, isLoading]);

  return (
    <div className="flex-1 min-h-0 overflow-y-auto px-3 py-3 space-y-1 bg-gray-50">
      {/* Welcome message shown when no conversation yet */}
      {messages.length === 0 && !isLoading && (
        <div className="flex items-start gap-2 mb-3">
          <div className="w-7 h-7 rounded-full bg-gradient-to-br from-yellow-300 to-yellow-500 flex items-center justify-center shrink-0 mt-0.5 shadow-sm">
            <HardHat size={14} className="text-yellow-900" strokeWidth={2} />
          </div>
          <div className="bg-white border border-gray-200 rounded-2xl rounded-bl-sm px-4 py-3 shadow-sm max-w-[92%]">
            <p className="text-sm text-gray-800 whitespace-pre-wrap leading-relaxed">
              {WELCOME_TEXT}
            </p>
          </div>
        </div>
      )}

      {/* Conversation messages */}
      {messages.map((msg) => (
        <MessageBubble key={msg.id} message={msg} />
      ))}

      {/* Typing indicator while waiting for response */}
      {isLoading && <TypingIndicator />}

      {/* Invisible anchor for auto-scroll */}
      <div ref={bottomRef} />
    </div>
  );
};

export default ChatContainer;
