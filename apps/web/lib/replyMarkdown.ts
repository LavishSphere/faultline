/**
 * Block parser for the model's chat reply (rendered by components/explore/chat/ReplyText.tsx). A minimal safe markdown
 * subset: paragraphs, "-"/"*" and "1." lists, "#" headings, "---" rules and GitHub-flavored tables. It only splits the
 * text into blocks; it never computes, rounds or reorders anything, and every character of every cell is kept as the
 * model wrote it. If parsing throws for any reason, the reply falls back to plain paragraphs.
 */

export type Align = "left" | "right" | "center" | null;

export type TableBlock = {
  kind: "table";
  header: string[];
  /** Alignment as written in the separator row (":--", "--:", ":-:"); null where the model gave none. */
  align: Align[];
  /** True where every non-empty body cell of the column reads as a number (rendered right-aligned, mono). */
  numeric: boolean[];
  rows: string[][];
};

export type Block =
  | { kind: "p"; lines: string[] }
  | { kind: "h"; text: string }
  | { kind: "hr" }
  | { kind: "ul"; items: string[] }
  | { kind: "ol"; items: string[]; start: number }
  | TableBlock;

const BULLET = /^\s*[-*•]\s+(.*)$/;
const NUMBERED = /^\s*(\d{1,3})[.)]\s+(.*)$/;
const HEADING = /^\s{0,3}#{1,4}\s+(.*)$/;
const RULE = /^\s{0,3}([-*_])(?:\s*\1){2,}\s*$/;
const SEP_CELL = /^:?-+:?$/;
// A number as a model writes one in a table: 102, -256, −1,234.5, $12k, 40%, (3.2), +0.4pp, 1.2x, 12 wk, ~5.
const NUMERIC = /^[~≈<>]?[(+\-−]?[$€£]?\d[\d,]*(?:\.\d+)?\s?(?:%|pp|bp|bps|x|[kKmMbB]|bn|mo|wk|wks|weeks?|months?)?\)?$/;
const EMPTYISH = /^(?:|—|–|-|n\/a|N\/A)$/;

/**
 * Split one table row into cells. A leading and trailing "|" are optional. "\|" is a literal pipe, and a pipe inside a
 * `code span` does not split, so text such as `a|b` survives. Returns null when the line has no unescaped pipe.
 */
export function splitRow(line: string): string[] | null {
  const s = line.trim();
  const cells: string[] = [];
  let cur = "";
  let inCode = false;
  let pipes = 0;
  for (let i = 0; i < s.length; i += 1) {
    const ch = s[i];
    if (ch === "\\" && s[i + 1] === "|") {
      cur += "|";
      i += 1;
    } else if (ch === "`") {
      inCode = !inCode;
      cur += ch;
    } else if (ch === "|" && !inCode) {
      pipes += 1;
      cells.push(cur);
      cur = "";
    } else {
      cur += ch;
    }
  }
  cells.push(cur);
  if (pipes === 0) return null;
  if (s.startsWith("|")) cells.shift();
  if (s.endsWith("|") && !s.endsWith("\\|") && cells.length > 0) cells.pop();
  return cells.map((c) => c.trim());
}

/** The alignments of a separator row such as "|:---|---:|:-:|", or null when the line is not one. */
export function parseSeparator(line: string): Align[] | null {
  if (!line.includes("-")) return null;
  const cells = splitRow(line);
  if (!cells || cells.length === 0) return null;
  const out: Align[] = [];
  for (const c of cells) {
    const t = c.replace(/\s+/g, "");
    if (!SEP_CELL.test(t)) return null;
    const l = t.startsWith(":");
    const r = t.endsWith(":");
    out.push(l && r ? "center" : r ? "right" : l ? "left" : null);
  }
  return out;
}

export function isNumericCell(cell: string): boolean {
  const t = cell.replace(/\*\*/g, "").replace(/`/g, "").trim();
  return NUMERIC.test(t);
}

/**
 * Try to read a GFM table starting at lines[i]: a header row, a separator row with the same number of cells, then body
 * rows until a blank line or a line without a pipe. Ragged body rows are padded with empty cells; a row with extra
 * cells widens the table (extra header cells are empty) so no text is dropped.
 */
export function parseTableAt(lines: string[], i: number): { block: TableBlock; next: number } | null {
  const header = splitRow(lines[i] ?? "");
  const align = parseSeparator(lines[i + 1] ?? "");
  if (!header || !align || header.length !== align.length) return null;
  const rows: string[][] = [];
  let j = i + 2;
  while (j < lines.length) {
    const line = lines[j] ?? "";
    if (!line.trim()) break;
    const cells = splitRow(line);
    if (!cells) break;
    rows.push(cells);
    j += 1;
  }
  const width = Math.max(header.length, ...rows.map((r) => r.length));
  const pad = (r: string[]) => [...r, ...Array<string>(width - r.length).fill("")];
  const paddedRows = rows.map(pad);
  const numeric = Array.from({ length: width }, (_, c) => {
    const vals = paddedRows.map((r) => r[c] ?? "").filter((v) => !EMPTYISH.test(v.trim()));
    return vals.length > 0 && vals.every(isNumericCell);
  });
  return {
    block: {
      kind: "table",
      header: pad(header),
      align: [...align, ...Array<Align>(width - align.length).fill(null)],
      numeric,
      rows: paddedRows,
    },
    next: j,
  };
}

function parseBlocks(text: string): Block[] {
  const blocks: Block[] = [];
  let para: string[] | null = null;
  let list: Extract<Block, { kind: "ul" | "ol" }> | null = null;
  const flush = () => {
    if (para) blocks.push({ kind: "p", lines: para });
    if (list) blocks.push(list);
    para = null;
    list = null;
  };
  const lines = text.replace(/\r\n?/g, "\n").split("\n");
  let i = 0;
  while (i < lines.length) {
    const line = lines[i] ?? "";
    if (!line.trim()) {
      flush();
      i += 1;
      continue;
    }
    if (line.includes("|")) {
      const table = parseTableAt(lines, i);
      if (table) {
        flush();
        blocks.push(table.block);
        i = table.next;
        continue;
      }
    }
    const h = HEADING.exec(line);
    const b = BULLET.exec(line);
    const n = NUMBERED.exec(line);
    if (h) {
      flush();
      blocks.push({ kind: "h", text: h[1] ?? "" });
    } else if (RULE.test(line)) {
      flush();
      blocks.push({ kind: "hr" });
    } else if (b || n) {
      const kind = b ? "ul" : "ol";
      if (para) {
        blocks.push({ kind: "p", lines: para });
        para = null;
      }
      if (!list || list.kind !== kind) {
        if (list) blocks.push(list);
        // An ordered list keeps the number the model wrote, so "2." after a nested bullet or a blank line stays 2.
        list = kind === "ul" ? { kind, items: [] } : { kind, items: [], start: Number(n?.[1] ?? 1) };
      }
      list.items.push((b ? b[1] : n?.[2]) ?? "");
    } else if (list && /^\s{2,}\S/.test(line)) {
      // An indented continuation of the previous list item.
      list.items[list.items.length - 1] += ` ${line.trim()}`;
    } else {
      if (list) {
        blocks.push(list);
        list = null;
      }
      (para ??= []).push(line);
    }
    i += 1;
  }
  flush();
  return blocks;
}

/** Split a reply into blocks. Never throws: on any parser error the reply is shown as plain paragraphs. */
export function parseReply(text: string): Block[] {
  try {
    return parseBlocks(text);
  } catch {
    return text
      .replace(/\r\n?/g, "\n")
      .split(/\n\s*\n/)
      .filter((p) => p.trim())
      .map((p) => ({ kind: "p" as const, lines: p.split("\n") }));
  }
}
