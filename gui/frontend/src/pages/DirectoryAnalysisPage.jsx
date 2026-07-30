import { useEffect, useState } from "react";
import { ErrorNotice, Loading } from "../components";
import {
  getAnalysisDirectoryInspection,
  getAnalysisConfig,
  inspectAnalysisDirectory,
  loadDirectoryCalibrationImage,
  runDirectoryAnalysis,
} from "../api";
import { CalibrationWorkspace } from "./AnalysisSetupPage";

export function DirectoryAnalysisPage() {
  const [directory, setDirectory] = useState("");
  const [outputDirectory, setOutputDirectory] = useState("");
  const [blackThreshold, setBlackThreshold] = useState(10);
  const [inspection, setInspection] = useState(null);
  const [inspectionProgress, setInspectionProgress] = useState(null);
  const [calibrationImage, setCalibrationImage] = useState("");
  const [imageData, setImageData] = useState(null);
  const [config, setConfig] = useState(null);
  const [calibration, setCalibration] = useState(null);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState(null);
  const [result, setResult] = useState(null);

  useEffect(() => {
    getAnalysisConfig().then(payload => setConfig(payload.config)).catch(setError);
  }, []);

  const inspect = async event => {
    event.preventDefault();
    setBusy("inspect");
    setError(null);
    setResult(null);
    setInspection(null);
    setInspectionProgress({ completed_images: 0, total_images: 0, status: "queued" });
    setCalibrationImage("");
    setImageData(null);
    setCalibration(null);
    try {
      const started = await inspectAnalysisDirectory(directory, blackThreshold);
      let value;
      while (true) {
        value = await getAnalysisDirectoryInspection(started.job_id);
        setInspectionProgress(value);
        if (value.status === "completed") break;
        if (value.status === "failed") {
          throw new Error(value.error || "Directory inspection failed.");
        }
        await new Promise(resolve => window.setTimeout(resolve, 400));
      }
      setDirectory(value.directory);
      setInspection(value);
      setOutputDirectory(`${value.directory}/analysis`);
    } catch (reason) {
      setError(reason);
    } finally {
      setBusy("");
      setInspectionProgress(null);
    }
  };

  const chooseCalibration = async name => {
    setCalibrationImage(name);
    setImageData(null);
    setCalibration(null);
    setError(null);
    if (!name) return;
    setBusy("image");
    try {
      const value = await loadDirectoryCalibrationImage(directory, name, blackThreshold);
      setImageData(value.image_data);
    } catch (reason) {
      setError(reason);
    } finally {
      setBusy("");
    }
  };

  const analyze = async () => {
    setBusy("analyze");
    setError(null);
    setResult(null);
    try {
      setResult(await runDirectoryAnalysis({
        directory,
        output_directory: outputDirectory,
        black_mean_threshold: blackThreshold,
        calibration_image: calibrationImage,
        config: calibration.config,
        roi: calibration.roi,
      }));
    } catch (reason) {
      setError(reason);
    } finally {
      setBusy("");
    }
  };

  if (!config) return <Loading label="Loading analysis settings" />;

  return <section className="directory-analysis-page">
    <header className="react-page-heading">
      <h2>Analyze an image directory</h2>
      <p>Inspect a local directory, calibrate canopy segmentation, and analyze every readable non-black image.</p>
    </header>
    <ErrorNotice error={error} />

    <form className="card directory-source" onSubmit={inspect}>
      <div>
        <label>Image directory<input value={directory} onChange={event => setDirectory(event.target.value)} placeholder="/path/to/captures" required /></label>
        <label>Black-image cutoff<input type="number" min="0" max="255" step="0.5" value={blackThreshold} onChange={event => setBlackThreshold(Number(event.target.value))} /></label>
      </div>
      <p>Images with mean grayscale intensity at or below this cutoff are excluded before calibration and analysis.</p>
      <button type="submit" disabled={busy === "inspect"}>{busy === "inspect" ? "Inspecting…" : "Inspect directory"}</button>
      {busy === "inspect" && <div className="directory-inspection-progress" role="status" aria-live="polite">
        <div><span>{inspectionProgress?.total_images ? `Inspecting image ${inspectionProgress.completed_images} of ${inspectionProgress.total_images}` : "Finding supported images…"}</span><strong>{inspectionProgress?.total_images ? `${Math.round(inspectionProgress.completed_images / inspectionProgress.total_images * 100)}%` : "…"}</strong></div>
        <progress max={inspectionProgress?.total_images || 1} value={inspectionProgress?.completed_images || 0} />
      </div>}
    </form>

    {inspection && <section className="card directory-inspection">
      <header><div><h3>1. Choose a calibration image</h3><p>Calibration is mandatory. Only readable, non-black images can be selected.</p></div>
        <div className="directory-counts"><strong>{inspection.usable_count} usable</strong><span>{inspection.black_excluded_count} black excluded</span><span>{inspection.unreadable_excluded_count} unreadable excluded</span></div>
      </header>
      {inspection.usable_count ? <label>Calibration image<select value={calibrationImage} onChange={event => chooseCalibration(event.target.value)}>
        <option value="">Select an image…</option>
        {inspection.images.map(name => <option key={name} value={name}>{name}</option>)}
      </select></label> : <div className="alert error">No readable, non-black images were found.</div>}
    </section>}

    {imageData && <CalibrationWorkspace
      key={`${directory}/${calibrationImage}`}
      initialConfig={config}
      initialImageData={imageData}
      initialFileName={calibrationImage}
      onComplete={setCalibration}
      onInvalidated={() => { setCalibration(null); setResult(null); }}
    />}

    {calibration && <section className="card directory-run">
      <div><h3>3. Analyze directory</h3><p>All {inspection.usable_count} usable images will use this calibration. Black and unreadable images remain excluded.</p></div>
      <label>Output directory<input value={outputDirectory} onChange={event => setOutputDirectory(event.target.value)} required /></label>
      <button type="button" onClick={analyze} disabled={busy === "analyze"}>{busy === "analyze" ? "Analyzing images…" : "Analyze directory"}</button>
    </section>}
    {result && <section className="alert success directory-result"><strong>Analysis complete.</strong> {result.analyzed_images} images produced {result.result_rows} trait rows in <code>{result.output_directory}</code>.</section>}
  </section>;
}
