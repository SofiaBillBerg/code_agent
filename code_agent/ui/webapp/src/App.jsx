import React, { useEffect, useState } from "react";

/**
 * Code Agent Web UI main view.
 *
 * Lists the registered capabilities, lets the user pick one, enter JSON
 * params, and invoke it. The server returns the invocation response plus
 * the audited receipt, both rendered here.
 */
export default function App() {
	const [capabilities, setCapabilities] = useState([]);
	const [loadError, setLoadError] = useState(null);
	const [loadingCapabilities, setLoadingCapabilities] = useState(true);
	const [selectedId, setSelectedId] = useState("");
	const [paramsText, setParamsText] = useState("{}");
	const [result, setResult] = useState(null);
	const [error, setError] = useState(null);
	const [invoking, setInvoking] = useState(false);

	const loadCapabilities = async () => {
		setLoadingCapabilities(true);
		setLoadError(null);
		try {
			const res = await fetch("/capabilities");
			if (!res.ok) {
				throw new Error(
					`GET /capabilities failed with status ${res.status}`,
				);
			}
			const data = await res.json();
			setCapabilities(data);
			if (data.length > 0) {
				setSelectedId(data[0].id);
			}
		} catch (err) {
			setLoadError(
				err.message || "Failed to reach the backend. Is `code-agent serve --web` running?",
			);
		} finally {
			setLoadingCapabilities(false);
		}
	};

	useEffect(() => {
		loadCapabilities();
	}, []);

	const selected = capabilities.find((c) => c.id === selectedId);

	const invoke = async () => {
		setInvoking(true);
		setError(null);
		setResult(null);
		let params;
		try {
			params = JSON.parse(paramsText || "{}");
		} catch (err) {
			setError(`Params are not valid JSON: ${err.message}`);
			setInvoking(false);
			return;
		}
		try {
			const res = await fetch("/invoke", {
				method: "POST",
				headers: { "Content-Type": "application/json" },
				body: JSON.stringify({ capability_id: selectedId, params }),
			});
			const body = await res.json();
			if (!res.ok) {
				throw new Error(
					(body && body.detail) ||
						`POST /invoke failed with status ${res.status}`,
				);
			}
			setResult(body);
		} catch (err) {
			setError(String(err.message || err));
		} finally {
			setInvoking(false);
		}
	};

	return (
		<div
			style={{
				maxWidth: 860,
				margin: "0 auto",
				padding: "1.5rem",
				fontFamily: "system-ui, sans-serif",
			}}
		>
			<h1>Code Agent Web UI</h1>

			{loadError && (
				<p style={{ color: "#b00020" }}>
					Failed to load capabilities: {loadError}
				</p>
			)}
			{loadError && (
				<button onClick={loadCapabilities} style={{ marginTop: "0.4rem" }}>
					Retry
				</button>
			)}

			<section>
				<h2>Capabilities</h2>
				{capabilities.length === 0 && !loadError ? (
					<p>Loading capabilities...</p>
				) : (
					<ul style={{ listStyle: "none", padding: 0 }}>
						{capabilities.map((c) => (
							<li key={c.id} style={{ marginBottom: "0.4rem" }}>
								<label
									style={{
										display: "flex",
										gap: "0.5rem",
										alignItems: "baseline",
									}}
								>
									<input
										type="radio"
										name="capability"
										value={c.id}
										checked={selectedId === c.id}
										onChange={() => setSelectedId(c.id)}
									/>
									<strong>{c.id}</strong>
									<span style={{ color: "#555" }}>- {c.intent || ""}</span>
								</label>
							</li>
						))}
					</ul>
				)}
			</section>

			{selected && (
				<section>
					<h2>Invoke: {selected.id}</h2>
					<p style={{ color: "#555" }}>
						Risk class: {selected.risk_class ?? "n/a"} . Input schema:{" "}
						{selected.input_schema
							? JSON.stringify(selected.input_schema)
							: "{}"}
					</p>
					<label htmlFor="params">Params (JSON)</label>
					<br />
					<textarea
						id="params"
						value={paramsText}
						onChange={(e) => setParamsText(e.target.value)}
						rows={4}
						style={{
							width: "100%",
							fontFamily: "monospace",
							marginTop: "0.3rem",
						}}
						spellCheck={false}
					/>
					<br />
					<button
						onClick={invoke}
						disabled={invoking}
						style={{ marginTop: "0.6rem" }}
					>
						{invoking ? "Invoking..." : "Invoke"}
					</button>
				</section>
			)}

			{error && <p style={{ color: "#b00020" }}>{error}</p>}

			{result && (
				<section>
					<h2>Result</h2>
					<h3>Response</h3>
					<pre
						style={{
							background: "#f6f6f6",
							padding: "0.8rem",
							overflow: "auto",
						}}
					>
						{JSON.stringify(result.response, null, 2)}
					</pre>
					<h3>Receipt</h3>
					<pre
						style={{
							background: "#f6f6f6",
							padding: "0.8rem",
							overflow: "auto",
						}}
					>
						{JSON.stringify(result.receipt, null, 2)}
					</pre>
				</section>
			)}
		</div>
	);
}
