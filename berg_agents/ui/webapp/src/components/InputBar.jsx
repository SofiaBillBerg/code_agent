import React from "react";

/**
 * InputBar component
 * Chat input field with send button
 * Disabled while streaming or HITL pending
 */
function InputBar({input, setInput, onSend, disabled, onKeyDown}) {
    return (
        <div className="input-bar-container">
            <textarea
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={onKeyDown}
                placeholder="Type a message..."
                rows={2}
                disabled={disabled}
                className="input-bar-textarea"
            />
            <button
                onClick={onSend}
                disabled={disabled || !input.trim()}
                className="input-bar-button"
            >
                {disabled ? "Sending..." : "Send"}
            </button>
        </div>
    );
}

export default InputBar;
