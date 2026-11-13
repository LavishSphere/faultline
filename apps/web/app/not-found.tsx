import Link from "next/link";

export default function NotFound() {
  return (
    <div className="mx-auto flex w-full max-w-[1760px] flex-1 flex-col justify-center gap-6 px-4 py-16 md:px-10">
      <p className="kicker">404</p>
      <h1 className="display text-[clamp(3rem,8vw,7rem)]">No such <em>screen</em></h1>
      <Link
        href="/rewind"
        className="w-fit rounded-md border border-line px-4 py-2 font-mono text-xs uppercase tracking-[0.16em] hover:border-line-strong"
      >
        Go to Rewind →
      </Link>
    </div>
  );
}
