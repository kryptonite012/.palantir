import type { StyleSpecification } from "maplibre-gl";

/** Fully offline MapLibre style: a locally served Natural Earth country layer, no tile servers or glyph URLs. */
export function offlineStyle(dark: boolean): StyleSpecification {
  return {
    version: 8,
    sources: { countries: { type: "geojson", data: "/map/ne_110m_countries.geojson" } },
    layers: [
      { id: "bg", type: "background", paint: { "background-color": dark ? "#0d1419" : "#dfe8ef" } },
      { id: "land", type: "fill", source: "countries", paint: { "fill-color": dark ? "#1b252e" : "#f5f7f9", "fill-outline-color": dark ? "#2f3d4a" : "#aab7c3" } },
      { id: "borders", type: "line", source: "countries", paint: { "line-color": dark ? "#33424f" : "#b9c5cf", "line-width": 0.6 } },
    ],
  };
}
