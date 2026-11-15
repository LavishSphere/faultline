import type { Step } from "@/lib/steps";
import { ChatPanel } from "./chat/ChatPanel";

/**
 * Screen F: LIVE EXPLORE, the home screen `/` and the first step, before the Blind Replay. The live engine-tool chat
 * ("Ask the engine", #186) is the whole screen and carries the page's h1. The legacy Tavily headline analyzer was
 * removed in #220. Separate from the Blind Replay.
 */
// eslint-disable-next-line @typescript-eslint/no-unused-vars
export function ExploreScreen({ step }: { step: Step }) {
  return <ChatPanel />;
}
