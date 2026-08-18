import { useEffect, useRef, useState } from "react";
import { Navigate, NavLink, Outlet, Route, Routes } from "react-router-dom";
import { useSchedulerHealth } from "./hooks";
import { getDevelopmentStatus, setDevelopmentMode } from "./api";
import { SchedulerPage } from "./pages/SchedulerPage";
import { ScheduleBuilderPage } from "./pages/ScheduleBuilderPage";
import { ScheduleReviewPage } from "./pages/ScheduleReviewPage";
import { ActivationPage } from "./pages/ActivationPage";
import { CameraPage } from "./pages/CameraPage";
import { ExperimentDownloadPage } from "./pages/ExperimentDownloadPage";
import { ExperimentHistoryPage } from "./pages/ExperimentHistoryPage";
import { AnalysisSetupPage } from "./pages/AnalysisSetupPage";
import { CaptureModePage } from "./pages/CaptureModePage";
import { DirectoryAnalysisPage } from "./pages/DirectoryAnalysisPage";

const healthLabels = {
  healthy: "Healthy", waiting_for_schedule: "Waiting for schedule",
  invalid_schedule: "Invalid schedule", stale: "Scheduler not responding",
  unavailable: "Unavailable",
};

function Shell() {
  const [contactOpen, setContactOpen] = useState(false);
  const [development, setDevelopment] = useState(null);
  const [developmentOpen, setDevelopmentOpen] = useState(false);
  const [developmentError, setDevelopmentError] = useState(null);
  const [developmentSaving, setDevelopmentSaving] = useState(false);
  const contactTrigger = useRef(null);
  const contactClose = useRef(null);
  const { data, error } = useSchedulerHealth();
  const health = data ?? { status: error ? "unavailable" : "loading", age_seconds: null, message: error?.message ?? "Loading scheduler health" };
  const label = healthLabels[health.status] ?? "Loading";

  useEffect(() => {
    let active = true;
    const refresh = () => getDevelopmentStatus()
      .then(value => { if (active) setDevelopment(value); })
      .catch(() => { if (active) setDevelopment(null); });
    refresh();
    const timer = window.setInterval(refresh, 5000);
    return () => { active = false; window.clearInterval(timer); };
  }, []);

  useEffect(() => {
    if (!contactOpen && !developmentOpen) return undefined;
    const previousOverflow = document.body.style.overflow;
    const handleKeyDown = (event) => {
      if (event.key === "Escape") {
        setContactOpen(false);
        setDevelopmentOpen(false);
      }
    };
    document.body.style.overflow = "hidden";
    document.addEventListener("keydown", handleKeyDown);
    if (contactOpen) contactClose.current?.focus();
    return () => {
      document.body.style.overflow = previousOverflow;
      document.removeEventListener("keydown", handleKeyDown);
      if (contactOpen) contactTrigger.current?.focus();
    };
  }, [contactOpen, developmentOpen]);

  const updateDevelopment = async () => {
    setDevelopmentSaving(true);
    setDevelopmentError(null);
    try {
      setDevelopment(await setDevelopmentMode(!development.enabled));
      setDevelopmentOpen(false);
    } catch (reason) {
      setDevelopmentError(reason);
    } finally {
      setDevelopmentSaving(false);
    }
  };

  return <>
    <header className="topbar"><div className="topbar-inner"><div><h1 className="phenopi-identity"><span className="phenopi-identity-controls"><a className="phenopi-home-link" href="/scheduler"><span className="phenopi-wordmark">Phenopi</span></a><span ref={contactTrigger} className="phenopi-about-trigger" role="button" tabIndex="0" aria-label="About Phenopi and its developer" aria-haspopup="dialog" aria-expanded={contactOpen} onClick={() => setContactOpen(true)} onKeyDown={(event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        setContactOpen(true);
      }
    }}>About</span></span></h1><p>Experiment setup and analysis interface</p></div>
      <div className="topbar-status">{development?.available && <button className={`development-pill${development.enabled ? " development-pill--enabled" : ""}`} type="button" disabled={!development.can_toggle} title={development.blocked_reason ?? (development.enabled ? "Disable development mode" : "Enable development mode")} onClick={() => { setDevelopmentError(null); setDevelopmentOpen(true); }}>{development.enabled ? "Development mode on" : "Enable development mode"}</button>}<a className={`status-pill status-pill--${health.status}`} href="/scheduler" title={health.message} aria-label={`${label}. ${health.message}`}>
        <span className="status-pill-dot" aria-hidden="true" /><strong>{label}</strong><small>{health.age_seconds == null ? "—" : `${Math.round(health.age_seconds)}s`}</small>
      </a></div></div></header>
    <nav className="primary-tabs" aria-label="Primary navigation">
      <NavLink to="/scheduler">Experiments</NavLink>
      <NavLink to="/experiments">History</NavLink>
      <NavLink to="/directory-analysis">Analyze directory</NavLink>
    </nav>
    <main className="layout"><Outlet /></main>
    {contactOpen && <div className="phenopi-modal-backdrop" role="presentation" onMouseDown={(event) => {
      if (event.target === event.currentTarget) setContactOpen(false);
    }}>
      <section className="phenopi-modal" role="dialog" aria-modal="true" aria-labelledby="phenopi-modal-title">
        <button ref={contactClose} className="phenopi-modal-close" type="button" aria-label="Close developer information" onClick={() => setContactOpen(false)}>×</button>
        <span className="phenopi-modal-eyebrow">Phenopi</span>
        <h2 id="phenopi-modal-title">Koen Reinders</h2>
        <p className="phenopi-modal-role">Developer and MSc researcher</p>
        <p className="phenopi-modal-summary">Phenopi is my MSc thesis research project for developing a modular, reproducible plant phenotyping platform. It schedules repeat image capture, supports camera alignment and calibrated canopy analysis, and tracks and exports experiment results.</p>
        <div className="phenopi-modal-links">
          <a href="mailto:koenf.reinders@gmail.com"><span>Email</span><strong>koenf.reinders@gmail.com</strong></a>
          <a href="https://github.com/kfreinders/phenopi" target="_blank" rel="noreferrer"><span>GitHub</span><strong>kfreinders/phenopi</strong></a>
        </div>
      </section>
    </div>}
    {developmentOpen && <div className="phenopi-modal-backdrop" role="presentation" onMouseDown={(event) => {
      if (event.target === event.currentTarget) setDevelopmentOpen(false);
    }}>
      <section className="phenopi-modal development-modal" role="dialog" aria-modal="true" aria-labelledby="development-modal-title">
        <button className="phenopi-modal-close" type="button" aria-label="Close development mode confirmation" onClick={() => setDevelopmentOpen(false)}>×</button>
        <span className="phenopi-modal-eyebrow">Capture source</span>
        <h2 id="development-modal-title">{development?.enabled ? "Disable development mode?" : "Enable development mode?"}</h2>
        <p>{development?.enabled ? "New experiments will use the Raspberry Pi camera again." : "Camera previews and scheduled captures will use sample images. Exported runs will be marked as development data."}</p>
        {developmentError && <div className="alert error" role="alert">{developmentError.message}</div>}
        {!development?.enabled && development?.sample_error && <div className="alert error" role="alert">{development.sample_error}</div>}
        <div className="actions"><button className="secondary" type="button" onClick={() => setDevelopmentOpen(false)}>Cancel</button><button type="button" disabled={developmentSaving || (!development?.enabled && Boolean(development?.sample_error))} onClick={updateDevelopment}>{developmentSaving ? "Updating…" : development?.enabled ? "Use real camera" : "Use sample images"}</button></div>
      </section>
    </div>}
  </>;
}

export default function App() {
  return <Routes><Route element={<Shell />}>
    <Route index element={<Navigate to="/scheduler" replace />} />
    <Route path="scheduler" element={<SchedulerPage />} />
    <Route path="schedule" element={<CaptureModePage />} />
    <Route path="schedule/edit" element={<CaptureModePage edit />} />
    <Route path="schedule/build" element={<ScheduleBuilderPage />} />
    <Route path="schedule/build/edit" element={<ScheduleBuilderPage edit />} />
    <Route path="schedule/review" element={<ScheduleReviewPage />} />
    <Route path="schedule/activation" element={<ActivationPage />} />
    <Route path="camera" element={<CameraPage />} />
    <Route path="analysis" element={<AnalysisSetupPage />} />
    <Route path="directory-analysis" element={<DirectoryAnalysisPage />} />
    <Route path="experiments/:runId" element={<ExperimentDownloadPage />} />
    <Route path="experiments" element={<ExperimentHistoryPage />} />
    <Route path="*" element={<Navigate to="/scheduler" replace />} />
  </Route></Routes>;
}
