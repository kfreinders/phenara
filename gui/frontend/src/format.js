export function formatDateTime(value) {
  return value
    ? new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" }).format(new Date(value))
    : "—";
}

export function formatBytes(value) {
  if (value == null) return "—";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let size = value;
  let index = 0;
  while (size >= 1000 && index < units.length - 1) {
    size /= 1000;
    index += 1;
  }
  return `${size.toFixed(index < 3 ? 0 : 1)} ${units[index]}`;
}

export function relativeFutureTime(value, now = new Date()) {
  if (!value) return "";
  const seconds = Math.max(0, Math.round((new Date(value) - now) / 1000));
  if (seconds < 60) return `in ${seconds} sec`;
  if (seconds < 3600) return `in ${Math.ceil(seconds / 60)} min`;
  if (seconds < 86400) {
    return `in ${Math.floor(seconds / 3600)} hr ${Math.ceil((seconds % 3600) / 60)} min`;
  }
  return `in ${Math.ceil(seconds / 86400)} days`;
}

