"use client";
import { useEffect, useMemo, useRef, useState } from "react";

const SEV = ["critical", "high", "medium", "low"];
const SEV_COLOR = { critical: "#b91c1c", high: "#ef4444", medium: "#f59e0b", low: "#3b82f6" };
const ICON = { secrets: "🔑", dependencies: "📦", code: "🧩", iac: "🏗️", docker: "🐳" };
const scoreColor = (s) => (s >= 80 ? "#22c55e" : s >= 60 ? "#84cc16" : s >= 40 ? "#f59e0b" : "#ef4444");
const scoreLabel = (s) => (s >= 80 ? "Excellent" : s >= 60 ? "Good" : s >= 40 ? "Needs improvement" : "Poor");

function Ring({ value }) {
  const [v, setV] = useState(0);
  useEffect(() => {
    const t = setTimeout(() => setV(value), 50);
    return () => clearTimeout(t);
  }, [value]);
  const r = 62, c = 2 * Math.PI * r;
  return (
    <svg width="160" height="160" viewBox="0 0 160 160" role="img" aria-label={`Security score ${value} out of 100`}>
      <circle cx="80" cy="80" r={r} fill="none" stroke="var(--line)" strokeWidth="14" />
      <circle cx="80" cy="80" r={r} fill="none" stroke={scoreColor(value)} strokeWidth="14" strokeLinecap="round"
        strokeDasharray={c} strokeDashoffset={c * (1 - v / 100)} transform="rotate(-90 80 80)"
        style={{ transition: "stroke-dashoffset .9s ease" }} />
      <text x="80" y="88" textAnchor="middle" fontSize="40" fontWeight="800" fill="currentColor">{value}</text>
      <text x="80" y="110" textAnchor="middle" fontSize="12" fill="var(--muted)">/ 100</text>
    </svg>
  );
}

export default function Home() {
  const [catalog, setCatalog] = useState([]);
  const [picked, setPicked] = useState([]);
  const [file, setFile] = useState(null);
  const [drag, setDrag] = useState(false);
  const [scan, setScan] = useState(null);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const [filter, setFilter] = useState("all");
  const [limit, setLimit] = useState(30);
  const timer = useRef(null);
  const input = useRef(null);

  useEffect(() => {
    fetch("/api/v1/scanners")
      .then((r) => r.json())
      .then((d) => { setCatalog(d); setPicked(d.map((s) => s.key)); })
      .catch(() => setErr("Cannot reach the API"));
    return () => clearTimeout(timer.current);
  }, []);

  const toggle = (k) => setPicked((p) => (p.includes(k) ? p.filter((x) => x !== k) : [...p, k]));
  const meta = (k) => catalog.find((s) => s.key === k);

  async function poll(id) {
    try {
      const d = await (await fetch(`/api/v1/scans/${id}`)).json();
      setScan(d);
      if (d.status === "done" || d.status === "failed") return setBusy(false);
      timer.current = setTimeout(() => poll(id), 1000);
    } catch {
      setErr("Lost connection to the API");
      setBusy(false);
    }
  }

  async function start() {
    clearTimeout(timer.current);
    setErr(""); setScan(null); setBusy(true); setFilter("all"); setLimit(30);
    const body = new FormData();
    body.append("file", file);
    body.append("scanners", picked.join(","));
    try {
      const r = await fetch("/api/v1/scans", { method: "POST", body });
      const d = await r.json();
      if (!r.ok) throw new Error(d.detail || "Upload failed");
      setScan({ status: "queued", filename: file.name });
      poll(d.id);
    } catch (e) {
      setErr(e.message);
      setBusy(false);
    }
  }

  function choose(f) {
    if (!f) return;
    if (!f.name.toLowerCase().endsWith(".zip")) return setErr("Please choose a .zip file");
    setErr(""); setFile(f);
  }

  const result = scan?.result;
  const all = useMemo(() => {
    if (!result) return [];
    return Object.entries(result)
      .filter(([k, v]) => k !== "modules" && v?.findings)
      .flatMap(([k, v]) => v.findings.map((f) => ({ ...f, module: k })))
      .sort((a, b) => SEV.indexOf(a.severity) - SEV.indexOf(b.severity));
  }, [result]);
  const counts = useMemo(() => Object.fromEntries(SEV.map((s) => [s, all.filter((f) => f.severity === s).length])), [all]);
  const shown = all.filter((f) => filter === "all" || f.severity === filter);
  const ready = file && picked.length > 0 && !busy;

  return (
    <>
      <header className="top">
        <div className="logo" aria-hidden>
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round"><path d="M12 3l8 3v6c0 5-3.4 8.4-8 9-4.6-.6-8-4-8-9V6l8-3z" /><path d="M9 12l2 2 4-4" /></svg>
        </div>
        <span className="brand">SecureShip</span>
        <span className="pill">Open source · MIT</span>
      </header>

      <main>
        <h1>Ship <span className="grad">secure code</span>, faster.</h1>
        <p className="lead">Pick your scanners, upload a project as a .zip and get a security score in seconds. Your code is scanned statically and never executed.</p>

        <h2>1 · Choose scanners</h2>
        <div className="grid">
          {catalog.map((s) => {
            const on = picked.includes(s.key);
            return (
              <button key={s.key} type="button" className={`card sc ${on ? "on" : ""}`} aria-pressed={on} onClick={() => toggle(s.key)}>
                <span className="chk">{on ? "✓" : ""}</span>
                <span className="ic">{ICON[s.key] || "🛡️"}</span>
                <b>{s.label}</b>
                <small>{s.description}</small>
                <span className="badge">{s.type} · {s.tool}</span>
              </button>
            );
          })}
        </div>

        <h2>2 · Upload project</h2>
        <div className={`card dz ${drag ? "drag" : ""}`} role="button" tabIndex={0}
          onClick={() => input.current?.click()}
          onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && input.current?.click()}
          onDragOver={(e) => { e.preventDefault(); setDrag(true); }}
          onDragLeave={() => setDrag(false)}
          onDrop={(e) => { e.preventDefault(); setDrag(false); choose(e.dataTransfer.files[0]); }}>
          <input ref={input} type="file" accept=".zip" hidden onChange={(e) => choose(e.target.files[0])} />
          <div className="big">📁</div>
          <b>{file ? file.name : "Drop your .zip here or click to browse"}</b>
          <div className="muted">{file ? `${(file.size / 1024 / 1024).toFixed(2)} MB` : "Max 25 MB"}</div>
        </div>
        <button className="btn" disabled={!ready} onClick={start}>
          {busy ? <><span className="spin" />Scanning…</> : "Run scan →"}
        </button>
        {err && <p className="err">{err}</p>}
        {picked.length === 0 && <p className="muted">Select at least one scanner.</p>}

        {scan && scan.status !== "done" && scan.status !== "failed" && (
          <p className="muted"><span className="spin" />Status: {scan.status}…</p>
        )}
        {scan?.status === "failed" && <p className="err">Scan failed: {scan.error}</p>}

        {scan?.status === "done" && (
          <section className="card res">
            <div className="row">
              <Ring value={scan.score} />
              <div className="mods">
                <h3 style={{ margin: 0, fontSize: 26 }}>{scoreLabel(scan.score)}</h3>
                <div className="muted">{scan.filename}</div>
                {Object.entries(result.modules || {}).map(([m, s]) => (
                  <div className="mod" key={m}>
                    <div className="h"><span>{ICON[m]} {meta(m)?.label || m} <span className="muted">· {meta(m)?.tool}</span></span><b>{s}</b></div>
                    <div className="bar"><i style={{ width: `${s}%`, background: scoreColor(s) }} /></div>
                  </div>
                ))}
              </div>
            </div>

            {Object.entries(result.errors || {}).map(([k, msg]) => (
              <div className="warn" key={k}><b>{meta(k)?.tool || k}</b> could not run: {msg}</div>
            ))}

            <div className="chips">
              <button className={`chip ${filter === "all" ? "on" : ""}`} onClick={() => { setFilter("all"); setLimit(30); }}>All ({all.length})</button>
              {SEV.filter((s) => counts[s]).map((s) => (
                <button key={s} className={`chip ${filter === s ? "on" : ""}`} onClick={() => { setFilter(s); setLimit(30); }}>
                  <span style={{ color: filter === s ? "#fff" : SEV_COLOR[s] }}>●</span> {s} ({counts[s]})
                </button>
              ))}
            </div>

            {all.length === 0 && <p className="muted">🎉 No issues found.</p>}
            {shown.slice(0, limit).map((f, i) => (
              <div className="f" key={i}>
                <span className="tag" style={{ background: SEV_COLOR[f.severity] }}>{f.severity}</span>
                <b>{f.rule}</b> <span className="muted">· {meta(f.module)?.tool}</span>
                <div><code>{f.file}{f.line ? `:${f.line}` : ""}</code></div>
                <div className="muted">{f.description}</div>
              </div>
            ))}
            {shown.length > limit && (
              <button className="btn" style={{ marginTop: 12 }} onClick={() => setLimit(limit + 50)}>Show more ({shown.length - limit} left)</button>
            )}
          </section>
        )}
      </main>

      <footer>
        Designed &amp; built by <b>Javid Mamedov</b> · SecureShip is open source (MIT)
      </footer>
    </>
  );
}
