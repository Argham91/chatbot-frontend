import React, { useRef, useEffect } from 'react';
import { Send, Trash2 } from 'lucide-react';

interface Props {
  value: string;
  onChange: (val: string) => void;
  onSend: () => void;
  onClear: () => void;
  isLoading: boolean;
}

const ChatInput: React.FC<Props> = ({ value, onChange, onSend, onClear, isLoading }) => {
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  // Auto-resize textarea height (max ~3 lines)
  useEffect(() => {
    const ta = textareaRef.current;
    if (!ta) return;
    ta.style.height = 'auto';
    ta.style.height = Math.min(ta.scrollHeight, 80) + 'px';
  }, [value]);

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    // Send on Enter (not Shift+Enter — that adds a new line)
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      if (!isLoading && value.trim()) onSend();
    }
  };

  return (
    <div className="shrink-0 border-t border-gray-100 bg-white px-3 py-2.5 rounded-b-2xl">
      {/* Input row */}
      <div className="flex items-end gap-2">
        <textarea
          ref={textareaRef}
          rows={1}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          onKeyDown={handleKeyDown}
          disabled={isLoading}
          placeholder="Ask about production, quality, equipment…"
          className="flex-1 resize-none rounded-xl border border-gray-200 bg-gray-50 px-3 py-2
                     text-sm text-gray-800 placeholder-gray-400 outline-none
                     focus:border-blue-400 focus:ring-1 focus:ring-blue-100
                     disabled:opacity-50 disabled:cursor-not-allowed
                     transition-colors overflow-hidden leading-5"
        />
        <button
          onClick={onSend}
          disabled={isLoading || !value.trim()}
          className="w-9 h-9 bg-blue-600 hover:bg-blue-700 disabled:bg-gray-300
                     rounded-xl flex items-center justify-center shrink-0
                     transition-colors disabled:cursor-not-allowed"
          title="Send message (Enter)"
        >
          <Send size={15} className="text-white" />
        </button>
      </div>

      {/* Clear button */}
      <div className="flex justify-end mt-1.5">
        <button
          onClick={onClear}
          disabled={isLoading}
          className="flex items-center gap-1 text-[11px] text-gray-400 hover:text-red-500
                     transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
          title="Clear chat history"
        >
          <Trash2 size={11} />
          Clear chat
        </button>
      </div>
    </div>
  );
};

export default ChatInput;
