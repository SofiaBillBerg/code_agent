import {useState, useEffect, useCallback, useRef} from 'react';

/**
 * Custom React hook for streaming protocol v2 events from the code_agent server.
 * Backend is FastAPI + protocol.py translate_stream -> web.py _push_protocol_event -> SSE GET /threads/{id}/stream/events
 */
export function useCustomStream(apiUrl, assistantId) {
    const [threadId, setThreadId] = useState(null);
    const [messages, setMessages] = useState([]);
    const [toolCalls, setToolCalls] = useState([]);
    const [isLoading, setIsLoading] = useState(false);
    const [error, setError] = useState(null);
    const [interrupt, setInterrupt] = useState(null);
    const [subagents, setSubagents] = useState(new Map());
    const [todos, setTodos] = useState([]);
    const eventSourceRef = useRef(null);
    const currentMessageRef = useRef(null);
    const localThreadIdRef = useRef(null);

    const generateUUID = useCallback(() => {
        return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, function (c) {
            const r = Math.random() * 16 | 0;
            const v = c === 'x' ? r : (r & 0x3 | 0x8);
            return v.toString(16);
        });
    }, []);

    const createThread = useCallback(() => {
        const tid = generateUUID();
        localThreadIdRef.current = tid;
        setThreadId(tid);
        return tid;
    }, [generateUUID]);

    const updateSubagent = useCallback((ns, updater) => {
        const id = Array.isArray(ns) && ns.length ? ns[ns.length - 1] : (ns || 'unknown');
        const name = (Array.isArray(ns) && ns.length)
            ? (String(ns[ns.length - 1]).split(':')[0] || ns[ns.length - 1])
            : 'Subagent';
        setSubagents(prev => {
            const next = new Map(prev);
            const existing = next.get(id) || {id, name, status: 'running', namespace: ns, messages: [], toolCalls: []};
            next.set(id, updater(existing));
            return next;
        });
    }, []);

    const submit = useCallback(async (input) => {
        let tid = localThreadIdRef.current;
        if (!tid) tid = createThread();
        console.log('[SUBMIT] posting to', `${apiUrl}/threads/${tid}/commands`, input);
        setIsLoading(true);
        setError(null);
        setInterrupt(null);
        const humanMessage = {id: `human-${Date.now()}`, role: 'human', text: input.messages?.[0]?.content || ''};
        setMessages(prev => [...prev, humanMessage]);
        try {
            const response = await fetch(`${apiUrl}/threads/${tid}/commands`, {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({method: 'run.start', params: {input: {messages: input.messages}}}),
            });
            const body = await response.text();
            console.log('[SUBMIT] response', response.status, body);
            if (!response.ok) throw new Error(`HTTP error: ${response.status} ${body}`);
        } catch (err) {
            console.error('[SUBMIT] error', err);
            setError(err.message);
            setIsLoading(false);
        }
    }, [apiUrl, createThread]);

    useEffect(() => {
        if (!threadId || !isLoading) return;
        console.log('[SSE] opening EventSource', `${apiUrl}/threads/${threadId}/stream/events`);
        const eventSource = new EventSource(`${apiUrl}/threads/${threadId}/stream/events`);
        eventSourceRef.current = eventSource;

        eventSource.onopen = () => console.log('[SSE] open', threadId);
        eventSource.onmessage = (event) => {
            try {
                const data = JSON.parse(event.data);
                const method = data.method;
                const eventData = data.params?.data || {};
                console.log('[SSE] message', method, eventData.event, data);
                const nsMsg = data.params?.namespace || [];
                const isRootMessage = !nsMsg || nsMsg.length === 0;
                if (method === 'messages') {
                    const eventType = eventData.event;
                    if (!isRootMessage) {
                        // Track subagent messages via updateSubagent
                        if (eventType === 'message-start') {
                            const msgId = eventData.id || eventData.message?.id || `sa-${Date.now()}`;
                            const role = eventData.role || eventData.message?.role || 'ai';
                            updateSubagent(nsMsg, (sa) => ({
                                ...sa,
                                messages: [...(sa.messages || []), {id: msgId, role, text: '', status: 'streaming'}],
                            }));
                        } else if (eventType === 'content-block-delta') {
                            const delta = eventData.delta?.text || eventData.delta?.content || '';
                            updateSubagent(nsMsg, (sa) => {
                                const msgs = sa.messages || [];
                                const lastMsg = msgs[msgs.length - 1];
                                if (lastMsg && lastMsg.status === 'streaming') {
                                    const updated = {...lastMsg, text: (lastMsg.text || '') + delta};
                                    return {...sa, messages: [...msgs.slice(0, -1), updated]};
                                }
                                return {
                                    ...sa,
                                    messages: [...msgs, {
                                        id: `sa-${Date.now()}`,
                                        role: 'ai',
                                        text: delta,
                                        status: 'streaming'
                                    }]
                                };
                            });
                        } else if (eventType === 'message-finish') {
                            updateSubagent(nsMsg, (sa) => {
                                const msgs = sa.messages || [];
                                const lastMsg = msgs[msgs.length - 1];
                                if (lastMsg && lastMsg.status === 'streaming') {
                                    const updated = {
                                        ...lastMsg,
                                        status: 'complete',
                                        text: eventData.message?.content || eventData.content || lastMsg.text
                                    };
                                    return {...sa, messages: [...msgs.slice(0, -1), updated]};
                                }
                                return sa;
                            });
                        }
                    } else if (eventType === 'message-start') {
                        const msgId = eventData.id || eventData.message?.id || `ai-${Date.now()}`;
                        const role = eventData.role || eventData.message?.role || 'ai';
                        currentMessageRef.current = {id: msgId, role, text: '', tool_calls: []};
                        setMessages(prev => [...prev, {...currentMessageRef.current}]);
                    } else if (eventType === 'content-block-delta') {
                        const delta = eventData.delta?.text || eventData.delta?.content || '';
                        // Regression 3 fix (S5.2.1): lazily create the assistant
                        // message if message-start was missed (POST/GET race), so a
                        // delta is never silently dropped.
                        if (!currentMessageRef.current) {
                            const msgId = eventData.message?.id || eventData.id || `ai-${Date.now()}`;
                            currentMessageRef.current = {id: msgId, role: 'ai', text: '', tool_calls: []};
                            setMessages(prev => [...prev, {...currentMessageRef.current}]);
                        }
                        currentMessageRef.current.text += delta;
                        const snapshot = {...currentMessageRef.current};
                        const snapId = snapshot.id;
                        setMessages(prev => {
                            const next = [...prev];
                            const idx = next.findIndex(m => m && m.id === snapId);
                            if (idx >= 0) next[idx] = snapshot;
                            else next.push(snapshot);
                            return next;
                        });
                    } else if (eventType === 'message-finish') {
                        // Regression 3 fix (S5.2.2): reconstruct the assistant message
                        // from the finish payload if message-start was missed.
                        if (!currentMessageRef.current) {
                            const msgId = eventData.message?.id || eventData.id || `ai-${Date.now()}`;
                            const finishText = eventData.message?.content || eventData.content || '';
                            if (finishText) {
                                currentMessageRef.current = {id: msgId, role: 'ai', text: finishText, tool_calls: []};
                                setMessages(prev => [...prev, {...currentMessageRef.current}]);
                            }
                            currentMessageRef.current = null;
                        } else {
                            const snapshot = {...currentMessageRef.current};
                            const snapId = snapshot.id;
                            // Drop empty tool-only turns that never produced text (prevents 5 empty bubbles)
                            const isEmpty = !snapshot.text || !snapshot.text.trim();
                            if (isEmpty) {
                                setMessages(prev => prev.filter(m => m && m.id !== snapId));
                            } else {
                                setMessages(prev => {
                                    const next = [...prev];
                                    const idx = next.findIndex(m => m && m.id === snapId);
                                    if (idx >= 0) next[idx] = snapshot;
                                    return next;
                                });
                            }
                            currentMessageRef.current = null;
                        }
                    }
                } else if (method === 'tools') {
                    const eventType = eventData.event;
                    console.log('[SSE] tools', eventType, eventData);
                    const subNs = nsMsg && nsMsg.length ? nsMsg : null;
                    if (eventType === 'tool-started') {
                        const callId = eventData.toolCallId || eventData.tool_call_id || eventData.id || `call-${Date.now()}`;
                        const name = eventData.name || eventData.tool_name || 'unknown';
                        const inputVal = eventData.input || eventData.args || {};
                        if (subNs) {
                            updateSubagent(subNs, (sa) => ({
                                ...sa,
                                status: 'running',
                                toolCalls: [...(sa.toolCalls || []), {
                                    callId,
                                    name,
                                    input: inputVal,
                                    status: 'running'
                                }],
                            }));
                        } else {
                            setToolCalls(prev => [...prev, {callId, name, input: inputVal, status: 'running'}]);
                        }
                    } else if (eventType === 'tool-finished' || eventType === 'tool_finished' || eventType === 'tool-end') {
                        const callId = eventData.toolCallId || eventData.tool_call_id || eventData.id;
                        const output = eventData.output || eventData.result || '';
                        if (subNs) {
                            updateSubagent(subNs, (sa) => ({
                                ...sa,
                                toolCalls: (sa.toolCalls || []).map(tc => tc.callId === callId ? {
                                    ...tc,
                                    status: 'complete',
                                    output
                                } : tc),
                            }));
                        } else {
                            setToolCalls(prev => prev.map(tc => tc.callId === callId ? {
                                ...tc,
                                status: 'complete',
                                output
                            } : tc));
                        }
                    } else if (eventType === 'tool-error') {
                        const callId = eventData.toolCallId || eventData.tool_call_id || eventData.id;
                        const errMsg = eventData.error || eventData.message || 'tool error';
                        if (subNs) {
                            updateSubagent(subNs, (sa) => ({
                                ...sa,
                                toolCalls: (sa.toolCalls || []).map(tc => tc.callId === callId ? {
                                    ...tc,
                                    status: 'error',
                                    error: errMsg
                                } : tc),
                            }));
                        } else {
                            setToolCalls(prev => prev.map(tc => tc.callId === callId ? {
                                ...tc,
                                status: 'error',
                                error: errMsg
                            } : tc));
                        }
                    }
                } else if (method === 'lifecycle') {
                    const eventType = eventData.event;
                    const node = data.params?.node;
                    const ns = data.params?.namespace;
                    const isTerminal = !node && Array.isArray(ns) && ns.length === 0;
                    console.log('[SSE] lifecycle', eventType, 'node:', node, 'ns:', ns, 'terminal:', isTerminal);
                    if (Array.isArray(ns) && ns.length > 0) {
                        // Subagent lifecycle events
                        if (eventType === 'started' || eventType === 'running') {
                            updateSubagent(ns, (sa) => ({...sa, status: 'running'}));
                        } else if (eventType === 'completed' || eventType === 'finished' || eventType === 'done') {
                            updateSubagent(ns, (sa) => ({...sa, status: 'complete'}));
                        } else if (eventType === 'failed' || eventType === 'error') {
                            const errMsg = eventData.error || eventData.message || 'subagent failed';
                            updateSubagent(ns, (sa) => ({...sa, status: 'failed', error: errMsg}));
                        }
                    } else if (eventType === 'completed' || eventType === 'finished' || eventType === 'done' || eventType === 'complete') {
                        if (!isTerminal) {
                            console.log('[SSE] ignoring intermediate lifecycle completed for node', node);
                            // do not close - wait for terminal lifecycle completed
                        } else {
                            // Regression 3 fix (S5.2.2): commit whatever text we have,
                            // reconstructing the message if message-start/finish were missed.
                            const msgText = (currentMessageRef.current && currentMessageRef.current.text)
                                || eventData.message?.content
                                || eventData.content
                                || '';
                            if (msgText) {
                                const msgId = (currentMessageRef.current && currentMessageRef.current.id)
                                    || eventData.message?.id
                                    || eventData.id
                                    || `ai-${Date.now()}`;
                                const snapshot = {id: msgId, role: 'ai', text: msgText, tool_calls: []};
                                setMessages(prev => {
                                    const exists = prev.some(m => m && m.id === msgId);
                                    if (exists) return prev.map(m => m && m.id === msgId ? snapshot : m);
                                    return [...prev, snapshot];
                                });
                                currentMessageRef.current = null;
                            }
                            setIsLoading(false);
                            setInterrupt(null);
                            console.log('[SSE] terminal completed -> isLoading false');
                        }
                    } else if (eventType === 'interrupted' || eventType === 'input-requested') {
                        setInterrupt(eventData.value || eventData.message || 'Approval required');
                    } else if (eventType === 'failed' || eventType === 'error') {
                        console.error('[SSE] lifecycle failed', eventData, 'node:', node);
                        // only fail terminal or if no terminal will come - treat intermediate failed as error still
                        if (isTerminal || node) {
                            setError(eventData.error || eventData.message || 'stream failed');
                            if (isTerminal) setIsLoading(false);
                        }
                    }
                } else if (method === 'input') {
                    if (eventData.event === 'input-requested') setInterrupt(eventData.value || eventData.message || 'Input required');
                } else if (method === 'values') {
                    console.log('[SSE] values', eventData);
                } else if (method === 'todos') {
                    // Handle todos events - update state for UI display
                    const todoItems = eventData?.todos || [];
                    setTodos(todoItems);
                }
            } catch (err) {
                console.error('[SSE] Failed to parse event:', err, event.data);
            }
        };
        eventSource.onerror = (err) => {
            console.error('[SSE] EventSource error:', err, 'readyState', eventSource.readyState);
            if (eventSource.readyState === 2) {
                eventSource.close();
                setIsLoading(false);
            }
        };
        return () => {
            console.log('[SSE] closing EventSource', threadId);
            eventSource.close();
        };
    }, [apiUrl, threadId, isLoading]);

    const respond = useCallback(async (response) => {
        const tid = localThreadIdRef.current;
        if (!tid) return;
        try {
            await fetch(`${apiUrl}/threads/${tid}/commands`, {
                method: 'POST', headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({method: 'input.respond', params: {response}}),
            });
            setInterrupt(null);
        } catch (err) {
            setError(err.message);
        }
    }, [apiUrl]);

    return {threadId, messages, toolCalls, subagents, isLoading, todos, error, interrupt, submit, respond};
}
