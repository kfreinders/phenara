import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../api";
import { ErrorNotice, Loading } from "../components";
import { formatBytes } from "../format";

export function ExperimentDownloadPage() {
  const { runId } = useParams();
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [downloadStarted, setDownloadStarted] = useState(false);
  const [saved, setSaved] = useState(false);
  const [confirmation, setConfirmation] = useState("");
  const [deleting, setDeleting] = useState(false);
  const [deleted, setDeleted] = useState(false);

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
  return <section className="download-page">
    <div className="react-page-heading"><span className="eyebrow">Finished experiment</span><h2>{metadataOnly ? "Experiment record" : "Download experiment data"}</h2><p>{metadataOnly ? "The raw files were exported and removed; reproducible experiment metadata remains in Phenopi." : "Save the complete dataset to the attached computer before clearing it from Phenopi."}</p></div>
    {error && <ErrorNotice error={error} />}
    <section className="card download-summary">
      <div><span>Experiment</span><strong>{data.run.name}</strong><small>{data.start_date.replaceAll("-", "/")} → {data.end_date.replaceAll("-", "/")}{data.run.researcher ? ` · ${data.run.researcher}` : ""}</small></div>
      <div><span>Archive</span><strong>{data.archive_ready ? formatBytes(data.archive_size_bytes) : data.data_present ? "Preparing…" : "Data removed"}</strong><small>ZIP archive containing the run manifest, capture log, images, and generated files.</small></div>
    </section>
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
    {!downloadStarted && !deleted && <Link className="button-link secondary" to="/scheduler">Back to scheduler overview</Link>}
    {metadataOnly && <Link className="button-link secondary" to="/experiments">Back to experiment history</Link>}
  </section>;
}
