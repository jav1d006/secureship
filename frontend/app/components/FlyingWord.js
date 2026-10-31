"use client";
import { useEffect, useRef, useState } from "react";

// The letters of "DevSecOps" fly in from every direction (random angle, depth, spin, blur) and lock into place.
// Dev / Sec / Ops are coloured as the three disciplines. Click the word to replay it. Skipped for prefers-reduced-motion.
const GROUPS = [["Dev", "g-dev"], ["Sec", "g-sec"], ["Ops", "g-ops"]];

export default function FlyingWord() {
  const root = useRef(null);
  const [run, setRun] = useState(0);

  useEffect(() => {
    const el = root.current;
    if (!el || window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    const letters = [...el.querySelectorAll(".fl")];
    const reach = Math.max(window.innerWidth, window.innerHeight);
    const rnd = (n) => (Math.random() - 0.5) * 2 * n;
    const html = document.documentElement;
    const prev = html.style.overflow;
    html.style.overflow = "hidden";       // flying letters start outside the viewport; do not flash scrollbars
    el.classList.remove("landed");

    const anims = letters.map((l, i) => {
      const a = Math.random() * Math.PI * 2, d = reach * (0.55 + Math.random() * 0.7);
      return l.animate([
        { transform: `translate3d(${Math.cos(a) * d}px, ${Math.sin(a) * d}px, ${-500 - Math.random() * 700}px) rotateX(${rnd(540)}deg) rotateY(${rnd(540)}deg) rotateZ(${rnd(300)}deg) scale(${2.2 + Math.random() * 2.5})`, opacity: 0, filter: "blur(16px)" },
        { opacity: 1, filter: "blur(2px)", offset: 0.6 },
        { transform: "translate3d(0, 0, 70px) rotateX(0) rotateY(0) rotateZ(0) scale(1.12)", filter: "blur(0)", offset: 0.86 },
        { transform: "none", opacity: 1, filter: "blur(0)" },
      ], { duration: 1500 + Math.random() * 600, delay: i * 85, easing: "cubic-bezier(.22,.8,.24,1)", fill: "backwards" });
    });
    const done = Promise.all(anims.map((a) => a.finished)).then(() => { el.classList.add("landed"); html.style.overflow = prev; }).catch(() => {});
    return () => { anims.forEach((a) => a.cancel()); html.style.overflow = prev; void done; };
  }, [run]);

  let n = 0;
  return (
    <div ref={root} className="flying" role="img" aria-label="DevSecOps" onClick={() => setRun((r) => r + 1)} title="Click to replay">
      {GROUPS.map(([word, cls]) => (
        <span key={word} className={`fg ${cls}`} aria-hidden="true">
          {[...word].map((ch) => <span key={n} className="fl" style={{ "--i": n++ }}>{ch}</span>)}
        </span>
      ))}
    </div>
  );
}
