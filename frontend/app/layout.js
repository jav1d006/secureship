import "./globals.css";
export const metadata = { title: "SecureShip", description: "Open-source security scanner" };
export default function RootLayout({ children }) {
  return (<html lang="en"><body>{children}</body></html>);
}
