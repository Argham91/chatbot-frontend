import React, { useState } from 'react';
import { MessageSquare, X } from 'lucide-react';
import ChatPanel from './ChatPanel';

/**
 * ChatbotWidget — floating chat button + panel.
 *
 * Renders a fixed-position 💬 FAB button at the bottom-right of every page.
 * Clicking it toggles the chat panel open/closed.
 * The panel is positioned just above the button.
 *
 * Drop this component once inside AppShell and it appears on all pages
 * without any routing or sidebar changes.
 */
const ChatbotWidget: React.FC = () => {
  const [isOpen, setIsOpen] = useState(false);

  return (
    <>
      {/* Floating chat panel — rendered above the FAB */}
      {isOpen && (
        <div
          className="fixed z-50 drop-shadow-2xl"
          style={{ bottom: 88, right: 16 }}
        >
          <ChatPanel onClose={() => setIsOpen(false)} />
        </div>
      )}

      {/* FAB — always visible at bottom-right */}
      <button
        onClick={() => setIsOpen((prev) => !prev)}
        className="fixed z-50 w-14 h-14 rounded-full bg-blue-600 hover:bg-blue-700
                   shadow-lg hover:shadow-xl flex items-center justify-center
                   transition-all duration-200 group"
        style={{ bottom: 24, right: 24 }}
        title={isOpen ? 'Close Mines Assistant' : 'Open Mines Assistant'}
      >
        {isOpen ? (
          <X size={22} className="text-white" />
        ) : (
          <MessageSquare size={22} className="text-white" />
        )}

        {/* Tooltip label on hover */}
        {!isOpen && (
          <span
            className="absolute right-16 bg-gray-800 text-white text-xs px-2.5 py-1
                       rounded-lg whitespace-nowrap opacity-0 group-hover:opacity-100
                       transition-opacity pointer-events-none"
          >
            Mines Assistant
          </span>
        )}
      </button>
    </>
  );
};

export default ChatbotWidget;
