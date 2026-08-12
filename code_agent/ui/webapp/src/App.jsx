import React, { useEffect, useRef, useState } from "react";

const STORAGE_KEY = "code_agent_chat_history";

function loadHistory() {
	try {
		const raw = localStorage.getItem(STORAGE_KEY);
		if (raw) return JSON.parse(raw);
	} catch {
		// ignore corrupt history
	}
	return [];
}

function saveHistory(history) {
	try {
		localStorage.setItem(STORAGE_KEY, JSON.stringify(history));
	} catch {
		// ignore storage failures
	}
}

export default function App() {
	const [history, setHistory] = useState(() => loadHistory());
	const [input, setInput] = useState("");
	const [sending, setSending] = useState(false);
	const [error, setError] = useState(null);
	const messagesRef = useRef(null);

	useEffect(() => {
		saveHistory(history);
	}, [history]);

	useEffect(() => {
		if (messagesRef.current) {
			messagesRef.current.scrollTop = messagesRef.current.scrollHeight;
		}
	}, [history, sending]);

	const send = async () => {
		const message = input.trim();
		if (!message || sending) return;
		setInput("");
		setError(null);
		setSending(true);
		const nextHistory = [
			...history,
			{ role: "user", content: message },
		];
		setHistory(nextHistory);
		try {
			const res = await fetch("/chat", {
				method: "POST",
				headers: { "Content-Type": "application/json" },
				body: JSON.stringify({ message }),
			});
			const body = await res.json();
			if (!res.ok) {
				throw new Error(body?.detail || `POST /chat failed with status ${res.status}`);
			}
			setHistory([
				...nextHistory,
				{ role: "assistant", content: body.response },
			]);
		} catch (err) {
			setError(String(err.message || err));
		} finally {
			setSending(false);
		}
	};

	const onKeyDown = (event) => {
		if (event.key === "Enter" && !event.shiftKey) {
			event.preventDefault();
			send();
		}
	};

	return (
		<div
			style={{
				maxWidth: 860,
				margin: "0 auto",
				padding: "1.5rem",
				fontFamily: "system-ui, sans-serif",
				height: "100vh",
				display: "flex",
				flexDirection: "column",
			}}
		>
			<header style={{ marginBottom: "1rem" }}>
				<h1 style={{ margin: 0 }}>Code Agent Chat</h1>
				<p style={{ margin: "0.25rem 0 0", color: "#555" }}>
					Chat with the agent. It can read, edit, and create files for you.
				</p>
			</header>

			<section
				ref={messagesRef}
				style={{
					flex: 1,
					overflowY: "auto",
					border: "1px solid #e5e5e5",
					borderRadius: 8,
					padding: "1rem",
					background: "#fafafa",
				}}
			>
				{history.length === 0 && (
					<p style={{ color: "#777" }}>
						No messages yet. Try: "Create a Python module with a factorial function."
					</p>
				)}
				{history.map((item, index) => (
					<div
						key={index}
						style={{
							marginBottom: "0.75rem",
							display: "flex",
							justifyContent: item.role === "user" ? "flex-end" : "flex-start",
						}}
					>
						<div
							style={{
								background: item.role === "user" ? "#e5f0ff" : "#ffffff",
								border: "1px solid #e5e5e5",
								borderRadius: 8,
								padding: "0.6rem 0.8rem",
								maxWidth: "75%",
								whiteSpace: "pre-wrap",
								wordBreak: "break-word",
							}}
						>
							<div style={{ fontSize: "0.75rem", color: "#888", marginBottom: "0.2rem" }}>
								{item.role === "user" ? "You" : "Agent"}
							</div>
							<div>{item.content}</div>
						</div>
					</div>
				))}
				{sending && (
					<div style={{ marginBottom: "0.75rem", display: "flex", justifyContent: "flex-start" }}>
						<div
							style={{
								background: "#ffffff",
								border: "1px solid #e5e5e5",
								borderRadius: 8,
								padding: "0.6rem 0.8rem",
								color: "#777",
							}}
						>
							Thinking...
						</div>
					</div>
				)}
			</section>

			{error && (
				<p style={{ color: "#b00020", marginTop: "0.6rem" }}>{error}</p>
			)}

			<div style={{ marginTop: "0.8rem", display: "flex", gap: "0.5rem" }}>
				<textarea
					value={input}
					onChange={(e) => setInput(e.target.value)}
					onKeyDown={onKeyDown}
					placeholder="Type a message..."
					rows={2}
					disabled={sending}
					style={{
						flex: 1,
						resize: "vertical",
						padding: "0.6rem",
						borderRadius: 6,
						border: "1px solid #ccc",
						fontFamily: "inherit",
					}}
				/>
				<button
					onClick={send}
					disabled={sending || !input.trim()}
					style={{
						padding: "0.6rem 1rem",
						borderRadius: 6,
						border: "none",
						background: "#111",
						color: "#fff",
						cursor: sending ? "not-allowed" : "pointer",
					}}
				>
					{sending ? "Sending..." : "Send"}
				</button>
			</div>
		</div>
	);
}
