import { useEffect, useRef, useState } from "react";
import { Link, Navigate, useNavigate, useSearchParams } from "react-router-dom";
import { ErrorNotice, HelpTip, Loading, WorkflowSteps } from "../components";
import { attachDraftAnalysis, detectAnalysisRoi, getAnalysisConfig, getCameraPreview, previewAnalysis, saveAnalysisProfile } from "../api";

const stageLabels = {
  channel: ["LAB channel", "Values used for thresholding"],
  mask: ["Plant mask", "White pixels are selected"],
  overlay: ["Segmentation overlay", "Selected plant material"],
};

function blobToDataUrl(blob) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result);
    reader.onerror = () => reject(new Error("The confirmed camera preview could not be loaded."));
    reader.readAsDataURL(blob);
  });
}

export function AnalysisSetupPage() {
  const [params] = useSearchParams();
  if (params.get("workflow") !== "schedule") {
    return <Navigate to="/schedule" replace />;
  }
  return <ScheduledAnalysisSetupPage />;
}

function ScheduledAnalysisSetupPage() {
  return <CalibrationWorkspace />;
}

export function CalibrationWorkspace({
  initialConfig = null,
  initialImageData = null,
  initialFileName = "",
  onComplete = null,
  onInvalidated = null,
}) {
  const navigate = useNavigate();
  const scheduleWorkflow = !onComplete;
  const [config, setConfig] = useState(initialConfig);
  const [defaultConfig, setDefaultConfig] = useState(
    initialConfig ? { ...initialConfig } : null,
  );
  const [imageData, setImageData] = useState(initialImageData);
  const [fileName, setFileName] = useState(initialFileName);
  const [stages, setStages] = useState(null);
  const [roi, setRoi] = useState(null);
  const [analysisCrop, setAnalysisCrop] = useState({ x: 0, y: 0, width: 1, height: 1 });
  const [maskExclusions, setMaskExclusions] = useState([]);
  const [brushRadius, setBrushRadius] = useState(0.015);
  const [detectingRoi, setDetectingRoi] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [activeControl, setActiveControl] = useState(null);
  const requestNumber = useRef(0);
  const roiResult = useRef(null);
  const previewArea = useRef(null);

  useEffect(() => {
    if (!scheduleWorkflow) {
      setConfig(initialConfig);
      setDefaultConfig(initialConfig ? { ...initialConfig } : null);
      setImageData(initialImageData);
      setFileName(initialFileName);
      setStages(null);
      setRoi(null);
      setSaved(false);
      setAnalysisCrop({ x: 0, y: 0, width: 1, height: 1 });
      setMaskExclusions([]);
      setError(null);
      return;
    }
    getAnalysisConfig()
      .then(payload => {
        if (!payload.workflow_available) {
          navigate("/schedule", { replace: true });
          return;
        }
        if (!payload.camera_aligned) {
          navigate("/camera?workflow=schedule", { replace: true });
          return;
        }
        setConfig(payload.config);
        setDefaultConfig({ ...payload.config });
        setSaved(payload.profile_saved);
        return getCameraPreview().then(blobToDataUrl);
      })
      .then(dataUrl => {
        if (!dataUrl) return;
        setFileName("Confirmed camera preview");
        setImageData(dataUrl);
      })
      .catch(setError);
  }, [
    initialConfig,
    initialFileName,
    initialImageData,
    navigate,
    scheduleWorkflow,
  ]);

  useEffect(() => {
    if (!imageData || !config) return;
    const controller = new AbortController();
    const currentRequest = ++requestNumber.current;
    const timer = window.setTimeout(async () => {
      setLoading(true);
      setError(null);
      try {
        const result = await previewAnalysis(imageData, config, analysisCrop, maskExclusions, controller.signal);
        if (currentRequest === requestNumber.current) setStages(result.stages);
      } catch (reason) {
        if (reason.name !== "AbortError" && currentRequest === requestNumber.current) setError(reason);
      } finally {
        if (currentRequest === requestNumber.current) setLoading(false);
      }
    }, 350);
    return () => { window.clearTimeout(timer); controller.abort(); };
  }, [imageData, config, analysisCrop, maskExclusions]);

  useEffect(() => {
    if (!roi || !roiResult.current) return;
    const frame = window.requestAnimationFrame(() => {
      roiResult.current?.focus({ preventScroll: true });
      const reducedMotion = window.matchMedia?.(
        "(prefers-reduced-motion: reduce)"
      ).matches;
      roiResult.current?.scrollIntoView({
        behavior: reducedMotion ? "auto" : "smooth",
        block: "start",
      });
    });
    return () => window.cancelAnimationFrame(frame);
  }, [roi]);

  useEffect(() => {
    const cards = previewArea.current?.querySelectorAll("[data-control-group]");
    if (!cards?.length) return undefined;
    if (typeof IntersectionObserver === "undefined") {
      setActiveControl(cards[0].dataset.controlGroup);
      return undefined;
    }
    const visibility = new Map();
    const observer = new IntersectionObserver(entries => {
      entries.forEach(entry => visibility.set(entry.target, entry.isIntersecting ? entry.intersectionRatio : 0));
      const visible = [...visibility.entries()].sort((left, right) => right[1] - left[1])[0];
      if (visible?.[1] > 0) setActiveControl(visible[0].dataset.controlGroup);
    }, { rootMargin: "-15% 0px -45% 0px", threshold: [0, .1, .25, .5, .75] });
    cards.forEach(card => { visibility.set(card, 0); observer.observe(card); });
    return () => observer.disconnect();
  }, [stages, roi]);

  const selectImage = event => {
    const file = event.target.files?.[0];
    if (!file) return;
    if (!file.type.startsWith("image/")) {
      setError(new Error("Choose a JPEG or PNG calibration image."));
      return;
    }
    if (file.size > 10_000_000) {
      setError(new Error("The calibration image must be 10 MB or smaller."));
      return;
    }
    const reader = new FileReader();
    reader.onload = () => {
      setFileName(file.name);
      setImageData(reader.result);
      setStages(null);
      setRoi(null);
      setSaved(false);
      setAnalysisCrop({ x: 0, y: 0, width: 1, height: 1 });
      setMaskExclusions([]);
      setError(null);
    };
    reader.onerror = () => setError(new Error("The calibration image could not be read."));
    reader.readAsDataURL(file);
  };

  const update = (key, value) => {
    setRoi(null);
    setSaved(false);
    onInvalidated?.();
    if (key === "rotate_angle") {
      setMaskExclusions([]);
    }
    setConfig(current => ({ ...current, [key]: value }));
  };
  const updateCrop = value => {
    setRoi(null);
    setSaved(false);
    onInvalidated?.();
    setMaskExclusions([]);
    setAnalysisCrop(value);
  };
  const updateMaskExclusions = updater => {
    setRoi(null);
    setSaved(false);
    onInvalidated?.();
    setMaskExclusions(updater);
  };
  const restoreDefaults = () => {
    if (!defaultConfig) return;
    setConfig({ ...defaultConfig });
    setMaskExclusions([]);
    setRoi(null);
    setSaved(false);
    onInvalidated?.();
    setError(null);
  };
  const detectRoi = async () => {
    setDetectingRoi(true);
    setError(null);
    try {
      const result = await detectAnalysisRoi(imageData, config, analysisCrop, maskExclusions);
      setRoi(result);
    } catch (reason) {
      setError(reason);
    } finally {
      setDetectingRoi(false);
    }
  };
  const saveProfile = async () => {
    setSaving(true);
    setError(null);
    try {
      if (scheduleWorkflow) {
        await saveAnalysisProfile(config, roi.definition);
      } else {
        await onComplete({
          config,
          roi: roi.definition,
          analysisCrop,
          maskExclusions,
        });
      }
      setSaved(true);
      if (scheduleWorkflow) {
        await attachDraftAnalysis();
        navigate("/schedule/review");
      }
    } catch (reason) {
      setError(reason);
    } finally {
      setSaving(false);
    }
  };
  const useSavedProfile = async () => {
    setSaving(true);
    setError(null);
    try {
      await attachDraftAnalysis();
      navigate("/schedule/review");
    } catch (reason) {
      setError(reason);
    } finally {
      setSaving(false);
    }
  };
  if (!config) return <Loading label="Loading analysis settings" />;
  const defaultsChanged = Boolean(defaultConfig) && (JSON.stringify(config) !== JSON.stringify(defaultConfig) || maskExclusions.length > 0);

  return <section className="analysis-page">
    {scheduleWorkflow && <WorkflowSteps current={4} analysisEnabled />}
    <header className="react-page-heading analysis-page-heading"><div><h2>{scheduleWorkflow ? "Calibrate canopy analysis" : "Calibrate directory analysis"}</h2><p>Tune plant segmentation using a representative calibration image.</p></div>{scheduleWorkflow && <Link className="button-link secondary" to="/schedule/build/edit"><span aria-hidden="true">←</span> Back to schedule</Link>}</header>
    <ErrorNotice error={error} />
    <section className={`card analysis-workflow-intro${saved ? " analysis-workflow-intro--saved" : ""}`}><div><span aria-hidden="true">{saved ? "✓" : scheduleWorkflow ? "4" : "2"}</span><div><h3>{saved ? (scheduleWorkflow ? "This experiment is calibrated" : "Directory calibration ready") : "Calibration required"}</h3><p>{saved ? (scheduleWorkflow ? "Continue with the calibration already saved for this experiment, or replace it below after changing the camera or tray setup." : "The calibrated settings and ROI grid are ready for directory analysis.") : "Canopy measurements cannot start until segmentation and the ROI grid have been calibrated."}</p></div></div>{scheduleWorkflow && saved && <button type="button" onClick={useSavedProfile} disabled={saving}>{saving ? "Loading…" : "Use this calibration"}</button>}</section>
    <div className="analysis-setup-layout">
      <aside className="card analysis-controls">
        <div className="analysis-controls-actions"><button type="button" className="secondary analysis-restore-defaults" disabled={!defaultsChanged} onClick={restoreDefaults}>Restore defaults</button></div>
        {scheduleWorkflow ? <div className="analysis-image-picker">
          <strong>Calibration image</strong>
          <label className="button-link secondary analysis-file-button">
            {fileName ? "Choose another image" : "Choose image"}
            <input type="file" accept="image/jpeg,image/png" onChange={selectImage} />
          </label>
          {fileName && <small title={fileName}>{fileName}</small>}
        </div> : <div className="analysis-image-picker"><strong>Calibration image</strong><small title={fileName}>{fileName}</small></div>}
        <fieldset className={`analysis-control-group${activeControl === "orientation" ? " is-active" : ""}`} disabled={!imageData}>
          <legend>Image orientation</legend>
          <RangeControl label="Rotation" help="Straighten a tilted tray before cropping and segmentation. Positive and negative values rotate the image in opposite directions." value={config.rotate_angle} min={-10} max={10} step={0.1} suffix="°" onChange={value => update("rotate_angle", value)} />
        </fieldset>
        <fieldset className={`analysis-control-group${activeControl === "channel" ? " is-active" : ""}`} disabled={!imageData}>
          <legend>LAB channel</legend>
          <label className="analysis-control"><span><span className="analysis-setting-label">Channel <HelpTip id="analysis-help-setting-channel" label="channel setting">LAB separates an image into lightness (L), green-to-magenta color (A), and blue-to-yellow color (B). Choose the channel where plants contrast most clearly with the background, then check the result in the Plant mask preview. White pixels are treated as plant; black pixels are treated as background.</HelpTip></span><output>{config.sepchannel.toUpperCase()}</output></span>
            <select value={config.sepchannel} onChange={event => update("sepchannel", event.target.value)}>
              <option value="l">L — lightness</option><option value="a">A — green to magenta</option><option value="b">B — blue to yellow</option>
            </select>
          </label>
        </fieldset>
        <fieldset className={`analysis-control-group${activeControl === "mask" ? " is-active" : ""}`} disabled={!imageData}>
          <legend>Plant mask</legend>
          <RangeControl label="Threshold" help="The plant mask is a black-and-white image used to separate plants from their surroundings. Pixels at or below this 0–255 cutoff become white plant pixels; higher-valued pixels become black background." value={config.threshold} min={0} max={255} onChange={value => update("threshold", value)} />
          <RangeControl label="Remove small regions" help="Remove isolated white areas smaller than this many pixels. Increase it to suppress small specks of noise, but avoid values that erase small leaves." value={config.fill_size} min={0} max={2000} step={10} onChange={value => update("fill_size", value)} />
        </fieldset>
        <fieldset className={`analysis-control-group${activeControl === "roi" ? " is-active" : ""}`} disabled={!imageData}>
          <legend>ROI grid</legend>
          <div className="analysis-grid-size">
            <label><span className="analysis-setting-label">Rows <HelpTip id="analysis-help-setting-rows" label="ROI rows">Enter how many horizontal rows of pots or plants are present inside the selected analysis area.</HelpTip></span><input type="number" min="1" max="30" value={config.roi_rows} onChange={event => update("roi_rows", Number(event.target.value))} /></label>
            <label><span className="analysis-setting-label">Columns <HelpTip id="analysis-help-setting-columns" label="ROI columns">Enter how many vertical columns of pots or plants are present inside the selected analysis area.</HelpTip></span><input type="number" min="1" max="30" value={config.roi_cols} onChange={event => update("roi_cols", Number(event.target.value))} /></label>
          </div>
          <RangeControl label="ROI diameter" help="Scale every automatically detected ROI circle. Increase this when plant material extends beyond the circles; reduce it to avoid overlap with neighbouring plants." value={Math.round(config.roi_diameter_scale * 100)} min={50} max={200} step={5} suffix="%" onChange={value => update("roi_diameter_scale", value / 100)} />
          <div className="analysis-detect-action"><button type="button" className="analysis-detect-button" onClick={detectRoi} disabled={detectingRoi}>{detectingRoi ? "Detecting ROI grid…" : roi ? "Detect ROI grid again" : "Detect ROI grid"}</button><HelpTip id="analysis-help-setting-detect" label="ROI grid detection">Find one reusable measurement region for each expected row-and-column position using the current plant mask.</HelpTip></div>
        </fieldset>
      </aside>
      <section ref={previewArea} className={`analysis-preview-area${loading ? " is-updating" : ""}`} aria-live="polite">
        {!imageData && <div className="card analysis-empty"><span aria-hidden="true">◫</span><h3>Select a calibration image</h3><p>The segmentation stages will appear here as you adjust the controls.</p></div>}
        {imageData && !stages && <Loading label="Generating analysis preview" />}
        {stages && <div className="analysis-stage-grid">
          <article className="card analysis-stage analysis-stage--crop" data-control-group="orientation">
            <header><div><h3>Analysis area</h3><p>Drag across the image to isolate the tray</p></div><button type="button" className="text-button analysis-crop-reset" onClick={() => updateCrop({ x: 0, y: 0, width: 1, height: 1 })}>Reset</button></header>
            <CropSelector image={stages.original} crop={analysisCrop} onChange={updateCrop} />
          </article>
          {Object.entries(stageLabels).map(([key, [title, description]]) => <article className="card analysis-stage" data-control-group={key === "channel" ? "channel" : "mask"} key={key}>
            <header><div><h3>{title}</h3><p>{description}</p></div>{loading && key === "overlay" && <span className="analysis-updating">Updating…</span>}</header>
            {key === "mask" ? <MaskEditor image={stages.mask} strokes={maskExclusions} setStrokes={updateMaskExclusions} radius={brushRadius} setRadius={setBrushRadius} /> : <div className="analysis-stage-image"><img src={stages[key]} alt={`${title} analysis preview`} /></div>}
          </article>)}
          <article ref={roiResult} className="card analysis-stage analysis-stage--roi" data-control-group="roi" tabIndex="-1">
            <header><div><h3>Automatic ROI grid</h3><p>{roi ? `${roi.definition.rows} × ${roi.definition.columns} reusable regions` : "Detect reusable plant measurement regions"}</p></div><span className={roi ? "analysis-roi-ready" : "analysis-roi-waiting"}>{roi ? "Detected" : "Not detected"}</span></header>
            {roi ? <><div className="analysis-stage-image"><img src={roi.overlay} alt="Automatically detected PlantCV ROI grid" /></div>
              <footer className="analysis-save-profile"><div><strong>{saved ? (scheduleWorkflow ? "Analysis setup saved" : "Directory calibration ready") : "Ready to save"}</strong><p>{scheduleWorkflow ? "This calibration will be stored only with this experiment." : "Confirm this calibration before analyzing the directory."}</p></div><button type="button" onClick={saveProfile} disabled={saving || saved}>{saving ? "Saving…" : saved ? "Calibration ready" : scheduleWorkflow ? "Save and continue to review" : "Use this calibration"}</button></footer></> : <div className="analysis-roi-placeholder" aria-label="ROI grid has not been detected"><span className="analysis-roi-placeholder-grid" aria-hidden="true">{Array.from({ length: 12 }, (_, index) => <i key={index} />)}</span><p>Set the tray rows and columns, then select <strong>Detect ROI grid</strong>.</p></div>}
          </article>
        </div>}
      </section>
    </div>
  </section>;
}

function RangeControl({ label, help, value, min, max, step = 1, suffix = "", onChange }) {
  const helpId = `analysis-help-setting-${label.toLowerCase().replaceAll(" ", "-")}`;
  return <label className="analysis-control"><span><span className="analysis-setting-label">{label} <HelpTip id={helpId} label={`${label} setting`}>{help}</HelpTip></span><span className="analysis-control-value-wrap"><input className="analysis-control-value" type="number" value={value} min={min} max={max} step={step} aria-label={`${label} exact value`} onChange={event => { if (event.target.value !== "") onChange(Number(event.target.value)); }} />{suffix && <small>{suffix}</small>}</span></span>
    <input type="range" value={value} min={min} max={max} step={step} onChange={event => onChange(Number(event.target.value))} />
  </label>;
}

function CropSelector({ image, crop, onChange }) {
  const element = useRef(null);
  const drag = useRef(null);
  const position = event => {
    const bounds = element.current.getBoundingClientRect();
    return {
      x: Math.max(0, Math.min(1, (event.clientX - bounds.left) / bounds.width)),
      y: Math.max(0, Math.min(1, (event.clientY - bounds.top) / bounds.height)),
    };
  };
  const start = event => {
    const action = event.target.dataset.cropAction;
    if (!action) return;
    event.currentTarget.setPointerCapture(event.pointerId);
    drag.current = {
      action,
      handle: event.target.dataset.cropHandle,
      point: position(event),
      crop,
    };
  };
  const move = event => {
    if (!drag.current) return;
    const point = position(event);
    onChange(adjustCrop(
      drag.current.crop,
      drag.current.action,
      drag.current.handle,
      point.x - drag.current.point.x,
      point.y - drag.current.point.y,
    ));
  };
  const finish = () => {
    drag.current = null;
  };
  return <div ref={element} className="analysis-crop-canvas" onPointerDown={start} onPointerMove={move} onPointerUp={finish} onPointerCancel={finish}>
    <img src={image} alt="Calibration image for selecting the analysis area" draggable={false} />
    <span className="analysis-crop-selection" data-crop-action="move" style={{ left: `${crop.x * 100}%`, top: `${crop.y * 100}%`, width: `${crop.width * 100}%`, height: `${crop.height * 100}%` }}>
      <i data-crop-action="resize" data-crop-handle="nw" /><i data-crop-action="resize" data-crop-handle="ne" /><i data-crop-action="resize" data-crop-handle="se" /><i data-crop-action="resize" data-crop-handle="sw" />
    </span>
  </div>;
}

export function adjustCrop(crop, action, handle, deltaX, deltaY, minimum = 0.02) {
  const clamp = (value, lower, upper) => Math.max(lower, Math.min(upper, value));
  const normalized = value => Math.round(value * 1_000_000) / 1_000_000;
  if (action === "move") {
    return {
      ...crop,
      x: normalized(clamp(crop.x + deltaX, 0, 1 - crop.width)),
      y: normalized(clamp(crop.y + deltaY, 0, 1 - crop.height)),
    };
  }
  let left = crop.x;
  let right = crop.x + crop.width;
  let top = crop.y;
  let bottom = crop.y + crop.height;
  if (handle?.includes("w")) left = clamp(left + deltaX, 0, right - minimum);
  if (handle?.includes("e")) right = clamp(right + deltaX, left + minimum, 1);
  if (handle?.includes("n")) top = clamp(top + deltaY, 0, bottom - minimum);
  if (handle?.includes("s")) bottom = clamp(bottom + deltaY, top + minimum, 1);
  return {
    x: normalized(left),
    y: normalized(top),
    width: normalized(right - left),
    height: normalized(bottom - top),
  };
}

function MaskEditor({ image, strokes, setStrokes, radius, setRadius }) {
  const surface = useRef(null);
  const canvas = useRef(null);
  const drawing = useRef(false);
  const [cursor, setCursor] = useState(null);

  useEffect(() => {
    const redraw = () => {
      const bounds = surface.current?.getBoundingClientRect();
      const context = canvas.current?.getContext("2d");
      if (!bounds || !context) return;
      const scale = window.devicePixelRatio || 1;
      canvas.current.width = Math.max(1, Math.round(bounds.width * scale));
      canvas.current.height = Math.max(1, Math.round(bounds.height * scale));
      context.scale(scale, scale);
      context.clearRect(0, 0, bounds.width, bounds.height);
      context.strokeStyle = "rgba(0, 0, 0, .88)";
      context.fillStyle = "rgba(0, 0, 0, .88)";
      context.lineCap = "round";
      context.lineJoin = "round";
      for (const stroke of strokes) {
        const brush = stroke.radius * Math.min(bounds.width, bounds.height);
        context.lineWidth = brush * 2;
        context.beginPath();
        stroke.points.forEach((point, index) => {
          const x = point.x * bounds.width;
          const y = point.y * bounds.height;
          if (index === 0) context.moveTo(x, y);
          else context.lineTo(x, y);
        });
        context.stroke();
        if (stroke.points.length === 1) {
          const point = stroke.points[0];
          context.beginPath();
          context.arc(point.x * bounds.width, point.y * bounds.height, brush, 0, Math.PI * 2);
          context.fill();
        }
      }
      if (cursor) {
        const brush = radius * Math.min(bounds.width, bounds.height);
        context.beginPath();
        context.arc(
          cursor.x * bounds.width,
          cursor.y * bounds.height,
          brush,
          0,
          Math.PI * 2,
        );
        context.strokeStyle = "#fff";
        context.lineWidth = 2;
        context.shadowColor = "rgba(0, 0, 0, .8)";
        context.shadowBlur = 3;
        context.stroke();
        context.shadowBlur = 0;
      }
    };
    redraw();
    const observer = new ResizeObserver(redraw);
    if (surface.current) observer.observe(surface.current);
    return () => observer.disconnect();
  }, [strokes, image, cursor, radius]);

  const point = event => {
    const bounds = surface.current.getBoundingClientRect();
    return {
      x: Math.max(0, Math.min(1, (event.clientX - bounds.left) / bounds.width)),
      y: Math.max(0, Math.min(1, (event.clientY - bounds.top) / bounds.height)),
    };
  };
  const start = event => {
    drawing.current = true;
    event.currentTarget.setPointerCapture(event.pointerId);
    const nextPoint = point(event);
    setCursor(nextPoint);
    setStrokes(current => [...current, { radius, points: [nextPoint] }]);
  };
  const move = event => {
    const nextPoint = point(event);
    setCursor(nextPoint);
    if (!drawing.current) return;
    setStrokes(current => {
      const next = [...current];
      const stroke = next[next.length - 1];
      const previous = stroke.points[stroke.points.length - 1];
      if (Math.hypot(nextPoint.x - previous.x, nextPoint.y - previous.y) < 0.002) return current;
      next[next.length - 1] = { ...stroke, points: [...stroke.points, nextPoint] };
      return next;
    });
  };
  const finish = () => { drawing.current = false; };

  return <div className="analysis-mask-editor">
    <div className="analysis-mask-tools">
      <label>Brush size<input type="range" min="0.002" max="0.06" step="0.002" value={radius} onChange={event => setRadius(Number(event.target.value))} /></label>
      <button type="button" className="secondary" disabled={!strokes.length} onClick={() => setStrokes(current => current.slice(0, -1))}>Undo stroke</button>
      <button type="button" className="text-button" disabled={!strokes.length} onClick={() => setStrokes([])}>Clear edits</button>
    </div>
    <p className="analysis-mask-hint">Brush over white artefacts to exclude them from ROI calibration.</p>
    <div ref={surface} className="analysis-mask-surface" onPointerDown={start} onPointerMove={move} onPointerEnter={event => setCursor(point(event))} onPointerLeave={() => setCursor(null)} onPointerUp={finish} onPointerCancel={finish}>
      <img src={image} alt="Editable plant-mask analysis preview" draggable={false} />
      <canvas ref={canvas} />
    </div>
  </div>;
}
