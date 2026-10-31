"use client";
import { useEffect, useRef } from "react";

// A stack of cargo containers. Idle: slowly turning. Scanning: a laser plane sweeps through it.
// Done: containers are tinted by what the scan found (green = clean, red/orange/amber = findings).
const COLS = 3, ROWS = 2, LAYERS = 3, SIZE = [1.7, 0.7, 0.7], GAP = 0.06;

const css = (name, fallback) => getComputedStyle(document.documentElement).getPropertyValue(name).trim() || fallback;

function pickTints(counts, total) {
  const order = ["critical", "high", "medium", "low"];
  const sum = order.reduce((n, k) => n + (counts[k] || 0), 0);
  const tints = Array(total).fill("ok");
  if (!sum) return tints;
  let slot = 0;
  // Scatter deterministically so the colours do not form one solid block.
  const scatter = Array.from({ length: total }, (_, i) => (i * 7) % total);
  for (const k of order) {
    const n = counts[k] ? Math.min(total - slot, Math.max(1, Math.round((counts[k] / sum) * Math.min(total - 2, sum)))) : 0;
    for (let i = 0; i < n && slot < total; i++) tints[scatter[slot++]] = k;
  }
  return tints;
}

export default function Cargo({ state = "idle", counts = {} }) {
  const host = useRef(null);
  const api = useRef(null);
  const latest = useRef({ state, counts });
  latest.current = { state, counts };

  useEffect(() => {
    let dead = false, raf = 0, cleanup = () => {};
    (async () => {
      let THREE;
      try { THREE = await import("three"); } catch { return; }
      const el = host.current;
      if (dead || !el) return;
      let renderer;
      try { renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, powerPreference: "low-power" }); } catch { return; }
      renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
      el.appendChild(renderer.domElement);
      renderer.domElement.setAttribute("aria-hidden", "true");

      const scene = new THREE.Scene();
      const camera = new THREE.PerspectiveCamera(32, 1, 0.1, 50);
      camera.position.set(5.2, 3.7, 6.2);
      camera.lookAt(0, 0.1, 0);
      scene.add(new THREE.AmbientLight(0xffffff, 0.9));
      const sun = new THREE.DirectionalLight(0xffffff, 1.2);
      sun.position.set(4, 8, 5);
      scene.add(sun);

      const group = new THREE.Group();
      scene.add(group);
      const boxes = [];
      const geo = new THREE.BoxGeometry(...SIZE.map((v) => v - GAP));
      const edgeGeo = new THREE.EdgesGeometry(geo);
      for (let y = 0; y < LAYERS; y++) for (let z = 0; z < ROWS; z++) for (let x = 0; x < COLS; x++) {
        const mat = new THREE.MeshStandardMaterial({ roughness: 0.55, metalness: 0.1 });
        const mesh = new THREE.Mesh(geo, mat);
        mesh.position.set((x - (COLS - 1) / 2) * SIZE[0], (y - (LAYERS - 1) / 2) * SIZE[1], (z - (ROWS - 1) / 2) * SIZE[2]);
        const edges = new THREE.LineSegments(edgeGeo, new THREE.LineBasicMaterial({ transparent: true, opacity: 0.55 }));
        mesh.add(edges);
        group.add(mesh);
        boxes.push({ mesh, mat, edges, tint: "ok", flash: 0 });
      }

      const plane = new THREE.Mesh(new THREE.PlaneGeometry(4.6, 3.2),
        new THREE.MeshBasicMaterial({ transparent: true, opacity: 0.28, side: THREE.DoubleSide, depthWrite: false }));
      plane.rotation.x = Math.PI / 2;
      plane.visible = false;
      scene.add(plane);
      const planeEdge = new THREE.LineSegments(new THREE.EdgesGeometry(plane.geometry), new THREE.LineBasicMaterial());
      plane.add(planeEdge);

      const reduce = window.matchMedia("(prefers-reduced-motion: reduce)");
      let current = { state: "idle", counts: {} }, tints = [], t = 0, mx = 0, my = 0;
      const colors = {};

      const readTheme = () => {
        colors.base = new THREE.Color(css("--surface", "#f8f9f6")).lerp(new THREE.Color(css("--line", "#cdd6d1")), 0.55);
        colors.edge = new THREE.Color(css("--ink", "#0e1a17"));
        colors.seal = new THREE.Color(css("--seal", "#0b6b57"));
        for (const k of ["ok", "critical", "high", "medium", "low"]) colors[k] = new THREE.Color(css(`--${k === "critical" ? "crit" : k === "medium" ? "med" : k}`, "#888"));
        paint();
      };
      const paint = () => {
        boxes.forEach((b, i) => {
          const tint = current.state === "done" ? tints[i] : null;
          const shade = colors.base.clone().lerp(colors.seal, 0.16 + 0.14 * ((i * 37) % 11) / 10);
          b.mat.color.copy(tint ? colors[tint] : shade).lerp(colors.base, tint === "ok" ? 0.3 : tint ? 0.05 : 0);
          b.edges.material.color.copy(colors.edge);
        });
        plane.material.color.copy(colors.seal);
        planeEdge.material.color.copy(colors.seal);
        render();
      };
      const render = () => renderer.render(scene, camera);

      const resize = () => {
        const w = el.clientWidth || 300, h = el.clientHeight || 240;
        renderer.setSize(w, h, false);
        renderer.domElement.style.width = "100%"; renderer.domElement.style.height = "100%";
        camera.aspect = w / h;
        camera.updateProjectionMatrix();
        render();
      };
      const ro = new ResizeObserver(resize); ro.observe(el);
      const onMove = (e) => { const r = el.getBoundingClientRect(); mx = ((e.clientX - r.left) / r.width - 0.5); my = ((e.clientY - r.top) / r.height - 0.5); };
      window.addEventListener("pointermove", onMove, { passive: true });
      const mo = new MutationObserver(readTheme); mo.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
      const mq = window.matchMedia("(prefers-color-scheme: dark)"); mq.addEventListener("change", readTheme);

      api.current = (next) => {
        current = next;
        tints = pickTints(next.counts || {}, boxes.length);
        plane.visible = next.state === "scanning";
        paint();
      };

      const loop = () => {
        raf = requestAnimationFrame(loop);
        if (reduce.matches) return;
        t += 0.016;
        group.rotation.y += current.state === "scanning" ? 0.006 : 0.0025;
        group.rotation.x += ((my * 0.35) - group.rotation.x) * 0.05;
        camera.position.x += ((5.2 + mx * 1.4) - camera.position.x) * 0.05;
        camera.lookAt(0, 0.1, 0);
        if (current.state === "scanning") {
          const y = Math.sin(t * 1.6) * 1.15;
          plane.position.y = y;
          boxes.forEach((b) => { const d = Math.abs(b.mesh.getWorldPosition(plane.position.clone()).y - y); b.mat.emissive.copy(colors.seal).multiplyScalar(d < 0.45 ? 0.55 : 0); });
        } else boxes.forEach((b) => b.mat.emissive.setScalar(0));
        render();
      };

      readTheme(); resize();
      if (!reduce.matches) loop();

      cleanup = () => {
        cancelAnimationFrame(raf); ro.disconnect(); mo.disconnect(); mq.removeEventListener("change", readTheme);
        window.removeEventListener("pointermove", onMove);
        geo.dispose(); edgeGeo.dispose(); plane.geometry.dispose();
        boxes.forEach((b) => { b.mat.dispose(); b.edges.material.dispose(); });
        renderer.dispose(); renderer.domElement.remove();
        api.current = null;
      };
      api.current(latest.current);
    })();
    return () => { dead = true; cleanup(); };
  }, []);

  const key = `${state}:${counts.critical || 0}:${counts.high || 0}:${counts.medium || 0}:${counts.low || 0}`;
  useEffect(() => { api.current?.({ state, counts }); }, [key]); // eslint-disable-line react-hooks/exhaustive-deps
  return <div ref={host} className="cargo" />;
}
