import React, {useEffect, useState} from "react";

/**
 * ToolCallRow component
 * Shows tool execution progress: spinner on start, elapsed time + output on end
 * Collapsible display for tool output
 * Renders all three states: running, finished, error
 * Compatible with @langchain/react AssembledToolCall shape
 */
function ToolCallRow({toolCall}) {
    const [expanded, setExpanded] = React.useState(false);
    const [elapsed, setElapsed] = React.useState(0);

    // Map useStream status to legacy labels
    const status = toolCall.status === "finished" ? "done" : toolCall.status === "error" ? "error" : toolCall.status;

    // Track elapsed time from tool_start
    React.useEffect(() => {
        if (status === "pending" || status === "running") {
            setElapsed(0);
            const startTime = Date.now();
            const interval = setInterval(() => {
                setElapsed((Date.now() - startTime) / 1000);
            }, 100);
            return () => clearInterval(interval);
        }
    }, [status, toolCall.callId]);

    // Update elapsed time when tool ends with specific duration
    React.useEffect(() => {
        if ((status === "done" || status === "finished") && toolCall.elapsedS !== undefined) {
            setElapsed(toolCall.elapsedS);
        }
    }, [status, toolCall.elapsedS, toolCall.callId]);

    const toolName = toolCall.name || toolCall.tool || "Unknown tool";
    const toolInput = toolCall.input ?? toolCall.args ?? {};
    const toolOutput = toolCall.output ?? toolCall.result ?? "";
    const toolError = toolCall.error ?? "";

    const truncatedOutput =
        toolOutput && typeof toolOutput === "string" && toolOutput.length > 200
            ? toolOutput.substring(0, 200) + "…"
            : toolOutput;

    return (
        <div className="tool-call">
            <button
                onClick={() => setExpanded(!expanded)}
                className="tool-call-header"
            >
                <span className="tool-call-name">
                    {(status === "pending" || status === "running") && (
                        <span className="spinner" style={{marginRight: "0.5rem"}}>
                            ⟳
                        </span>
                    )}
                    {toolName}
                </span>
                <span className="tool-call-meta">
                    {status === "done" || status === "finished"
                        ? `${elapsed.toFixed(1)}s`
                        : (status === "pending" || status === "running")
                            ? `${elapsed.toFixed(1)}s...`
                            : ""}
                </span>
            </button>
            {expanded && (status === "done" || status === "finished") && (
                <div className="tool-call-body">
                    <div className="tool-call-input">
                        {JSON.stringify(toolInput, null, 2)}
                    </div>
                    <div className="tool-call-output">
                        Output: {truncatedOutput}
                    </div>
                    {toolOutput && typeof toolOutput === "string" && toolOutput.length > 200 && (
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
            {expanded && status === "error" && (
                <div className="tool-call-error">
                    Error: {toolError || "Unknown error"}
                </div>
            )}
        </div>
    );
}

export default ToolCallRow;
