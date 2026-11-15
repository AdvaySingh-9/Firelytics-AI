import React, { useEffect, useMemo, useState } from "react";
import { investigations } from "./data";
import "./styles.css";
const API = import.meta.env.VITE_API_BASE_URL || "http://localhost:8000/api";
const assetLabel = {
  metadata_only: "Metadata only",
  experimental_data: "Experimental data listed",
  research_documents: "Research documents listed",
  analyzed_data: "Analyzed data listed",
};
const sections = [
  [
    "1. OVERVIEW",
    [
      "Experiment Title",
      "Problem Statement",
      "Objective",
      "Background",
      "Research Questions",
    ],
  ],
  [
    "2. EXPERIMENT DETAILS",
    [
      "Experimental Setup",
      "Materials & Equipment",
      "Experimental Conditions",
      "Methodology",
      "Variables",
      "Data Collection",
    ],
  ],
  [
    "3. RESULTS & ANALYSIS",
    [
      "Key Observations",
      "Results",
      "Scientific Explanation",
      "Earth vs. Microgravity Comparison",
      "Limitations",
      "Conclusion",
    ],
  ],
  [
    "4. PRACTICAL INSIGHTS",
    [
      "Fire Safety Implications",
      "Space Mission Relevance",
      "Future Research",
      "References & Sources",
    ],
  ],
];
function App() {
  const [page, setPage] = useState("home"),
    [query, setQuery] = useState(""),
    [selected, setSelected] = useState("PSI-69"),
    [picked, setPicked] = useState(["PSI-69", "PSI-68"]),
    [compareMode, setCompareMode] = useState("studies"),
    [testA, setTestA] = useState("baseline"),
    [testB, setTestB] = useState("changed"),
    [apiStatus, setApiStatus] = useState("Checking API…"),
    [remote, setRemote] = useState(false);
  const studies = investigations;
  const study = studies.find((x) => x.study_id === selected) || studies[0];
  const results = useMemo(() => {
    const q = query.toLowerCase().trim();
    if (!q) return studies;
    return studies
      .map((s) => ({
        ...s,
        score:
          [
            s.study_id,
            s.title,
            s.acronym,
            s.objective,
            s.summary,
            s.assets.join(" "),
          ]
            .join(" ")
            .toLowerCase()
            .split(q).length - 1,
      }))
      .filter((s) => s.score > 0)
      .sort((a, b) => b.score - a.score);
  }, [query]);
  useEffect(() => {
    fetch(`${API}/health`)
      .then((r) => (r.ok ? r.json() : Promise.reject()))
      .then(() => {
        setApiStatus("FastAPI connected");
        setRemote(true);
      })
      .catch(() => setApiStatus("Demo catalogue mode"));
  }, []);
  const openStudy = (id) => {
    setSelected(id);
    setPage("detail");
  };
  const togglePick = (id) =>
    setPicked((p) =>
      p.includes(id)
        ? p.filter((x) => x !== id)
        : p.length < 4
          ? [...p, id]
          : p,
    );
  const explain = () => setPage("explain");
  const compareTests = () => {
    setCompareMode("tests");
    setPage("compare");
  };
  const compareStudies = () => {
    setCompareMode("studies");
    setPage("compare");
  };
  const ask = () => {
    setPage("search");
  };
  return (
    <div className="app">
      <header className="top">
        <div className="brand" onClick={() => setPage("home")}>
          <span className="logo">F</span>
          <span>
            FIRELYTICS <b>AI</b>
            <small>MICROGRAVITY COMBUSTION INTELLIGENCE</small>
          </span>
        </div>
        <div className="topright">
          <span className="status">
            <i /> {apiStatus}
          </span>
          <button className="ghost" onClick={() => setPage("home")}>
            Home
          </button>
        </div>
      </header>
      <main>
        {page === "home" && (
          <>
            <section className="hero">
              <div>
                <div className="eyebrow">
                  NASA PHYSICAL SCIENCES INFORMATICS
                </div>
                <h1>
                  Explore combustion
                  <br />
                  <em>research in microgravity.</em>
                </h1>
                <p>
                  Search investigations, open experiment metadata, and use
                  AI-assisted workflows to explain and compare the research.
                </p>
                <div className="searchbar">
                  <input
                    value={query}
                    onChange={(e) => setQuery(e.target.value)}
                    onKeyDown={(e) => e.key === "Enter" && setPage("search")}
                    placeholder="Search an experiment using AI… e.g. How do heptane droplets burn in microgravity?"
                  />
                  <button onClick={ask}>⌕</button>
                </div>
                <div className="hint">
                  Try: FLEX · flame extinction · droplet combustion · spacecraft
                  fire safety
                </div>
              </div>
              <div className="hero-art">
                <div className="orb orb1" />
                <div className="orb orb2" />
                <div className="orbit" />
                <div className="flame">✦</div>
                <div className="art-caption">COMBUSTION / MICROGRAVITY</div>
              </div>
            </section>
            <section className="section-head">
              <div>
                <div className="eyebrow">RESEARCH CATALOGUE</div>
                <h2>Explore investigations</h2>
                <p>Select an investigation to view its details and AI tools.</p>
              </div>
              <span className="count">
                {studies.length} TEAM-CATALOGUED STUDIES
              </span>
            </section>
            <div className="study-grid">
              {studies.map((s, i) => (
                <button
                  className="study-card"
                  key={s.study_id}
                  onClick={() => openStudy(s.study_id)}
                >
                  <div className="card-top">
                    <span className="study-id">{s.study_id}</span>
                    <span className="arrow">↗</span>
                  </div>
                  <h3>{s.title}</h3>
                  <p>{s.objective}</p>
                  <div className="card-foot">
                    <span className="pill">
                      {assetLabel[s.availability] || "Metadata"}
                    </span>
                    <span>{s.assets.length} asset categories</span>
                  </div>
                </button>
              ))}
            </div>
            <div className="notice">
              Catalogue coverage reflects the 11 investigations supplied by the
              project team. It is not a complete NASA PSI catalogue.
            </div>
          </>
        )}
        {page === "search" && (
          <>
            <div className="page-title">
              <div className="eyebrow">AI SMART SEARCH</div>
              <h1>Search investigations</h1>
              <p>
                Find relevant PSI records using natural-language questions or
                keywords.
              </p>
            </div>
            <div className="searchbar wide">
              <input
                autoFocus
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="Ask about a fuel, suppressant, experiment objective, or research area…"
              />
              <button>⌕</button>
            </div>
            <div className="result-meta">
              {results.length} matching investigations · ranked by local
              catalogue keyword relevance
            </div>
            <div className="study-grid">
              {results.map((s) => (
                <button
                  className="study-card"
                  key={s.study_id}
                  onClick={() => openStudy(s.study_id)}
                >
                  <div className="card-top">
                    <span className="study-id">{s.study_id}</span>
                    <span className="arrow">↗</span>
                  </div>
                  <h3>{s.title}</h3>
                  <p>{s.objective}</p>
                  <div className="card-foot">
                    <span className="pill">{assetLabel[s.availability]}</span>
                    <span>Open investigation →</span>
                  </div>
                </button>
              ))}
            </div>
            {!results.length && (
              <div className="empty">
                No matching records in the current catalogue. Try “FLEX”,
                “droplet”, or “combustion”.
              </div>
            )}
          </>
        )}
        {page === "detail" && (
          <>
            <div className="crumb" onClick={() => setPage("home")}>
              ← All investigations <span>/ {study.study_id}</span>
            </div>
            <div className="detail-head">
              <div>
                <div className="eyebrow">
                  INVESTIGATION PROFILE · {study.study_id}
                </div>
                <h1>{study.title}</h1>
                <p>{study.objective}</p>
                <div className="tags">
                  <span className="pill">
                    {study.acronym !== "—" ? study.acronym : "NASA PSI"}
                  </span>
                  <span className="pill">{assetLabel[study.availability]}</span>
                  <span className="pill">
                    {study.assets.length} asset categories listed
                  </span>
                </div>
              </div>
              <a
                className="source"
                href={study.source_url}
                target="_blank"
                rel="noreferrer"
              >
                Open NASA PSI ↗
              </a>
            </div>
            <div className="detail-layout">
              <article className="panel main-panel">
                <div className="panel-title">
                  <span>INVESTIGATION DETAILS</span>
                  <span className="muted">Metadata view</span>
                </div>
                <h3>Objective</h3>
                <p>{study.objective}</p>
                <h3>Research metadata</h3>
                <div className="metadata-grid">
                  <div>
                    <small>Investigation ID</small>
                    <b>{study.study_id}</b>
                  </div>
                  <div>
                    <small>Acronym</small>
                    <b>{study.acronym}</b>
                  </div>
                  <div>
                    <small>Research area</small>
                    <b>
                      {study.study_id === "PSI-69"
                        ? "Combustion Science"
                        : "Not enriched in local catalogue"}
                    </b>
                  </div>
                  <div>
                    <small>Sub-research area</small>
                    <b>
                      {study.study_id === "PSI-69"
                        ? "Spacecraft Fire Safety"
                        : "Not enriched in local catalogue"}
                    </b>
                  </div>
                  <div>
                    <small>Flight platform</small>
                    <b>
                      {study.study_id === "PSI-69"
                        ? "International Space Station (ISS)"
                        : "Not enriched in local catalogue"}
                    </b>
                  </div>
                  <div>
                    <small>DOI</small>
                    <b>
                      {study.study_id === "PSI-69"
                        ? "10.60555/mbq8-0451"
                        : "Not listed in local catalogue"}
                    </b>
                  </div>
                </div>
                <h3>Available data categories</h3>
                <div className="asset-list">
                  {study.assets.length ? (
                    study.assets.map((a) => <span key={a}>✓ {a}</span>)
                  ) : (
                    <span>
                      Only metadata is listed in the team's supplied inventory.
                      Other file categories are not listed here.
                    </span>
                  )}
                </div>
                <div className="notice">
                  Asset availability is based on the team inventory, not a
                  file-by-file audit of NASA PSI. “Not listed” does not mean
                  confirmed absent.
                </div>
              </article>
              <aside className="ai-panel">
                <div className="ai-label">✦ AI CORNER</div>
                <p>Explore this investigation with focused research tools.</p>
                <button className="action primary" onClick={explain}>
                  Explain this experiment{" "}
                  <small>Get the details in simple words</small>
                </button>
                <button className="action" onClick={compareTests}>
                  Compare tests{" "}
                  <small>Compare test runs within this experiment</small>
                </button>
                <button className="action" onClick={compareStudies}>
                  Compare experiments{" "}
                  <small>Compare this study with another PSI record</small>
                </button>
                <div className="ai-foot">
                  AI functions are currently metadata-grounded demo workflows.
                  Connect a document retrieval model for source-level findings.
                </div>
              </aside>
            </div>
          </>
        )}
        {page === "explain" && (
          <>
            <div className="crumb" onClick={() => setPage("detail")}>
              ← Back to {study.study_id}
            </div>
            <div className="page-title">
              <div className="eyebrow">AI EXPLANATION · {study.study_id}</div>
              <h1>{study.title}</h1>
              <p>
                A structured, plain-language guide based on the investigation
                metadata available in this project.
              </p>
            </div>
            <div className="explain-wrap">
              <div className="explain-banner">
                <span>✦</span>
                <div>
                  <b>Metadata-grounded explanation</b>
                  <p>
                    This view explains the study design and stated objectives.
                    It does not claim to summarize unavailable experimental
                    results.
                  </p>
                </div>
              </div>
              {sections.map(([heading, items], i) => (
                <section className="explain-section" key={heading}>
                  <h2>{heading}</h2>
                  {items.map((item, j) => (
                    <div className="explain-row" key={item}>
                      <b>{item}</b>
                      <p>{explainText(study, item, i, j)}</p>
                    </div>
                  ))}
                </section>
              ))}
              <div className="source-line">
                Source:{" "}
                <a href={study.source_url} target="_blank" rel="noreferrer">
                  NASA PSI investigation record ↗
                </a>{" "}
                ·{" "}
                {study.study_id === "PSI-69"
                  ? "DOI: 10.60555/mbq8-0451"
                  : "Source details should be verified on NASA PSI."}
              </div>
            </div>
          </>
        )}
        {page === "compare" && (
          <>
            <div className="crumb" onClick={() => setPage("detail")}>
              ← Back to investigation
            </div>
            <div className="page-title">
              <div className="eyebrow">AI COMPARISON WORKSPACE</div>
              <h1>
                {compareMode === "tests"
                  ? "Compare tests"
                  : "Compare experiments"}
              </h1>
              <p>
                {compareMode === "tests"
                  ? "Compare two test runs from the same experiment using their objectives, initial parameters, changed parameters, and conclusions."
                  : "Select investigations to compare their objectives, methods, metadata, and evidence availability."}
              </p>
            </div>
            <div className="mode-tabs">
              <button
                className={compareMode === "tests" ? "active" : ""}
                onClick={() => setCompareMode("tests")}
              >
                Compare tests
              </button>
              <button
                className={compareMode === "studies" ? "active" : ""}
                onClick={() => setCompareMode("studies")}
              >
                Compare experiments
              </button>
            </div>
            {compareMode === "studies" ? (
              <>
                <div className="selector-grid">
                  {studies.map((s) => (
                    <label className="selector" key={s.study_id}>
                      <input
                        type="checkbox"
                        checked={picked.includes(s.study_id)}
                        onChange={() => togglePick(s.study_id)}
                      />
                      <span>
                        <b>{s.study_id}</b>
                        {s.title}
                      </span>
                    </label>
                  ))}
                </div>
                <div className="compare-columns">
                  {picked.length ? (
                    picked.map((id) => {
                      const s = studies.find((x) => x.study_id === id);
                      return (
                        <div className="compare-col" key={id}>
                          <div className="study-id">{s.study_id}</div>
                          <h3>{s.title}</h3>
                          <h4>OBJECTIVE</h4>
                          <p>{s.objective}</p>
                          <h4>RESEARCH AREA</h4>
                          <p>
                            {s.study_id === "PSI-69"
                              ? "Combustion Science"
                              : "Not enriched in local catalogue"}
                          </p>
                          <h4>DATA AVAILABILITY</h4>
                          <p>
                            {assetLabel[s.availability]} · {s.assets.length}{" "}
                            listed categories
                          </p>
                          <h4>CONCLUSION</h4>
                          <p>
                            Conclusion is not included in the current metadata
                            catalogue. Review the linked source documents before
                            drawing conclusions.
                          </p>
                        </div>
                      );
                    })
                  ) : (
                    <div className="empty">
                      Select at least one investigation above.
                    </div>
                  )}
                </div>
              </>
            ) : (
              <>
                <div className="test-controls">
                  <label>
                    Test 1
                    <select
                      value={testA}
                      onChange={(e) => setTestA(e.target.value)}
                    >
                      <option value="baseline">
                        Baseline test (metadata framework)
                      </option>
                      <option value="uploadedA">Uploaded test record A</option>
                    </select>
                  </label>
                  <label>
                    Test 2
                    <select
                      value={testB}
                      onChange={(e) => setTestB(e.target.value)}
                    >
                      <option value="changed">
                        Changed-parameter test (metadata framework)
                      </option>
                      <option value="uploadedB">Uploaded test record B</option>
                    </select>
                  </label>
                </div>
                <div className="compare-columns">
                  <div className="compare-col">
                    <div className="study-id">TEST 1</div>
                    <h3>Baseline test</h3>
                    <h4>OBJECTIVE</h4>
                    <p>
                      Establish the reference condition for the selected
                      experiment.
                    </p>
                    <h4>INITIAL PARAMETERS</h4>
                    <p>
                      Enter or upload the test-level conditions, fuel, pressure,
                      oxygen fraction, droplet size, and suppressant details to
                      populate this comparison.
                    </p>
                    <h4>CONCLUSION</h4>
                    <p>Awaiting test-level source data.</p>
                  </div>
                  <div className="compare-col">
                    <div className="study-id">TEST 2</div>
                    <h3>Changed-parameter test</h3>
                    <h4>OBJECTIVE</h4>
                    <p>
                      Evaluate the effect of one or more changed experimental
                      parameters against the reference condition.
                    </p>
                    <h4>CHANGES IN PARAMETERS</h4>
                    <p>
                      Parameter differences will be identified once two actual
                      test records are supplied. No numerical differences are
                      inferred from study-level metadata.
                    </p>
                    <h4>CONCLUSION</h4>
                    <p>Awaiting test-level source data.</p>
                  </div>
                </div>
                <div className="notice">
                  Test-level records have not been supplied in the current
                  catalogue. This comparison layout is ready for actual
                  experimental tables; it intentionally does not invent test
                  measurements or conclusions.
                </div>
              </>
            )}
          </>
        )}
      </main>
      <footer>
        <span>FIRELYTICS AI</span>
        <span>Research support · Not an operational fire-safety system</span>
        <span>NASA PSI metadata · Team catalogue</span>
      </footer>
    </div>
  );
}
function explainText(s, item, section, index) {
  if (item === "Experiment Title") return s.title;
  if (item === "Objective") return s.objective;
  if (item === "Problem Statement")
    return "The investigation addresses how combustion and flame behaviour can differ in microgravity, where buoyancy-driven flow is reduced or absent. The exact problem statement should be checked against the original investigation record.";
  if (item === "Background")
    return "Microgravity combustion research helps researchers understand how fuel, oxygen, heat transfer, and flame extinction interact when buoyant convection is altered.";
  if (item === "Research Questions")
    return "Questions may concern flammability boundaries, droplet burning and extinction, and the role of environmental conditions or suppressant agents, where specified by the source.";
  if (item === "Experimental Setup" || item === "Materials & Equipment")
    return s.study_id === "PSI-69"
      ? "The FLEX investigation used the Combustion Integrated Rack and Multi-user Droplet Combustion Apparatus on the International Space Station."
      : "Detailed setup and equipment are not enriched in this local metadata record.";
  if (
    item === "Experimental Conditions" ||
    item === "Variables" ||
    item === "Methodology"
  )
    return s.study_id === "PSI-69"
      ? "The FLEX approach describes tests that vary ambient pressure, oxygen mole fraction, droplet size, and suppressant conditions; some flight tests also examine slow sub-buoyant flow. Consult the source for the precise test matrix."
      : "Detailed conditions and methods are not included in this local catalogue record.";
  if (item === "Data Collection")
    return s.assets.includes("Experimental Table")
      ? "An experimental table is listed in the team inventory. Its measurements must be opened and checked at the NASA PSI source before interpretation."
      : "No experimental table is listed in the supplied team inventory.";
  if (section === 2)
    return "Specific observations, numerical results, and conclusions are not available in this metadata-only explanation. Open the NASA PSI source documents or experimental tables to review the actual evidence.";
  if (section === 3)
    return "This section requires source-level findings and supporting measurements. Firelytics does not generate operational recommendations from metadata alone.";
  return "This information is not present in the currently enriched metadata. Refer to the official NASA PSI investigation record and its available documents.";
}
export default App;
