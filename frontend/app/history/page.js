"use client";
import Link from "next/link";
import { useEffect, useState } from "react";
import { ago, api, scoreColor } from "../lib";

const PAGE = 20;

export default function History() {
  const [rows, setRows] = useState(null);
  const [more, setMore] = useState(false);
  const [confirm, setConfirm] = useState("");
  const [err, setErr] = useState("");

  async function load(offset = 0) {
    try {
      const d = await api(`/scans?limit=${PAGE + 1}&offset=${offset}`);
      setMore(d.length > PAGE);
      setRows((r) => (offset ? [...(r || []), ...d.slice(0, PAGE)] : d.slice(0, PAGE)));
    } catch (e) { setErr(e.message); }
  }
  useEffect(() => { load(); }, []);

  async function remove(id) {
    try { await api(`/scans/${id}`, { method: "DELETE" }); setRows((r) => r.filter((x) => x.id !== id)); setConfirm(""); }
    catch (e) { setErr(e.message); }
  }

  return (
    <main className="wrap">
      <div className="pagehead">
        <div>
          <h1>History</h1>
          <p className="lead" style={{ marginTop: 10 }}>Your scans from this browser and your API keys. Results are deleted after 30 days.</p>
        </div>
        <Link href="/" className="btn">New scan</Link>
      </div>
      {err && <p className="err" role="alert">{err}</p>}
      {rows && rows.some((r) => r.status === "done") && (() => {
        const done = rows.filter((r) => r.status === "done").slice().reverse();
        const avg = Math.round(done.reduce((n, r) => n + r.score, 0) / done.length);
        const last = done[done.length - 1].score, prev = done.length > 1 ? done[done.length - 2].score : null;
        const pts = done.map((r, i) => `${done.length === 1 ? 60 : (i / (done.length - 1)) * 120},${34 - (r.score / 100) * 30}`).join(" ");
        return (
          <div className="stats">
            <div className="card stat"><b>{rows.length}</b><span>scans shown</span></div>
            <div className="card stat"><b style={{ color: scoreColor(avg) }}>{avg}</b><span>average score</span></div>
            <div className="card stat"><b style={{ color: scoreColor(last) }}>{last}{prev !== null && <small style={{ fontSize: 14, marginLeft: 8, color: last >= prev ? "var(--ok)" : "var(--crit)" }}>{last >= prev ? "▲" : "▼"} {Math.abs(last - prev)}</small>}</b><span>latest score</span></div>
            <div className="card stat"><svg viewBox="0 0 120 36" width="100%" height="36" role="img" aria-label="Score trend"><circle cx={done.length === 1 ? 60 : 120} cy={34 - (last / 100) * 30} r="3" fill="var(--seal)" /><polyline points={pts} fill="none" stroke="var(--seal)" strokeWidth="2" strokeLinejoin="round" strokeLinecap="round" /></svg><span>score trend</span></div>
          </div>
        );
      })()}

      <div className="card" style={{ overflow: "hidden" }}>
        {rows === null && !err && <div className="empty"><span className="spin" /></div>}
        {rows && rows.length === 0 && (
          <div className="empty">
            <h3>No scans yet</h3>
            <p>Upload a project and your results will be listed here.</p>
            <Link href="/" className="btn">Scan a project</Link>
          </div>
        )}
        {rows && rows.length > 0 && (
          <table className="tbl">
            <thead><tr><th>Project</th><th>Score</th><th className="hide">Scanners</th><th>When</th><th /></tr></thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.id}>
                  <td><Link href={`/?scan=${r.id}`} className="mono">{r.filename}</Link></td>
                  <td>
                    {r.status === "done"
                      ? <span className="score" style={{ background: scoreColor(r.score) }}>{r.score}</span>
                      : <span className="status">{r.status}</span>}
                  </td>
                  <td className="hide muted">{(r.scanners || "").split(",").filter(Boolean).length}</td>
                  <td className="muted">{ago(r.created_at)}</td>
                  <td style={{ textAlign: "right", whiteSpace: "nowrap" }}>
                    {confirm === r.id ? (
                      <>
                        <button className="btn danger sm" onClick={() => remove(r.id)}>Delete scan</button>{" "}
                        <button className="btn ghost sm" onClick={() => setConfirm("")}>Cancel</button>
                      </>
                    ) : (
                      <button className="btn ghost sm" onClick={() => setConfirm(r.id)}>Delete</button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
      {more && <button className="btn ghost" style={{ marginTop: 14 }} onClick={() => load(rows.length)}>Load more</button>}
    </main>
  );
}
