"use client";
import { useRef, useState } from "react";

const SEV = { critical: "#991b1b", high: "#dc2626", medium: "#d97706", low: "#2563eb", info: "#6b7280" };
const color = (s) => (s >= 80 ? "#16a34a" : s >= 60 ? "#65a30d" : s >= 40 ? "#d97706" : "#dc2626");
const label = (s) => (s >= 80 ? "Excellent" : s >= 60 ? "Good" : s >= 40 ? "Needs improvement" : "Poor");

function Score({ value }) {
  const r = 54, c = 2 * Math.PI * r;
  return (
    <svg width="140" height="140" viewBox="0 0 140 140" role="img" aria-label={`Score ${value}`}>
      <circle cx="70" cy="70" r={r} fill="none" stroke="var(--line)" strokeWidth="12" />
      <circle cx="70" cy="70" r={r} fill="none" stroke={color(value)} strokeWidth="12" strokeLinecap="round"
        strokeDasharray={c} strokeDashoffset={c * (1 - value / 100)} transform="rotate(-90 70 70)" />
      <text x="70" y="79" textAnchor="middle" fontSize="34" fontWeight="700" fill="currentColor">{value}</text>
    </svg>
  );
}

export default function Home() {
  const [scan, setScan] = useState(null);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const timer = useRef(null);

  async function poll(id) {
    try {
      const d = await (await fetch(`/api/scans/${id}`)).json();
      setScan(d);
      if (d.status === "done" || d.status === "failed") return setBusy(false);
      timer.current = setTimeout(() => poll(id), 1500);
    } catch {
      setErr("Lost connection to the API"); setBusy(false);
    }
  }

  async function upload(file) {
    if (!file) return;
    clearTimeout(timer.current);
    setErr(""); setScan(null); setBusy(true);
    const body = new FormData();
    body.append("file", file);
    try {
      const r = await fetch("/api/scans", { method: "POST", body });
      const d = await r.json();
      if (!r.ok) throw new Error(d.detail || "Upload failed");
      setScan({ status: "queued", filename: file.name });
      poll(d.id);
    } catch (e) { setErr(e.message); setBusy(false); }
  }

  const result = scan?.result;
  const findings = result
    ? Object.entries(result).filter(([k, v]) => k !== "modules" && v?.findings).flatMap(([k, v]) => v.findings.map((f) => ({ ...f, module: k })))
    : [];

  return (
    <main>
      <h1>SecureShip</h1>
      <p className="muted">Upload your project as a .zip and get a security score. Your code is scanned, never executed.</p>

      <label className="drop card">
        <input type="file" accept=".zip" disabled={busy} onChange={(e) => upload(e.target.files[0])} />
        <strong>{busy ? "Scanning…" : "Choose a .zip file"}</strong>
        <div className="muted">Max 25 MB</div>
      </label>

      {err && <p className="err">{err}</p>}
      {scan && scan.status !== "done" && scan.status !== "failed" && <p className="muted">Status: {scan.status}…</p>}
      {scan?.status === "failed" && <p className="err">Scan failed: {scan.error}</p>}

      {scan?.status === "done" && (
        <div className="card">
          <div className="row">
            <Score value={scan.score} />
            <div style={{ flex: 1, minWidth: 220 }}>
              <h2 style={{ margin: 0 }}>{label(scan.score)}</h2>
              <div className="muted">{scan.filename}</div>
              {Object.entries(result.modules || {}).map(([m, s]) => (
                <div key={m} style={{ marginTop: 10 }}>
                  <span style={{ textTransform: "capitalize" }}>{m}</span> <b>{s}</b>
                  <div className="bar"><i style={{ width: `${s}%`, background: color(s) }} /></div>
                </div>
              ))}
            </div>
          </div>
          <h3>Findings ({findings.length})</h3>
          {findings.length === 0 && <p className="muted">No issues found.</p>}
          {findings.map((f, i) => (
            <div className="f" key={i}>
              <span className="tag" style={{ background: SEV[f.severity] || SEV.info }}>{f.severity}</span>
              <b>{f.rule}</b> <span className="muted">in</span> <code>{f.file}:{f.line}</code>
              <div className="muted">{f.description}</div>
            </div>
          ))}
        </div>
      )}
    </main>
  );
}
