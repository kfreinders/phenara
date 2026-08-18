import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../api";
import { ErrorNotice, Loading } from "../components";
import { formatBytes, formatDateTime } from "../format";

const stateLabels = {
  completed: "Completed", cancelled: "Cancelled", failed: "Failed",
  superseded: "Superseded", active: "Active",
};

function OutcomeGraphic({ summary, label }) {
  if (!summary) return <div className="record-empty">No {label.toLowerCase()} summary recorded</div>;
  const total = Number(summary.total ?? 0);
  const values = [
    ["succeeded", Number(summary.succeeded ?? summary.completed ?? 0), "Succeeded"],
    ["failed", Number(summary.failed ?? 0), "Failed"],
    ["missed", Number(summary.missed ?? 0), "Missed"],
  ];
  const reported = values.reduce((sum, [, value]) => sum + value, 0);
  const unresolved = Math.max(0, total - reported);
  return <div className="record-outcome">
    <div className="record-outcome-heading"><div><span>{label}</span><strong>{values[0][1]} / {total || "—"}</strong></div><small>successful</small></div>
    <div className="record-outcome-bar" role="img" aria-label={`${label}: ${values[0][1]} succeeded, ${values[1][1]} failed, ${values[2][1]} missed out of ${total}`}>
      {values.map(([key, value]) => value > 0 && <span className={`record-outcome-segment record-outcome-segment--${key}`} style={{ width: `${total ? value / total * 100 : 0}%` }} key={key} />)}
      {unresolved > 0 && <span className="record-outcome-segment record-outcome-segment--unresolved" style={{ width: `${unresolved / total * 100}%` }} />}
    </div>
    <div className="record-outcome-legend">{values.map(([key, value, text]) => <span key={key}><i className={`record-dot record-dot--${key}`} />{text} <strong>{value}</strong></span>)}{unresolved > 0 && <span><i className="record-dot record-dot--unresolved" />Unreported <strong>{unresolved}</strong></span>}</div>
  </div>;
}

function ScheduleGraphic({ schedule }) {
  if (!schedule) return <div className="record-empty">Schedule metadata unavailable</div>;
  const customTimes = schedule.daily_times ? Object.values(schedule.daily_times).flat() : [];
  const times = [...new Set(customTimes.length ? customTimes : (schedule.times ?? []))].sort();
  const pointCount = schedule.daily_times
    ? Object.values(schedule.daily_times).reduce((sum, values) => sum + values.length, 0)
    : times.length * Number(schedule.num_days ?? 0);
  const expected = pointCount * Number(schedule.replicates ?? 1);
  return <div className="record-schedule">
    <div className="record-metrics">
      <div><strong>{schedule.num_days ?? "—"}</strong><span>days</span></div>
      <div><strong>{expected || "—"}</strong><span>planned captures</span></div>
      <div><strong>{schedule.replicates ?? 1}</strong><span>replicates</span></div>
      <div><strong>{schedule.analysis ? "Yes" : "No"}</strong><span>image analysis</span></div>
    </div>
    {times.length > 0 && <div className="record-time-rail"><div className="record-time-line" />{times.map(time => {
      const [hours, minutes] = time.split(":").map(Number);
      const left = Math.max(0, Math.min(100, ((hours * 60 + minutes) / 1440) * 100));
      return <span className="record-time-point" style={{ left: `${left}%` }} key={time}><i /><small>{time}</small></span>;
    })}</div>}
    <p>{schedule.daily_times ? "Custom daily timing" : `${times.length} time point${times.length === 1 ? "" : "s"} per day`}{schedule.replicates > 1 ? ` · ${schedule.replicate_interval_seconds}s between replicates` : ""}</p>
  </div>;
}

function MetadataItem({ label, children, mono = false }) {
  return <div className="record-metadata-item"><dt>{label}</dt><dd className={mono ? "record-mono" : undefined}>{children ?? "—"}</dd></div>;
}

async function copyText(value) {
  if (navigator.clipboard?.writeText) return navigator.clipboard.writeText(value);
  const input = document.createElement("textarea");
  input.value = value; input.style.position = "fixed"; input.style.opacity = "0";
  document.body.appendChild(input); input.select();
  const copied = document.execCommand("copy");
  input.remove();
  if (!copied) throw new Error("Copy is unavailable");
}

export function ExperimentDownloadPage() {
  const { runId } = useParams();
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [downloadStarted, setDownloadStarted] = useState(false);
  const [saved, setSaved] = useState(false);
  const [confirmation, setConfirmation] = useState("");
  const [deleting, setDeleting] = useState(false);
  const [deleted, setDeleted] = useState(false);
  const [scheduleCopyStatus, setScheduleCopyStatus] = useState("idle");

  useEffect(() => {
    let active = true; let timer;
    const load = async () => {
      try {
        const result = await api(`/api/experiments/${runId}`);
        if (!active) return;
        setData(result); setError(null);
        if (!result.archive_ready && result.data_present) {
          timer = window.setTimeout(load, 3000);
        }
      } catch (reason) {
        if (active) setError(reason);
      }
    };
    load();
    return () => { active = false; window.clearTimeout(timer); };
  }, [runId]);

  const removeData = async () => {
    setDeleting(true); setError(null);
    try {
      await api(`/api/experiments/${runId}`, {
        method: "DELETE",
        body: JSON.stringify({
          schedule_hash: data.schedule_hash,
          experiment_name: confirmation,
          archive_saved_confirmed: saved,
        }),
      });
      setDeleted(true);
    } catch (reason) {
      setError(reason); setDeleting(false);
    }
  };

  if (!data && !error) return <Loading label="Preparing experiment download" />;
  if (!data) return <ErrorNotice error={error} />;
  const nameMatches = confirmation === data.run.name;
  const metadataOnly = !data.data_present;
  const schedule = data.schedule;
  const scheduleJson = schedule ? `${JSON.stringify(schedule, null, 2)}\n` : "";
  const scheduleFilename = `${data.run.name.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "") || "experiment"}-schedule.json`;
  return <section className="download-page">
    <div className="react-page-heading record-heading"><div><span className="eyebrow">Experiment record</span><h2>{data.run.name}</h2><p>Review the experiment protocol, outcomes, and reproducibility metadata.</p></div><span className={`lifecycle-badge lifecycle-badge--${data.state}`}>{stateLabels[data.state] ?? data.state}</span></div>
    {error && <ErrorNotice error={error} />}
    <section className="card download-summary">
      <div><span>Experiment period</span><strong>{data.start_date.replaceAll("-", "/")} → {data.end_date.replaceAll("-", "/")}</strong><small>{schedule?.num_days ? `${schedule.num_days} day${schedule.num_days === 1 ? "" : "s"}` : "Recorded experiment period"}</small></div>
      <div><span>Data archive</span><strong>{data.archive_ready ? formatBytes(data.archive_size_bytes) : data.data_present ? "Preparing…" : "Exported and removed"}</strong><small>{metadataOnly ? `${data.archive_name ?? "ZIP archive"}${data.archive_size_bytes != null ? ` · ${formatBytes(data.archive_size_bytes)}` : ""}` : "ZIP with the manifest, capture log, images, and generated files."}</small></div>
      {data.run.notes && <div className="record-notes"><span>Experiment notes</span><p>{data.run.notes}</p></div>}
    </section>
    <section className="record-grid">
      <section className="card record-panel"><header><span className="eyebrow">Outcomes</span><h3>Capture results</h3></header><OutcomeGraphic summary={data.capture_summary} label="Captures" />{data.analysis_summary && <OutcomeGraphic summary={data.analysis_summary} label="Analyses" />}</section>
      <section className="card record-panel"><header><span className="eyebrow">Protocol</span><h3>Protocol summary</h3></header><ScheduleGraphic schedule={schedule} /></section>
    </section>
    <section className="card record-panel record-metadata"><header><h3>Metadata</h3></header>
      <dl>
        <MetadataItem label="Archive name">{data.archive_name}</MetadataItem><MetadataItem label="Archive SHA-256" mono>{data.archive_sha256}</MetadataItem><MetadataItem label="Created">{formatDateTime(data.created_at ?? data.run.created_at)}</MetadataItem><MetadataItem label="Deleted locally">{formatDateTime(data.deleted_at)}</MetadataItem><MetadataItem label="Exported">{formatDateTime(data.exported_at)}</MetadataItem><MetadataItem label="Finished">{formatDateTime(data.ended_at)}</MetadataItem><MetadataItem label="Researcher">{data.run.researcher}</MetadataItem><MetadataItem label="Run ID" mono>{data.run.id}</MetadataItem><MetadataItem label="Schedule SHA-256" mono>{data.schedule_hash}</MetadataItem>
      </dl>
    </section>
    {schedule && <details className="card record-schedule-source"><summary><span><strong>Full experiment configuration</strong><small>Capture timing, replicates, analysis settings, and ROI calibration</small></span><span aria-hidden="true">⌄</span></summary><div className="record-schedule-source-body"><div className="record-source-actions"><button className="secondary" type="button" onClick={async () => { try { await copyText(scheduleJson); setScheduleCopyStatus("copied"); } catch { setScheduleCopyStatus("failed"); } window.setTimeout(() => setScheduleCopyStatus("idle"), 1800); }}>{scheduleCopyStatus === "copied" ? "Copied" : scheduleCopyStatus === "failed" ? "Copy failed" : "Copy schedule JSON"}</button><a className="button-link secondary" href={`data:application/json;charset=utf-8,${encodeURIComponent(scheduleJson)}`} download={scheduleFilename}>Download schedule JSON</a></div><pre>{scheduleJson}</pre></div></details>}
    {!deleted && data.data_present && <section className="card download-action">
      <div className={`download-icon${data.archive_ready ? " download-icon--ready" : ""}`} aria-hidden="true">↓</div>
      <div><h3>{data.archive_ready ? "Your archive is ready" : "Creating the archive"}</h3><p>{data.archive_ready ? "Keep this page open while your browser saves the ZIP file." : "Large experiments can take a little while to package. This page updates automatically."}</p></div>
      {data.archive_ready && <a className="primary-link" href={`/api/experiments/${runId}/download`} onClick={() => setDownloadStarted(true)}>Download ZIP</a>}
    </section>}
    {downloadStarted && !deleted && <section className="card data-cleanup">
      <div><span className="eyebrow">Free storage</span><h3>Has the download finished?</h3><p>Open or safely store the ZIP on your computer first. You can then remove the Pi’s copy to make room for the next experiment.</p></div>
      <label className="cleanup-check"><input type="checkbox" checked={saved} onChange={event => setSaved(event.target.checked)} /> I have saved the downloaded archive somewhere safe.</label>
      {saved && <label className="cleanup-name">Type <strong>{data.run.name}</strong> to confirm deletion<input value={confirmation} onChange={event => setConfirmation(event.target.value)} autoComplete="off" /></label>}
      <button className="danger-button" disabled={!saved || !nameMatches || deleting} onClick={removeData}>{deleting ? "Deleting experiment data…" : "Delete data from Phenopi"}</button>
      <small>This permanently deletes both the dataset and its ZIP archive from the Raspberry Pi.</small>
    </section>}
    {deleted && <section className="card cleanup-complete"><span aria-hidden="true">✓</span><div><h3>Local experiment data deleted</h3><p>The copy on Phenopi has been removed. Keep your downloaded archive safe.</p></div><Link className="primary-link" to="/schedule">Create next schedule</Link></section>}
  </section>;
}
