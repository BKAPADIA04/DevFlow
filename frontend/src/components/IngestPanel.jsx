import { useState } from "react";
import { ingestText } from "../api";

export default function IngestPanel({ onIngested }) {
  const [text, setText] = useState("");
  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  async function handleSubmit(event) {
    event.preventDefault();
    if (!text.trim()) return;
    setLoading(true);
    setError(null);
    try {
      const extracted = await ingestText(text);
      setResult(extracted);
      setText("");
      onIngested?.();
    } catch (err) {
      setError(err.message);
      setResult(null);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="panel">
      <h2>Add data</h2>
      <form onSubmit={handleSubmit} className="panel-form">
        <textarea
          value={text}
          onChange={(event) => setText(event.target.value)}
          placeholder="Paste a PR description, commit message, review comment, CI log, or incident report..."
          rows={5}
        />
        <button type="submit" disabled={loading}>
          {loading ? "Extracting..." : "Add to graph"}
        </button>
      </form>

      {error && <p className="error">{error}</p>}

      {result && (
        <div className="ingest-result">
          <p>
            Added {result.entities.length} entities and {result.relationships.length} relationships.
          </p>
          <div className="chips">
            {result.entities.map((entity) => (
              <span className="chip" key={entity.id}>
                {entity.type}: {entity.id}
              </span>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
