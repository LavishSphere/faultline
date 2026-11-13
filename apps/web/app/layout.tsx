import type { Metadata, Viewport } from "next";
import Link from "next/link";
import { GeistMono } from "geist/font/mono";
import { GeistSans } from "geist/font/sans";
import localFont from "next/font/local";
import "./globals.css";
import { HealthChip } from "@/components/HealthChip";
import { HealthProvider } from "@/components/HealthProvider";
import { KeyNav } from "@/components/KeyNav";
import { ProvenanceBadge } from "@/components/ProvenanceBadge";
import { ReplayTimeline } from "@/components/ReplayTimeline";
import { ThemeToggle } from "@/components/ThemeToggle";
import { THEME_STORAGE_KEY } from "@/lib/theme";

// Instrument Serif (SIL OFL 1.1, see app/fonts/instrument-serif/OFL.txt) is vendored, so a clean build
// needs no network and no font CDN is contacted at runtime. Geist / Geist Mono come from the `geist` package.
const instrumentSerif = localFont({
  src: [
    { path: "./fonts/instrument-serif/instrument-serif-latin-400-normal.woff2", weight: "400", style: "normal" },
    { path: "./fonts/instrument-serif/instrument-serif-latin-400-italic.woff2", weight: "400", style: "italic" },
  ],
  variable: "--font-instrument-serif",
  display: "swap",
  fallback: ["ui-serif", "Georgia", "serif"],
});

export const metadata: Metadata = {
  title: { default: "FAULTLINE", template: "%s · FAULTLINE" },
  description: "Test the decision before you live with it. Point-in-time replay and deterministic financial stress testing.",
};

export const viewport: Viewport = {
  themeColor: [
    { media: "(prefers-color-scheme: dark)", color: "#0a0e17" },
    { media: "(prefers-color-scheme: light)", color: "#f8fafc" },
  ],
  width: "device-width",
  initialScale: 1,
};

// Applies a stored theme choice before first paint (no flash). Static, no data.
const themeScript = `try{var t=localStorage.getItem(${JSON.stringify(THEME_STORAGE_KEY)});if(t==="light"||t==="dark")document.documentElement.setAttribute("data-theme",t)}catch(e){}`;

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html
      lang="en"
      suppressHydrationWarning
      className={`${GeistSans.variable} ${GeistMono.variable} ${instrumentSerif.variable}`}
    >
      <head>
        <script dangerouslySetInnerHTML={{ __html: themeScript }} />
      </head>
      <body className="min-h-dvh overflow-x-hidden">
        <a
          href="#main"
          className="sr-only z-50 rounded-md bg-accent px-3 py-2 font-mono text-xs uppercase text-bg focus:not-sr-only focus:fixed focus:left-3 focus:top-3"
        >
          Skip to content
        </a>
        <HealthProvider>
          <div className="flex min-h-dvh flex-col">
            <div className="sticky top-0 z-40 bg-bg/75 backdrop-blur-[12px]">
              <header className="border-b border-line">
                <div className="mx-auto flex w-full max-w-[1760px] items-center justify-between gap-3 px-4 py-3 md:px-10">
                  <div className="flex min-w-0 items-center gap-4 md:gap-6">
                    <Link
                      href="/rewind"
                      className="flex items-center gap-2.5 rounded-sm"
                      aria-label="FAULTLINE, go to first screen"
                    >
                      <span
                        aria-hidden="true"
                        className="relative block size-4 overflow-hidden rounded-sm border border-text-2"
                      >
                        <span className="absolute left-[-30%] top-1/2 h-px w-[160%] -rotate-[28deg] bg-accent" />
                      </span>
                      <span className="font-mono text-[13px] font-medium tracking-[0.28em] text-text">FAULTLINE</span>
                    </Link>
                    <span className="hidden h-4 w-px bg-line md:block" aria-hidden="true" />
                    <div className="hidden items-center gap-2 md:flex">
                      <span className="kicker">Case</span>
                      <ProvenanceBadge kind="NOT AVAILABLE" detail="No case loaded" />
                    </div>
                  </div>
                  <div className="flex min-w-0 items-center gap-2">
                    <HealthChip />
                    <ThemeToggle />
                  </div>
                </div>
              </header>
              <ReplayTimeline />
            </div>
            <main id="main" className="flex flex-1 flex-col">
              {children}
            </main>
          </div>
        </HealthProvider>
        <KeyNav />
      </body>
    </html>
  );
}
