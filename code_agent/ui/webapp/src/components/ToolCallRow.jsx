import React, {useEffect, useState} from "react";

/**
 * ToolCallRow component
 * Shows tool execution progress: spinner on start, elapsed time + output on end
 * Collapsible display for tool output
 * Renders all three states: running, finished, error
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

    // Generic fallback for unknown tools
    const toolName = toolCall.tool || toolCall.name || "Unknown tool";
    const toolInput = toolCall.input || toolCall.arguments || {};
    const toolOutput = toolCall.output || toolCall.result || "";
    const toolError = toolCall.error || "";

    // Truncate output to 200 chars with ellipsis
    const truncatedOutput =
        toolOutput && toolOutput.length > 200
            ? toolOutput.substring(0, 200) + "…"
            : toolOutput;

    return (
        <div className="tool-call">
            <button
                onClick={() => setExpanded(!expanded)}
                className="tool-call-header"
            >
                <span className="tool-call-name">
                    {toolCall.status === "pending" && (
                        <span className="spinner" style={{marginRight: "0.5rem"}}>
                            ⟳
                        </span>
                    )}
                    {toolName}
                </span>
                <span className="tool-call-meta">
                    {toolCall.status === "done"
                        ? `${elapsed.toFixed(1)}s`
                        : toolCall.status === "pending"
                            ? `${elapsed.toFixed(1)}s...`
                            : ""}
                </span>
            </button>
            {expanded && toolCall.status === "done" && (
                <div className="tool-call-body">
                    <div className="tool-call-input">
                        {JSON.stringify(toolInput, null, 2)}
                    </div>
                    <div className="tool-call-output">
                        Output: {truncatedOutput}
                    </div>
                    {toolOutput && toolOutput.length > 200 && (
                        <details>
                            <summary className="tool-call-summary">
                                Show full output
                            </summary>
                            <div className="tool-call-full-output">
                                {toolOutput}
                            </div>
                        </details>
                    )}
                </div>
            )}
            {expanded && toolCall.status === "error" && (
                <div className="tool-call-error">
                    Error: {toolError || "Unknown error"}
                </div>
            )}
        </div>
    );
}

export default ToolCallRow;
