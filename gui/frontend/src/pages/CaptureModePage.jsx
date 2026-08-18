import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api";
import { ErrorNotice, Loading, WorkflowSteps } from "../components";

export function CaptureModePage({ edit = false }) {
  const navigate = useNavigate();
  const [selected, setSelected] = useState(null);
  const [profileSaved, setProfileSaved] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    api(`/api/schedule/configure?edit=${edit}`)
      .then(data => {
        if (!edit && data.draft_state === "ready") {
          navigate("/schedule/review", { replace: true });
          return;
        }
        if (edit) setSelected(Boolean(data.form.analysis_enabled));
        setProfileSaved(data.analysis_profile_saved);
        setLoaded(true);
      })
      .catch(setError);
  }, [edit, navigate]);

  if (!loaded && !error) return <Loading label="Loading capture options" />;
  const continueToSchedule = () => navigate(`/schedule/build${edit ? "/edit" : ""}?analysis=${selected ? "1" : "0"}`);

  return <><WorkflowSteps current={1} analysisEnabled={selected === true} /><section className="capture-mode-page card">
    <div className="card-header"><div><h2>Choose capture mode</h2><p>Step 1: choose what Phenara should do with each captured image.</p></div></div>
    <ErrorNotice error={error} />
    {loaded && <><div className="analysis-choice-options capture-mode-options">
      <button type="button" className={selected === false ? "is-selected" : ""} aria-pressed={selected === false} onClick={() => setSelected(false)}><CameraModeIcon /><span>Images only</span><small>Capture and store photographs without running the canopy pipeline.</small></button>
      <button type="button" className={selected === true ? "is-selected" : ""} aria-pressed={selected === true} onClick={() => setSelected(true)}><AnalyzeModeIcon /><span>Analyze canopy</span><small>Calibrate the pipeline, then analyze images automatically between captures.</small>{profileSaved && <i>Saved calibration available</i>}</button>
    </div>
    <div className="capture-mode-footer"><p>{selected === true ? "This workflow includes canopy calibration after camera alignment." : selected === false ? "This workflow stores the original photographs without canopy measurements." : "Select a capture mode to continue."}</p><button type="button" disabled={selected === null} onClick={continueToSchedule}>Continue to schedule</button></div></>}
  </section></>;
}

function CameraModeIcon() {
  return <svg className="analysis-choice-icon" viewBox="0 0 96 72" aria-hidden="true">
    <path className="icon-surface" d="M15 23h16l5-8h24l5 8h16a8 8 0 0 1 8 8v27a8 8 0 0 1-8 8H15a8 8 0 0 1-8-8V31a8 8 0 0 1 8-8Z" />
    <circle className="icon-detail" cx="48" cy="44" r="15" />
    <circle className="icon-lens" cx="48" cy="44" r="8" />
    <path className="icon-detail" d="M72 31h8" />
  </svg>;
}

function AnalyzeModeIcon() {
  const leaves = [-75, -15, 45, 105, 165, 225];
  return <svg className="analysis-choice-icon analysis-choice-icon--canopy" viewBox="0 0 96 72" aria-hidden="true">
    <g className="icon-rosette">
      {leaves.map(angle => <path d="M38 35C30 30 30 18 38 8c8 10 8 22 0 27Z" transform={`rotate(${angle} 38 35)`} key={angle} />)}
      <circle cx="38" cy="35" r="5" />
    </g>
    <circle className="icon-magnifier" cx="64" cy="43" r="16" />
    <path className="icon-magnifier" d="m76 55 12 12" />
  </svg>;
}
