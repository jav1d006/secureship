// Keep the CSP in sync with nginx/nginx.conf. Production only: `next dev` needs eval for hot reload.
const csp = [
  "default-src 'self'", "script-src 'self' 'unsafe-inline'", "style-src 'self' 'unsafe-inline'",
  "img-src 'self' data:", "font-src 'self'", "connect-src 'self'", "object-src 'none'",
  "base-uri 'none'", "form-action 'self'", "frame-ancestors 'none'",
].join("; ");

const securityHeaders = [
  { key: "Content-Security-Policy", value: csp },
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "X-Frame-Options", value: "DENY" },
  { key: "Referrer-Policy", value: "no-referrer" },
  { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=(), payment=(), usb=()" },
  { key: "Cross-Origin-Opener-Policy", value: "same-origin" },
  { key: "Cross-Origin-Resource-Policy", value: "same-origin" },
  { key: "Strict-Transport-Security", value: "max-age=63072000; includeSubDomains" },
];

module.exports = {
  output: "standalone",
  poweredByHeader: false,
  images: { unoptimized: true },
  async headers() {
    return process.env.NODE_ENV === "production" ? [{ source: "/:path*", headers: securityHeaders }] : [];
  },
};
