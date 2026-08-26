import React, {useEffect, useState} from "react";

/**
 * HitlSurface component — Human-in-the-loop approval card.
 *
 * Renders the agent's pending interrupt as one or more "action requests"
 * (tool name + JSON args) and emits a LangChain HITL *decision* through
 * `onDecision`, using the schema understood by langchain's
 * HumanInTheLoopMiddleware resume path:
 *
 *   - approve: {"type": "approve"}
 *   - reject:  {"type": "reject", "message": "..."}
 *   - edit:    {"type": "edit", "edited_action": {"name": ..., "args": ...}}
 *
 * When several actions were interrupted in parallel, a decision *array* is
 * emitted so each action gets exactly one entry (order-aligned).
 */

/**
 * Normalize any supported interrupt payload into a flat list of actions.
 *
 * Supported shapes:
 *   - protocol v2 value:  {action_requests: [{action|name, args}], review_configs?}
 *   - array of interrupts: [{value: {action_requests: [...]}}]
 *   - legacy surface prop: {tool: string, input: object}
 *
 * @param {object|string} pending - Structured interrupt from useCustomStream
 *   ({id, value}) or a plain string message (no editable args).
 * @returns {Array<{name: string, args: object}>}
 */
function extractActions(pending) {
    if (!pending || typeof pending !== "object") return [];
    const value = pending.value;

    // Collect raw action entries from every known container shape.
    let raw = [];
    if (value && Array.isArray(value.action_requests)) {
        raw = value.action_requests;
    } else if (Array.isArray(value)) {
        // Multiple simultaneous interrupts (parallel branches): flatten them.
        raw = value.flatMap((item) => {
            if (item?.value?.action_requests) return item.value.action_requests;
            if (item?.action_requests) return item.action_requests;
            if (item?.action || item?.name) return [item];
            return [];
        });
    }

    // Legacy fallback: {tool, input} shape from older UI wiring.
    if (!raw.length && pending.tool !== undefined) {
        raw = [{action: pending.tool, args: pending.input}];
    }

    // Map to a uniform {name, args} view.
    return raw.map((a) => ({
        name: a.action || a.name || "unknown",
        args: a.args ?? a.input ?? {},
    }));
}

function HitlSurface({pending, onDecision}) {
    const [showEdit, setShowEdit] = useState(false);
    const [editedArgs, setEditedArgs] = useState("");
    const [editError, setEditError] = useState(null);
    const [elapsed, setElapsed] = useState(0);

    const actions = extractActions(pending);

    // Track elapsed time while HITL is pending (reset whenever it clears).
    useEffect(() => {
        if (!pending) {
            setElapsed(0);
            return;
        }
        const startTime = Date.now();
        const interval = setInterval(() => {
            setElapsed((Date.now() - startTime) / 1000);
        }, 1000);
        return () => clearInterval(interval);
    }, [pending]);

    // Pre-fill the edit textarea with the first action's current args.
    useEffect(() => {
        if (actions.length > 0) {
            try {
                setEditedArgs(JSON.stringify(actions[0].args, null, 2));
            } catch {
                setEditedArgs(String(actions[0].args));
            }
        }
        setShowEdit(false);
        setEditError(null);
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [pending]);

    if (!pending) return null;

    /** Continue without changes → approve every action. */
    const handleContinue = () => {
        onDecision(
            actions.length > 1
                ? actions.map(() => ({type: "approve"}))
                : {type: "approve"},
        );
    };

    /** Reject every action with a short human-readable reason. */
    const handleReject = () => {
        const decision = {type: "reject", message: "Rejected by user"};
        onDecision(
            actions.length > 1
                ? actions.map(() => ({...decision}))
                : decision,
        );
    };

    /**
     * Submit edited args for the FIRST action; remaining actions (if any)
     * continue unchanged so the decisions array stays order-aligned.
     */
    const handleEditSubmit = () => {
        try {
            const parsedArgs = JSON.parse(editedArgs);
            const first = actions[0];
            const editDecision = {
                type: "edit",
                edited_action: {name: first.name, args: parsedArgs},
            };
            onDecision(
                actions.length > 1
                    ? [editDecision, ...actions.slice(1).map(() => ({type: "approve"}))]
                    : editDecision,
            );
        } catch (err) {
            setEditError(`Invalid JSON: ${err.message}`);
        }
    };

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
            <div
                style={{
                    fontSize: "0.9rem",
                    fontWeight: "600",
                    color: "#e65100",
                    display: "flex",
                    justifyContent: "space-between",
                    alignItems: "center",
                }}
            >
                <span>Awaiting your approval</span>
                <span style={{fontSize: "0.8rem", color: "#e65100"}}>
          Waiting: {elapsed.toFixed(1)}s
        </span>
            </div>

            {/* Render every pending action (tool name + args). */}
            {actions.map((action, idx) => (
                <div key={idx} style={{display: "flex", flexDirection: "column", gap: "0.4rem"}}>
                    <div style={{fontSize: "0.85rem"}}>
                        <span style={{color: "#666"}}>{idx === 0 ? "The agent" : "…also"} wants to run </span>
                        <span style={{fontFamily: "monospace", color: "#1a73e8"}}>
              {action.name}
            </span>
                        <span style={{color: "#666"}}>:</span>
                        {actions.length > 1 && showEdit && idx === 0 && (
                            <span style={{marginLeft: "0.5rem", fontSize: "0.75rem", color: "#999"}}>
                (editing applies to this action)
              </span>
                        )}
                    </div>
                    <pre
                        style={{
                            margin: 0,
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
            {JSON.stringify(action.args, null, 2)}
          </pre>
                </div>
            ))}

            {/* Fallback when the payload carried no parseable actions. */}
            {actions.length === 0 && (
                <div style={{fontSize: "0.85rem", whiteSpace: "pre-wrap"}}>
                    {typeof pending.value === "string"
                        ? pending.value
                        : JSON.stringify(pending.value ?? pending, null, 2)}
                </div>
            )}

            {showEdit && actions.length > 0 && (
                <div style={{display: "flex", flexDirection: "column", gap: "0.5rem"}}>
          <textarea
              value={editedArgs}
              onChange={(e) => {
                  setEditedArgs(e.target.value);
                  setEditError(null);
              }}
              style={{
                  width: "100%",
                  padding: "0.5rem",
                  borderRadius: "4px",
                  border: "1px solid #ccc",
                  fontFamily: "monospace",
                  fontSize: "0.8rem",
                  resize: "vertical",
                  minHeight: "100px",
              }}
              placeholder="Edit JSON args here"
          />
                    {editError && (
                        <div
                            style={{
                                padding: "0.5rem",
                                background: "#ffebee",
                                border: "1px solid #f44336",
                                borderRadius: "4px",
                                color: "#b00020",
                                fontSize: "0.8rem",
                            }}
                        >
                            {editError}
                        </div>
                    )}
                </div>
            )}

            <div style={{display: "flex", gap: "0.75rem", marginTop: "0.5rem"}}>
                <button
                    onClick={() => {
                        if (showEdit) {
                            handleEditSubmit();
                        } else {
                            handleContinue();
                        }
                    }}
                    style={{
                        flex: 1,
                        padding: "0.6rem 1rem",
                        border: "none",
                        borderRadius: "6px",
                        background: showEdit ? "#1565c0" : "#2e7d32",
                        color: "#fff",
                        fontSize: "0.9rem",
                        cursor: "pointer",
                        fontWeight: "500",
                    }}
                >
                    {showEdit ? "Save & Continue" : "Continue"}
                </button>
                <button
                    onClick={handleReject}
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
                {actions.length > 0 && (
                    <button
                        onClick={() => {
                            setShowEdit(!showEdit);
                            setEditError(null);
                        }}
                        style={{
                            padding: "0.6rem 1rem",
                            border: "1px solid #ccc",
                            borderRadius: "6px",
                            background: "transparent",
                            color: "#666",
                            fontSize: "0.9rem",
                            cursor: "pointer",
                        }}
                    >
                        {showEdit ? "Cancel Edit" : "Edit Args"}
                    </button>
                )}
            </div>
        </div>
    );
}

export default HitlSurface;
