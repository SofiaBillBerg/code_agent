import {useState, useEffect, useCallback, useRef} from 'react';

/**
 * Custom React hook for streaming protocol v2 events from the code_agent server.
 *
 * This replaces @langchain/react's useStream because the server implements
 * a custom protocol v2 SSE format, not the LangGraph API format that
 * @langchain/react expects.
 */
export function useCustomStream(apiUrl, assistantId) {
    const [threadId, setThreadId] = useState(null);
    const [messages, setMessages] = useState([]);
    const [toolCalls, setToolCalls] = useState([]);
    const [isLoading, setIsLoading] = useState(false);
    const [error, setError] = useState(null);
    const [interrupt, setInterrupt] = useState(null);
    const eventSourceRef = useRef(null);
    const currentMessageRef = useRef(null);
    const localThreadIdRef = useRef(null);

    // Generate a UUID v4
    const generateUUID = useCallback(() => {
        return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, function (c) {
            const r = Math.random() * 16 | 0;
            const v = c === 'x' ? r : (r & 0x3 | 0x8);
            return v.toString(16);
        });
    }, []);

    // Create a new thread locally (no server call needed)
    const createThread = useCallback(() => {
        const tid = generateUUID();
        localThreadIdRef.current = tid;
        setThreadId(tid);
        return tid;
    }, [generateUUID]);

    // Send a message to the agent
    const submit = useCallback(async (input) => {
        let tid = localThreadIdRef.current;
        if (!tid) {
            tid = createThread();
        }

        setIsLoading(true);
        setError(null);
        setInterrupt(null);

        // Add the human message to the local state immediately
        const humanMessage = {
            id: `human-${Date.now()}`,
            role: 'human',
            text: input.messages?.[0]?.content || '',
        };
        setMessages(prev => [...prev, humanMessage]);

        try {
            const response = await fetch(`${apiUrl}/threads/${tid}/commands`, {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({
                    method: 'run.start',
                    params: {
                        input: {
                            messages: input.messages,
                        },
                    },
                }),
            });

            if (!response.ok) {
                throw new Error(`HTTP error: ${response.status}`);
            }
        } catch (err) {
            setError(err.message);
            setIsLoading(false);
        }
    }, [apiUrl, createThread]);

    // Stream events from the server
    useEffect(() => {
        if (!threadId || !isLoading) return;

        const eventSource = new EventSource(
            `${apiUrl}/threads/${threadId}/stream/events`
        );
        eventSourceRef.current = eventSource;

        eventSource.onmessage = (event) => {
            try {
                const data = JSON.parse(event.data);
                const method = data.method;
                const params = data.params || {};
                const eventData = params.data || {};

                if (method === 'messages') {
                    const eventType = eventData.event;

                    if (eventType === 'message-start') {
                        // A new AI message is starting
                        const msg = eventData.message || {};
                        currentMessageRef.current = {
                            id: msg.id || `ai-${Date.now()}`,
                            role: 'ai',
                            text: '',
                            tool_calls: [],
                        };
                    } else if (eventType === 'content-block-delta') {
                        // Append text delta to current message
                        if (currentMessageRef.current) {
                            const delta = eventData.delta?.text || '';
                            currentMessageRef.current.text += delta;
                        }
                    } else if (eventType === 'message-finish') {
                        // AI message finished — commit it
                        if (currentMessageRef.current) {
                            const finishedMsg = {...currentMessageRef.current};
                            setMessages(prev => [...prev, finishedMsg]);
                            currentMessageRef.current = null;
                        }
                    }
                } else if (method === 'tools') {
                    const eventType = eventData.event;
                    if (eventType === 'tool-started') {
                        const tc = {
                            callId: eventData.tool_call_id || eventData.id,
                            name: eventData.tool_name,
                            input: eventData.input || {},
                            status: 'running',
                        };
                        setToolCalls(prev => [...prev, tc]);
                    } else if (eventType === 'tool-finished') {
                        setToolCalls(prev =>
                            prev.map(tc =>
                                tc.callId === (eventData.tool_call_id || eventData.id)
                                    ? {...tc, status: 'complete', output: eventData.output}
                                    : tc
                            )
                        );
                    }
                } else if (method === 'lifecycle') {
                    const eventType = eventData.event;
                    if (eventType === 'completed') {
                        setIsLoading(false);
                        setInterrupt(null);
                    } else if (eventType === 'interrupted') {
                        setInterrupt(eventData.message || 'Approval required');
                    }
                } else if (method === 'input') {
                    const eventType = eventData.event;
                    if (eventType === 'input-requested') {
                        setInterrupt(eventData.message || 'Input required');
                    }
                }
            } catch (err) {
                console.error('[STREAM] Failed to parse event:', err);
            }
        };

        eventSource.onerror = (err) => {
            console.error('[STREAM] EventSource error:', err);
            eventSource.close();
            setIsLoading(false);
        };

        return () => {
            eventSource.close();
        };
    }, [apiUrl, threadId, isLoading]);

    // Respond to an interrupt
    const respond = useCallback(async (response) => {
        const tid = localThreadIdRef.current;
        if (!tid) return;

        try {
            await fetch(`${apiUrl}/threads/${tid}/commands`, {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({
                    method: 'input.respond',
                    params: {
                        response: response,
                    },
                }),
            });
            setInterrupt(null);
        } catch (err) {
            setError(err.message);
        }
    }, [apiUrl]);

    return {
        threadId,
        messages,
        toolCalls,
        isLoading,
        error,
        interrupt,
        submit,
        respond,
    };
}
