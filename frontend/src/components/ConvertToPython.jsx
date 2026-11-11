import { useState } from "react";
import { api } from "../api.js";
import { Alert, Empty } from "./ui.jsx";
import BusinessLogic from "./BusinessLogic.jsx";

function download(filename, text) {
  const blob = new Blob([text], { type: "text/plain" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.click();
  URL.revokeObjectURL(url);
}

/** Converts the selected paragraph (and the paragraphs it PERFORMs) into a Python module. */
export default function ConvertToPython({ analysisId, name }) {
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  function convert() {
    setBusy(true);
    setError(null);
    api
      .paragraphPython(analysisId, name)
      .then(setResult)
      .catch((e) => setError(e.message))
      .finally(() => setBusy(false));
  }

  return (
    <div className="convert-block">
      <div className="convert-actions">
        <button type="button" className="action-btn" onClick={convert} disabled={busy}>
          {busy ? "CONVERTING…" : "CONVERT TO PYTHON"}
        </button>
        {result && (
          <>
            <button type="button" className="text-btn" onClick={() => download(`${name.toLowerCase()}.py`, result.module)}>
              Download module
            </button>
            <button type="button" className="text-btn" onClick={() => download("cobol_runtime.py", result.runtime)}>
              Download runtime
            </button>
          </>
        )}
      </div>
      {error && <Alert tone="error">{error}</Alert>}
      {result && (
        <>
          <p className="convert-note">
            Converted: {result.paragraphs.join(", ")}. The module needs cobol_runtime.py in the same folder.
          </p>
          {result.notes.length > 0 && (
            <Alert tone="warn">{result.notes.length} statement(s) were not converted: {result.notes.slice(0, 4).join(" · ")}</Alert>
          )}
          <h3 className="sub-title">Python module</h3>
          <pre className="code code-compact convert-code">{result.module}</pre>
          <BusinessLogic analysisId={analysisId} name={name} />
        </>
      )}
      {!result && !error && <Empty>Converts this paragraph and the paragraphs it PERFORMs into Python.</Empty>}
    </div>
  );
}
