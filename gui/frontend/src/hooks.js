import { useEffect, useState } from "react";
import { getSchedulerHealth, getSchedulerStatus } from "./api";

function usePolling(loader, interval) {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  useEffect(() => {
    let active = true;
    let inFlight = false;
    const refresh = async () => {
      if (inFlight) return;
      inFlight = true;
      try {
        const value = await loader();
        if (active) { setData(value); setError(null); }
      } catch (reason) {
        if (active) setError(reason);
      } finally {
        inFlight = false;
      }
    };
    refresh();
    const timer = window.setInterval(refresh, interval);
    return () => { active = false; window.clearInterval(timer); };
  }, [loader, interval]);
  return { data, error, setData };
}

export const useSchedulerStatus = (interval = 5000) => usePolling(getSchedulerStatus, interval);
export const useSchedulerHealth = (interval = 5000) => usePolling(getSchedulerHealth, interval);
