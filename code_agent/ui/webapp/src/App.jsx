import React, {useEffect, useState, useRef, useCallback} from "react";
import {useStream, useMessages, useToolCalls} from "@langchain/react";
import {AIMessage, HumanMessage} from "@langchain/core/messages";
import "./styles.css";
import ToolCallRow from "./components/ToolCallRow";
import ProviderSelector from "./components/ProviderSelector";
import HitlSurface from "./components/HitlSurface";
import InputBar from "./components/InputBar";
import SubagentCard from "./components/SubagentCard";
import TodoList from "./components/TodoList";
import MarkdownRenderer from "./components/MarkdownRenderer";
import {apiFetch} from "./api";

const AGENT_URL =
    import.meta.env.VITE_API_BASE_URL ||
    (typeof window !== "undefined" ? window.location.origin : "http://localhost:8001");

function AppContent() {
    const stream = useStream({
        assistantId: "code_agent",
        apiUrl: AGENT_URL,
    });

    const messages = useMessages(stream);
    const toolCalls = useToolCalls(stream);
    const subagents = [...stream.subagents.values()];
    const todos = Array.isArray(stream.values?.todos) ? stream.values.todos : [];
    const interrupt = stream.interrupt;
    const isLoading = stream.isLoading;
    const threadId = stream.threadId;
    const error = stream.error;

    const [input, setInput] = useState("");
    const [theme, setTheme] = useState("light");
    const [providers, setProviders] = useState(null);
    const [activeProvider, setActiveProvider] = useState(null);
    const messagesEndRef = useRef(null);
    const messagesContainerRef = useRef(null);

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
        apiFetch("/providers")
            .then((res) => (res.ok ? res.json() : []))
            .then((data) => setProviders(data || []))
            .catch(() => setProviders([]));
    }, []);

    // Load active provider on mount
    useEffect(() => {
        apiFetch("/providers/active")
            .then((res) => (res.ok ? res.json() : null))
            .then((data) => {
                if (data) setActiveProvider(data);
            })
            .catch(() => setActiveProvider(null));
    }, []);

    // Auto-scroll messages on new content
    useEffect(() => {
        if (messagesEndRef.current) {
            messagesEndRef.current.scrollIntoView({behavior: "smooth"});
        }
    }, [messages, toolCalls, interrupt]);

    const handleSend = useCallback(async () => {
        const message = input.trim();
        if (!message || isLoading) return;
        setInput("");
        await stream.submit({
            messages: [{type: "human", content: message}],
        });
    }, [input, isLoading, stream]);

    const handleApprove = useCallback(async () => {
        await stream.respond({approved: true});
    }, [stream]);

    const handleReject = useCallback(async () => {
        await stream.respond({approved: false});
    }, [stream]);

    const handleCancel = useCallback(async () => {
        await stream.stop();
    }, [stream]);

    const onKeyDown = useCallback(
        (event) => {
            if (event.key === "Enter" && !event.shiftKey) {
                event.preventDefault();
                handleSend();
            }
        },
        [handleSend],
    );

    // Build a lookup of assembled tool calls by call id
    const toolCallsByCallId = useCallback(
        (calls) => {
            const map = new Map();
            calls.forEach((tc) => map.set(tc.callId, tc));
            return map;
        },
        [],
    );

    const toolCallMap = toolCallsByCallId(toolCalls);

    return (
        <div className="app-container">
            <header className="app-header">
                <div style={{display: "flex", justifyContent: "space-between", alignItems: "flex-start"}}>
                    <div>
                        <h1 style={{margin: 0}}>Code Agent Chat</h1>
                        <p className="app-header-subtitle">
                            Chat with the agent. It can read, edit, and create files for you.
                        </p>
                        {threadId && (
                            <p className="thread-id">
                                Thread: {threadId}
                            </p>
                        )}
                    </div>
                    <div className="header-actions">
                        <button
                            onClick={() => {
                                window.dispatchEvent(new CustomEvent("new-thread"));
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
                pending={interrupt}
                onApprove={handleApprove}
                onReject={handleReject}
            />

            {/* Todo List */}
            {todos.length > 0 && (
                <TodoList todos={todos}/>
            )}

            {/* Subagent Cards */}
            {subagents.length > 0 && (
                <div style={{marginBottom: "0.75rem"}}>
                    {subagents.map((subagent) => (
                        <SubagentCard key={subagent.id} subagent={subagent}/>
                    ))}
                </div>
            )}

            {/* Messages Area */}
            <section
                ref={messagesContainerRef}
                style={{
                    flex: 1,
                    overflowY: "auto",
                    border: `1px solid ${theme === "light" ? "#e5e5e5" : "#444"}`,
                    borderRadius: "8px",
                    padding: "1rem",
                    backgroundColor: theme === "light" ? "#fafafa" : "#2a2a2a",
                }}
            >
                {messages.length === 0 && (
                    <p style={{color: theme === "light" ? "#777" : "#aaa"}}>
                        No messages yet. Try: "Create a Python module with a factorial function."
                    </p>
                )}
                {messages.map((msg, index) => {
                    const isHuman = HumanMessage.isInstance(msg);
                    const isAi = AIMessage.isInstance(msg);
                    const msgToolCalls = isAi ? (msg.tool_calls || []) : [];

                    return (
                        <div
                            key={msg.id || index}
                            style={{
                                marginBottom: "0.75rem",
                                display: "flex",
                                justifyContent: isHuman ? "flex-end" : "flex-start",
                            }}
                        >
                            <div
                                style={{
                                    background: isHuman ? "#e5f0ff" : "#2a4a6a",
                                    border: `1px solid ${theme === "light" ? "#e5e5e5" : "#444"}`,
                                    borderRadius: "8px",
                                    padding: "0.6rem 0.8rem",
                                    maxWidth: "75%",
                                    whiteSpace: "pre-wrap",
                                    wordBreak: "break-word",
                                }}
                            >
                                <div
                                    style={{
                                        fontSize: "0.75rem",
                                        color: theme === "light" ? "#888" : "#aaa",
                                        marginBottom: "0.2rem",
                                    }}
                                >
                                    {isHuman ? "You" : "Agent"}
                                </div>
                                <div>
                                    <MarkdownRenderer
                                        content={typeof msg.text === "string" ? msg.text : ""}
                                    />
                                    {msgToolCalls.length > 0 && (
                                        <div style={{marginTop: "0.5rem"}}>
                                            {msgToolCalls.map((tc, toolIdx) => {
                                                const assembled = toolCallMap.get(tc.id);
                                                return (
                                                    <ToolCallRow
                                                        key={toolIdx}
                                                        toolCall={
                                                            assembled || {
                                                                name: tc.name,
                                                                input: tc.args,
                                                                status: "running",
                                                                callId: tc.id,
                                                            }
                                                        }
                                                    />
                                                );
                                            })}
                                        </div>
                                    )}
                                </div>
                            </div>
                        </div>
                    );
                })}
                {isLoading && !interrupt && (
                    <div
                        style={{
                            marginBottom: "0.75rem",
                            display: "flex",
                            justifyContent: "flex-start",
                            gap: "0.5rem",
                        }}
                    >
                        <div
                            style={{
                                background: "#ffffff",
                                border: `1px solid ${theme === "light" ? "#e5e5e5" : "#444"}`,
                                borderRadius: "8px",
                                padding: "0.6rem 0.8rem",
                                color: theme === "light" ? "#777" : "#aaa",
                            }}
                        >
                            <span
                                style={{
                                    animation: "spin 1s linear infinite",
                                    marginRight: "0.5rem",
                                }}
                            >
                                ⟳
                            </span>
                            Thinking...
                        </div>
                        <button
                            onClick={handleCancel}
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
                <div ref={messagesEndRef}/>
            </section>

            {error && (
                <p className="error-text">{typeof error === "string" ? error : String(error)}</p>
            )}

            {/* Input Bar */}
            <div className="input-bar">
                <InputBar
                    input={input}
                    setInput={setInput}
                    onSend={handleSend}
                    disabled={isLoading || !!interrupt}
                    onKeyDown={onKeyDown}
                />
                {isLoading && (
                    <p className="streaming-status">Streaming response...</p>
                )}
            </div>
        </div>
    );
}

export default function App() {
    const [streamKey, setStreamKey] = useState(0);

    useEffect(() => {
        const handler = () => setStreamKey((k) => k + 1);
        window.addEventListener("new-thread", handler);
        return () => window.removeEventListener("new-thread", handler);
    }, []);

    return <AppContent key={streamKey}/>;
}
