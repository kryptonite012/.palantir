import { useEffect, useRef } from "react";
import * as echarts from "echarts";
import { useAtlas } from "../app/store";

/** Thin ECharts wrapper that follows the Atlas theme and resizes with its container. */
export function Chart({ option, height = 240 }: { option: echarts.EChartsOption; height?: number }) {
  const ref = useRef<HTMLDivElement>(null);
  const theme = useAtlas((s) => s.theme);
  useEffect(() => {
    if (!ref.current) return;
    const chart = echarts.init(ref.current, undefined, { renderer: "canvas" });
    const css = getComputedStyle(document.documentElement);
    const c = (v: string) => `rgb(${css.getPropertyValue(v).trim().split(" ").join(",")})`;
    chart.setOption({
      backgroundColor: "transparent",
      textStyle: { color: c("--muted"), fontSize: 11 },
      color: [c("--accent"), c("--ok"), c("--warn"), c("--hypo"), c("--danger")],
      grid: { left: 48, right: 16, top: 24, bottom: 40 },
      tooltip: { trigger: "axis", backgroundColor: c("--panel"), borderColor: c("--line"), textStyle: { color: c("--ink") } },
      ...option,
    });
    const ro = new ResizeObserver(() => chart.resize());
    ro.observe(ref.current);
    return () => {
      ro.disconnect();
      chart.dispose();
    };
  }, [option, theme]);
  return <div ref={ref} style={{ height }} className="w-full" />;
}
