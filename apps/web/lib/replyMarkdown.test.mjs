// The chat reply's block parser (#241): GFM tables, lists and rules. Cell text is kept exactly as the model wrote it.
import assert from "node:assert/strict";
import { test } from "node:test";
import { isNumericCell, parseReply, parseSeparator, splitRow } from "./replyMarkdown.ts";

test("a GFM table becomes one table block with header, rows and numeric columns", () => {
  const blocks = parseReply("Here:\n| Option | P5 | P50 | P95 |\n|---|---|---|---|\n| Keep | -256 | 102 | 360 |\n| **Cut** | −1,200 | 40% | $3.2k |\n\nAfter.");
  assert.deepEqual(blocks.map((b) => b.kind), ["p", "table", "p"]);
  const t = blocks[1];
  assert.deepEqual(t.header, ["Option", "P5", "P50", "P95"]);
  assert.deepEqual(t.rows, [
    ["Keep", "-256", "102", "360"],
    ["**Cut**", "−1,200", "40%", "$3.2k"],
  ]);
  assert.deepEqual(t.align, [null, null, null, null]);
  assert.deepEqual(t.numeric, [false, true, true, true]);
});

test("separator alignment colons are read as left / right / center", () => {
  assert.deepEqual(parseSeparator("|:---|---:|:-:|---|"), ["left", "right", "center", null]);
  assert.deepEqual(parseSeparator(" :-- | --: "), ["left", "right"]);
  assert.equal(parseSeparator("| a | --- |"), null);
  assert.equal(parseSeparator("---"), null);
  const [t] = parseReply("a | b\n:-- | --:\n1 | 2");
  assert.equal(t.kind, "table");
  assert.deepEqual(t.align, ["left", "right"]);
});

test("ragged rows are padded, and extra cells widen the table instead of being dropped", () => {
  const [t] = parseReply("| A | B | C |\n|---|---|---|\n| 1 |\n| 1 | 2 | 3 | 4 |");
  assert.equal(t.kind, "table");
  assert.deepEqual(t.header, ["A", "B", "C", ""]);
  assert.deepEqual(t.rows, [
    ["1", "", "", ""],
    ["1", "2", "3", "4"],
  ]);
  assert.equal(t.align.length, 4);
});

test("escaped pipes and pipes inside code spans stay in the cell", () => {
  assert.deepEqual(splitRow("| a \\| b | `x|y` | c |"), ["a | b", "`x|y`", "c"]);
  const [t] = parseReply("| Rule | Value |\n|---|---|\n| `p|q` | a \\| b |");
  assert.deepEqual(t.rows, [["`p|q`", "a | b"]]);
});

test("a header and separator with different cell counts is not a table", () => {
  const blocks = parseReply("| A | B |\n|---|---|---|\n| 1 | 2 |");
  assert.deepEqual(blocks.map((b) => b.kind), ["p"]);
  assert.equal(blocks[0].lines.length, 3);
});

test("a prose line with pipes and no separator row stays a paragraph", () => {
  const text = "Range: P5 | P50 | P95 are -256 | 102 | 360.\nNext line.";
  const blocks = parseReply(text);
  assert.deepEqual(blocks, [{ kind: "p", lines: ["Range: P5 | P50 | P95 are -256 | 102 | 360.", "Next line."] }]);
  assert.equal(splitRow("no pipes here"), null);
});

test("a table ends at a blank line or a line without a pipe", () => {
  const blocks = parseReply("| A | B |\n|---|---|\n| 1 | 2 |\nPlain text after.");
  assert.deepEqual(blocks.map((b) => b.kind), ["table", "p"]);
  assert.equal(blocks[0].rows.length, 1);
});

test("numeric cells: signs, unicode minus, commas, %, currency, suffixes; words are not numbers", () => {
  for (const v of ["102", "-256", "−1,234.5", "$12k", "40%", "(3.2)", "+0.4pp", "1.2x", "12 wk", "**360**"]) assert.ok(isNumericCell(v), v);
  for (const v of ["Keep", "P50", "12 to 14", "n/a", ""]) assert.ok(!isNumericCell(v), v);
  const [t] = parseReply("| X | Y |\n|---|---|\n| a | — |\n| b | 5 |");
  assert.deepEqual(t.numeric, [false, true]);
});

test("numbered lists keep the number written after a nested bullet; bold leads stay inline text", () => {
  const blocks = parseReply("1. **Keep:** hold cash\n   - P50 102\n2. **Cut:** trim hiring");
  assert.deepEqual(blocks, [
    { kind: "ol", items: ["**Keep:** hold cash"], start: 1 },
    { kind: "ul", items: ["P50 102"] },
    { kind: "ol", items: ["**Cut:** trim hiring"], start: 2 },
  ]);
  assert.deepEqual(parseReply("**Bottom line:** keep payroll."), [{ kind: "p", lines: ["**Bottom line:** keep payroll."] }]);
});

test("a '---' line is a rule, not a stray paragraph", () => {
  assert.deepEqual(parseReply("A\n\n---\n\nB").map((b) => b.kind), ["p", "hr", "p"]);
});
