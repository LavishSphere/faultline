"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { HOME_STEP, sectionSteps, stepFromPath, stepHref } from "@/lib/steps";

/**
 * Primary header nav: Explore (the product) first, then a small link into the Blind Replay (the proof). The five
 * replay steps are drawn by ReplayTimeline, only on replay pages. Navigation only: no dates or values.
 */
export function SiteNav() {
  const current = stepFromPath(usePathname());
  const onExplore = current?.section === "live";
  const onReplay = current?.section === "replay";
  const firstReplay = sectionSteps("replay")[0]!;
  return (
    <nav aria-label="Primary" className="flex min-w-0 items-center gap-1 md:gap-2">
      <Link
        href={stepHref(HOME_STEP)}
        aria-current={onExplore ? "step" : undefined}
        data-testid="nav-live-explore"
        className={`rounded-md px-2.5 py-1 text-sm font-medium transition-colors ${
          onExplore ? "bg-accent-soft text-text" : "text-text-2 hover:bg-hover hover:text-text"
        }`}
      >
        Explore
      </Link>
      <Link
        href={stepHref(firstReplay)}
        aria-current={onReplay ? "true" : undefined}
        data-testid="nav-blind-replay"
        aria-label="Blind Replay"
        className={`whitespace-nowrap rounded-md px-2 py-1 font-mono text-[11px] uppercase tracking-[0.12em] transition-colors ${
          onReplay ? "bg-hover text-text" : "text-muted hover:bg-hover hover:text-text"
        }`}
      >
        <span className="sm:hidden">Replay</span>
        <span className="hidden sm:inline">Blind Replay</span>
      </Link>
    </nav>
  );
}
