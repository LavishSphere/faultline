import type { ReactNode } from "react";
import type { Step } from "@/lib/steps";

export function ScreenHeader({ step, aside }: { step: Step; aside?: ReactNode }) {
  return (
    <header className="flex flex-col gap-6 lg:flex-row lg:items-end lg:justify-between lg:gap-16">
      <div className="min-w-0">
        <p className="kicker num">
          <span className="text-text-2">{String(step.index + 1).padStart(2, "0")}</span>
          <span className="mx-2 text-line-strong">/</span>
          {step.phase}
        </p>
        <h1 className="display mt-4 text-[clamp(3.5rem,8.5vw,8.5rem)] text-text">
          {step.titlePre ? <>{step.titlePre} </> : null}
          <em>{step.titleEm}</em>
        </h1>
      </div>
      <div className="flex max-w-xl flex-col gap-4 lg:items-end lg:pb-3 lg:text-right">
        <p className="text-base leading-relaxed text-text-2 md:text-[17px]">{step.lede}</p>
        {aside}
      </div>
    </header>
  );
}
