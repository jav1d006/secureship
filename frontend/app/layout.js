import "./globals.css";
import Header from "./components/Header";

export const metadata = {
  title: "SecureShip — open-source security scanner",
  description: "Upload a project, pick your scanners and get a security score with every finding explained.",
  authors: [{ name: "Javid Mamedov" }],
};

export default function RootLayout({ children }) {
  return (
    <html lang="en">
      <body>
        <a className="skip" href="#main">Skip to content</a>
        <Header />
        {children}
        <footer>
          <div className="wrap">
            <span>Designed &amp; built by <b>Javid Mamedov</b></span>
            <span>Open source · MIT · code is scanned statically and never executed</span>
          </div>
        </footer>
      </body>
    </html>
  );
}
