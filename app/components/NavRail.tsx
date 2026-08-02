"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useState } from "react";
import styles from "./NavRail.module.css";

const LINKS = [
  { href: "/", label: "Library" },
  { href: "/import", label: "Import" },
  { href: "/recommended", label: "Recommendations" },
  { href: "/profile", label: "Preferences" },
];

export function NavRail() {
  const pathname = usePathname();
  const router = useRouter();
  const [loggingOut, setLoggingOut] = useState(false);

  if (pathname === "/login") {
    return (
      <div className={styles.wordmarkOnly}>
        <span className={styles.wordmark}>ALAM</span>
      </div>
    );
  }

  async function handleLogout() {
    setLoggingOut(true);
    try {
      await fetch("/auth/logout", { method: "POST" });
    } finally {
      router.push("/login");
      router.refresh();
    }
  }

  return (
    <nav className={styles.rail}>
      <Link href="/" className={styles.wordmark}>
        ALAM
      </Link>
      <ul className={styles.links}>
        {LINKS.map((link) => {
          const active =
            link.href === "/"
              ? pathname === "/" || pathname.startsWith("/library")
              : pathname.startsWith(link.href);
          return (
            <li key={link.href}>
              <Link
                href={link.href}
                className={active ? `${styles.link} ${styles.linkActive}` : styles.link}
              >
                {link.label}
              </Link>
            </li>
          );
        })}
      </ul>
      <button type="button" className={styles.logout} onClick={handleLogout} disabled={loggingOut}>
        {loggingOut ? "Signing out…" : "Sign out"}
      </button>
    </nav>
  );
}
