import type { Metadata } from "next";
import { Fraunces, IBM_Plex_Mono, Newsreader } from "next/font/google";
import { NavRail } from "./components/NavRail";
import "./globals.css";
import layoutStyles from "./layout.module.css";

const fraunces = Fraunces({
  variable: "--font-fraunces",
  subsets: ["latin"],
  style: ["normal", "italic"],
});

const newsreader = Newsreader({
  variable: "--font-newsreader",
  subsets: ["latin"],
  style: ["normal", "italic"],
});

const plexMono = IBM_Plex_Mono({
  variable: "--font-plex-mono",
  subsets: ["latin"],
  weight: ["400", "500"],
});

export const metadata: Metadata = {
  title: "ALAM — a reading companion",
  description: "A private, voice-driven reading journal with spoiler-safe insights.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html
      lang="en"
      className={`${fraunces.variable} ${newsreader.variable} ${plexMono.variable}`}
    >
      <body>
        <div className={layoutStyles.shell}>
          <NavRail />
          <main className={layoutStyles.content}>{children}</main>
        </div>
      </body>
    </html>
  );
}
