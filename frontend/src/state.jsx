import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { api } from "./api.js";

const STORAGE_KEY = "cobol-flow-analysis-id";

const AnalysisContext = createContext(null);

function readStoredId() {
  try {
    return window.localStorage.getItem(STORAGE_KEY);
  } catch {
    return null;
  }
}

function writeStoredId(id) {
  try {
    if (id) window.localStorage.setItem(STORAGE_KEY, id);
    else window.localStorage.removeItem(STORAGE_KEY);
  } catch {
    /* storage can be blocked; the analysis simply will not survive a reload */
  }
}

/** Holds the current analysis for every screen. */
export function AnalysisProvider({ children }) {
  const [analysis, setAnalysis] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    const id = readStoredId();
    if (!id) return;
    api
      .getAnalysis(id)
      .then(setAnalysis)
      .catch(() => writeStoredId(null));
  }, []);

  const load = useCallback(async (name, source) => {
    setBusy(true);
    setError(null);
    try {
      const data = await api.analyze(name, source);
      setAnalysis(data);
      writeStoredId(data.id);
      return data;
    } catch (err) {
      setError(err.message);
      return null;
    } finally {
      setBusy(false);
    }
  }, []);

  const clear = useCallback(() => {
    setAnalysis(null);
    setError(null);
    writeStoredId(null);
  }, []);

  const value = useMemo(
    () => ({ analysis, busy, error, setError, load, clear }),
    [analysis, busy, error, load, clear]
  );
  return <AnalysisContext.Provider value={value}>{children}</AnalysisContext.Provider>;
}

export function useAnalysis() {
  const ctx = useContext(AnalysisContext);
  if (!ctx) throw new Error("useAnalysis must be used inside AnalysisProvider");
  return ctx;
}
