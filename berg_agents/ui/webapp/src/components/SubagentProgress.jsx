import React from 'react';

/**
 * SubagentProgress component
 * @param {{ subagents: Array<{id: string, name: string, status: string}> }} props
 */
function SubagentProgress({subagents}) {
    const completed = subagents.filter(sa => sa.status === 'complete').length;
    const total = subagents.length;
    const percentage = total > 0 ? Math.round((completed / total) * 100) : 0;

    return (
        <div className="mb-4">
            <div className="flex justify-between items-center text-sm text-gray-600 mb-2">
                <span>Subagent Progress</span>
                <span>{completed}/{total} complete</span>
            </div>
            <div className="h-2 bg-gray-100 rounded-full overflow-hidden">
                <div
                    className="h-full bg-blue-500 transition-all duration-300"
                    style={{width: `${percentage}%`}}
                />
            </div>
        </div>
    );
}

export default SubagentProgress;
