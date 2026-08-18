import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { getExperiments } from "../api";
import { ErrorNotice, Loading } from "../components";
import { formatBytes } from "../format";

const labels = {
  active: "Active", completed: "Completed", cancelled: "Cancelled",
  failed: "Failed", superseded: "Superseded",
};

export function ExperimentHistoryPage() {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [query, setQuery] = useState("");
  const [state, setState] = useState("all");
  useEffect(() => { getExperiments().then(setData).catch(setError); }, []);
  const experiments = useMemo(() => (data?.experiments ?? []).filter(run => {
    const matchesQuery = `${run.name} ${run.researcher ?? ""}`.toLowerCase().includes(query.trim().toLowerCase());
    return matchesQuery && (state === "all" || run.state === state);
  }), [data, query, state]);
  if (!data && !error) return <Loading label="Loading experiment history" />;
  if (!data) return <ErrorNotice error={error} />;
  return <section className="history-page">
    <header className="react-page-heading"><h2>Experiment history</h2><p>Phenara retains reproducible metadata for the latest {data.terminal_limit} experiments without keeping their raw images on the Pi.</p></header>
    {data.raw_data_blocker_ids.length > 0 && <section className="card history-cleanup-alert" role="alert"><div><h3>Raw experiment data still occupies the Pi</h3><p>Download and remove it before activating another experiment.</p></div><Link className="primary-link" to={`/experiments/${data.raw_data_blocker_ids[0]}`}>Review and clean up</Link></section>}
    {data.warnings.length > 0 && <div className="schedule-warning">Some experiment folders could not be indexed: {data.warnings.join("; ")}</div>}
    <section className="card history-controls"><label>Search<input value={query} onChange={event => setQuery(event.target.value)} placeholder="Experiment or researcher" /></label><label>State<select value={state} onChange={event => setState(event.target.value)}><option value="all">All states</option>{Object.entries(labels).map(([value, label]) => <option value={value} key={value}>{label}</option>)}</select></label><div><strong>{data.retained_terminal_count} / {data.terminal_limit}</strong><span>metadata records retained</span></div></section>
    <div className="history-list">{experiments.map(run => <Link className="history-row-link" to={`/experiments/${run.run_id}`} key={run.run_id}><article className="card history-row"><div className="history-identity"><span className={`lifecycle-badge lifecycle-badge--${run.state}`}>{labels[run.state] ?? run.state}</span><h3>{run.name}</h3><p>{run.start_date} → {run.end_date}{run.researcher ? ` · ${run.researcher}` : ""}</p><div className="history-state"><strong>{run.data_present ? "Cleanup required" : "Metadata only"}</strong><span>{run.data_present ? "Raw files remain locally" : "Raw files exported and removed"}</span></div></div><div className="history-outcomes"><strong>{run.capture_summary?.succeeded ?? "—"}</strong><span>successful captures</span>{run.archive_size_bytes != null && <small>Exported ZIP: {formatBytes(run.archive_size_bytes)}</small>}</div><span className="history-card-arrow" aria-hidden="true">→</span></article></Link>)}</div>
    {experiments.length === 0 && <section className="card schedule-empty"><h3>No matching experiments</h3><p>Try another search or state filter.</p></section>}
  </section>;
}
