"use client";
import { useEffect, useMemo, useRef, useState } from "react";
import { scoreColor, scoreLabel, api } from "./lib";
import Cargo from "./components/Cargo";

const SEV = ["critical", "high", "medium", "low"];
const SEV_COLOR = { critical: "var(--crit)", high: "var(--high)", medium: "var(--med)", low: "var(--low)" };

const SKIP = new Set(["node_modules", ".git", ".next", "dist", "build", "__pycache__", ".venv", "venv", ".terraform", ".idea", ".mypy_cache"]);
const MAX_FILES = 1000, MAX_BYTES = 25 * 1024 * 1024;
const skipped = (path) => path.split("/").slice(0, -1).some((d) => SKIP.has(d));

async function walk(entry, base, out) {
  if (entry.isFile) {
    const f = await new Promise((ok, no) => entry.file(ok, no));
    out.push({ f, path: base + entry.name });
  } else if (entry.isDirectory && !SKIP.has(entry.name)) {
    const rd = entry.createReader();
    for (;;) {
      const batch = await new Promise((ok, no) => rd.readEntries(ok, no));
      if (!batch.length) break;
      for (const e of batch) await walk(e, base + entry.name + "/", out);
    }
  }
}


function Seal({ value }) {
  const [v, setV] = useState(0);
  useEffect(() => {
    const t = setTimeout(() => setV(value), 60);
    return () => clearTimeout(t);
  }, [value]);
  const r = 70, c = 2 * Math.PI * r;
  const ticks = Array.from({ length: 60 }, (_, i) => i);
  return (
    <svg width="180" height="180" viewBox="0 0 180 180" role="img" aria-label={`Security score ${value} out of 100`}>
      {ticks.map((i) => (
        <line key={i} x1="90" y1="6" x2="90" y2={i % 5 === 0 ? 15 : 11} stroke="var(--line)" strokeWidth={i % 5 === 0 ? 2 : 1}
          transform={`rotate(${i * 6} 90 90)`} />
      ))}
      <circle cx="90" cy="90" r={r} fill="none" stroke="var(--line)" strokeWidth="9" />
      <circle cx="90" cy="90" r={r} fill="none" stroke={scoreColor(value)} strokeWidth="9" strokeLinecap="butt"
        strokeDasharray={c} strokeDashoffset={c * (1 - v / 100)} transform="rotate(-90 90 90)"
        style={{ transition: "stroke-dashoffset .9s cubic-bezier(.2,.8,.2,1)" }} />
      <text x="90" y="100" textAnchor="middle" fontSize="54" fontWeight="800" fill="currentColor" letterSpacing="-2">{value}</text>
      <text x="90" y="124" textAnchor="middle" fontSize="12" fontWeight="700" fill="var(--muted)">OUT OF 100</text>
    </svg>
  );
}

export default function Home() {
  const [catalog, setCatalog] = useState([]);
  const [picked, setPicked] = useState([]);
  const [items, setItems] = useState([]);
  const [drag, setDrag] = useState(false);
  const [scan, setScan] = useState(null);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const [filter, setFilter] = useState("all");
  const [limit, setLimit] = useState(30);
  const [q, setQ] = useState("");
  const [share, setShare] = useState(null);
  const [note, setNote] = useState("");
  const [confirmDel, setConfirmDel] = useState(false);
  const [mailOn, setMailOn] = useState(false);
  const [mailOpen, setMailOpen] = useState(false);
  const [mailTo, setMailTo] = useState("");
  const [mailBusy, setMailBusy] = useState(false);
  const [t0, setT0] = useState(0);
  const [, tick] = useState(0);
  const timer = useRef(null);
  const input = useRef(null);
  const dirInput = useRef(null);

  useEffect(() => {
    api("/config").then((c) => setMailOn(!!c.email)).catch(() => {});
    fetch("/api/v1/scanners")
      .then((r) => r.json())
      .then((d) => { setCatalog(d); setPicked(d.map((s) => s.key)); })
      .catch(() => setErr("Cannot reach the API"));
    const id = new URLSearchParams(window.location.search).get("scan");
    if (id && /^[0-9a-f]{32}$/.test(id)) { setBusy(true); poll(id); }
    return () => clearTimeout(timer.current);
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (!busy) return;
    const i = setInterval(() => tick((n) => n + 1), 1000);
    return () => clearInterval(i);
  }, [busy]);
  const flash = (m) => { setNote(m); setTimeout(() => setNote(""), 2200); };
  const copy = async (text) => { try { await navigator.clipboard.writeText(text); flash("Copied"); } catch { flash("Copy failed"); } };
  const PRESETS = [
    ["All", () => catalog.map((s) => s.key)],
    ["Quick", () => ["secrets", "code", "shell"].filter((k) => catalog.some((s) => s.key === k))],
    ["Secrets only", () => ["secrets"]],
    ["None", () => []],
  ];
  async function sendMail(e) {
    e.preventDefault();
    setMailBusy(true); setErr("");
    try {
      await api(`/scans/${scan.id}/email`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ to: mailTo.trim() }) });
      flash(`Report sent to ${mailTo.trim()}`); setMailOpen(false); setMailTo("");
    } catch (e2) { setErr(e2.message); }
    setMailBusy(false);
  }
  async function doShare() {
    try {
      const d = await api(`/scans/${scan.id}/share`, { method: "POST" });
      setShare(`![security](${window.location.origin}${d.badge_url})`);
    } catch (e) { setErr(e.message); }
  }
  async function unshare() {
    try { await api(`/scans/${scan.id}/share`, { method: "DELETE" }); setShare(null); flash("Badge link revoked"); }
    catch (e) { setErr(e.message); }
  }
  async function removeScan() {
    try { await api(`/scans/${scan.id}`, { method: "DELETE" }); setScan(null); setShare(null); setConfirmDel(false); flash("Scan deleted"); }
    catch (e) { setErr(e.message); }
  }

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
    setErr(""); setScan(null); setShare(null); setQ(""); setT0(Date.now()); setBusy(true); setFilter("all"); setLimit(30);
    const body = new FormData();
    if (items.length === 1 && items[0].path.toLowerCase().endsWith(".zip")) body.append("file", items[0].f);
    else items.forEach(({ f, path }) => body.append("files", f, path));
    body.append("scanners", picked.join(","));
    try {
      const r = await fetch("/api/v1/scans", { method: "POST", body });
      const d = await r.json();
      if (!r.ok) throw new Error(d.detail || "Upload failed");
      setScan({ status: "queued", filename: label });
      poll(d.id);
    } catch (e) {
      setErr(e.message);
      setBusy(false);
    }
  }

  function choose(list) {
    const ok = list.filter((x) => !skipped(x.path));
    if (!ok.length) return setErr("No files to scan");
    if (ok.length > MAX_FILES) return setErr(`Too many files (${ok.length}); the limit is ${MAX_FILES}. Upload a .zip instead.`);
    if (ok.reduce((n, x) => n + x.f.size, 0) > MAX_BYTES) return setErr("Upload is larger than 25 MB");
    setErr(""); setItems(ok);
  }
  const fromInput = (e) => {
    choose([...e.target.files].map((f) => ({ f, path: f.webkitRelativePath || f.name })));
    e.target.value = "";
  };
  async function onDrop(e) {
    e.preventDefault(); setDrag(false);
    const entries = [...e.dataTransfer.items].map((i) => i.webkitGetAsEntry?.()).filter(Boolean);
    if (!entries.length) return choose([...e.dataTransfer.files].map((f) => ({ f, path: f.name })));
    const out = [];
    try { for (const en of entries) await walk(en, "", out); } catch { return setErr("Could not read the dropped folder"); }
    choose(out);
  }
  const bytes = items.reduce((n, x) => n + x.f.size, 0);
  const label = items.length === 1 ? items[0].path : `${items[0]?.path.split("/")[0]} (${items.length} files)`;

  const result = scan?.result;
  const all = useMemo(() => {
    if (!result) return [];
    return Object.entries(result)
      .filter(([k, v]) => k !== "modules" && v?.findings)
      .flatMap(([k, v]) => v.findings.map((f) => ({ ...f, module: k })))
      .sort((a, b) => SEV.indexOf(a.severity) - SEV.indexOf(b.severity));
  }, [result]);
  const counts = useMemo(() => Object.fromEntries(SEV.map((s) => [s, all.filter((f) => f.severity === s).length])), [all]);
  const needle = q.trim().toLowerCase();
  const shown = all.filter((f) => (filter === "all" || f.severity === filter) &&
    (!needle || `${f.rule} ${f.file} ${f.description} ${f.module}`.toLowerCase().includes(needle)));
  const ready = items.length > 0 && picked.length > 0 && !busy;

  return (
    <>
      <main className="wrap" id="main">
        <section className="hero">
          <div>
            <h1>Check your code before it ships.</h1>
            <p className="lead">Upload a project, pick the scanners and get a 0–100 security score with every finding explained.</p>
          </div>
          <Cargo state={scan?.status === "done" ? "done" : busy ? "scanning" : "idle"} counts={counts} />
        </section>

        <h2><span className="n">1</span>Choose scanners</h2>
        <div className="chips" style={{ margin: "0 0 12px" }} role="group" aria-label="Scanner presets">
          {PRESETS.map(([label, fn]) => {
            const want = fn();
            const on = want.length === picked.length && want.every((k) => picked.includes(k));
            return <button key={label} type="button" className={`chip ${on ? "on" : ""}`} onClick={() => setPicked(want)}>{label}</button>;
          })}
          <span className="muted small" style={{ alignSelf: "center" }}>{picked.length} of {catalog.length} selected</span>
        </div>
        <div className="grid">
          {catalog.map((s) => {
            const on = picked.includes(s.key);
            return (
              <button key={s.key} type="button" className={`sc ${on ? "on" : ""}`} aria-pressed={on} onClick={() => toggle(s.key)}>
                <b>{s.label}</b>
                <span className="chk" aria-hidden>{on ? "✓" : ""}</span>
                <small>{s.description}</small>
                <span className="badge">{s.type} · {s.tool}</span>
              </button>
            );
          })}
        </div>

        <h2><span className="n">2</span>Add your project</h2>
        <div className={`card dz ${drag ? "drag" : ""}`} aria-label="Drop zone"
          onClick={() => input.current?.click()}
          onDragOver={(e) => { e.preventDefault(); setDrag(true); }}
          onDragLeave={() => setDrag(false)}
          onDrop={onDrop}>
          <input ref={input} type="file" multiple hidden onChange={fromInput} />
          <input ref={dirInput} type="file" webkitdirectory="" directory="" hidden onChange={fromInput} />
          <svg width="34" height="34" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden><path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V7z" /></svg>
          <b>{items.length ? label : "Drop a folder, files or a .zip here"}</b>
          <div className="muted small">{items.length ? `${(bytes / 1024 / 1024).toFixed(2)} MB` : "Up to 25 MB. node_modules, .git and build folders are skipped."}</div>
          <div className="row" style={{ gap: 8, justifyContent: "center", marginTop: 14 }} onClick={(e) => e.stopPropagation()}>
            <button type="button" className="chip" onClick={() => input.current?.click()}>Files or .zip</button>
            <button type="button" className="chip" onClick={() => dirInput.current?.click()}>Folder</button>
          </div>
        </div>
        <div className="runbar">
          <button className="btn" disabled={!ready} onClick={start}>
            {busy ? <><span className="spin" />Scanning</> : "Run scan"}
          </button>
          {picked.length === 0 && <span className="muted small">Select at least one scanner.</span>}
          {busy && scan && scan.status !== "done" && scan.status !== "failed" && (
            <span className="steps" aria-live="polite">
              <i className="on">Uploaded</i>
              <i className={scan.status === "running" ? "on" : ""}>{scan.status === "running" ? "Scanning" : "Queued"}</i>
              <i>Results</i>
              <span className="muted small mono">{Math.max(0, Math.round((Date.now() - t0) / 1000))}s</span>
            </span>
          )}
        </div>
        {err && <p className="err" role="alert">{err}</p>}
        {scan?.status === "failed" && <p className="err" role="alert">Scan failed: {scan.error}</p>}

        {scan?.status === "done" && (
          <section className="card res">
            <div className="row">
              <Seal value={scan.score} />
              <div className="mods">
                <div className="verdict" style={{ color: scoreColor(scan.score) }}>{scoreLabel(scan.score)}</div>
                <div className="muted small mono">{scan.filename}</div>
                {Object.entries(result.modules || {}).map(([m, s]) => (
                  <div className="mod" key={m}>
                    <div className="h"><span>{meta(m)?.label || m} <span className="muted">· {meta(m)?.tool}</span></span><b>{s}</b></div>
                    <div className="bar"><i style={{ width: `${s}%`, background: scoreColor(s) }} /></div>
                  </div>
                ))}
              </div>
            </div>

            {Object.entries(result.errors || {}).map(([k, msg]) => (
              <div className="warn" key={k}><b>{meta(k)?.tool || k}</b> could not run: {msg}</div>
            ))}

            {Object.entries(result.skipped || {}).map(([k, msg]) => (
              <div className="muted" key={k} style={{ fontSize: 13, margin: "4px 0" }}>
                {meta(k)?.label || k} skipped: {msg}
              </div>
            ))}

            <div className="toolbar">
              <span className="muted small">
                {result.timings ? `Scanned in ${Object.values(result.timings).reduce((a, b) => Math.max(a, b), 0).toFixed(0)}s` : ""}
              </span>
              <span className="grow" />
              {["pdf", "sarif", "csv", "json"].map((f) => (
                <a key={f} className="btn ghost sm" href={`/api/v1/scans/${scan.id}/export?format=${f}`} download>{f.toUpperCase()}</a>
              ))}
              {mailOn && <button className="btn ghost sm" onClick={() => setMailOpen(!mailOpen)} aria-expanded={mailOpen}>E-mail PDF</button>}
              <button className="btn ghost sm" onClick={doShare}>Badge</button>
              {confirmDel ? (
                <><button className="btn danger sm" onClick={removeScan}>Delete scan</button><button className="btn ghost sm" onClick={() => setConfirmDel(false)}>Cancel</button></>
              ) : <button className="btn ghost sm" onClick={() => setConfirmDel(true)}>Delete</button>}
            </div>
            {mailOpen && (
              <form className="form" style={{ margin: "0 0 12px" }} onSubmit={sendMail}>
                <input className="text" type="email" required value={mailTo} onChange={(e) => setMailTo(e.target.value)}
                  placeholder="name@company.com" aria-label="Send the PDF report to this e-mail address" autoComplete="email" />
                <button className="btn sm" disabled={mailBusy}>{mailBusy ? "Sending" : "Send report"}</button>
              </form>
            )}
            {share && (
              <div className="reveal" style={{ padding: 14, margin: "12px 0 0" }}>
                <div className="muted small">Public badge: anyone with the link sees only the score. Paste into a README:</div>
                <div className="secret" style={{ margin: "8px 0 0" }}>
                  <code>{share}</code>
                  <button className="btn sm" onClick={() => copy(share)}>Copy</button>
                  <button className="btn danger sm" onClick={unshare}>Revoke</button>
                </div>
              </div>
            )}
            <div className="chips">
              <button className={`chip ${filter === "all" ? "on" : ""}`} onClick={() => { setFilter("all"); setLimit(30); }}>All ({all.length})</button>
              {SEV.filter((s) => counts[s]).map((s) => (
                <button key={s} className={`chip ${filter === s ? "on" : ""}`} onClick={() => { setFilter(s); setLimit(30); }}>
                  <span style={{ color: filter === s ? "inherit" : SEV_COLOR[s] }}>●</span> {s} ({counts[s]})
                </button>
              ))}
            </div>

            {all.length > 0 && (
              <input className="text" style={{ width: "100%", margin: "10px 0 6px" }} type="search" value={q} aria-label="Search findings"
                placeholder="Search by rule, file or description" onChange={(e) => { setQ(e.target.value); setLimit(30); }} />
            )}
            {all.length === 0 && <p className="muted">No issues found by the selected scanners.</p>}
            {all.length > 0 && shown.length === 0 && <p className="muted">No findings match your filters.</p>}
            {shown.slice(0, limit).map((f, i) => (
              <details className="f" key={i}>
                <summary>
                  <span className="tag" style={{ background: SEV_COLOR[f.severity] }}>{f.severity}</span>
                  <b>{f.rule}</b> <span className="muted">· {meta(f.module)?.tool}</span>
                  <code className="loc">{f.file}{f.line ? `:${f.line}` : ""}</code>
                </summary>
                <div className="muted" style={{ margin: "8px 0" }}>{f.description || "No description provided."}</div>
                <button type="button" className="btn ghost sm" onClick={() => copy(`${f.file}${f.line ? `:${f.line}` : ""}`)}>Copy location</button>
              </details>
            ))}
            {shown.length > limit && (
              <button className="btn ghost" style={{ marginTop: 12 }} onClick={() => setLimit(limit + 50)}>Show more ({shown.length - limit} left)</button>
            )}
          </section>
        )}
      </main>

    {note && <div className="toast" role="status">{note}</div>}
    </>
  );
}
