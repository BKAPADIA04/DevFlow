import { useState } from "react";
import { askQuestion } from "../api";

export default function AskPanel() {
  const [question, setQuestion] = useState("");
  const [answer, setAnswer] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  async function handleSubmit(event) {
    event.preventDefault();
    if (!question.trim()) return;
    setLoading(true);
    setError(null);
    try {
      const result = await askQuestion(question);
      setAnswer(result);
    } catch (err) {
      setError(err.message);
      setAnswer(null);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="panel">
      <h2>Ask</h2>
      <form onSubmit={handleSubmit} className="panel-form">
        <textarea
          value={question}
          onChange={(event) => setQuestion(event.target.value)}
          placeholder="e.g. Who has permission to modify repo-devflow-core and what team are they part of?"
          rows={3}
        />
        <button type="submit" disabled={loading}>
          {loading ? "Thinking..." : "Ask"}
        </button>
      </form>

      {error && <p className="error">{error}</p>}

      {answer && (
        <div className="answer">
          <span className={`badge ${answer.source}`}>{answer.source}</span>
          {!answer.has_sufficient_evidence && (
            <span className="badge insufficient">insufficient evidence</span>
          )}
          <p>{answer.answer}</p>
          {answer.cited_entity_ids.length > 0 && (
            <div className="chips">
              {answer.cited_entity_ids.map((id) => (
                <span className="chip" key={id}>
                  {id}
                </span>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
