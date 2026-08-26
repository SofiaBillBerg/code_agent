import React, {useCallback, useEffect, useRef, useState} from "react";
import {useCustomStream} from "./useCustomStream.js";
import ToolCallRow, {toolTarget} from "./components/ToolCallRow";
import TodoList from "./components/TodoList";
import SubagentCard from "./components/SubagentCard";
import SubagentProgress from "./components/SubagentProgress";
import HitlSurface from "./components/HitlSurface";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import rehypeHighlight from "rehype-highlight";

const AGENT_URL = import.meta.env.VITE_API_BASE_URL || (typeof window !== "undefined" ? window.location.origin : "http://localhost:8001");

function AppContent() {
    const stream = useCustomStream(AGENT_URL, "code-agent");

    const {
        messages, toolCalls, isLoading, error, interrupt, submit, respond, subagents, todos, stopRun, threadId, newChat,
    } = stream;

    const [input, setInput] = useState("");
    const [models, setModels] = useState([]);
    const [activeModel, setActiveModel] = useState(null);
    const [switchingModel, setSwitchingModel] = useState(false);
    const pendingSwitchRef = useRef(null);
    const messagesEndRef = useRef(null);

    // Fetch available models on mount
    useEffect(() => {
        async function loadModels() {
            try {
                const resp = await fetch(`${AGENT_URL}/models`);
                if (resp.ok) {
                    const data = await resp.json();
                    setModels(data.models || []);
                    // Find currently active model
                    const active = (data.models || []).find((m) => m.is_active);
                    if (active) setActiveModel(active);
                }
            } catch (e) {
                console.warn("Failed to load models:", e);
            }
        }

        loadModels().then(r => console.log("Models loaded:", r));
    }, []);

    // Switch model handler
    const handleModelChange = useCallback(async (newModel) => {
        if (!newModel || switchingModel) return;
        // Optimistically reflect the choice even before a thread exists;
        // the actual server-side switch happens once a thread is created.
        setActiveModel(newModel);
        setModels((prev) => prev.map((m) => ({
            ...m,
            is_active: m.model === newModel.model && m.provider === newModel.provider
        })));
        if (!threadId) {
            console.log("No thread yet; model switch deferred to first message:", newModel.model);
            pendingSwitchRef.current = newModel;
            return;
        }
        await switchThreadModel(threadId, newModel);
    }, [threadId, switchingModel, AGENT_URL]);

    // POST the model switch for an existing thread.
    const switchThreadModel = useCallback(async (tid, newModel) => {
        if (switchingModel) return;
        setSwitchingModel(true);
        try {
            const resp = await fetch(`${AGENT_URL}/threads/${tid}/model`, {
                method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({
                    provider: newModel.provider, model: newModel.model, base_url: newModel.base_url,
                }),
            });
            if (resp.ok) {
                const result = await resp.json();
                console.log("Model switched:", result);
                pendingSwitchRef.current = null;
                // The agent rebuilds server-side; client stream continues with new model
            } else {
                console.error("Model switch failed:", await resp.text());
            }
        } catch (e) {
            console.error("Model switch error:", e);
        } finally {
            setSwitchingModel(false);
        }
    }, [switchingModel, AGENT_URL]);

    // A model chosen before/at message time is switched as soon as the thread
    // exists AND no run is executing — the backend rejects mid-run switches
    // (409), so wait for idle and retry then.
    useEffect(() => {
        if (threadId && !isLoading && pendingSwitchRef.current && !switchingModel) {
            switchThreadModel(threadId, pendingSwitchRef.current).then(r => console.log("Pending model switch attempted:", r)).catch(e => console.error("Pending model switch failed:", e));
        }
    }, [threadId, isLoading, switchingModel, switchThreadModel]);

    /**
     * Run recap card state: shown once when a run transitions from active to
     * finished so the user gets a one-glance summary of what happened instead
     * of having to scroll through every individual tool chip.
     */
    const [recap, setRecap] = useState(null);
    const prevLoadingRef = useRef(false);
    useEffect(() => {
        if (prevLoadingRef.current && !isLoading && toolCalls.length > 0) {
            const targets = [...new Set(toolCalls.map((tc) => toolTarget(tc.input)).filter(Boolean)),];
            setRecap({steps: toolCalls.length, files: targets});
        }
        prevLoadingRef.current = isLoading;
    }, [isLoading, toolCalls]);

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

    /**
     * Forward a HITL decision from HitlSurface to the backend.
     * `decision` is either a single decision object ({type: approve|edit|reject})
     * or an array of decisions (one per parallel action).
     */
    const handleDecision = useCallback(async (decision) => {
        console.log("[DEBUG] HITL decision:", decision);
        await respond(decision);
    }, [respond]);

    const onKeyDown = useCallback((event) => {
        if (event.key === "Enter" && !event.shiftKey) {
            event.preventDefault();
            handleSend().then(r => console.log("[DEBUG] handleSend completed:", r)).catch(e => console.error("[DEBUG] handleSend failed:", e));
        }
    }, [handleSend],);

    const toolCallMap = useCallback((calls) => {
        const map = new Map();
        calls.forEach((tc) => map.set(tc.callId || tc.id, tc));
        return map;
    }, []);

    const assembledToolCalls = toolCallMap(toolCalls);
    const subagentArray = Array.from((stream.subagents || []).values());

    // Status-indicator state (M2/S2.2): one explicit badge for whether the
    // model is working, paused for approval, or idle. While working, the
    // badge names the CURRENT tool + target + step count so the user always
    // knows what the agent is doing right now.
    const runningTool = [...toolCalls]
        .reverse()
        .find((tc) => tc.status === "running" || tc.status === "pending");
    let workLabel = "Working\u2026";
    if (runningTool) {
        const targetText = toolTarget(runningTool.input);
        workLabel = `${runningTool.name}` + (targetText ? ` \u2192 ${targetText}` : "") + ` \u00b7 step ${toolCalls.length}`;
    }
    const status = interrupt ? {
        label: "Awaiting your approval",
        color: "#ff9800",
        pulse: false
    } : isLoading ? {label: workLabel, color: "#1976d2", pulse: true} : {label: "Idle", color: "#9e9e9e", pulse: false};

    return (<div style={{padding: "1rem", maxWidth: "800px", margin: "0 auto"}}>
        <div style={{display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "1rem"}}>
            <h1 style={{margin: 0}}>Berg Agents Chat</h1>
            <div style={{display: "flex", gap: "1rem", alignItems: "center"}}>
                {/* New chat: reset the conversation (fresh thread, empty
                        history) so degraded context from a previous task never
                        bleeds into the next one. */}
                <button
                    onClick={() => {
                        pendingSwitchRef.current = null;
                        setActiveModel(null);
                        setRecap(null);
                        newChat();
                    }}
                    disabled={isLoading}
                    style={{
                        padding: "0.4rem 0.8rem",
                        borderRadius: "6px",
                        border: "1px solid #1976d2",
                        background: "#e3f2fd",
                        color: "#1976d2",
                        cursor: isLoading ? "not-allowed" : "pointer",
                        fontSize: "0.85rem",
                    }}
                >
                    + New chat
                </button>
                {/* Export the current thread as a Markdown transcript. */}
                {threadId && (<a
                    href={`${AGENT_URL}/threads/${threadId}/export`}
                    style={{
                        padding: "0.4rem 0.8rem",
                        borderRadius: "6px",
                        border: "1px solid #ccc",
                        background: "white",
                        color: "#444",
                        textDecoration: "none",
                        fontSize: "0.85rem",
                    }}
                >
                    ⬇ Export
                </a>)}
                {threadId &&
                    <p style={{margin: 0, fontSize: "0.85rem", color: "#666"}}><code>Thread: {threadId}</code></p>}
                {models.length > 0 && (<select
                    value={activeModel ? `${activeModel.provider}:${activeModel.model}` : ""}
                    onChange={(e) => {
                        // NOTE: model ids may contain ":" (e.g. "qwen3.5:9b"),
                        // so match on the full composite value, never split(":").
                        const selected = models.find((m) => `${m.provider}:${m.model}` === e.target.value);
                        if (selected) handleModelChange(selected).then(r => console.log("Model change handled:", r)).catch(e => console.error("Model change failed:", e));
                    }}
                    disabled={switchingModel || isLoading}
                    style={{
                        padding: "0.4rem 0.6rem",
                        borderRadius: "6px",
                        border: "1px solid #ccc",
                        background: "white",
                        fontSize: "0.85rem",
                        minWidth: "200px",
                    }}
                >
                    <option value="">Select model...</option>
                    {models.map((m) => (
                        <option key={`${m.provider}:${m.model}`} value={`${m.provider}:${m.model}`}>
                            {m.display_name} {m.is_active && "✓"}
                        </option>))}
                </select>)}
                {switchingModel && (<span style={{fontSize: "0.8rem", color: "#1976d2"}}>
                            ⟳ Switching...
                        </span>)}
            </div>
        </div>

        {/* Working-status indicator (M2/S2.2) */}
        <div style={{display: "flex", alignItems: "center", gap: "0.5rem", marginBottom: "0.75rem"}}>
                <span
                    style={{
                        width: "10px",
                        height: "10px",
                        borderRadius: "50%",
                        background: status.color,
                        animation: status.pulse ? "pulse 1.2s ease-in-out infinite" : "none",
                    }}
                />
            <span style={{fontSize: "0.85rem", color: status.color, fontWeight: 500}}>
                    {status.label}
                </span>
        </div>

        {error && <p style={{color: "red"}}>Error: {typeof error === "string" ? error : JSON.stringify(error)}</p>}

        <SubagentProgress subagents={subagentArray}/>

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
                let content = msg.text ?? (typeof msg.content === "string" ? msg.content : JSON.stringify(msg.content ?? ""));

                // Split leaked <think>...</think> reasoning blocks out of the
                // visible answer and render them as a collapsed section.
                let thinking = "";
                if (isAi && content.includes("<think>")) {
                    const parts = [];
                    content = content.replace(/<think>([\s\S]*?)<\/think>/g, (_, t) => {
                        thinking += (thinking ? "\n\n" : "") + t.trim();
                        return "";
                    });
                    // An unterminated <think> (stream cut mid-reasoning).
                    const openIdx = content.indexOf("<think>");
                    if (openIdx >= 0) {
                        thinking += (thinking ? "\n\n" : "") + content.slice(openIdx + 7).trim();
                        content = content.slice(0, openIdx);
                    }
                    parts.push(content);
                    content = parts.join("").trim();
                }
                const msgToolCalls = isAi ? (msg.tool_calls || msg.toolCalls || []) : [];

                return (<div
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
                        {thinking && (<details style={{marginBottom: "0.4rem", fontSize: "0.85rem"}}>
                            <summary style={{cursor: "pointer", color: "#7b61a8"}}>
                                💭 Reasoning
                            </summary>
                            <pre style={{
                                whiteSpace: "pre-wrap", color: "#666", margin: "0.3rem 0 0"
                            }}>{thinking}</pre>
                        </details>)}
                        <div style={{lineHeight: "1.5"}}>
                            <ReactMarkdown
                                remarkPlugins={[remarkGfm]}
                                rehypePlugins={[rehypeHighlight]}
                            >
                                {content}
                            </ReactMarkdown>
                        </div>
                        {msgToolCalls.length > 0 && (<div style={{marginTop: "0.5rem"}}>
                            {msgToolCalls.map((tc, toolIdx) => {
                                const assembled = assembledToolCalls.get(tc.id || tc.callId);
                                return (<ToolCallRow
                                    key={toolIdx}
                                    toolCall={assembled || {
                                        name: tc.name,
                                        input: tc.args || tc.input,
                                        status: "running",
                                        callId: tc.id || tc.callId,
                                    }}
                                />);
                            })}
                        </div>)}
                    </div>
                </div>);
            })}
            {/* Root-level tool activity (S2 regression fix): the hook stores
                    every non-subagent tool execution in `toolCalls`, but until now
                    only message-attached calls were rendered - so runs that only
                    called tools looked completely dead in the UI. */}
            {/* Root-level tool activity, collapsed into a details block so
                    long runs (50+ steps) don't bury the conversation. Stays
                    open while the run is active for live visibility. */}
            {toolCalls.length > 0 && (<details
                open={isLoading}
                style={{marginTop: "0.75rem"}}
            >
                <summary style={{cursor: "pointer", fontSize: "0.85rem", color: "#555"}}>
                    🔧 Tool activity ({toolCalls.length} step{toolCalls.length === 1 ? "" : "s"})
                    {isLoading && " ⟳ running…"}
                </summary>
                <div style={{marginTop: "0.4rem"}}>
                    {toolCalls.map((tc) => (<ToolCallRow key={tc.callId} toolCall={tc}/>))}
                </div>
            </details>)}
            {subagents && subagents.length > 0 && (<div style={{marginTop: "1rem"}}>
                {subagents.map((sa) => (<SubagentCard key={sa.id} subagent={sa}/>))}
            </div>)}
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
                </div>)}
            <div ref={messagesEndRef}/>
        </div>

        {/* Run recap card (Round-4 P3c): one-glance summary of a finished run. */}
        {recap && (<div
            style={{
                border: "1px solid #c8e6c9",
                background: "#f1f8e9",
                borderRadius: "8px",
                padding: "0.6rem 0.8rem",
                marginBottom: "0.75rem",
                fontSize: "0.85rem",
            }}
        >
            <div style={{display: "flex", justifyContent: "space-between", alignItems: "center"}}>
                <strong>Run finished &mdash; {recap.steps} tool steps</strong>
                <button
                    onClick={() => setRecap(null)}
                    style={{border: "none", background: "none", cursor: "pointer", fontSize: "1rem"}}
                    aria-label="Dismiss run summary"
                >
                    &times;
                </button>
            </div>
            {recap.files.length > 0 && (<div style={{color: "#555", marginTop: "0.25rem"}}>
                Files touched: {recap.files.slice(0, 8).join(", ")}
                {recap.files.length > 8 ? ` … (+${recap.files.length - 8} more)` : ""}
            </div>)}
        </div>)}

        <TodoList todos={stream.todos || []} onTodoUpdate={() => {
        }}/>

        {interrupt && <HitlSurface pending={interrupt} onDecision={handleDecision}/>}

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
            {/* Emergency brake (Round-4 P2): cancels the running agent task. */}
            {isLoading && !interrupt && (<button
                onClick={stopRun}
                style={{
                    padding: "0.5rem 1rem",
                    borderRadius: "4px",
                    border: "none",
                    background: "#d32f2f",
                    color: "white",
                    cursor: "pointer"
                }}
            >
                Stop
            </button>)}
        </div>
    </div>);
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
