import React, {useEffect, useState} from "react";

/**
 * HitlSurface component
 * Displays HITL (Human in the Loop) pending interrupt with Approve/Reject buttons
 * Shows full action context: tool name + complete args
 * Includes elapsed timer showing how long the agent has been waiting
 * Edit args: toggle a textarea pre-filled with JSON of the args, validate JSON before submit
 * Disables InputBar while displayed
 */
function HitlSurface({pending, onApprove, onReject}) {
    const [showEdit, setShowEdit] = useState(false);
    const [editedArgs, setEditedArgs] = useState("");
    const [editError, setEditError] = useState(null);
    const [elapsed, setElapsed] = useState(0);

    // Track elapsed time while HITL is pending
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

    // Initialize edited args when pending changes
    useEffect(() => {
        if (pending?.input) {
            try {
                setEditedArgs(JSON.stringify(pending.input, null, 2));
            } catch {
                setEditedArgs(String(pending.input));
            }
        }
        setEditError(null);
    }, [pending]);

    if (!pending) return null;

    const handleEditToggle = () => {
        setShowEdit(!showEdit);
        setEditError(null);
    };

    const handleEditChange = (e) => {
        setEditedArgs(e.target.value);
        setEditError(null);
    };

    const handleEditSubmit = () => {
        try {
            const parsed = JSON.parse(editedArgs);
            onApprove(parsed);
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
                <span>Human Approval Required</span>
                <span style={{fontSize: "0.8rem", color: "#e65100"}}>
          Waiting: {elapsed.toFixed(1)}s
        </span>
            </div>

            <div style={{fontSize: "0.85rem"}}>
        <span style={{fontFamily: "monospace", color: "#1a73e8"}}>
          {pending.tool}
        </span>
                <span style={{color: "#666"}}> wants to execute:</span>
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

            {showEdit && (
                <div style={{display: "flex", flexDirection: "column", gap: "0.5rem"}}>
          <textarea
              value={editedArgs}
              onChange={handleEditChange}
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
                            onApprove();
                        }
                    }}
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
                <button
                    onClick={handleEditToggle}
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
            </div>
        </div>
    );
}

export default HitlSurface;
