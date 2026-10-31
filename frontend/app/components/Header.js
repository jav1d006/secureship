"use client";
import { usePathname } from "next/navigation";
import Link from "next/link";

const LINKS = [["/", "Scan"], ["/history", "History"], ["/keys", "API keys"]];

export default function Header() {
  const path = usePathname();
  return (
    <header className="top">
      <div className="wrap">
        <Link href="/" className="brand">
          <span className="logo" aria-hidden>
            <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.6" strokeLinecap="round" strokeLinejoin="round"><path d="M12 3l8 3v6c0 5-3.4 8.4-8 9-4.6-.6-8-4-8-9V6l8-3z" /><path d="M9 12l2 2 4-4" /></svg>
          </span>
          SecureShip
        </Link>
        <nav className="nav" aria-label="Main">
          {LINKS.map(([href, label]) => (
            <Link key={href} href={href} aria-current={path === href ? "page" : undefined}>{label}</Link>
          ))}
        </nav>
        <a className="gh" href="https://github.com/jav1d006/secureship" rel="noopener noreferrer">GitHub</a>
      </div>
    </header>
  );
}
