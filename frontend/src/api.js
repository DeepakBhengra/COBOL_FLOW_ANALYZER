const BASE = "/api";

async function parse(res) {
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail || res.statusText || "Request failed");
  }
  return res.json();
}

export const api = {
  sample: () => fetch(`${BASE}/sample`).then(parse),
  analyze: (name, source) =>
    fetch(`${BASE}/analyze`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name, source }),
    }).then(parse),
  getAnalysis: (id) => fetch(`${BASE}/analyses/${id}`).then(parse),
  source: (id) => fetch(`${BASE}/analyses/${id}/source`).then(parse),
  paragraph: (id, name) =>
    fetch(`${BASE}/analyses/${id}/paragraphs/${encodeURIComponent(name)}`).then(parse),
  exportUrl: (id, fmt) => `${BASE}/analyses/${id}/export/${fmt}`,
  copybooks: (q = "") =>
    fetch(`${BASE}/copybooks?q=${encodeURIComponent(q)}&limit=300`).then(parse),
  copybook: (name) => fetch(`${BASE}/copybooks/${encodeURIComponent(name)}`).then(parse),
  copybookCategories: () => fetch(`${BASE}/copybooks/categories`).then(parse),
  saveFieldNote: (name, path, body) =>
    fetch(`${BASE}/copybooks/${encodeURIComponent(name)}/fields/${encodeURIComponent(path)}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }).then(parse),
  deleteFieldNote: (name, path) =>
    fetch(`${BASE}/copybooks/${encodeURIComponent(name)}/fields/${encodeURIComponent(path)}`, {
      method: "DELETE",
    }).then(parse),
  paragraphLocals: (id, name) =>
    fetch(`${BASE}/analyses/${id}/paragraphs/${encodeURIComponent(name)}/locals`).then(parse),
  inputBuffer: (id, buffer = "", assume = "") =>
    fetch(`${BASE}/analyses/${id}/input-buffer?buffer=${encodeURIComponent(buffer)}&assume=${encodeURIComponent(assume)}`).then(parse),
  businessLogic: (id, name) =>
    fetch(`${BASE}/analyses/${id}/paragraphs/${encodeURIComponent(name)}/business-logic`).then(parse),
  copybookProcedure: (name) =>
    fetch(`${BASE}/copybooks/${encodeURIComponent(name)}/procedure`).then(parse),
  paragraphPython: (id, name) =>
    fetch(`${BASE}/analyses/${id}/paragraphs/${encodeURIComponent(name)}/python`).then(parse),
  paragraphSummary: (id, name) =>
    fetch(`${BASE}/analyses/${id}/paragraphs/${encodeURIComponent(name)}/summary`).then(parse),
  programLog: (limit = 200) => fetch(`${BASE}/program-log?limit=${limit}`).then(parse),
  programHistory: (fingerprint) =>
    fetch(`${BASE}/program-log/${encodeURIComponent(fingerprint)}`).then(parse),
  saveProgramDetail: (fingerprint, body) =>
    fetch(`${BASE}/program-log/${encodeURIComponent(fingerprint)}/details`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }).then(parse),
  deleteProgramDetail: (fingerprint, category, key) =>
    fetch(
      `${BASE}/program-log/${encodeURIComponent(fingerprint)}/details?key=${encodeURIComponent(key)}&category=${encodeURIComponent(category)}`,
      { method: "DELETE" },
    ).then(parse),
  saveCopybookDescription: (name, description) =>
    fetch(`${BASE}/copybooks/${encodeURIComponent(name)}/description`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ description }),
    }).then(parse),
};
