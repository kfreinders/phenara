export async function api(path, options = {}) {
  const headers = new Headers(options.headers);
  if (options.body) headers.set("Content-Type", "application/json");
  if (["POST", "PUT", "PATCH", "DELETE"].includes(options.method?.toUpperCase())) {
    headers.set("X-Phenopi-Request", "1");
  }
  const response = await fetch(path, {
    cache: "no-store",
    ...options,
    headers,
  });
  if (!response.ok) {
    let message = `Request failed (${response.status})`;
    try {
      const payload = await response.json();
      if (typeof payload.detail === "string") message = payload.detail;
      else if (Array.isArray(payload.detail) && payload.detail[0]?.msg) {
        message = payload.detail[0].msg.replace(/^Value error, /, "");
      }
    } catch {}
    throw new Error(message);
  }
  return response.status === 204 ? null : response.json();
}

export async function apiBlob(path, options = {}) {
  const headers = new Headers(options.headers);
  if (["POST", "PUT", "PATCH", "DELETE"].includes(options.method?.toUpperCase())) {
    headers.set("X-Phenopi-Request", "1");
  }
  const response = await fetch(path, { cache: "no-store", ...options, headers });
  if (!response.ok) {
    let message = `Request failed (${response.status})`;
    try {
      const payload = await response.json();
      if (typeof payload.detail === "string") message = payload.detail;
    } catch {}
    throw new Error(message);
  }
  return response.blob();
}

export const getSchedulerStatus = () => api("/api/scheduler/status");
export const getSchedulerHealth = () => api("/api/scheduler/health");
export const getDevelopmentStatus = () => api("/api/development/status");
export const setDevelopmentMode = enabled => api(
  "/api/development/status",
  { method: "PUT", body: JSON.stringify({ enabled }) },
);
export const acquireCameraPreview = () => apiBlob(
  "/api/camera/preview",
  { method: "POST" },
);
export const getCameraPreview = () => apiBlob("/api/camera/preview");
export const getAnalysisConfig = () => api("/api/analysis/configure");
export const previewAnalysis = (imageData, config, analysisCrop, maskExclusions, signal) => api(
  "/api/analysis/preview",
  { method: "POST", body: JSON.stringify({ image_data: imageData, config, analysis_crop: analysisCrop, mask_exclusions: maskExclusions }), signal },
);
export const detectAnalysisRoi = (imageData, config, analysisCrop, maskExclusions) => api(
  "/api/analysis/roi",
  { method: "POST", body: JSON.stringify({ image_data: imageData, config, analysis_crop: analysisCrop, mask_exclusions: maskExclusions }) },
);
export const saveAnalysisProfile = (config, roi) => api(
  "/api/analysis/profile",
  { method: "PUT", body: JSON.stringify({ config, roi }) },
);
export const deleteAnalysisProfile = () => api(
  "/api/analysis/profile",
  { method: "DELETE" },
);
export const attachDraftAnalysis = () => api(
  "/api/schedule/draft/analysis",
  { method: "POST" },
);
