import type { Metadata } from "next";
import Link from "next/link";

import { SidebarNav } from "./components/sidebar-nav";
import "./globals.css";

export const metadata: Metadata = {
  title: "PDFRAG Console",
  description: "Inspectable enterprise document retrieval",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body>
        <div className="app-shell">
          <aside className="sidebar">
            <Link className="brand" href="/">
              <span className="brand-mark">P</span>
              <span>
                <strong>PDFRAG</strong>
                <small>Local console</small>
              </span>
            </Link>

            <SidebarNav />

            <div className="sidebar-note">
              <span className="pulse" />
              <div>
                <strong>Local mode</strong>
                <p>Full trace visibility enabled</p>
              </div>
            </div>
          </aside>

          <main className="main-content">{children}</main>
        </div>
      </body>
    </html>
  );
}
