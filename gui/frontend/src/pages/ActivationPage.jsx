import { useEffect, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { WorkflowSteps } from "../components";
import { useSchedulerStatus } from "../hooks";

export function ActivationPage() {
  const [params] = useSearchParams(); const expected = params.get("schedule_hash"); const navigate = useNavigate(); const { data, error } = useSchedulerStatus(2000); const [started] = useState(Date.now()); const [countdown, setCountdown] = useState(null);
  const analysisEnabled = params.get("analysis") === "1";
  const validHash = /^[0-9a-f]{64}$/.test(expected ?? "");
  const confirmed = Boolean(expected && data?.schedule?.hash === expected);
  useEffect(() => { if (!confirmed) return; setCountdown(5); const timer = window.setInterval(() => setCountdown(value => { if (value <= 1) { window.clearInterval(timer); navigate("/scheduler"); return 0; } return value - 1; }), 1000); return () => window.clearInterval(timer); }, [confirmed, navigate]);
  if (!validHash) return <><WorkflowSteps current={analysisEnabled ? 6 : 5} analysisEnabled={analysisEnabled} /><section className="activation-status card"><div className="activation-icon activation-icon--rejected">!</div><h2>Invalid activation link</h2><p>This link does not identify a schedule that can be confirmed.</p><Link className="button-link secondary" to="/schedule">Start schedule setup</Link></section></>;
  let kind = "waiting", title = "Waiting for scheduler confirmation", message = "The schedule was activated safely. Phenopi is waiting for the scheduler to load it.";
  if (confirmed) { kind = "confirmed"; title = "Schedule confirmed"; message = "The scheduler has loaded the schedule and is ready."; }
  else if (data?.status === "invalid_schedule" && Date.now() - started >= 35000) { kind = "rejected"; title = "Scheduler rejected the schedule"; message = data.message; }
  else if (Date.now() - started >= 90000) { title = "Schedule not yet confirmed"; message = "The scheduler has not confirmed the schedule within 90 seconds. It may still be loading."; }
  else if (error || ["stale", "unavailable"].includes(data?.status)) { title = "Confirmation paused"; message = "The scheduler is not responding, so activation cannot currently be confirmed."; }
  return <><WorkflowSteps current={analysisEnabled ? 6 : 5} analysisEnabled={analysisEnabled} /><section className="activation-status card" aria-live="polite"><div className={`activation-icon activation-icon--${kind}`}>{kind === "confirmed" ? "✓" : kind === "rejected" ? "!" : "↻"}</div><h2>{title}</h2><p>{message}</p>{confirmed && <p className="activation-redirect">Opening scheduler status in <strong>{countdown ?? 5}</strong>…</p>}</section></>;
}
