"use client";
import { useEffect } from "react";

// Full-page 3D harbour behind the whole site. Scrolling flies the camera from high above the sea,
// past the ship, down between the container stacks. While a scan runs a laser sweeps the ship;
// when it finishes the ship's containers are tinted by what was found. Day or night follows the theme.

const css = (n, f) => getComputedStyle(document.documentElement).getPropertyValue(n).trim() || f;
const isDark = () => {
  const t = document.documentElement.getAttribute("data-theme");
  return t ? t === "dark" : window.matchMedia("(prefers-color-scheme: dark)").matches;
};
const rng = (seed) => { let s = seed; return () => (s = (s * 16807) % 2147483647) / 2147483647; };
const ease = (x) => x * x * (3 - 2 * x);
const KEYS = [
  { p: [-30, 16, 46], t: [6, 1, -8] },
  { p: [-10, 6, 18], t: [4, 3, -8] },
  { p: [1, 3.2, 9], t: [11, 4, -16] },
];

function tintsFor(counts, total) {
  const order = ["critical", "high", "medium", "low"];
  const sum = order.reduce((n, k) => n + (counts[k] || 0), 0);
  const out = Array(total).fill(null);
  if (!sum) return out;
  const scatter = Array.from({ length: total }, (_, i) => (i * 11) % total);
  let slot = 0;
  for (const k of order) {
    const n = counts[k] ? Math.min(total - slot, Math.max(1, Math.round((counts[k] / sum) * Math.min(total - 3, sum)))) : 0;
    for (let i = 0; i < n && slot < total; i++) out[scatter[slot++]] = k;
  }
  return out.map((v) => v || "ok");
}

export default function Harbor() {
  useEffect(() => {
    let dead = false, cleanup = () => {};
    (async () => {
      let THREE;
      try { THREE = await import("three"); } catch { return; }
      if (dead) return;
      const small = window.matchMedia("(max-width: 760px)").matches;
      const reduce = window.matchMedia("(prefers-reduced-motion: reduce)");
      let renderer;
      try { renderer = new THREE.WebGLRenderer({ antialias: !small, powerPreference: "low-power" }); } catch { return; }
      renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, small ? 1.25 : 1.6));
      const dom = renderer.domElement;
      dom.className = "harbor"; dom.setAttribute("aria-hidden", "true");
      document.body.prepend(dom);

      const scene = new THREE.Scene();
      const camera = new THREE.PerspectiveCamera(42, 1, 0.1, 400);
      const C = (h) => new THREE.Color(h);
      const R = rng(7);

      // sky dome (vertical gradient) + fog
      const skyMat = new THREE.ShaderMaterial({
        side: THREE.BackSide, depthWrite: false, fog: false,
        uniforms: { top: { value: C("#000") }, bot: { value: C("#fff") } },
        vertexShader: "varying float h; void main(){ h = normalize(position).y; gl_Position = projectionMatrix*modelViewMatrix*vec4(position,1.); }",
        fragmentShader: "uniform vec3 top; uniform vec3 bot; varying float h; void main(){ gl_FragColor = vec4(mix(bot, top, smoothstep(0.0, 0.65, h)), 1.); }",
      });
      scene.add(new THREE.Mesh(new THREE.SphereGeometry(200, 24, 16), skyMat));
      scene.fog = new THREE.Fog("#fff", 45, 190);

      const hemi = new THREE.HemisphereLight(0xffffff, 0x335566, 1);
      const sun = new THREE.DirectionalLight(0xffffff, 1);
      sun.position.set(-30, 40, 20);
      scene.add(hemi, sun);

      // sea
      const seg = small ? 36 : 64;
      const seaGeo = new THREE.PlaneGeometry(320, 320, seg, seg).rotateX(-Math.PI / 2);
      const seaMat = new THREE.MeshStandardMaterial({ roughness: 0.3, metalness: 0.15, flatShading: true });
      const sea = new THREE.Mesh(seaGeo, seaMat);
      scene.add(sea);
      const sp = seaGeo.attributes.position, sx = Float32Array.from(sp.array.filter((_, i) => i % 3 === 0)), sz = Float32Array.from(sp.array.filter((_, i) => i % 3 === 2));

      // dock + container stacks (instanced)
      const dock = new THREE.Mesh(new THREE.BoxGeometry(46, 2.4, 70), new THREE.MeshStandardMaterial({ color: "#6b7571", roughness: 0.9 }));
      dock.position.set(30, -0.4, -12);
      scene.add(dock);
      const boxGeo = new THREE.BoxGeometry(2.4, 1, 1);
      const palette = ["#b5372f", "#2f5fa5", "#2f8f5b", "#d98a1c", "#8a8f94", "#7a3f8f", "#c9c3b0"].map(C);
      const slots = [];
      for (let x = 10; x < 46; x += 2.6) for (let z = -42; z < 14; z += 1.25) {
        if (R() < 0.18) continue;
        const h = 1 + Math.floor(R() * (x < 22 ? 2 : 4));
        for (let y = 0; y < h; y++) slots.push([x, 0.8 + 0.5 + y, z]);
      }
      const stacks = new THREE.InstancedMesh(boxGeo, new THREE.MeshStandardMaterial({ roughness: 0.6 }), slots.length);
      const m4 = new THREE.Matrix4();
      slots.forEach((s, i) => { m4.setPosition(...s); stacks.setMatrixAt(i, m4); stacks.setColorAt(i, palette[Math.floor(R() * palette.length)]); });
      scene.add(stacks);

      // gantry cranes
      const craneMat = new THREE.MeshStandardMaterial({ color: "#e0a526", roughness: 0.5 });
      const beacons = [];
      for (const z of [-34, -18, -2]) {
        const g = new THREE.Group();
        for (const dz of [0, 4]) for (const dx of [0, 5]) { const leg = new THREE.Mesh(new THREE.BoxGeometry(0.45, 11, 0.45), craneMat); leg.position.set(dx, 5.5, dz); g.add(leg); }
        const beam = new THREE.Mesh(new THREE.BoxGeometry(24, 0.7, 0.8), craneMat); beam.position.set(-5, 11.2, 2); g.add(beam);
        const b = new THREE.Mesh(new THREE.SphereGeometry(0.28, 8, 8), new THREE.MeshBasicMaterial({ color: "#ff3b30" })); b.position.set(-17, 11.8, 2); g.add(b); beacons.push(b);
        g.position.set(9, 0.8, z);
        scene.add(g);
      }

      // ship
      const ship = new THREE.Group();
      const outline = new THREE.Shape([[-3.2, 15], [3.2, 15], [3.2, -8], [0, -17], [-3.2, -8]].map(([x, y]) => new THREE.Vector2(x, y)));
      const hull = new THREE.Mesh(new THREE.ExtrudeGeometry(outline, { depth: 2.4, bevelEnabled: false }).rotateX(Math.PI / 2),
        new THREE.MeshStandardMaterial({ color: "#7d2b25", roughness: 0.6 }));
      hull.position.y = 1.1;
      ship.add(hull);
      const deck = new THREE.Mesh(new THREE.BoxGeometry(6.2, 0.15, 22), new THREE.MeshStandardMaterial({ color: "#3b4a4a" }));
      deck.position.set(0, 1.15, 3.5);
      ship.add(deck);
      const shipBox = new THREE.BoxGeometry(1.15, 1, 2.4);
      const shipSlots = [];
      for (const x of [-1.25, 0, 1.25]) for (let z = -7.5; z <= 9; z += 2.5) { const h = 1 + Math.floor(R() * 3); for (let y = 0; y < h; y++) shipSlots.push([x, 1.75 + y, z]); }
      const cargo = new THREE.InstancedMesh(shipBox, new THREE.MeshStandardMaterial({ roughness: 0.6 }), shipSlots.length);
      shipSlots.forEach((s, i) => { m4.setPosition(...s); cargo.setMatrixAt(i, m4); cargo.setColorAt(i, palette[Math.floor(R() * palette.length)]); });
      ship.add(cargo);
      const white = new THREE.MeshStandardMaterial({ color: "#e8ece9", roughness: 0.7 });
      const cabin = new THREE.Mesh(new THREE.BoxGeometry(5.6, 4.4, 3), white); cabin.position.set(0, 3.4, 12.5); ship.add(cabin);
      const bridge = new THREE.Mesh(new THREE.BoxGeometry(5, 1.5, 2.2), white); bridge.position.set(0, 6.4, 12.7); ship.add(bridge);
      const glow = new THREE.MeshBasicMaterial({ color: "#ffd98a" });
      const wins = new THREE.Mesh(new THREE.BoxGeometry(5.1, 0.45, 2.3), glow); wins.position.set(0, 6.5, 12.75); ship.add(wins);
      const wins2 = new THREE.Mesh(new THREE.BoxGeometry(5.7, 0.35, 3.05), glow); wins2.position.set(0, 3.6, 12.5); ship.add(wins2);
      ship.position.set(1.6, 0, -6);
      scene.add(ship);

      // scan beam
      const beam = new THREE.Mesh(new THREE.PlaneGeometry(9, 6), new THREE.MeshBasicMaterial({ transparent: true, opacity: 0.35, side: THREE.DoubleSide, depthWrite: false }));
      beam.position.set(1.6, 4, -6); beam.visible = false;
      scene.add(beam);

      // clouds (day) and stars + moon (night)
      const clouds = new THREE.Group();
      const cloudMat = new THREE.MeshBasicMaterial({ color: "#ffffff", transparent: true, opacity: 0.85, fog: false });
      for (let i = 0; i < 7; i++) {
        const c = new THREE.Group();
        for (let j = 0; j < 4; j++) { const s = new THREE.Mesh(new THREE.SphereGeometry(1, 8, 6), cloudMat); s.scale.set(5 + R() * 4, 1.6 + R(), 3 + R() * 2); s.position.set(j * 4 - 6, R(), R() * 2); c.add(s); }
        c.position.set(-120 + i * 40, 38 + R() * 18, -90 - R() * 40);
        clouds.add(c);
      }
      scene.add(clouds);
      const starPos = new Float32Array(900 * 3);
      for (let i = 0; i < 900; i++) { const a = R() * Math.PI * 2, e = 0.12 + R() * 1.3, r = 190; starPos.set([r * Math.cos(e) * Math.cos(a), r * Math.sin(e), r * Math.cos(e) * Math.sin(a)], i * 3); }
      const starGeo = new THREE.BufferGeometry().setAttribute("position", new THREE.BufferAttribute(starPos, 3));
      const stars = new THREE.Points(starGeo, new THREE.PointsMaterial({ color: "#ffffff", size: 1.6, sizeAttenuation: false, fog: false, transparent: true, opacity: 0.9 }));
      scene.add(stars);
      const moon = new THREE.Mesh(new THREE.SphereGeometry(5, 16, 12), new THREE.MeshBasicMaterial({ color: "#e9eef7", fog: false }));
      moon.position.set(-90, 95, -150);
      scene.add(moon);

      // theme
      const sevCol = {};
      let dark = false;
      const applyTheme = () => {
        dark = isDark();
        const top = dark ? "#07122a" : "#7fb4dc", bot = dark ? "#244c75" : "#e6eef0";
        skyMat.uniforms.top.value.set(top); skyMat.uniforms.bot.value.set(bot);
        scene.fog.color.set(bot);
        seaMat.color.set(dark ? "#12405a" : "#3f8fa6");
        hemi.color.set(dark ? "#4a6fa5" : "#ffffff"); hemi.groundColor.set(dark ? "#06121c" : "#3a5566"); hemi.intensity = dark ? 1.0 : 1.05;
        sun.color.set(dark ? "#8fb0ff" : "#fff1d6"); sun.intensity = dark ? 1.0 : 1.6;
        clouds.visible = !dark; stars.visible = dark; moon.visible = dark;
        glow.visible = true; glow.color.set(dark ? "#ffd98a" : "#cfe3ee");
        beam.material.color.set(css("--seal", "#0b6b57"));
        for (const [k, v] of [["critical", "--crit"], ["high", "--high"], ["medium", "--med"], ["low", "--low"], ["ok", "--ok"]]) sevCol[k] = C(css(v, "#888"));
        recolor(); render();
      };

      let scan = window.__ssScan || { state: "idle", counts: {} }, tints = [];
      const recolor = () => {
        tints = scan.state === "done" ? tintsFor(scan.counts || {}, shipSlots.length) : [];
        const base = new THREE.Color();
        shipSlots.forEach((_, i) => {
          const t = tints[i];
          if (t) cargo.setColorAt(i, sevCol[t]);
          else { base.set(palette[Math.floor(rng(i + 3)() * palette.length)]); cargo.setColorAt(i, base); }
        });
        cargo.instanceColor.needsUpdate = true;
        beam.visible = scan.state === "scanning";
      };
      const onScan = (e) => { scan = e.detail; recolor(); render(); };
      window.addEventListener("secureship:scan", onScan);

      // camera
      let prog = 0, cur = 0, mx = 0, my = 0;
      const readProg = () => {
        const max = Math.max(500, document.documentElement.scrollHeight - window.innerHeight);
        prog = Math.min(1, Math.max(0, window.scrollY / max));
      };
      const place = () => {
        const x = Math.min(1, Math.max(0, cur)) * (KEYS.length - 1), i = Math.min(KEYS.length - 2, Math.floor(x)), f = ease(x - i);
        const a = KEYS[i], b = KEYS[i + 1];
        const L = (p, q) => p + (q - p) * f;
        camera.position.set(L(a.p[0], b.p[0]) + mx * 2.2, L(a.p[1], b.p[1]) - my * 1.2, L(a.p[2], b.p[2]));
        camera.lookAt(L(a.t[0], b.t[0]), L(a.t[1], b.t[1]), L(a.t[2], b.t[2]));
      };
      const render = () => { place(); renderer.render(scene, camera); };
      const resize = () => { renderer.setSize(window.innerWidth, window.innerHeight, false); camera.aspect = window.innerWidth / window.innerHeight; camera.updateProjectionMatrix(); render(); };
      const onScroll = () => { readProg(); if (reduce.matches) return; };
      const onMove = (e) => { mx = e.clientX / window.innerWidth - 0.5; my = e.clientY / window.innerHeight - 0.5; };
      window.addEventListener("scroll", onScroll, { passive: true });
      window.addEventListener("resize", resize);
      window.addEventListener("pointermove", onMove, { passive: true });
      const mo = new MutationObserver(applyTheme); mo.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
      const mq = window.matchMedia("(prefers-color-scheme: dark)"); mq.addEventListener("change", applyTheme);

      let raf = 0, t = 0, frames = 0, last = performance.now(), acc = 0, lowQuality = false;
      const loop = () => {
        raf = requestAnimationFrame(loop);
        const now = performance.now(); acc += now - last; last = now;
        if (++frames === 90 && acc / 90 > 45 && !lowQuality) { lowQuality = true; renderer.setPixelRatio(0.7); resize(); }   // slow GPU: render smaller, animate the sea less
        t += 0.016;
        if (!lowQuality || frames % 3 === 0) for (let i = 0; i < sx.length; i++) sp.setY(i, Math.sin(sx[i] * 0.09 + t * 0.9) * 0.28 + Math.sin(sz[i] * 0.13 + t * 1.2) * 0.22);
        sp.needsUpdate = true;
        ship.position.y = Math.sin(t * 0.8) * 0.07; ship.rotation.z = Math.sin(t * 0.6) * 0.012; ship.rotation.x = Math.sin(t * 0.5) * 0.008;
        clouds.position.x = ((t * 0.8) % 160) - 80;
        beacons.forEach((b, i) => { b.visible = !dark || Math.sin(t * 3 + i) > -0.2; });
        if (scan.state === "scanning") { beam.position.z = -6 + Math.sin(t * 1.5) * 12; }
        cur += (prog - cur) * 0.06;
        mx *= 0.995; // keeps parallax gentle when the pointer rests
        render();
      };

      readProg(); cur = reduce.matches ? 0 : prog;
      applyTheme(); resize();
      if (!reduce.matches) loop();

      cleanup = () => {
        cancelAnimationFrame(raf); mo.disconnect(); mq.removeEventListener("change", applyTheme);
        window.removeEventListener("scroll", onScroll); window.removeEventListener("resize", resize);
        window.removeEventListener("pointermove", onMove); window.removeEventListener("secureship:scan", onScan);
        scene.traverse((o) => { o.geometry?.dispose?.(); const m = o.material; (Array.isArray(m) ? m : m ? [m] : []).forEach((x) => x.dispose()); });
        renderer.dispose(); dom.remove();
      };
    })();
    return () => { dead = true; cleanup(); };
  }, []);
  return <div className="scrim" aria-hidden="true" />;
}
