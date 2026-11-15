import type { ReactNode } from "react";

/**
 * The model's reply as text, with a minimal safe markdown subset: paragraphs, "-"/"*" and "1." lists, "#" headings,
 * **bold** and `code`. Everything becomes React text nodes (no HTML is parsed, no dangerouslySetInnerHTML), and every
 * character of the reply is kept: numbers are shown exactly as the model wrote them, never recomputed.
 */

type Block =
  | { kind: "p"; lines: string[] }
  | { kind: "h"; text: string }
  | { kind: "ul" | "ol"; items: string[] };

const BULLET = /^\s*[-*•]\s+(.*)$/;
const NUMBERED = /^\s*\d{1,3}[.)]\s+(.*)$/;
const HEADING = /^\s{0,3}#{1,4}\s+(.*)$/;

export function parseReply(text: string): Block[] {
  const blocks: Block[] = [];
  let para: string[] | null = null;
  let list: { kind: "ul" | "ol"; items: string[] } | null = null;
  const flush = () => {
    if (para) blocks.push({ kind: "p", lines: para });
    if (list) blocks.push(list);
    para = null;
    list = null;
  };
  for (const line of text.replace(/\r\n?/g, "\n").split("\n")) {
    if (!line.trim()) {
      flush();
      continue;
    }
    const h = HEADING.exec(line);
    const b = BULLET.exec(line);
    const n = NUMBERED.exec(line);
    if (h) {
      flush();
      blocks.push({ kind: "h", text: h[1] ?? "" });
    } else if (b || n) {
      const kind = b ? "ul" : "ol";
      if (para) {
        blocks.push({ kind: "p", lines: para });
        para = null;
      }
      if (!list || list.kind !== kind) {
        if (list) blocks.push(list);
        list = { kind, items: [] };
      }
      list.items.push((b ?? n)?.[1] ?? "");
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
  }
  flush();
  return blocks;
}

function inline(text: string, keyBase: string): ReactNode[] {
  const out: ReactNode[] = [];
  const re = /(\*\*[^*\n]+\*\*|`[^`\n]+`)/g;
  let last = 0;
  let m: RegExpExecArray | null;
  let i = 0;
  while ((m = re.exec(text)) !== null) {
    if (m.index > last) out.push(text.slice(last, m.index));
    const tok = m[0];
    if (tok.startsWith("**")) {
      out.push(
        <strong key={`${keyBase}-${i}`} className="font-semibold text-text">
          {tok.slice(2, -2)}
        </strong>,
      );
    } else {
      out.push(
        <code key={`${keyBase}-${i}`} className="rounded-sm bg-hover px-1 py-px font-mono text-[0.9em] text-text">
          {tok.slice(1, -1)}
        </code>,
      );
    }
    last = m.index + tok.length;
    i += 1;
  }
  if (last < text.length) out.push(text.slice(last));
  return out;
}

export function ReplyText({ text, className = "" }: { text: string; className?: string }) {
  const blocks = parseReply(text);
  return (
    <div
      className={`flex min-w-0 flex-col gap-3 break-words text-[15px] leading-relaxed text-text-2 [overflow-wrap:anywhere] md:text-base 2xl:text-[17px] ${className}`}
      data-testid="chat-reply"
    >
      {blocks.map((b, bi) => {
        if (b.kind === "h") {
          return (
            <p key={bi} className="font-medium text-text">
              {inline(b.text, `h${bi}`)}
            </p>
          );
        }
        if (b.kind === "p") {
          return (
            <p key={bi}>
              {b.lines.map((l, li) => (
                <span key={li}>
                  {li > 0 ? <br /> : null}
                  {inline(l, `p${bi}-${li}`)}
                </span>
              ))}
            </p>
          );
        }
        const items = b.items.map((it, ii) => (
          <li key={ii} className="pl-1">
            {inline(it, `l${bi}-${ii}`)}
          </li>
        ));
        return b.kind === "ul" ? (
          <ul key={bi} className="flex list-disc flex-col gap-1 pl-5 marker:text-accent">
            {items}
          </ul>
        ) : (
          <ol key={bi} className="flex list-decimal flex-col gap-1 pl-6 marker:font-mono marker:text-muted">
            {items}
          </ol>
        );
      })}
    </div>
  );
}
