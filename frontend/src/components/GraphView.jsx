import { useCallback, useEffect, useRef, useState } from "react";
import ForceGraph2D from "react-force-graph-2d";
import { fetchGraph } from "../api";

const LABEL_COLORS = {
  Repository: "#8b5cf6",
  Commit: "#0ea5e9",
  File: "#22c55e",
  PullRequest: "#f59e0b",
  Developer: "#ef4444",
  Team: "#ec4899",
  Review: "#14b8a6",
  CIRun: "#a3a3a3",
  Deployment: "#6366f1",
  Incident: "#dc2626",
  Permission: "#84cc16",
};

export default function GraphView({ refreshSignal }) {
  const [graphData, setGraphData] = useState({ nodes: [], links: [] });
  const [selected, setSelected] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const containerRef = useRef(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await fetchGraph();
      setGraphData({
        nodes: data.nodes,
        links: data.edges.map((edge) => ({
          source: edge.source,
          target: edge.target,
          type: edge.type,
        })),
      });
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load, refreshSignal]);

  return (
    <div className="panel graph-panel">
      <div className="graph-header">
        <h2>Knowledge graph</h2>
        <button type="button" onClick={load} disabled={loading}>
          {loading ? "Loading..." : "Refresh"}
        </button>
      </div>

      {error && <p className="error">{error}</p>}

      <div className="graph-canvas" ref={containerRef}>
        <ForceGraph2D
          graphData={graphData}
          width={containerRef.current?.clientWidth || 600}
          height={480}
          nodeLabel={(node) => `${node.label}: ${node.id}`}
          nodeColor={(node) => LABEL_COLORS[node.label] || "#999"}
          linkLabel={(link) => link.type}
          linkDirectionalArrowLength={4}
          linkDirectionalArrowRelPos={1}
          onNodeClick={(node) => setSelected(node)}
        />
      </div>

      <div className="legend">
        {Object.entries(LABEL_COLORS).map(([label, color]) => (
          <span key={label} className="legend-item">
            <span className="legend-swatch" style={{ backgroundColor: color }} />
            {label}
          </span>
        ))}
      </div>

      {selected && (
        <div className="node-details">
          <h3>
            {selected.label}: {selected.id}
          </h3>
          <ul>
            {Object.entries(selected.properties || {}).map(([key, value]) => (
              <li key={key}>
                <strong>{key}:</strong> {value}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
