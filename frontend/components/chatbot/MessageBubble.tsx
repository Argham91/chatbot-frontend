import React from 'react';
import { HardHat, User } from 'lucide-react';
import { ChatMessage } from '../../types';
import ResponseRenderer from './ResponseRenderer';

interface Props {
  message: ChatMessage;
}

/** Formats a timestamp (ms) as HH:MM */
const formatTime = (ts: number): string => {
  const d = new Date(ts);
  return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
};

/** Animated 3-dot typing indicator shown while assistant is responding. */
export const TypingIndicator: React.FC = () => (
  <div className="flex items-start gap-2 mb-3">
    <div className="w-7 h-7 rounded-full bg-gradient-to-br from-yellow-300 to-yellow-500 flex items-center justify-center shrink-0 mt-0.5 shadow-sm">
      <HardHat size={14} className="text-yellow-900" strokeWidth={2} />
    </div>
    <div className="bg-white border border-gray-200 rounded-2xl rounded-bl-sm px-4 py-3 shadow-sm">
      <div className="flex gap-1 items-center h-4">
        <span className="w-2 h-2 bg-blue-400 rounded-full animate-bounce [animation-delay:0ms]" />
        <span className="w-2 h-2 bg-blue-400 rounded-full animate-bounce [animation-delay:150ms]" />
        <span className="w-2 h-2 bg-blue-400 rounded-full animate-bounce [animation-delay:300ms]" />
      </div>
    </div>
  </div>
);

const MessageBubble: React.FC<Props> = ({ message }) => {
  const isUser = message.role === 'user';

  if (isUser) {
    // User message — right-aligned, blue
    const text = message.blocks[0]?.content || '';
    return (
      <div className="flex items-end justify-end gap-2 mb-3">
        <div className="max-w-[80%]">
          <div className="bg-blue-600 text-white rounded-2xl rounded-br-sm px-4 py-2.5 shadow-sm">
            <p className="text-sm whitespace-pre-wrap leading-relaxed">{text}</p>
          </div>
          <p className="text-[10px] text-gray-400 text-right mt-1 pr-1">{formatTime(message.timestamp)}</p>
        </div>
        <div className="w-7 h-7 rounded-full bg-gray-200 flex items-center justify-center shrink-0 mb-5">
          <User size={14} className="text-gray-600" />
        </div>
      </div>
    );
  }

  // Assistant message — left-aligned, white card
  return (
    <div className="flex items-start gap-2 mb-3">
      <div className="w-7 h-7 rounded-full bg-gradient-to-br from-yellow-300 to-yellow-500 flex items-center justify-center shrink-0 mt-0.5 shadow-sm">
        <HardHat size={14} className="text-yellow-900" strokeWidth={2} />
      </div>
      <div className="max-w-[92%]">
        <div className="bg-white border border-gray-200 rounded-2xl rounded-bl-sm px-4 py-3 shadow-sm">
          <ResponseRenderer blocks={message.blocks} />
        </div>
        <p className="text-[10px] text-gray-400 mt-1 pl-1">{formatTime(message.timestamp)}</p>
      </div>
    </div>
  );
};

export default MessageBubble;
