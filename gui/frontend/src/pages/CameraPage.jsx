import { useEffect, useRef, useState } from "react";
import { Link, Navigate, useNavigate, useSearchParams } from "react-router-dom";
import { api } from "../api";
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
  const video = useRef(null);
  const stream = useRef(null);
  const [draft, setDraft] = useState(null);
  const [active, setActive] = useState(false);
  const [status, setStatus] = useState("Inactive");
  const [resolution, setResolution] = useState("—");
  const [error, setError] = useState(null);
  const [saving, setSaving] = useState(false);

  const stop = () => {
    stream.current?.getTracks().forEach(track => track.stop());
    stream.current = null;
    if (video.current) video.current.srcObject = null;
    setActive(false);
    setStatus("Inactive");
    setResolution("—");
  };

  useEffect(() => {
    api("/api/schedule/draft")
      .then(setDraft)
      .catch(() => navigate("/schedule", { replace: true }));
    return stop;
  }, [navigate]);

  const start = async () => {
    setError(null);
    setStatus("Requesting camera access…");
    try {
      const media = await navigator.mediaDevices.getUserMedia({
        video: { width: { ideal: 1280 }, height: { ideal: 720 } },
        audio: false,
      });
      stream.current = media;
      video.current.srcObject = media;
      video.current.onloadedmetadata = () => {
        setResolution(`${video.current.videoWidth} × ${video.current.videoHeight}`);
        setActive(true);
        setStatus("Live");
      };
    } catch (reason) {
      setStatus("Camera access failed");
      setError(reason.name === "NotAllowedError"
        ? "Camera access was denied by the browser."
        : reason.name === "NotFoundError"
          ? "No camera was found."
          : `Could not start camera preview: ${reason.message}`);
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
    <WorkflowSteps current={3} analysisEnabled={analysisEnabled} />
    <header className="camera-heading"><div><h2>Align the camera</h2><p>Acquire a still from the Phenopi camera and verify the complete tray is framed consistently.</p></div><Link className="button-link secondary" to="/schedule/build/edit"><span aria-hidden="true">←</span> Back to schedule</Link></header>
    <ErrorNotice error={error} />
    <div className="camera-layout">
      <section className="camera-preview-card card">
        <div className="camera-stage"><video ref={video} autoPlay muted playsInline hidden={!active} />{!active && <div className="camera-placeholder"><span className="camera-placeholder-icon" aria-hidden="true"><svg viewBox="0 0 24 24"><path d="M8.5 6 10 4h4l1.5 2H19a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h3.5Z"/><circle cx="12" cy="12.5" r="3.5"/></svg></span><h3>Camera inactive</h3><p>Start the preview to inspect alignment.</p></div>}</div>
        <div className="camera-controls"><button type="button" onClick={start} disabled={active}>Start camera</button><button type="button" className="secondary" onClick={stop} disabled={!active}>Stop camera</button></div>
      </section>
      <aside className="camera-info-card card"><h3>Alignment check</h3><dl className="camera-status-list"><div><dt>Status</dt><dd>{status}</dd></div><div><dt>Resolution</dt><dd>{resolution}</dd></div></dl><div className={`camera-note${aligned ? " camera-note--confirmed" : ""}`}><strong>{aligned ? "Alignment confirmed" : "Before continuing"}</strong><p>{aligned ? "This experiment has completed its camera check." : "Verify that the tray is level, fully visible and in the intended orientation."}</p></div></aside>
    </div>
    <footer className="camera-workflow-footer"><div><strong>{aligned ? "Camera alignment complete" : "Confirm the experiment framing"}</strong><p>{aligned ? "Continue to the next experiment setup step." : "Confirmation is enabled after starting the camera preview."}</p></div><div className="camera-controls">{!aligned && <button type="button" onClick={confirm} disabled={!active || saving}>{saving ? "Saving…" : "Confirm alignment"}</button>}{aligned && <Link className="camera-continue-link" to={next}>Continue {analysisEnabled ? "to calibration" : "to review"} <span aria-hidden="true">→</span></Link>}</div></footer>
  </section>;
}
