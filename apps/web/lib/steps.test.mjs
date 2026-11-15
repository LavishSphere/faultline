// Presenter order: `/` is Live Explore (the home screen); the five Blind Replay screens follow, unchanged in order.
import assert from "node:assert/strict";
import { test } from "node:test";
import { HOME_STEP, PHASES, STEPS, findStep, sectionSteps, stepFromPath, stepHref } from "./steps.ts";

test("home `/` is Live Explore, and /explore resolves to the same step", () => {
  assert.equal(HOME_STEP.slug, "explore");
  assert.equal(stepFromPath("/")?.slug, "explore");
  assert.equal(stepFromPath("/explore/")?.slug, "explore");
  assert.equal(stepHref(HOME_STEP), "/explore");
});

test("every Blind Replay screen keeps its own route, in presenter order", () => {
  assert.deepEqual(
    sectionSteps("replay").map((s) => s.slug),
    ["rewind", "decision", "cascade", "reveal", "research"],
  );
  for (const slug of ["rewind", "decision", "cascade", "reveal", "research"]) {
    assert.equal(stepFromPath(`/${slug}/`)?.slug, slug);
  }
  assert.equal(stepFromPath("/nope/"), undefined);
});

test("indices are the array positions, so ← / → walk Explore then the replay", () => {
  STEPS.forEach((s, i) => assert.equal(s.index, i));
  assert.deepEqual(sectionSteps("live").map((s) => s.slug), ["explore"]);
  assert.equal(STEPS[1]?.slug, "rewind");
  assert.equal(findStep("research")?.index, STEPS.length - 1);
});

test("phases are listed in the order their steps appear", () => {
  const seen = [...new Set(STEPS.map((s) => s.phase))];
  assert.deepEqual(seen, [...PHASES]);
});
