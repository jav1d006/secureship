"use client";
import { useEffect, useState } from "react";

// Signature moment: DEVSECOPS resolves out of the dark (scale + blur + opacity, a short controlled glitch),
// while the 3D core sends out a light pulse. Pure CSS for the reveal, so it never blocks the app.
// Plays once per page load; moving between pages and back does not replay it.
let played = false;

export default function WordMark() {
  const [skip] = useState(() => played);
  useEffect(() => {
    if (played) return;
    const id = setTimeout(() => {
      played = true;
      window.__ssPulseAt = Date.now();
      window.dispatchEvent(new Event("secureship:pulse"));
    }, 560);
    return () => clearTimeout(id);
  }, []);
  return (
    <div className={skip ? "word done" : "word"} data-text="DEVSECOPS" role="img" aria-label="DevSecOps">
      DEV<b>SEC</b>OPS
    </div>
  );
}
