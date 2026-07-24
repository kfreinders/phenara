import { useEffect, useState } from "react";
import { Link, Navigate, useNavigate, useSearchParams } from "react-router-dom";
import { acquireCameraPreview, api, getCameraPreview } from "../api";
import { ErrorNotice, Loading, WorkflowSteps } from "../components";

export function CameraPage() {
  const [params] = useSearchParams();
  if (params.get("workflow") !== "schedule") {
    return <Navigate to="/schedule" replace />;
  }
  return <ExperimentCameraAlignment />;
}

function ExperimentCameraAlignment() {
  const navigate = useNavigate();
  const [draft, setDraft] = useState(null);
  const [previewUrl, setPreviewUrl] = useState(null);
  const [resolution, setResolution] = useState("—");
  const [error, setError] = useState(null);
  const [capturing, setCapturing] = useState(false);
  const [saving, setSaving] = useState(false);

  const showPreview = blob => {
    setPreviewUrl(current => {
      if (current) URL.revokeObjectURL(current);
      return URL.createObjectURL(blob);
    });
  };

  useEffect(() => {
    let mounted = true;
    api("/api/schedule/draft")
      .then(async payload => {
        if (!mounted) return;
        setDraft(payload);
        if (payload.camera_preview_ready) {
          try {
            const blob = await getCameraPreview();
            if (mounted) showPreview(blob);
          } catch {}
        }
      })
      .catch(() => navigate("/schedule", { replace: true }));
    return () => { mounted = false; };
  }, [navigate]);

  useEffect(() => () => {
    if (previewUrl) URL.revokeObjectURL(previewUrl);
  }, [previewUrl]);

  const capture = async () => {
    setCapturing(true);
    setError(null);
    try {
      showPreview(await acquireCameraPreview());
      setDraft(current => ({
        ...current,
        camera_aligned: false,
        camera_preview_ready: true,
      }));
    } catch (reason) {
      setError(reason);
    } finally {
      setCapturing(false);
    }
  };

  const confirm = async () => {
    setSaving(true);
    setError(null);
    try {
      setDraft(await api("/api/schedule/draft/camera", { method: "POST" }));
    } catch (reason) {
      setError(reason);
    } finally {
      setSaving(false);
    }
  };

  if (!draft) return <Loading label="Loading camera alignment" />;
  const aligned = draft.camera_aligned;
  const analysisEnabled = draft.analysis_requested;
  const next = analysisEnabled ? "/analysis?workflow=schedule" : "/schedule/review";

  return <section className="camera-page">
    <WorkflowSteps current={2} analysisEnabled={analysisEnabled} />
    <header className="camera-heading"><div><h2>Align the camera</h2><p>Acquire a still from the Phenopi camera and verify the complete tray is framed consistently.</p></div><Link className="button-link secondary" to="/schedule/edit"><span aria-hidden="true">←</span> Back to configure</Link></header>
    <ErrorNotice error={error} />
    <div className="camera-layout">
      <section className="camera-preview-card card">
        <div className="camera-stage">{previewUrl && <img src={previewUrl} alt="Current Phenopi camera alignment preview" onLoad={event => setResolution(`${event.currentTarget.naturalWidth} × ${event.currentTarget.naturalHeight}`)} />}{!previewUrl && <div className="camera-placeholder"><span className="camera-placeholder-icon" aria-hidden="true"><svg viewBox="0 0 24 24"><path d="M8.5 6 10 4h4l1.5 2H19a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h3.5Z"/><circle cx="12" cy="12.5" r="3.5"/></svg></span><h3>No preview acquired</h3><p>Acquire a still to inspect the actual capture framing.</p></div>}</div>
        <div className="camera-controls"><button type="button" onClick={capture} disabled={capturing}>{capturing ? "Acquiring preview…" : previewUrl ? "Acquire another preview" : "Acquire camera preview"}</button></div>
      </section>
      <aside className="camera-info-card card"><h3>Alignment check</h3><dl className="camera-status-list"><div><dt>Status</dt><dd>{capturing ? "Capturing…" : aligned ? "Confirmed" : previewUrl ? "Ready to confirm" : "Waiting for preview"}</dd></div><div><dt>Resolution</dt><dd>{resolution}</dd></div></dl><div className={`camera-note${aligned ? " camera-note--confirmed" : ""}`}><strong>{aligned ? "Alignment confirmed" : "Before continuing"}</strong><p>{aligned ? "This experiment has completed its camera check." : "Verify that the tray is level, fully visible and in the intended orientation."}</p></div></aside>
    </div>
    <footer className="camera-workflow-footer"><div><strong>{aligned ? "Camera alignment complete" : "Confirm the experiment framing"}</strong><p>{aligned ? "The confirmed still will also seed canopy calibration when requested." : "Inspect the acquired still before confirming."}</p></div><div className="camera-controls">{!aligned && <button type="button" onClick={confirm} disabled={!previewUrl || saving || capturing}>{saving ? "Saving…" : "Confirm alignment"}</button>}{aligned && <Link className="camera-continue-link" to={next}>Continue {analysisEnabled ? "to calibration" : "to review"} <span aria-hidden="true">→</span></Link>}</div></footer>
  </section>;
}
