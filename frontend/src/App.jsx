import { useState } from "react";
import "./App.css";
import AskPanel from "./components/AskPanel";
import IngestPanel from "./components/IngestPanel";
import GraphView from "./components/GraphView";

function App() {
  const [refreshSignal, setRefreshSignal] = useState(0);

  return (
    <div className="app">
      <header>
        <h1>DevFlow</h1>
        <p>Ask questions, add new source text, and browse the knowledge graph.</p>
      </header>
      <main className="layout">
        <div className="column">
          <AskPanel />
          <IngestPanel onIngested={() => setRefreshSignal((n) => n + 1)} />
        </div>
        <div className="column">
          <GraphView refreshSignal={refreshSignal} />
        </div>
      </main>
    </div>
  );
}

export default App;
