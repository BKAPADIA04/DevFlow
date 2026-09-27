const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || "http://localhost:8000";

async function request(path, options) {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!response.ok) {
    const text = await response.text();
    throw new Error(`${path} failed (${response.status}): ${text}`);
  }
  return response.json();
}

export function askQuestion(question) {
  return request("/api/ask", {
    method: "POST",
    body: JSON.stringify({ question }),
  });
}

export function ingestText(text) {
  return request("/api/ingest", {
    method: "POST",
    body: JSON.stringify({ text }),
  });
}

export function fetchGraph(limit = 300) {
  return request(`/api/graph?limit=${limit}`);
}
