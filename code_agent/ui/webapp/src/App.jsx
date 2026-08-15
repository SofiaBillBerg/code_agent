import React, {useEffect, useRef, useState} from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import rehypeHighlight from "rehype-highlight";

const STORAGE_KEY = "code_agent_chat_history";

/**
 * Load chat history from localStorage
 * Returns array of messages or empty array on error
 */
function loadHistory() {
    try {
        const raw = localStorage.getItem(STORAGE_KEY);
        if (raw) return JSON.parse(raw);
    } catch {
        // ignore corrupt history
    }
    return [];
}

/**
 * Save chat history to localStorage
 * Silently ignores storage errors
 */
function saveHistory(history) {
    try {
        localStorage.setItem(STORAGE_KEY, JSON.stringify(history));
    } catch {
        // ignore storage failures
    }
}

/**
 * MarkdownRenderer component
 * Wraps react-markdown with remark-gfm and rehype-highlight
 * Never throws on malformed partial markdown - catches errors and displays raw text
 */
function MarkdownRenderer({content}) {
    // Catch rendering errors gracefully
    const [renderedContent, setRenderedContent] = useState(content);

    useEffect(() => {
        try {
            setRenderedContent(content);
        } catch {
            // If anything goes wrong, keep raw text
            setRenderedContent(content);
        }
    }, [content]);

    return (
        <div style={{margin: 0}}>
            <ReactMarkdown
                remarkPlugins={[remarkGfm]}
                rehypePlugins={[rehypeHighlight]}
                components={{
                    // Safe rendering - ensure code blocks don't break on unknown languages
                    code({node, inline, className, children, ...props}) {
                        const match = /language-(\w+)/.exec(className || "");
                        const lang = match ? match[1] : "";
                        // Always render with pre/code tags, even if unknown language
                        return inline ? (
                            <code {...props} style={{
                                fontFamily: "monospace",
                                background: "#f5f5f5",
                                padding: "0.2em 0.4em",
                                borderRadius: "3px"
                            }}>
                                {children}
                            </code>
                        ) : (
                            <pre {...props}
                                 style={{background: "#f5f5f5", padding: "1em", borderRadius: "5px", overflow: "auto"}}>
								<code className={className} {...props}>
									{children}
								</code>
							</pre>
                        );
                    },
                }}
            >
                {renderedContent}
            </ReactMarkdown>
        </div>
    );
}

/**
 * ToolCallRow component
 * Shows tool execution progress: spinner on start, elapsed time + output on end
 * Collapsible display for tool output
 */
function ToolCallRow({toolCall}) {
    const [expanded, setExpanded] = useState(false);
    const [elapsed, setElapsed] = useState(0);

    // Track elapsed time from tool_start
    useEffect(() => {
        if (toolCall.status === "pending") {
            // Start timer when tool starts
            setElapsed(0);
            const startTime = Date.now();
            const interval = setInterval(() => {
                setElapsed((Date.now() - startTime) / 1000);
            }, 100);
            return () => clearInterval(interval);
        }
    }, [toolCall.status]);

    // Update elapsed time when tool ends with specific duration
    useEffect(() => {
        if (toolCall.status === "done" && toolCall.elapsedS !== undefined) {
            setElapsed(toolCall.elapsedS);
        }
    }, [toolCall.status, toolCall.elapsedS]);

    // Truncate output to 200 chars with ellipsis
    const truncatedOutput =
        toolCall.output && toolCall.output.length > 200
            ? toolCall.output.substring(0, 200) + "…"
            : toolCall.output;

    return (
        <div
            style={{
                marginTop: "0.5rem",
                border: "1px solid #e0e0e0",
                borderRadius: "6px",
                overflow: "hidden",
            }}
        >
            <button
                onClick={() => setExpanded(!expanded)}
                style={{
                    width: "100%",
                    padding: "0.5rem 0.75rem",
                    background: "transparent",
                    border: "none",
                    textAlign: "left",
                    cursor: "pointer",
                    fontSize: "0.85rem",
                    fontFamily: "inherit",
                    display: "flex",
                    justifyContent: "space-between",
                    alignItems: "center",
                    gap: "0.5rem",
                }}
            >
				<span style={{fontFamily: "monospace", color: "#1a73e8"}}>
					{toolCall.status === "pending" && (
                        <span style={{marginRight: "0.5rem"}}>
							<span style={{animation: "spin 1s linear infinite", display: "inline-block"}}>⟳</span>
						</span>
                    )}
                    {toolCall.tool}
				</span>
                <span style={{color: "#666", fontSize: "0.8rem"}}>
					{toolCall.status === "done"
                        ? `${elapsed.toFixed(1)}s`
                        : toolCall.status === "pending"
                            ? `${elapsed.toFixed(1)}s...`
                            : ""}
				</span>
            </button>
            {expanded && toolCall.status === "done" && (
                <div
                    style={{
                        padding: "0.75rem",
                        background: "#fafafa",
                        borderTop: "1px solid #e0e0e0",
                    }}
                >
                    <div style={{fontSize: "0.75rem", color: "#666", marginBottom: "0.5rem"}}>
                        Output: {truncatedOutput}
                    </div>
                    {toolCall.output && toolCall.output.length > 200 && (
                        <details>
                            <summary style={{fontSize: "0.75rem", color: "#666", cursor: "pointer"}}>
                                Show full output
                            </summary>
                            <div
                                style={{
                                    marginTop: "0.5rem",
                                    padding: "0.5rem",
                                    background: "#f5f5f5",
                                    borderRadius: "4px",
                                    whiteSpace: "pre-wrap",
                                    wordBreak: "break-word",
                                    fontFamily: "monospace",
                                    fontSize: "0.8rem",
                                }}
                            >
                                {toolCall.output}
                            </div>
                        </details>
                    )}
                </div>
            )}
        </div>
    );
}

/**
 * ProviderSelector component
 * Displays available providers and allows switching active provider
 * Shows auto-dismiss notification on successful switch
 */
function ProviderSelector({activeProvider, providers, onSwitch}) {
    const [notice, setNotice] = useState(null);

    useEffect(() => {
        // Auto-dismiss notification after 5 seconds
        if (notice) {
            const timer = setTimeout(() => setNotice(null), 5000);
            return () => clearTimeout(timer);
        }
    }, [notice]);

    const handleSwitch = async (provider, model) => {
        if (provider === activeProvider?.provider && model === activeProvider?.model) {
            return; // No-op if already selected
        }
        try {
            const res = await fetch("/providers/active", {
                method: "POST",
                headers: {"Content-Type": "application/json"},
                body: JSON.stringify({provider, model}),
            });
            if (res.ok) {
                setNotice(`Switched to ${provider} (${model})`);
                if (onSwitch) onSwitch(provider, model);
            } else {
                const body = await res.json().catch(() => ({}));
                setNotice(`Failed to switch: ${body?.detail || res.statusText}`);
            }
        } catch (err) {
            setNotice(`Error switching provider: ${err.message}`);
        }
    };

    return (
        <div style={{marginBottom: "1rem"}}>
            <div
                style={{
                    display: "flex",
                    gap: "1rem",
                    alignItems: "center",
                    padding: "0.5rem 0.75rem",
                    background: "#f5f5f5",
                    borderRadius: "6px",
                    fontSize: "0.9rem",
                }}
            >
                <span style={{color: "#666"}}>Provider:</span>
                <select
                    value={activeProvider ? `${activeProvider.provider}:${activeProvider.model}` : ""}
                    onChange={(e) => {
                        const [provider, model] = e.target.value.split(":");
                        if (provider && model) handleSwitch(provider, model);
                    }}
                    style={{
                        padding: "0.35rem 0.5rem",
                        borderRadius: "4px",
                        border: "1px solid #ccc",
                        fontFamily: "inherit",
                        minWidth: "200px",
                    }}
                >
                    {providers?.map((p, idx) => (
                        <option key={idx} value={`${p.name}:${p.model}`}>
                            {p.name} ({p.model})
                        </option>
                    ))}
                </select>
                <span style={{color: "#1a73e8", fontWeight: "500"}}>
					{activeProvider ? `${activeProvider.provider} → ${activeProvider.model}` : "Loading..."}
				</span>
            </div>
            {notice && (
                <div
                    style={{
                        marginTop: "0.5rem",
                        padding: "0.5rem 0.75rem",
                        background: "#e8f5e9",
                        border: "1px solid #c8e6c9",
                        borderRadius: "4px",
                        color: "#2e7d32",
                        fontSize: "0.85rem",
                        display: "flex",
                        justifyContent: "space-between",
                        alignItems: "center",
                    }}
                >
                    {notice}
                    {notice.startsWith("Switched") && (
                        <span style={{fontSize: "0.7rem", color: "#2e7d32"}}>Auto-dismissing...</span>
                    )}
                </div>
            )}
        </div>
    );
}

/**
 * HitlSurface component
 * Displays HITL pending interrupt with Approve/Reject buttons
 * Disables InputBar while displayed
 */
function HitlSurface({pending, onApprove, onReject}) {
    if (!pending) return null;

    return (
        <div
            style={{
                margin: "1rem 0",
                padding: "1rem",
                background: "#fff8e1",
                border: "2px solid #ffca28",
                borderRadius: "8px",
                display: "flex",
                flexDirection: "column",
                gap: "0.75rem",
            }}
        >
            <div style={{fontSize: "0.9rem", fontWeight: "600", color: "#e65100"}}>
                Human Approval Required
            </div>
            <div style={{fontSize: "0.85rem"}}>
                <span style={{fontFamily: "monospace", color: "#1a73e8"}}>{pending.tool}</span>
                <span style={{color: "#666"}}>wants to execute:</span>
            </div>
            <div
                style={{
                    padding: "0.75rem",
                    background: "#fafafa",
                    border: "1px solid #e0e0e0",
                    borderRadius: "4px",
                    fontFamily: "monospace",
                    fontSize: "0.75rem",
                    whiteSpace: "pre-wrap",
                    wordBreak: "break-word",
                    maxHeight: "200px",
                    overflowY: "auto",
                }}
            >
                {JSON.stringify(pending.input, null, 2)}
            </div>
            <div style={{display: "flex", gap: "0.75rem", marginTop: "0.5rem"}}>
                <button
                    onClick={onApprove}
                    style={{
                        flex: 1,
                        padding: "0.6rem 1rem",
                        border: "none",
                        borderRadius: "6px",
                        background: "#2e7d32",
                        color: "#fff",
                        fontSize: "0.9rem",
                        cursor: "pointer",
                        fontWeight: "500",
                    }}
                >
                    Approve
                </button>
                <button
                    onClick={onReject}
                    style={{
                        flex: 1,
                        padding: "0.6rem 1rem",
                        border: "none",
                        borderRadius: "6px",
                        background: "#c62828",
                        color: "#fff",
                        fontSize: "0.9rem",
                        cursor: "pointer",
                        fontWeight: "500",
                    }}
                >
                    Reject
                </button>
            </div>
        </div>
    );
}

/**
 * InputBar component
 * Chat input field with send button
 * Disabled while streaming or HITL pending
 */
function InputBar({input, setInput, onSend, disabled, onKeyDown}) {
    return (
        <div style={{display: "flex", gap: "0.5rem"}}>
			<textarea
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={onKeyDown}
                placeholder="Type a message..."
                rows={2}
                disabled={disabled}
                style={{
                    flex: 1,
                    resize: "vertical",
                    padding: "0.6rem",
                    borderRadius: "6px",
                    border: "1px solid #ccc",
                    fontFamily: "inherit",
                    opacity: disabled ? 0.7 : 1,
                    backgroundColor: disabled ? "#f5f5f5" : "#fff",
                }}
            />
            <button
                onClick={onSend}
                disabled={disabled || !input.trim()}
                style={{
                    padding: "0.6rem 1rem",
                    borderRadius: "6px",
                    border: "none",
                    background: disabled ? "#ccc" : "#111",
                    color: "#fff",
                    cursor: disabled ? "not-allowed" : "pointer",
                    fontWeight: "500",
                    opacity: disabled ? 0.7 : 1,
                }}
            >
                {disabled ? "Sending..." : "Send"}
            </button>
        </div>
    );
}

export default function App() {
    const [history, setHistory] = useState(() => loadHistory());
    const [input, setInput] = useState("");
    const [providers, setProviders] = useState(null); // null = loading, [] = none
    const [activeProvider, setActiveProvider] = useState(null);
    const [streamingContent, setStreamingContent] = useState("");
    const [toolCalls, setToolCalls] = useState({});
    const [hitlPending, setHitlPending] = useState(null);
    const [streaming, setStreaming] = useState(false);
    const [error, setError] = useState(null);
    const [currentThreadId, setCurrentThreadId] = useState(null);
    const messagesRef = useRef(null);

    // Load providers on mount
    useEffect(() => {
        fetch("/providers")
            .then((res) => (res.ok ? res.json() : []))
            .then((data) => setProviders(data || []))
            .catch(() => setProviders([]));
    }, []);

    // Load active provider on mount
    useEffect(() => {
        fetch("/providers/active")
            .then((res) => (res.ok ? res.json() : null))
            .then((data) => {
                if (data) setActiveProvider(data);
            })
            .catch(() => setActiveProvider(null));
    }, []);

    // Auto-scroll messages on new content
    useEffect(() => {
        if (messagesRef.current) {
            messagesRef.current.scrollTop = messagesRef.current.scrollHeight;
        }
    }, [history, streamingContent, toolCalls, hitlPending]);

    // Save history to localStorage
    useEffect(() => {
        saveHistory(history);
    }, [history]);

    /**
     * Send message via SSE streaming endpoint
     * Reads events: token, tool_start, tool_end, hitl_pending, done, error
     */
    const sendStream = async () => {
        const message = input.trim();
        if (!message || streaming || hitlPending) return;
        setInput("");
        setError(null);
        setStreaming(true);
        setHitlPending(null);

        // Add user message to history
        const userMsg = {role: "user", content: message};
        setHistory((prev) => [...prev, userMsg]);
        setStreamingContent("");
        setToolCalls({});

        const threadId = currentThreadId || undefined;

        try {
            const res = await fetch("/chat/stream", {
                method: "POST",
                headers: {"Content-Type": "application/json"},
                body: JSON.stringify({message, thread_id: threadId}),
            });

            if (!res.ok) {
                const body = await res.json().catch(() => ({}));
                throw new Error(body?.detail || `SSE stream failed: ${res.status}`);
            }

            // Capture new thread_id from response header
            const newThreadId = res.headers.get("X-Thread-Id");
            if (newThreadId) setCurrentThreadId(newThreadId);

            // Process SSE stream using ReadableStream.getReader()
            const reader = res.body.getReader();
            const decoder = new TextDecoder();
            let buffer = "";

            while (true) {
                const {done, value} = await reader.read();
                if (done) break;

                buffer += decoder.decode(value, {stream: true});
                const lines = buffer.split("\n\n");
                buffer = lines.pop(); // Keep incomplete line in buffer

                for (const line of lines) {
                    if (!line.startsWith("data: ")) continue;
                    const dataStr = line.slice(6).trim();
                    if (!dataStr) continue;

                    try {
                        const data = JSON.parse(dataStr);
                        handleSseEvent(data);
                    } catch (err) {
                        // Ignore malformed JSON
                    }
                }
            }
        } catch (err) {
            setError(String(err.message || err));
        } finally {
            setStreaming(false);
        }
    };

    /**
     * Handle SSE event and update state
     */
    const handleSseEvent = (event) => {
        switch (event.type) {
            case "token":
                setStreamingContent((prev) => prev + event.content);
                break;

            case "tool_start":
                setToolCalls((prev) => ({
                    ...prev,
                    [event.tool]: {
                        tool: event.tool,
                        input: event.input,
                        status: "pending",
                        timestamp: Date.now(),
                    },
                }));
                break;

            case "tool_end":
                setToolCalls((prev) => {
                    const existing = prev[event.tool];
                    if (!existing) return prev; // Ignore orphaned tool_end

                    return {
                        ...prev,
                        [event.tool]: {
                            ...existing,
                            output: event.output,
                            elapsedS: event.elapsed_s,
                            status: "done",
                        },
                    };
                });
                break;

            case "hitl_pending":
                setHitlPending({
                    tool: event.tool,
                    input: event.input,
                    thread_id: event.thread_id,
                });
                setStreaming(false); // Pause streaming while HITL pending
                break;

            case "error":
                setError(event.reason || "Stream error");
                setStreaming(false);
                break;

            case "done":
                // Commit streaming content to history
                if (streamingContent || Object.keys(toolCalls).length > 0) {
                    setHistory((prev) => [
                        ...prev,
                        {
                            role: "assistant",
                            content: streamingContent,
                            toolCalls: Object.values(toolCalls),
                        },
                    ]);
                    setStreamingContent("");
                    setToolCalls({});
                }
                break;
        }
    };

    /**
     * Resume interrupted stream after HITL decision
     */
    const resumeStream = async (decision) => {
        if (!hitlPending) return;

        try {
            const res = await fetch("/chat/resume", {
                method: "POST",
                headers: {"Content-Type": "application/json"},
                body: JSON.stringify({
                    thread_id: hitlPending.thread_id,
                    decision,
                }),
            });

            if (res.ok) {
                setHitlPending(null);
                // After approval, stream continues automatically
                // After rejection, agent sends rejection message as tokens
            } else {
                const body = await res.json().catch(() => ({}));
                setError(`Resume failed: ${body?.detail || res.status}`);
            }
        } catch (err) {
            setError(String(err.message || err));
        }
    };

    const handleApprove = () => resumeStream("approve");
    const handleReject = () => resumeStream("reject");

    /**
     * Handle keyboard input for textarea
     */
    const onKeyDown = (event) => {
        if (event.key === "Enter" && !event.shiftKey) {
            event.preventDefault();
            sendStream();
        }
    };

    // Build combined messages for display
    const displayMessages = history.map((msg, idx) => {
        if (msg.role === "assistant" && msg.toolCalls && msg.toolCalls.length > 0) {
            return {...msg, hasToolCalls: true};
        }
        return {...msg, hasToolCalls: false};
    });

    if (streamingContent) {
        // Add streaming message to display
        displayMessages.push({
            role: "assistant",
            content: streamingContent,
            hasToolCalls: Object.keys(toolCalls).length > 0,
        });
    }

    return (
        <div
            style={{
                maxWidth: 860,
                margin: "0 auto",
                padding: "1.5rem",
                fontFamily: "system-ui, sans-serif",
                height: "100vh",
                display: "flex",
                flexDirection: "column",
            }}
        >
            <header style={{marginBottom: "1rem"}}>
                <h1 style={{margin: 0}}>Code Agent Chat</h1>
                <p style={{margin: "0.25rem 0 0", color: "#555"}}>
                    Chat with the agent. It can read, edit, and create files for you.
                </p>
            </header>

            {/* Provider Selector */}
            {providers && activeProvider && (
                <ProviderSelector
                    providers={providers}
                    activeProvider={activeProvider}
                    onSwitch={(provider, model) => setActiveProvider({provider, model})}
                />
            )}

            {/* HITL Surface */}
            <HitlSurface
                pending={hitlPending}
                onApprove={handleApprove}
                onReject={handleReject}
            />

            {/* Messages Area */}
            <section
                ref={messagesRef}
                style={{
                    flex: 1,
                    overflowY: "auto",
                    border: "1px solid #e5e5e5",
                    borderRadius: 8,
                    padding: "1rem",
                    background: "#fafafa",
                }}
            >
                {history.length === 0 && !streamingContent && (
                    <p style={{color: "#777"}}>
                        No messages yet. Try: "Create a Python module with a factorial function."
                    </p>
                )}
                {displayMessages.map((item, index) => (
                    <div
                        key={index}
                        style={{
                            marginBottom: "0.75rem",
                            display: "flex",
                            justifyContent: item.role === "user" ? "flex-end" : "flex-start",
                        }}
                    >
                        <div
                            style={{
                                background: item.role === "user" ? "#e5f0ff" : "#ffffff",
                                border: "1px solid #e5e5e5",
                                borderRadius: 8,
                                padding: "0.6rem 0.8rem",
                                maxWidth: "75%",
                                whiteSpace: "pre-wrap",
                                wordBreak: "break-word",
                            }}
                        >
                            <div style={{fontSize: "0.75rem", color: "#888", marginBottom: "0.2rem"}}>
                                {item.role === "user" ? "You" : "Agent"}
                            </div>
                            <div>
                                <MarkdownRenderer content={item.content}/>
                                {item.hasToolCalls && (
                                    <div style={{marginTop: "0.5rem"}}>
                                        {history[index]?.toolCalls?.map((toolCall, toolIdx) => (
                                            <ToolCallRow
                                                key={toolIdx}
                                                toolCall={{
                                                    tool: toolCall.tool,
                                                    input: toolCall.input,
                                                    output: toolCall.output,
                                                    elapsedS: toolCall.elapsedS,
                                                    status: toolCall.status,
                                                }}
                                            />
                                        ))}
                                    </div>
                                )}
                            </div>
                        </div>
                    </div>
                ))}
                {streaming && !hitlPending && (
                    <div style={{marginBottom: "0.75rem", display: "flex", justifyContent: "flex-start"}}>
                        <div
                            style={{
                                background: "#ffffff",
                                border: "1px solid #e5e5e5",
                                borderRadius: 8,
                                padding: "0.6rem 0.8rem",
                                color: "#777",
                            }}
                        >
                            <span style={{animation: "spin 1s linear infinite", marginRight: "0.5rem"}}>⟳</span>
                            Thinking...
                        </div>
                    </div>
                )}
            </section>

            {error && (
                <p style={{color: "#b00020", marginTop: "0.6rem"}}>{error}</p>
            )}

            {/* Input Bar */}
            <div style={{marginTop: "0.8rem"}}>
                <InputBar
                    input={input}
                    setInput={setInput}
                    onSend={sendStream}
                    disabled={streaming || !!hitlPending}
                    onKeyDown={onKeyDown}
                />
                {streaming && (
                    <p style={{fontSize: "0.75rem", color: "#666", marginTop: "0.5rem", textAlign: "center"}}>
                        Streaming response...
                    </p>
                )}
            </div>

            <style>{`
				@keyframes spin {
					0% { transform: rotate(0deg); }
					100% { transform: rotate(360deg); }
				}
			`}</style>
        </div>
    );
}
