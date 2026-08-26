# Subagent Streaming UI — Improvement Plan

> Created for Sofia 2026-08-22 after diagnosing 5 empty Agent bubbles on "can you create in a new file?"

## Bug just fixed ✓

**Empty Agent bubbles** after second prompt were tool-only LLM turns (no `content`, only `tool_calls`).

- `../../..` always emits `message-start` even for `content=""` → `useCustomStream` was pushing empty
  `{text:""}`.
- Sub-agent namespaces (`ns.length>0`) were also pushed to root stream.

**Fix applied (commit pending):**

- `../../..` — ignore non-root namespaces, drop empty `message-finish`
  (`isEmpty → filter`), lazy-create still preserved.
- `../../..` — `messages.filter(hasText||hasTools)` so empty Markdown not rendered.
- Rebuild: `vite 471 modules → dist/assets/index-tp9_dk8k.js 474.76 kB`.

Hard-reload http://localhost:8001/ (Ctrl+Shift+R) and retry single prompt to verify single bubble.

## Top 3 priority improvements (from earlier agent answer)

### 1. Subagent Tree Visualization (currently missing)

`stream.subagents` (protocol `tools` + `lifecycle` with namespace) exists but never rendered.

- Build `SubagentCard.jsx`: `useMessages(stream, subagent)` / `useToolCalls(stream, subagent)` selector hooks.
- Show per-subagent: name, status (running/complete/error), live text, tool calls count, collapsible.
- File: `../../..`

### 2. Progress & Tool-call surfacing

- Root `App.jsx` only shows `msg.tool_calls`; global `toolCalls` state not bound to message. Tool-only turns
  disappeared.
- Add `ToolCallEnhanced` row: input JSON, output, duration, error badge. Aggregate `toolCalls` under parent message via
  `callId`.
- Add progress bar: `completed / total` subagents.

### 3. Streaming fidelity

- Keep `recursion_limit:150` (protocol.py:406, web.py).
- Ensure `translate_stream` yields `content-block-delta` only when `chunk.content` non-empty; otherwise keep
  `message-start` from creating empty entry (backend guard).

## Proposed file layout

```
berg_agents/ui/webapp/src/
  components/
    SubagentCard.jsx      ← specialist card (status icon, collapsible, useMessages selector)
    SubagentProgress.jsx  ← bar + counter
    ToolCallEnhanced.jsx  ← enhanced tool row already exists, extend
  hooks/
    useSubagentStream.js  ← wraps useCustomStream, exposes `subagents: Map<id, SubagentDiscoverySnapshot>`
  App.jsx                ← filter empty + mount SubagentTree under AI message via tool_call_id index
```

## Minimal implementation sketch (React)

```tsx
// App.jsx snippet
const subagents = [...stream.subagents.values()];
const byCallId = new Map(subagents.map(s => [s.id, s]));
...
{
    messages.map(msg => {
        const turnSubs = AIMessage.isInstance(msg)
            ? (msg.tool_calls ?? []).map(tc => byCallId.get(tc.id)).filter(Boolean)
            : [];
        return <div key={msg.id}>
            <MessageBubble msg={msg}/>
            {turnSubs.map(sa => <SubagentCard key={sa.id} stream={stream} subagent={sa}/>)}
        </div>
    })
}
```

`SubagentCard` uses existing `useCustomStream` subagent handling once we expose `subagents` state:

```js
// useCustomStream.js add
const [subagents, setSubagents] = useState(new Map());
// on message where !isRootMessage -> update map
```

## Next steps — want me to implement?

1. Scaffold `SubagentCard` + `SubagentProgress` (Est ~1h, builds on current protocol)
2. Wire `useCustomStream` to expose `subagents` map (namespace → discovery snapshot)
3. Add e2e smoke: send "research X and write file" → expect 1 root bubble + N subagent cards + file on disk

Reply "implement subagent UI" and I'll create the components in a new branch.
