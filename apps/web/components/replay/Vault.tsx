import m from "./motion.module.css";

/**
 * Vault door glyph for the sealed outcome. Decorative (aria-hidden): the meaning is always carried by the text
 * beside it ("Sealed: the outcome is locked until reveal").
 */
export function Vault({ className = "", locked = true }: { className?: string; locked?: boolean }) {
  return (
    <svg viewBox="0 0 48 48" fill="none" aria-hidden="true" className={className}>
      <rect x="3.5" y="5.5" width="41" height="37" rx="4" stroke="currentColor" strokeWidth="1.5" />
      <rect x="1.5" y="12" width="3" height="6" rx="1" fill="currentColor" />
      <rect x="1.5" y="30" width="3" height="6" rx="1" fill="currentColor" />
      <circle cx="25" cy="24" r="12" stroke="currentColor" strokeWidth="1.5" />
      <circle cx="25" cy="24" r="8" stroke="currentColor" strokeOpacity="0.45" strokeWidth="1" strokeDasharray="2 2.5" />
      <g className={locked ? m.vaultLock : undefined}>
        <line x1="25" y1="15" x2="25" y2="33" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" />
        <line x1="16" y1="24" x2="34" y2="24" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" />
        <circle cx="25" cy="24" r="3" fill="currentColor" />
      </g>
      <line x1="8" y1="38.5" x2="14" y2="38.5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
    </svg>
  );
}
