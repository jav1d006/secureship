"use client";
import { useEffect, useRef } from "react";

// Full-page 3D security environment behind the site: a faceted core (the "shield") inside two slow rings,
// a shell of nodes joined by fine lines, data particles travelling along those lines and a faint floor grid.
// Pointer and scroll only nudge the camera. The core pulses when the page first reveals and while a scan runs;
// when a scan finishes the nodes are tinted by the real severity counts. Pauses when the tab is hidden.

const css = (n, f) => getComputedStyle(document.documentElement).getPropertyValue(n).trim() || f;
const isDark = () => {
  const t = document.documentElement.getAttribute("data-theme");
  return t ? t === "dark" : window.matchMedia("(prefers-color-scheme: dark)").matches;
};
const rng = (seed) => { let s = seed; return () => (s = (s * 16807) % 2147483647) / 2147483647; };
const ORDER = ["critical", "high", "medium", "low"];

function tintsFor(counts, total) {
  const sum = ORDER.reduce((n, k) => n + (counts[k] || 0), 0);
  const out = Array(total).fill(null);
  if (!sum) return out;
  const scatter = Array.from({ length: total }, (_, i) => (i * 7) % total);
  let slot = 0;
  for (const k of ORDER) {
    const n = counts[k] ? Math.min(total - slot, Math.max(1, Math.round((counts[k] / sum) * Math.min(total - 2, sum)))) : 0;
    for (let i = 0; i < n && slot < total; i++) out[scatter[slot++]] = k;
  }
  return out;
}

export default function Scene() {
  const box = useRef(null);
  useEffect(() => {
    let dead = false, cleanup = () => {};
    (async () => {
      let THREE;
      try { THREE = await import("three"); } catch { return; }
      if (dead || !box.current) return;
      const small = window.innerWidth < 700;
      const reduce = window.matchMedia("(prefers-reduced-motion: reduce)");
      const dom = document.createElement("canvas");
      let renderer;
      try { renderer = new THREE.WebGLRenderer({ canvas: dom, antialias: !small, alpha: true, powerPreference: "high-performance" }); }
      catch { return; }   // no WebGL: the CSS background stays
      renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, small ? 1.25 : 1.75));
      renderer.setClearColor(0x000000, 0);
      box.current.appendChild(dom);
      const C = (v) => new THREE.Color(v);

      const scene = new THREE.Scene();
      scene.fog = new THREE.FogExp2(0x050b17, 0.03);
      const camera = new THREE.PerspectiveCamera(42, 1, 0.1, 200);
      const root = new THREE.Group(); scene.add(root);
      const core = new THREE.Group(); root.add(core);
      const net = new THREE.Group(); root.add(net);

      const solidMat = new THREE.MeshPhysicalMaterial({ color: 0x0b1a2e, metalness: 0.85, roughness: 0.3, clearcoat: 1, clearcoatRoughness: 0.2, emissive: 0x3cffb0, emissiveIntensity: 0.15, flatShading: true });
      core.add(new THREE.Mesh(new THREE.IcosahedronGeometry(1.35, 1), solidMat));
      const wireMat = new THREE.LineBasicMaterial({ transparent: true, opacity: 0.8 });
      core.add(new THREE.LineSegments(new THREE.EdgesGeometry(new THREE.IcosahedronGeometry(1.4, 1)), wireMat));
      const innerMat = new THREE.MeshBasicMaterial({ transparent: true, opacity: 0.9 });
      const inner = new THREE.Mesh(new THREE.IcosahedronGeometry(0.6, 2), innerMat); core.add(inner);

      const tex = (() => {
        const c = document.createElement("canvas"); c.width = c.height = 128;
        const g = c.getContext("2d"), r = g.createRadialGradient(64, 64, 0, 64, 64, 64);
        r.addColorStop(0, "rgba(255,255,255,.9)"); r.addColorStop(0.25, "rgba(255,255,255,.28)"); r.addColorStop(1, "rgba(255,255,255,0)");
        g.fillStyle = r; g.fillRect(0, 0, 128, 128); return new THREE.CanvasTexture(c);
      })();
      const haloMat = new THREE.SpriteMaterial({ map: tex, transparent: true, depthWrite: false, blending: THREE.AdditiveBlending });
      const halo = new THREE.Sprite(haloMat); halo.scale.set(8, 8, 1); core.add(halo);

      const ringMat = new THREE.MeshBasicMaterial({ transparent: true, opacity: 0.55 });
      const ringA = new THREE.Mesh(new THREE.TorusGeometry(2.2, 0.012, 8, 160), ringMat); ringA.rotation.x = 1.25;
      const ringB = new THREE.Mesh(new THREE.TorusGeometry(2.8, 0.008, 8, 160), ringMat); ringB.rotation.set(0.5, 0.4, 0);
      core.add(ringA, ringB);

      const shockMat = new THREE.MeshBasicMaterial({ transparent: true, opacity: 0, side: THREE.DoubleSide, depthWrite: false });
      const shock = new THREE.Mesh(new THREE.RingGeometry(0.97, 1, 128), shockMat); shock.rotation.x = Math.PI / 2.6; root.add(shock);

      // nodes on a loose shell, joined to their nearest neighbours and, every third one, to the core
      const N = small ? 18 : 30, r = rng(11), pos = [];
      for (let i = 0; i < N; i++) {
        const y = 1 - ((i + 0.5) / N) * 2, rad = Math.sqrt(1 - y * y), th = i * 2.399963, R = 3.5 + r() * 3;
        pos.push(new THREE.Vector3(Math.cos(th) * rad * R, y * R * 0.8, Math.sin(th) * rad * R));
      }
      const edges = [], seen = new Set(), origin = new THREE.Vector3();
      const link = (a, b) => { const k = a < b ? `${a}-${b}` : `${b}-${a}`; if (!seen.has(k)) { seen.add(k); edges.push([a < 0 ? origin : pos[a], pos[b]]); } };
      pos.forEach((p, i) => {
        pos.map((q, j) => [j, p.distanceToSquared(q)]).filter(([j]) => j !== i).sort((a, b) => a[1] - b[1]).slice(0, 2).forEach(([j]) => link(i, j));
        if (i % 3 === 0) link(-1, i);
      });
      const lp = new Float32Array(edges.length * 6);
      edges.forEach(([a, b], i) => lp.set([a.x, a.y, a.z, b.x, b.y, b.z], i * 6));
      const lg = new THREE.BufferGeometry(); lg.setAttribute("position", new THREE.BufferAttribute(lp, 3));
      const lineMat = new THREE.LineBasicMaterial({ transparent: true, opacity: 0.28 });
      net.add(new THREE.LineSegments(lg, lineMat));

      const nodeMat = new THREE.MeshBasicMaterial();
      const nodes = new THREE.InstancedMesh(new THREE.OctahedronGeometry(0.075), nodeMat, N);
      const dummy = new THREE.Object3D();
      pos.forEach((p, i) => { dummy.position.copy(p); dummy.scale.setScalar(0.7 + r() * 0.8); dummy.updateMatrix(); nodes.setMatrixAt(i, dummy.matrix); });
      net.add(nodes);

      const P = small ? 50 : 120, pdata = Array.from({ length: P }, () => ({ e: Math.floor(r() * edges.length), t: r(), v: 0.1 + r() * 0.18, d: r() < 0.5 ? 1 : -1 }));
      const pp = new Float32Array(P * 3), pg = new THREE.BufferGeometry(); pg.setAttribute("position", new THREE.BufferAttribute(pp, 3));
      const pMat = new THREE.PointsMaterial({ size: 0.09, transparent: true, depthWrite: false, blending: THREE.AdditiveBlending });
      net.add(new THREE.Points(pg, pMat));

      const grid = new THREE.GridHelper(70, 70, 0xffffff, 0xffffff);
      grid.position.y = -4.6; const gridMats = [].concat(grid.material); gridMats.forEach((m) => { m.transparent = true; m.opacity = 0.16; });
      scene.add(grid);

      scene.add(new THREE.AmbientLight(0x35507a, 0.7));
      const key = new THREE.DirectionalLight(0x7aa7ff, 1.3); key.position.set(4, 5, 6); scene.add(key);
      const rim = new THREE.DirectionalLight(0x3cffb0, 0.8); rim.position.set(-5, 2, -4); scene.add(rim);
      const pl = new THREE.PointLight(0x3cffb0, 6, 22); core.add(pl);

      const sev = {};
      let dark = true, scan = window.__ssScan || { state: "idle", counts: {} };
      const mint = new THREE.Color();
      const recolor = () => {
        const tints = scan.state === "done" ? tintsFor(scan.counts || {}, N) : [];
        pos.forEach((_, i) => nodes.setColorAt(i, tints[i] ? sev[tints[i]] : mint));
        nodes.instanceColor.needsUpdate = true;
      };
      const applyTheme = () => {
        dark = isDark();
        mint.set(css("--seal", "#3cffb0"));
        const paper = css("--paper", "#050b17");
        scene.fog.color.set(paper); scene.fog.density = dark ? 0.03 : 0.018;
        const bl = dark ? THREE.AdditiveBlending : THREE.NormalBlending;
        for (const m of [haloMat, pMat, shockMat]) { m.blending = bl; m.needsUpdate = true; }
        for (const m of [wireMat, lineMat, ringMat, innerMat, shockMat, pMat]) m.color.copy(mint);
        solidMat.color.set(dark ? "#0b1a2e" : "#243648"); solidMat.emissive.copy(mint);
        haloMat.color.copy(mint); haloMat.opacity = dark ? 0.55 : 0.25;
        gridMats.forEach((m) => { m.color.copy(mint); m.opacity = dark ? 0.16 : 0.22; });
        lineMat.opacity = dark ? 0.28 : 0.4;
        pl.color.copy(mint); rim.color.copy(mint);
        for (const [k, v] of [["critical", "--crit"], ["high", "--high"], ["medium", "--med"], ["low", "--low"]]) sev[k] = C(css(v, "#888"));
        recolor(); frame();
      };

      let pulse = 0, shockT = 1, prog = 0, cur = 0, mx = 0, my = 0, tmx = 0, tmy = 0, t = 0, speed = 1, lastScanPulse = -9;
      const fire = (p = 1) => { pulse = Math.max(pulse, p); shockT = 0; };
      const onPulse = () => { fire(1); if (reduce.matches) frame(); };
      const onScan = (e) => { scan = e.detail; recolor(); speed = scan.state === "scanning" ? 2.4 : 1; frame(); };
      window.addEventListener("secureship:pulse", onPulse);
      window.addEventListener("secureship:scan", onScan);
      if (window.__ssPulseAt && Date.now() - window.__ssPulseAt < 2500) fire(1);   // reveal happened while the scene was still loading

      const readProg = () => { const m = Math.max(500, document.documentElement.scrollHeight - window.innerHeight); prog = Math.min(1, Math.max(0, window.scrollY / m)); };
      const place = () => {
        const aspect = window.innerWidth / window.innerHeight;
        root.position.x = (aspect > 1.25 ? Math.min(3.6, aspect * 1.6) : 0) * (1 - cur * 0.85);
        root.position.y = (aspect > 1.25 ? 0 : 2.2) + Math.sin(t * 0.6) * 0.1;
        const ang = cur * 1.1 + tmx * 0.3, dist = (aspect > 1.25 ? 11 : 14) - cur * 3;
        camera.position.set(Math.sin(ang) * dist, 0.8 + cur * 1.6 - tmy * 0.6, Math.cos(ang) * dist);
        camera.lookAt(0, 0, 0);
      };
      const frame = () => { place(); renderer.render(scene, camera); };
      const resize = () => { renderer.setSize(window.innerWidth, window.innerHeight, false); camera.aspect = window.innerWidth / window.innerHeight; camera.updateProjectionMatrix(); frame(); };
      const onScroll = () => { readProg(); if (reduce.matches) { cur = prog; frame(); } };
      const onMove = (e) => { tmx = e.clientX / window.innerWidth - 0.5; tmy = e.clientY / window.innerHeight - 0.5; };
      window.addEventListener("scroll", onScroll, { passive: true });
      window.addEventListener("resize", resize);
      window.addEventListener("pointermove", onMove, { passive: true });
      const mo = new MutationObserver(applyTheme); mo.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
      const mq = window.matchMedia("(prefers-color-scheme: dark)"); mq.addEventListener("change", applyTheme);

      let raf = 0, last = performance.now(), frames = 0, acc = 0, low = false;
      const loop = () => {
        raf = requestAnimationFrame(loop);
        const now = performance.now(), dt = Math.min(0.05, (now - last) / 1000); last = now; acc += dt * 1000;
        if (++frames === 90 && acc / 90 > 40 && !low) { low = true; renderer.setPixelRatio(0.75); resize(); }
        t += dt;
        if (scan.state === "scanning" && t - lastScanPulse > 1.8) { lastScanPulse = t; fire(0.55); }
        pulse = Math.max(0, pulse - dt * 0.9);
        if (shockT < 1) shockT = Math.min(1, shockT + dt / 1.5);
        const s = 1 + shockT * 9; shock.scale.set(s, s, s); shockMat.opacity = shockT < 1 ? (1 - shockT) * (dark ? 0.7 : 0.5) : 0;
        solidMat.emissiveIntensity = 0.15 + pulse * 1.1; pl.intensity = 6 + pulse * 26;
        innerMat.opacity = 0.75 + pulse * 0.25; wireMat.opacity = 0.7 + pulse * 0.3;
        halo.scale.setScalar(8 + pulse * 3);
        core.rotation.y += dt * 0.18 * speed; core.rotation.x = Math.sin(t * 0.3) * 0.12;
        ringA.rotation.z += dt * 0.25 * speed; ringB.rotation.y -= dt * 0.18 * speed;
        net.rotation.y += dt * 0.03 * speed;
        for (let i = 0; i < P; i++) {
          const d = pdata[i]; d.t += d.v * d.d * dt * speed;
          if (d.t > 1 || d.t < 0) { d.t = d.d > 0 ? 0 : 1; d.e = (d.e + 7) % edges.length; }
          const [a, b] = edges[d.e];
          pp[i * 3] = a.x + (b.x - a.x) * d.t; pp[i * 3 + 1] = a.y + (b.y - a.y) * d.t; pp[i * 3 + 2] = a.z + (b.z - a.z) * d.t;
        }
        pg.attributes.position.needsUpdate = true;
        mx += (tmx - mx) * 0.04; my += (tmy - my) * 0.04; cur += (prog - cur) * 0.05;
        place(); renderer.render(scene, camera);
      };
      const start = () => { if (!raf && !reduce.matches && !document.hidden) { last = performance.now(); loop(); } };
      const stop = () => { cancelAnimationFrame(raf); raf = 0; };
      const onVis = () => (document.hidden ? stop() : start());
      document.addEventListener("visibilitychange", onVis);

      readProg(); cur = prog;
      applyTheme(); resize(); start();

      cleanup = () => {
        stop(); mo.disconnect(); mq.removeEventListener("change", applyTheme); document.removeEventListener("visibilitychange", onVis);
        window.removeEventListener("scroll", onScroll); window.removeEventListener("resize", resize);
        window.removeEventListener("pointermove", onMove); window.removeEventListener("secureship:scan", onScan); window.removeEventListener("secureship:pulse", onPulse);
        scene.traverse((o) => { o.geometry?.dispose?.(); const m = o.material; (Array.isArray(m) ? m : m ? [m] : []).forEach((x) => x.dispose()); });
        tex.dispose(); renderer.dispose(); dom.remove();
      };
    })();
    return () => { dead = true; cleanup(); };
  }, []);
  return (<><div className="scene" ref={box} aria-hidden="true" /><div className="scrim" aria-hidden="true" /></>);
}
