export const scoreColor = (s) => (s >= 80 ? "var(--ok)" : s >= 60 ? "#65a30d" : s >= 40 ? "var(--med)" : "var(--crit)");
export const scoreLabel = (s) => (s >= 80 ? "Excellent" : s >= 60 ? "Good" : s >= 40 ? "Needs work" : "Poor");

export function ago(iso) {
  if (!iso) return "never";
  const s = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
  const units = [[31536000, "y"], [2592000, "mo"], [86400, "d"], [3600, "h"], [60, "min"]];
  for (const [sec, u] of units) if (s >= sec) return `${Math.floor(s / sec)} ${u} ago`;
  return "just now";
}

export async function api(path, opts) {
  const r = await fetch(`/api/v1${path}`, opts);
  const body = r.status === 204 ? null : await r.json().catch(() => ({}));
  if (!r.ok) throw new Error((body && body.detail) || `Request failed (${r.status})`);
  return body;
}
