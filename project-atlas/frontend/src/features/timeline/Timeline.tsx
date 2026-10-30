import { useMemo, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { usePQuery } from "../../app/hooks";
import { Badge, Card, Empty, ErrorBox, Field, Notice, PageHeader, Spinner, Table } from "../../components/ui";
import { Chart } from "../../components/Chart";

export function TimelinePage() {
  const nav = useNavigate();
  const [params] = useSearchParams();
  const [tz, setTz] = useState(() => Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC");
  const [range, setRange] = useState({ start: "", end: "" });
  const [cats, setCats] = useState<string[]>([]);
  const [gap, setGap] = useState(0);
  const [cmp, setCmp] = useState({ a: params.get("entity") ?? "", b: "", window: 86400 });
  const entity = params.get("entity");
  const tl = usePQuery<any>(["timeline"], "/timeline", {
    tz, start: range.start ? `${range.start}T00:00:00Z` : undefined, end: range.end ? `${range.end}T23:59:59Z` : undefined,
    category: cats, entity_id: entity ?? undefined, cluster_gap_seconds: gap || undefined, limit: 2000 });
  const compare = usePQuery<any>(["timeline-compare", cmp], "/timeline/compare", { entity_a: cmp.a, entity_b: cmp.b, window_seconds: cmp.window }, !!cmp.a && !!cmp.b);
  const option = useMemo(() => {
    const evs = tl.data?.events ?? [];
    const categories: string[] = tl.data?.categories ?? [];
    return {
      tooltip: { trigger: "item", formatter: (p: any) => `${p.data[2]}<br/>${p.data[0]}` },
      xAxis: { type: "time" }, yAxis: { type: "category", data: categories },
      dataZoom: [{ type: "inside" }, { type: "slider", height: 16, bottom: 6 }],
      grid: { left: 90, right: 16, top: 16, bottom: 50 },
      series: [{ type: "scatter", symbolSize: 7, data: evs.map((e: any) => [e.event_time, e.category, e.title]) }],
    };
  }, [tl.data]);
  return (
    <div className="space-y-3">
      <PageHeader title="Timeline" subtitle="Event time (UTC, displayed in your chosen zone). Record creation, ingestion and modification times are tracked separately." />
      <div className="flex flex-wrap items-end gap-2">
        <Field label="Display time zone"><input className="input w-44" value={tz} onChange={(e) => setTz(e.target.value)} /></Field>
        <Field label="From"><input className="input" type="date" value={range.start} onChange={(e) => setRange({ ...range, start: e.target.value })} /></Field>
        <Field label="To"><input className="input" type="date" value={range.end} onChange={(e) => setRange({ ...range, end: e.target.value })} /></Field>
        <Field label="Categories"><select multiple className="input h-14 w-40" value={cats} onChange={(e) => setCats([...e.target.selectedOptions].map((o) => o.value))}>
          {(tl.data?.categories ?? []).map((c: string) => <option key={c}>{c}</option>)}</select></Field>
        <Field label="Cluster gap (hours, 0 = off)"><input className="input w-24" type="number" min={0} value={gap / 3600} onChange={(e) => setGap(Number(e.target.value) * 3600)} /></Field>
        {entity && <Badge tone="accent">filtered to entity {entity.slice(-8)} <button onClick={() => nav("/timeline")}>×</button></Badge>}
      </div>
      {tl.isLoading ? <Spinner /> : tl.error ? <ErrorBox error={tl.error} /> : !tl.data.events.length ? <Empty title="No events">Map a datetime field to events during ingestion to populate the timeline.</Empty> : (
        <>
          <Card title={<>{tl.data.events.length} events {tl.data.truncated && <Badge tone="warn">truncated</Badge>}</>}><Chart option={option as any} height={260} /></Card>
          {tl.data.clusters && <Card title={`${tl.data.clusters.length} clusters (gap ≤ ${gap / 3600} h)`} bodyClass="">
            <Table maxHeight={200} columns={["Start (UTC)", "End (UTC)", "Events", "Span"]} rows={tl.data.clusters.map((c: any) => [c.start, c.end, c.size, `${(c.span_seconds / 3600).toFixed(1)} h`])} /></Card>}
          {tl.data.relationships_in_window?.length > 0 && <Card title="Relationships active in window" bodyClass="">
            <Table maxHeight={200} columns={["Source", "Type", "Target", "Valid from", "Valid to"]} rows={tl.data.relationships_in_window.map((r: any) => [r.source, r.rel_type, r.target, r.valid_from, r.valid_to ?? "—"])} /></Card>}
          <Card title="Events" bodyClass="">
            <Table maxHeight={420} columns={["Event time (display)", "Title", "Category", "Entity", "Source text", "Source TZ", "Ingested", "Duration"]}
              rows={tl.data.events.map((e: any) => [e.event_time_display ?? e.event_time, e.title, <Badge>{e.category}</Badge>,
                e.entity_id ? <button className="text-accent hover:underline" onClick={() => nav(`/entities/${e.entity_id}`)}>{e.entity_name}</button> : "—",
                <code className="font-mono text-xxs">{e.source_time_text}</code>, e.source_timezone, e.ingested_at.slice(0, 19),
                e.duration_seconds != null ? `${(e.duration_seconds / 60).toFixed(0)} min` : "—"])} />
          </Card>
        </>
      )}
      <Card title="Compare two entities">
        <div className="flex flex-wrap items-end gap-2">
          <Field label="Entity A id"><input className="input w-72 font-mono" value={cmp.a} onChange={(e) => setCmp({ ...cmp, a: e.target.value })} /></Field>
          <Field label="Entity B id"><input className="input w-72 font-mono" value={cmp.b} onChange={(e) => setCmp({ ...cmp, b: e.target.value })} /></Field>
          <Field label="Window (hours)"><input className="input w-24" type="number" value={cmp.window / 3600} onChange={(e) => setCmp({ ...cmp, window: Number(e.target.value) * 3600 })} /></Field>
        </div>
        {compare.data && (
          <div className="mt-2 space-y-1 text-xs">
            <p>A: {compare.data.a ? `${compare.data.a.count} events ${compare.data.a.first} → ${compare.data.a.last}` : "no events"}</p>
            <p>B: {compare.data.b ? `${compare.data.b.count} events ${compare.data.b.first} → ${compare.data.b.last}` : "no events"}</p>
            <p>Overlap: {compare.data.activity_overlap ? `${compare.data.activity_overlap.start} → ${compare.data.activity_overlap.end}` : "none"} · {compare.data.co_occurrences.length} co-occurrences within window</p>
            <Notice tone="warn">{compare.data.note}</Notice>
          </div>
        )}
      </Card>
    </div>
  );
}
