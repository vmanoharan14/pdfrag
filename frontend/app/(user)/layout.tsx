import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Benefits Search",
  description: "Search your benefits documents",
};

export default function UserLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return <div className="user-portal">{children}</div>;
}
