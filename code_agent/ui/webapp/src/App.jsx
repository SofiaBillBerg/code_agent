import React, {useEffect} from "react";
import "./styles.css";
import ToolCallRow from "./components/ToolCallRow";
import ProviderSelector from "./components/ProviderSelector";
import HitlSurface from "./components/HitlSurface";
import InputBar from "./components/InputBar";
import SubagentCard from "./components/SubagentCard";
import ThreadHistory from "./components/ThreadHistory";
import TodoList from "./components/TodoList";

/**
 * App component - orchestrator for the chat webapp
 * Handles SSE streaming, provider switching, HITL, and state management
 */
export default function App() {
    const [history, setHistory] = React.useState(() => {
        try {
            const raw = localStorage.getItem("code_agent_chat_history");
            return raw ? JSON.parse(raw) : [];
        } catch {
            return [];
        }
    });
    const [input, setInput] = React.useState("");
    const [providers, setProviders] = React.useState(null);
    const [activeProvider, setActiveProvider] = React.useState(null);
    const [streamingContent, setStreamingContent] = React.useState("");
    const [toolCalls, setToolCalls] = React.useState({});
    const [hitlPending, setHitlPending] = React.useState(null);
    const [streaming, setStreaming] = React.useState(false);
    const [error, setError] = React.useState(null);
    const [currentThreadId, setCurrentThreadId] = React.useState(null);
    const [theme, setTheme] = React.useState("light");
    const [connectionStatus, setConnectionStatus] = React.useState("disconnected");
    const [subagents, setSubagents] = React.useState({});
    const [todos, setTodos] = React.useState([]);
    const messagesRef = React.useRef(null);

    // Detect system color scheme preference
    useEffect(() => {
        const prefersDark = window.matchMedia("(prefers-color-scheme: dark)").matches;
        setTheme(prefersDark ? "dark" : "light");
    }, []);

    // Apply theme to root element
    useEffect(() => {
        const root = document.documentElement;
        root.setAttribute("data-theme", theme);
        localStorage.setItem("theme", theme);
    }, [theme]);

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

    // Connection state tracking
    useEffect(() => {
        let visible = true;
        let heartbeatTimer = null;
        let lastMessageTime = Date.now();

        const updateConnectionStatus = () => {
            const now = Date.now();
            const timeSinceLastMessage = now - lastMessageTime;

            if (streaming) {
                setConnectionStatus("live");
            } else if (hitlPending) {
                setConnectionStatus("pending");
            } else if (visible) {
                // Check if we received a message recently
                if (timeSinceLastMessage < 30000) {
                    setConnectionStatus("live");
                } else if (timeSinceLastMessage < 120000) {
                    setConnectionStatus("reconnecting");
                } else {
                    setConnectionStatus("disconnected");
                }
            }
        };

        const handleVisibilityChange = () => {
            visible = !document.hidden;
            updateConnectionStatus();
        };

        const handleMessageEvent = () => {
            lastMessageTime = Date.now();
            updateConnectionStatus();
        };

        // Listen for SSE events to update connection status
        const sseEventListener = (event) => {
            if (event.type) {
                lastMessageTime = Date.now();
                updateConnectionStatus();
            }
        };

        document.addEventListener("visibilitychange", handleVisibilityChange);

        return () => {
            document.removeEventListener("visibilitychange", handleVisibilityChange);
            if (heartbeatTimer) clearInterval(heartbeatTimer);
        };
    }, [streaming, hitlPending]);

    // Auto-scroll messages on new content
    useEffect(() => {
        if (messagesRef.current) {
            messagesRef.current.scrollTop = messagesRef.current.scrollHeight;
        }
    }, [history, streamingContent, toolCalls, hitlPending]);

    // Save history to localStorage
    useEffect(() => {
        try {
            localStorage.setItem("code_agent_chat_history", JSON.stringify(history));
        } catch {
            // ignore storage failures
        }
    }, [history]);

    // Send message via SSE streaming endpoint
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

            case "todos":
                setTodos(event.todos || []);
                break;

            case "subagent_start":
                setSubagents((prev) => ({
                    ...prev,
                    [event.id]: {
                        id: event.id,
                        name: event.name,
                        status: "running",
                        toolCalls: [],
                        output: "",
                    },
                }));
                break;

            case "subagent_end":
                setSubagents((prev) => {
                    const existing = prev[event.id];
                    if (!existing) return prev;
                    return {
                        ...prev,
                        [event.id]: {
                            ...existing,
                            status: event.status === "error" ? "failed" : "completed",
                        },
                    };
                });
                break;

            case "ping":
                // Keep connection alive - no state update needed
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
            sendStream().then(r => {
            }).catch(e => {
            });
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
        <div className="app-container">
            <header className="app-header">
                <div style={{display: "flex", justifyContent: "space-between", alignItems: "flex-start"}}>
                    <div>
                        <h1 style={{margin: 0}}>Code Agent Chat</h1>
                        <p className="app-header-subtitle">
                            Chat with the agent. It can read, edit, and create files for you.
                        </p>
                        {currentThreadId && (
                            <p className="thread-id">
                                Thread: {currentThreadId}
                            </p>
                        )}
                    </div>
                    <div className="header-actions">
                        <button
                            onClick={() => {
                                setCurrentThreadId(null);
                                setHistory([]);
                                setStreamingContent("");
                                setToolCalls({});
                                setHitlPending(null);
                                setError(null);
                                localStorage.removeItem("code_agent_chat_history");
                            }}
                            className="btn-secondary"
                        >
                            New Thread
                        </button>
                        <button
                            onClick={() => setTheme(theme === "light" ? "dark" : "light")}
                            className="btn-secondary"
                            aria-label="Toggle dark mode"
                        >
                            {theme === "light" ? "🌙" : "☀️"}
                        </button>
                    </div>
                </div>
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

            {/* Todo List */}
            {todos.length > 0 && (
                <TodoList todos={todos}/>
            )}

            {/* Subagent Cards */}
            {Object.values(subagents).length > 0 && (
                <div style={{marginBottom: "0.75rem"}}>
                    {Object.values(subagents).map((subagent) => (
                        <SubagentCard key={subagent.id} subagent={subagent}/>
                    ))}
                </div>
            )}

            {/* Thread History */}
            {currentThreadId && (
                <div style={{marginBottom: "0.75rem"}}>
                    <ThreadHistory history={history}/>
                </div>
            )}

            {/* Messages Area */}
            <section
                ref={messagesRef}
                style={{
                    flex: 1,
                    overflowY: "auto",
                    border: `1px solid ${theme === "light" ? "#e5e5e5" : "#444"}`,
                    borderRadius: "8px",
                    padding: "1rem",
                    backgroundColor: theme === "light" ? "#fafafa" : "#2a2a2a",
                }}
            >
                {history.length === 0 && !streamingContent && (
                    <p style={{color: theme === "light" ? "#777" : "#aaa"}}>
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
                                background: item.role === "user" ? "#e5f0ff" : "#2a4a6a",
                                border: `1px solid ${theme === "light" ? "#e5e5e5" : "#444"}`,
                                borderRadius: "8px",
                                padding: "0.6rem 0.8rem",
                                maxWidth: "75%",
                                whiteSpace: "pre-wrap",
                                wordBreak: "break-word",
                            }}
                        >
                            <div style={{
                                fontSize: "0.75rem",
                                color: theme === "light" ? "#888" : "#aaa",
                                marginBottom: "0.2rem"
                            }}>
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
                    <div
                        style={{marginBottom: "0.75rem", display: "flex", justifyContent: "flex-start", gap: "0.5rem"}}>
                        <div
                            style={{
                                background: "#ffffff",
                                border: `1px solid ${theme === "light" ? "#e5e5e5" : "#444"}`,
                                borderRadius: "8px",
                                padding: "0.6rem 0.8rem",
                                color: theme === "light" ? "#777" : "#aaa",
                            }}
                        >
                            <span style={{animation: "spin 1s linear infinite", marginRight: "0.5rem"}}>⟳</span>
                            Thinking...
                        </div>
                        <button
                            onClick={async () => {
                                if (!currentThreadId) return;
                                try {
                                    await fetch("/chat/cancel", {
                                        method: "POST",
                                        headers: {"Content-Type": "application/json"},
                                        body: JSON.stringify({thread_id: currentThreadId}),
                                    });
                                } catch (err) {
                                    console.error("Cancel failed:", err);
                                }
                            }}
                            style={{
                                padding: "0.4rem 0.75rem",
                                borderRadius: "4px",
                                border: "1px solid #b00020",
                                background: "rgba(176, 0, 32, 0.1)",
                                color: "#b00020",
                                fontSize: "0.8rem",
                                cursor: "pointer",
                            }}
                        >
                            Cancel
                        </button>
                    </div>
                )}
            </section>

            {error && (
                <p className="error-text">{error}</p>
            )}

            {/* Input Bar */}
            <div className="input-bar">
                <InputBar
                    input={input}
                    setInput={setInput}
                    onSend={sendStream}
                    disabled={streaming || !!hitlPending}
                    onKeyDown={onKeyDown}
                />
                {streaming && (
                    <p className="streaming-status">Streaming response...</p>
                )}
            </div>
        </div>
    );
}

/**
 * ConnectionBadge component
 * Shows connection state: live / reconnecting / disconnected
 */
function ConnectionBadge({status}) {
    const statusMap = {
        live: {color: "#2e7d32", label: "Live"},
        reconnecting: {color: "#f9a825", label: "Reconnecting"},
        disconnected: {color: "#b00020", label: "Disconnected"},
    };

    const s = statusMap[status] || statusMap.disconnected;

    return (
        <div
            style={{
                padding: "0.4rem 0.75rem",
                borderRadius: "4px",
                background: s.color === "#b00020" ? "rgba(176, 0, 32, 0.1)" : "rgba(46, 125, 50, 0.1)",
                color: s.color,
                fontSize: "0.85rem",
                fontWeight: "500",
                border: `1px solid ${s.color}`,
            }}
        >
            {s.label}
        </div>
    );
}

