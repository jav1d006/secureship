"use client";
import { useEffect, useState } from "react";
import { ago, api } from "../lib";

const MAX_KEYS = 5;

export default function Keys() {
  const [keys, setKeys] = useState(null);
  const [name, setName] = useState("");
  const [fresh, setFresh] = useState(null);     // the new key, shown once
  const [copied, setCopied] = useState(false);
  const [confirm, setConfirm] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  const load = () => api("/keys").then(setKeys).catch((e) => setErr(e.message));
  useEffect(() => { load(); }, []);

  async function create(e) {
    e.preventDefault();
    setBusy(true); setErr(""); setCopied(false);
    try {
      setFresh(await api("/keys", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name: name.trim() || "key" }) }));
      setName(""); load();
    } catch (e2) { setErr(e2.message); }
    setBusy(false);
  }

  async function revoke(id) {
    setErr("");
    try { await api(`/keys/${id}`, { method: "DELETE" }); setConfirm(""); if (fresh?.id === id) setFresh(null); load(); }
    catch (e2) { setErr(e2.message); }
  }

  async function copy() {
    try { await navigator.clipboard.writeText(fresh.api_key); setCopied(true); } catch { setErr("Copy failed. Select the key and copy it manually."); }
  }

  const full = keys && keys.length >= MAX_KEYS;
  const origin = typeof window === "undefined" ? "" : window.location.origin;

  return (
    <main className="wrap" id="main">
      <div className="pagehead">
        <div>
          <h1>API keys</h1>
          <p className="lead" style={{ marginTop: 10 }}>Scan from CI or a script. Scans started with a key appear in your History.</p>
        </div>
        {keys && <span className="muted small">{keys.length} of {MAX_KEYS} keys in use</span>}
      </div>

      {fresh && (
        <section className="reveal" aria-live="polite">
          <b>Key “{fresh.name}” created. Copy it now: it is not shown again.</b>
          <div className="secret">
            <code>{fresh.api_key}</code>
            <button className="btn sm" onClick={copy}>{copied ? "Copied" : "Copy key"}</button>
          </div>
          <div className="muted small">Use it as the <code>X-API-Key</code> header:</div>
          <pre>{`curl -H "X-API-Key: ${fresh.api_key}" \\
  -F "file=@project.zip" -F "scanners=secrets,code,semgrep" \\
  ${origin}/api/v1/scans`}</pre>
          <button className="btn ghost sm" style={{ marginTop: 12 }} onClick={() => setFresh(null)}>I saved it</button>
        </section>
      )}

      <form className="form" onSubmit={create}>
        <input className="text" value={name} onChange={(e) => setName(e.target.value)} maxLength={40}
          placeholder="Key name, for example github-actions" aria-label="Key name" disabled={full} />
        <button className="btn" disabled={busy || full}>{busy ? "Creating" : "Create key"}</button>
      </form>
      {full && <p className="muted small" style={{ marginTop: -10 }}>You have reached the limit of {MAX_KEYS} keys. Revoke one to create another.</p>}
      {err && <p className="err" role="alert">{err}</p>}

      <div className="card" style={{ overflowX: "auto" }}>
        {keys === null && !err && <div className="empty"><span className="spin" /></div>}
        {keys && keys.length === 0 && (
          <div className="empty">
            <h3>No API keys yet</h3>
            <p>Create a key to run scans from GitHub Actions or any script.</p>
          </div>
        )}
        {keys && keys.length > 0 && (
          <table className="tbl">
            <thead><tr><th>Name</th><th>Key</th><th className="hide">Created</th><th>Last used</th><th /></tr></thead>
            <tbody>
              {keys.map((k) => (
                <tr key={k.id}>
                  <td><b>{k.name}</b></td>
                  <td><code>{k.prefix}…</code></td>
                  <td className="hide muted">{ago(k.created_at)}</td>
                  <td className="muted">{ago(k.last_used_at)}</td>
                  <td style={{ textAlign: "right", whiteSpace: "nowrap" }}>
                    {confirm === k.id ? (
                      <>
                        <button className="btn danger sm" onClick={() => revoke(k.id)}>Revoke key</button>{" "}
                        <button className="btn ghost sm" onClick={() => setConfirm("")}>Cancel</button>
                      </>
                    ) : (
                      <button className="btn ghost sm" onClick={() => setConfirm(k.id)}>Revoke</button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
      <p className="muted small" style={{ marginTop: 14 }}>
        Revoking a key stops it working immediately. Keys act as this browser session, so clearing your cookies also removes access to this list.
      </p>
    </main>
  );
}
