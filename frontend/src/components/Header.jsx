import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

function formatNow(date) {
  return date.toLocaleString("en-US", {
    month: "numeric",
    day: "numeric",
    year: "numeric",
    hour: "numeric",
    minute: "2-digit",
    second: "2-digit",
    hour12: true,
  });
}

export default function Header({ label }) {
  const [now, setNow] = useState(() => new Date());

  useEffect(() => {
    const timer = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(timer);
  }, []);

  return (
    <header className="topbar">
      <nav className="breadcrumbs" aria-label="Breadcrumb">
        <Link to="/">Home</Link>
        <span className="sep">/</span>
        <span className="muted">Error Analysis</span>
        <span className="sep">/</span>
        <span className="current">{label}</span>
      </nav>
      <time className="timestamp" dateTime={now.toISOString()}>{formatNow(now)}</time>
    </header>
  );
}
