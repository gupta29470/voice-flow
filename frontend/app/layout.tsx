import type { Metadata } from "next";
import Link from "next/link";
import { Geist, Geist_Mono } from "next/font/google";
import "./globals.css";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "VoiceFlow — Production-grade Voice AI platform",
  description:
    "VoiceFlow: AI voice agents for debt collection and banking calls. Configure workflows, place live calls, and inspect transcripts and latency metrics.",
};

function LogoMark() {
  return (
    <span className="flex h-7 w-7 items-center justify-center rounded-lg bg-indigo-500/15 ring-1 ring-indigo-500/40">
      <svg
        width="14"
        height="14"
        viewBox="0 0 24 24"
        fill="none"
        className="text-indigo-400"
        aria-hidden
      >
        <path
          d="M3 10v4M7 7v10M11 4v16M15 8v8M19 10v4"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
        />
      </svg>
    </span>
  );
}

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html
      lang="en"
      className={`${geistSans.variable} ${geistMono.variable} h-full antialiased`}
    >
      <body className="flex min-h-full flex-col">
        <header className="sticky top-0 z-20 border-b border-white/5 bg-zinc-950/80 backdrop-blur">
          <div className="mx-auto flex h-14 max-w-7xl items-center justify-between px-4 sm:px-6">
            <Link href="/" className="flex items-center gap-2.5">
              <LogoMark />
              <span className="text-[15px] font-semibold tracking-tight text-zinc-50">
                VoiceFlow
              </span>
              <span className="hidden rounded-full border border-white/10 px-2 py-0.5 text-[11px] text-zinc-400 sm:inline-block">
                Production-grade Voice AI platform
              </span>
            </Link>
            <nav className="flex items-center gap-1 text-sm">
              <Link
                href="/"
                className="rounded-md px-3 py-1.5 text-zinc-300 transition-colors hover:bg-white/5 hover:text-zinc-50"
              >
                New Call
              </Link>
            </nav>
          </div>
        </header>
        <main className="mx-auto w-full max-w-7xl flex-1 px-4 py-8 sm:px-6">
          {children}
        </main>
        <footer className="border-t border-white/5 py-5">
          <p className="text-center text-xs text-zinc-600">
            VoiceFlow · AI voice agents for collections &amp; banking · Demo
          </p>
        </footer>
      </body>
    </html>
  );
}
