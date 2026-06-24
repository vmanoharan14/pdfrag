"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const links = [
  { href: "/", icon: "⌁", label: "Overview" },
  { href: "/chat", icon: "◫", label: "Chat" },
  { href: "/traces", icon: "⌘", label: "Traces" },
  { href: "/documents", icon: "▤", label: "Documents" },
  { href: "/search", icon: "⊙", label: "User Portal" },
];

export function SidebarNav() {
  const pathname = usePathname();

  return (
    <nav className="main-nav" aria-label="Main navigation">
      {links.map((link) => {
        const active =
          link.href === "/"
            ? pathname === "/"
            : pathname.startsWith(link.href.split("/demo")[0]);

        return (
          <Link className={active ? "active" : undefined} href={link.href} key={link.href}>
            <span className="nav-icon">{link.icon}</span>
            {link.label}
          </Link>
        );
      })}
    </nav>
  );
}
