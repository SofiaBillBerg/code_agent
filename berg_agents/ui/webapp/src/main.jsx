import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App.jsx";
import ErrorBoundary from "./components/ErrorBoundary.jsx";

// Global error handler to catch uncaught errors
window.addEventListener("error", (event) => {
    console.error("Global error:", event.error);
});

window.addEventListener("unhandledrejection", (event) => {
    console.error("Unhandled promise rejection:", event.reason);
});

ReactDOM.createRoot(document.getElementById("root")).render(
    <React.StrictMode>
        <ErrorBoundary>
            <App/>
        </ErrorBoundary>
    </React.StrictMode>,
);
