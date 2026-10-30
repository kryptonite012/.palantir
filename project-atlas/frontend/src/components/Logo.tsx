export function Logo({ compact = false }: { compact?: boolean }) {
  return (
    <div className="flex items-center gap-2">
      <img src="/atlas-icon.svg" alt="Project Atlas" className="h-7 w-7" />
      {!compact && (
        <div className="leading-tight">
          <div className="text-[13px] font-bold tracking-[0.18em]">ATLAS</div>
          <div className="text-[9px] uppercase tracking-[0.14em] text-muted">Navigate the complexity of data</div>
        </div>
      )}
    </div>
  );
}
