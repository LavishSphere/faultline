import type { ReactNode } from "react";

import { parseReply, type Align, type TableBlock } from "@/lib/replyMarkdown";

/**
 * The model's reply as text, with a minimal safe markdown subset (parsed in lib/replyMarkdown.ts): paragraphs, "-"/"*"
 * and "1." lists, "#" headings, "---" rules, GitHub-flavored tables, **bold** and `code`. Everything becomes React text
 * nodes (no HTML is parsed, no dangerouslySetInnerHTML), and every character of the reply is kept: numbers are shown
 * exactly as the model wrote them, never recomputed.
 */

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

const ALIGN_CLASS: Record<Exclude<Align, null>, string> = { left: "text-left", right: "text-right", center: "text-center" };

/** A GFM table from the reply. Scrolls inside its own box on narrow screens, so the page never scrolls sideways. */
function ReplyTable({ table, keyBase }: { table: TableBlock; keyBase: string }) {
  const cellClass = (c: number) => {
    const align = table.align[c] ?? (table.numeric[c] ? "right" : "left");
    const num = table.numeric[c] ? "whitespace-nowrap font-mono tabular-nums" : "min-w-[8ch]";
    return `${ALIGN_CLASS[align]} ${num} px-3 py-1.5 align-top first:pl-2 last:pr-2`;
  };
  return (
    <div
      className="max-w-full overflow-x-auto rounded-md border border-line focus-visible:outline-2 focus-visible:outline-accent"
      data-testid="chat-reply-table"
      role="region"
      aria-label="Table from the reply"
      tabIndex={0}
    >
      <table className="min-w-full border-collapse text-[0.9em] leading-snug [overflow-wrap:normal] [word-break:normal]">
        <thead className="bg-hover/60">
          <tr className="border-b border-line">
            {table.header.map((h, c) => (
              <th key={c} scope="col" className={`${cellClass(c)} font-medium text-text`}>
                {inline(h, `${keyBase}-h${c}`)}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {table.rows.map((r, ri) => (
            <tr key={ri} className="border-b border-line/60 last:border-b-0">
              {r.map((cell, c) => (
                <td key={c} className={cellClass(c)}>
                  {inline(cell, `${keyBase}-${ri}-${c}`)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
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
        if (b.kind === "hr") return <hr key={bi} className="border-line" />;
        if (b.kind === "table") return <ReplyTable key={bi} table={b} keyBase={`t${bi}`} />;
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
          <ol key={bi} start={b.start} className="flex list-decimal flex-col gap-1 pl-6 marker:font-mono marker:text-muted">
            {items}
          </ol>
        );
      })}
    </div>
  );
}
