# Offline basemap assets

`ne_110m_countries.geojson` is derived from Natural Earth 1:110m Admin 0 Countries
(https://www.naturalearthdata.com/, public domain). Properties were reduced to `name`
and `iso_a3` and coordinates rounded to 3 decimals. It is served locally; Project
Atlas never fetches map tiles from the internet.

To use higher-detail local vector tiles, place them under `public/map/` and reference
them from the MapLibre style in `src/features/maps/basemap.ts` (see docs/offline-operation.md).
