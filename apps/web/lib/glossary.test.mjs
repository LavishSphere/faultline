// Glossary labels must be the screens' exact text (PR #101 review): every `uiLabels` string has to appear in the
// apps/web source the screens are built from, so a label cannot silently drift when a screen's wording changes.
import assert from "node:assert/strict";
import { readFileSync, readdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { test } from "node:test";
import { fileURLToPath } from "node:url";
import { GLOSSARY } from "./glossary.ts";

const WEB = join(dirname(fileURLToPath(import.meta.url)), "..");
const SELF = join(WEB, "lib", "glossary.ts");

/** Every .ts/.tsx file under app/, components/ and lib/, except the glossary itself and tests. */
function sourceFiles(dir) {
  return readdirSync(dir, { withFileTypes: true }).flatMap((d) => {
    const p = join(dir, d.name);
    if (d.isDirectory()) return sourceFiles(p);
    return /\.tsx?$/.test(d.name) && !/\.test\./.test(d.name) && p !== SELF ? [p] : [];
  });
}

// JSX writes an apostrophe as &apos; and may wrap text across lines; the screen shows one space and a plain quote.
const decode = (s) =>
  s.replace(/&apos;/g, "'").replace(/&quot;/g, '"').replace(/&amp;/g, "&").replace(/\s+/g, " ");

const files = ["app", "components", "lib"].flatMap((d) => sourceFiles(join(WEB, d)));
const corpus = files.map((f) => decode(readFileSync(f, "utf8"))).join("\n");
const entries = Object.entries(GLOSSARY);

test("the scan covers the screens' source and leaves the glossary out", () => {
  assert.ok(files.length > 20, `only ${files.length} source files found`);
  assert.ok(!files.includes(SELF));
});

test("every entry has at least one uiLabel; none is blank or used by two entries", () => {
  const seen = new Map();
  for (const [term, e] of entries) {
    assert.ok(Array.isArray(e.uiLabels) && e.uiLabels.length > 0, `${term}: no uiLabels`);
    for (const label of e.uiLabels) {
      assert.equal(label, label.trim(), `${term}: label "${label}" has outer spaces`);
      assert.ok(label.length > 0, `${term}: blank label`);
      assert.ok(!seen.has(label), `"${label}" is a label of both ${seen.get(label)} and ${term}`);
      seen.set(label, term);
    }
  }
});

test("every uiLabels string appears verbatim in apps/web source", () => {
  const missing = entries.flatMap(([term, e]) => e.uiLabels.filter((l) => !corpus.includes(l)).map((l) => `${term}: "${l}"`));
  assert.deepEqual(missing, [], "labels not found on any screen's source; copy the current on-screen text");
});

test("docs/GLOSSARY.md has a section for every entry and the same count", () => {
  const md = readFileSync(join(WEB, "..", "..", "docs", "GLOSSARY.md"), "utf8").replace(/\r\n/g, "\n");
  for (const [term] of entries) assert.ok(md.includes(`\n### ${term}\n`), `docs/GLOSSARY.md has no section for ${term}`);
  assert.match(md, new RegExp(`\\n${entries.length} terms\\.\\n`));
});
