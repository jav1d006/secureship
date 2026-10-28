import "./globals.css";

export const metadata = {
  title: "SecureShip — open-source security scanner",
  description: "Pick your scanners, upload a .zip, get a security score. Built by Javid Mamedov.",
  authors: [{ name: "Javid Mamedov" }],
};

export default function RootLayout({ children }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
