import React, {useEffect, useState, useRef, useCallback} from "react";
import {useCustomStream} from "./useCustomStream.js";
import ToolCallRow from "./components/ToolCallRow";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import rehypeHighlight from "rehype-highlight";

const AGENT_URL =
    import.meta.env.VITE_API_BASE_URL ||
    (typeof window !== "undefined" ? window.location.origin : "http://localhost:8001");

function AppContent() {
    const stream = useCustomStream(AGENT_URL, "code-agent");

    const {
        messages,
        toolCalls,
        isLoading,
        error,
        interrupt,
        submit,
        respond,
    } = stream;

    const [input, setInput] = useState("");
    const messagesEndRef = useRef(null);

    useEffect(() => {
        console.log("[DEBUG] Stream state changed:", {
            isLoading,
            threadId: stream.threadId,
            error,
            messageCount: messages.length,
            toolCallCount: toolCalls.length,
            interrupt,
        });
    }, [isLoading, stream.threadId, error, messages, toolCalls, interrupt]);

    useEffect(() => {
        if (messagesEndRef.current) {
            messagesEndRef.current.scrollIntoView({behavior: "smooth"});
        }
    }, [messages, toolCalls, interrupt]);

    const handleSend = useCallback(async () => {
        const message = input.trim();
        console.log("[DEBUG] handleSend called:", {message, isLoading, threadId: stream.threadId});
        if (!message || isLoading) {
            console.log("[DEBUG] handleSend aborted");
            return;
        }
        setInput("");
        try {
            console.log("[DEBUG] Calling submit...");
            await submit({
                messages: [{type: "human", content: message}],
            });
            console.log("[DEBUG] submit completed");
        } catch (err) {
            console.error("[DEBUG] submit error:", err);
        }
    }, [input, isLoading, submit, stream.threadId]);

    const handleApprove = useCallback(async () => {
        console.log("[DEBUG] handleApprove called");
        await respond({approved: true});
    }, [respond]);

    const handleReject = useCallback(async () => {
        console.log("[DEBUG] handleReject called");
        await respond({approved: false});
    }, [respond]);

    const onKeyDown = useCallback(
        (event) => {
            if (event.key === "Enter" && !event.shiftKey) {
                event.preventDefault();
                handleSend();
            }
        },
        [handleSend],
    );

    const toolCallMap = useCallback((calls) => {
        const map = new Map();
        calls.forEach((tc) => map.set(tc.callId || tc.id, tc));
        return map;
    }, []);

    const assembledToolCalls = toolCallMap(toolCalls);

    return (
        <div style={{padding: "1rem", maxWidth: "800px", margin: "0 auto"}}>
            <h1>Code Agent Chat</h1>
            {stream.threadId && <p>Thread: {stream.threadId}</p>}
            {error && <p style={{color: "red"}}>Error: {typeof error === "string" ? error : JSON.stringify(error)}</p>}

            <div
                style={{
                    border: "1px solid #ccc",
                    borderRadius: "8px",
                    padding: "1rem",
                    minHeight: "300px",
                    maxHeight: "500px",
                    overflowY: "auto",
                    marginBottom: "1rem",
                }}
            >
                {messages.length === 0 && <p>No messages yet.</p>}
                {messages.filter(m => {
                    if (!m) return false;
                    const c = m.text ?? (typeof m.content === "string" ? m.content : "");
                    const hasText = typeof c === "string" ? c.trim().length > 0 : !!c;
                    const hasTools = (m.tool_calls || m.toolCalls || []).length > 0;
                    return hasText || hasTools;
                }).map((msg, index) => {
                    // useCustomStream returns plain objects {id, role, text}; also handle LangChain BaseMessage fallback
                    const role = msg.role || msg.getType?.() || "unknown";
                    const isHuman = role === "human" || role === "user";
                    const isAi = role === "ai" || role === "assistant";
                    const content = msg.text ?? (typeof msg.content === "string" ? msg.content : JSON.stringify(msg.content ?? ""));
                    const msgToolCalls = isAi ? (msg.tool_calls || msg.toolCalls || []) : [];

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
                                    background: isHuman ? "#e5f0ff" : "#f0f0f0",
                                    borderRadius: "8px",
                                    padding: "0.6rem 0.8rem",
                                    maxWidth: "75%",
                                }}
                            >
                                <div style={{fontSize: "0.75rem", color: "#888", marginBottom: "0.2rem"}}>
                                    {isHuman ? "You" : "Agent"}
                                </div>
                                <div style={{lineHeight: "1.5"}}>
                                    <ReactMarkdown
                                        remarkPlugins={[remarkGfm]}
                                        rehypePlugins={[rehypeHighlight]}
                                    >
                                        {content}
                                    </ReactMarkdown>
                                </div>
                                {msgToolCalls.length > 0 && (
                                    <div style={{marginTop: "0.5rem"}}>
                                        {msgToolCalls.map((tc, toolIdx) => {
                                            const assembled = assembledToolCalls.get(tc.id || tc.callId);
                                            return (
                                                <ToolCallRow
                                                    key={toolIdx}
                                                    toolCall={
                                                        assembled || {
                                                            name: tc.name,
                                                            input: tc.args || tc.input,
                                                            status: "running",
                                                            callId: tc.id || tc.callId,
                                                        }
                                                    }
                                                />
                                            );
                                        })}
                                    </div>
                                )}
                            </div>
                        </div>
                    );
                })}
                {isLoading && !interrupt && (
                    <div style={{marginBottom: "0.75rem", display: "flex", justifyContent: "flex-start"}}>
                        <div
                            style={{
                                background: "#ffffff",
                                border: "1px solid #ccc",
                                borderRadius: "8px",
                                padding: "0.6rem 0.8rem",
                                color: "#777",
                            }}
                        >
                            <span style={{animation: "spin 1s linear infinite", marginRight: "0.5rem"}}>
                                ⟳
                            </span>
                            Thinking...
                        </div>
                    </div>
                )}
                <div ref={messagesEndRef}/>
            </div>

            {interrupt && (
                <div
                    style={{
                        border: "2px solid #ff9800",
                        borderRadius: "8px",
                        padding: "1rem",
                        marginBottom: "1rem",
                        background: "#fff3e0",
                    }}
                >
                    <h3>Approval Required</h3>
                    <p>{typeof interrupt === "string" ? interrupt : JSON.stringify(interrupt)}</p>
                    <button onClick={handleApprove} style={{marginRight: "0.5rem"}}>Approve</button>
                    <button onClick={handleReject}>Reject</button>
                </div>
            )}

            <div style={{display: "flex", gap: "0.5rem"}}>
                <input
                    type="text"
                    value={input}
                    onChange={(e) => setInput(e.target.value)}
                    onKeyDown={onKeyDown}
                    placeholder="Type a message..."
                    disabled={isLoading || !!interrupt}
                    style={{flex: 1, padding: "0.5rem", borderRadius: "4px", border: "1px solid #ccc"}}
                />
                <button
                    onClick={handleSend}
                    disabled={isLoading || !!interrupt || !input.trim()}
                    style={{
                        padding: "0.5rem 1rem",
                        borderRadius: "4px",
                        border: "none",
                        background: "#1976d2",
                        color: "white",
                        cursor: "pointer"
                    }}
                >
                    Send
                </button>
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
