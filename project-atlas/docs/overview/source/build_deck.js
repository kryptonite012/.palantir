// Build docs/overview/Project-Atlas-Presentation.pptx
//
// Requirements (install anywhere, then point NODE_PATH at that node_modules):
//   npm install pptxgenjs@3.12.0 react-icons@5.3.0 react@18.3.1 react-dom@18.3.1 sharp@0.33.5
//   NODE_PATH=/path/to/node_modules node docs/overview/source/build_deck.js
//
// Content mirrors the technical overview PDF; all figures come from the repository's docs and recorded results.

const path = require("path");
const fs = require("fs");
const pptxgen = require("pptxgenjs");
const React = require("react");
const ReactDOMServer = require("react-dom/server");
const sharp = require("sharp");
const fa = require("react-icons/fa");

const HERE = __dirname;
const REPO = path.resolve(HERE, "..", "..", "..");
const SHOTS = path.join(REPO, "docs", "screenshots");
const OUT = path.resolve(HERE, "..", "Project-Atlas-Presentation.pptx");

// ------------------------------------------------------------------------------------------- theme
const THEME = {
  name: "Project Atlas",
  headFontFace: "Calibri",
  bodyFontFace: "Calibri",
  colors: {
    dk1: "151B23", lt1: "FFFFFF", dk2: "5C6A78", lt2: "F1F4F7",
    accent1: "2B6FA0", accent2: "4FA3D9", accent3: "268456", accent4: "B07814", accent5: "8E5CBE", accent6: "BA3434",
    hlink: "2B6FA0", folHlink: "8E5CBE",
  },
};
const HEX = THEME.colors; // for image data and hex-only options

const pres = new pptxgen();
pres.layout = "LAYOUT_WIDE"; // 13.333 x 7.5 in
pres.theme = { headFontFace: THEME.headFontFace, bodyFontFace: THEME.bodyFontFace };
pres.title = "Project Atlas — Technical Overview";
pres.subject = "Offline Intelligence and Data Operations Platform";
pres.author = "Project Atlas contributors";
pres.company = "Project Atlas";
const C = pres.SchemeColor;
const W = 13.333;
const M = 0.6; // side margin

// ------------------------------------------------------------------------------------------- assets
async function svgToPng(svg, size) {
  return (await sharp(Buffer.from(svg)).resize(size, size, { fit: "contain", background: { r: 0, g: 0, b: 0, alpha: 0 } }).png().toBuffer());
}
async function icon(name, hex = "FFFFFF") {
  const svg = ReactDOMServer.renderToStaticMarkup(React.createElement(fa[name], { size: 256, color: "#" + hex }));
  const buf = await svgToPng(svg, 256);
  return "image/png;base64," + buf.toString("base64");
}
async function logoPng() {
  const svg = fs.readFileSync(path.join(REPO, "frontend", "public", "atlas-icon.svg"));
  const buf = await sharp(svg, { density: 600 }).resize(512, 512).png().toBuffer();
  return "image/png;base64," + buf.toString("base64");
}
async function constellationPng(w, h, seed) {
  let s = seed;
  const rnd = () => ((s = (s * 9301 + 49297) % 233280) / 233280);
  const pts = Array.from({ length: 54 }, () => [rnd() * w, rnd() * h]);
  let lines = "";
  pts.forEach(([x, y], i) => {
    const near = pts.map((p, j) => [j, (p[0] - x) ** 2 + (p[1] - y) ** 2]).sort((a, b) => a[1] - b[1]).slice(1, 3);
    near.forEach(([j]) => { lines += `<line x1="${x}" y1="${y}" x2="${pts[j][0]}" y2="${pts[j][1]}" stroke="#2E5F86" stroke-width="1.4"/>`; });
  });
  const dots = pts.map(([x, y], i) => {
    const r = [3, 4.5, 6][i % 3];
    return `<circle cx="${x}" cy="${y}" r="${r}" fill="${r > 5 ? "#4FA3D9" : "#3B7FB0"}"/>`;
  }).join("");
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="${w}" height="${h}" viewBox="0 0 ${w} ${h}">${lines}${dots}</svg>`;
  const buf = await sharp(Buffer.from(svg)).png().toBuffer();
  return "image/png;base64," + buf.toString("base64");
}

// ------------------------------------------------------------------------------------------- layouts
function defineLayouts(logo) {
  pres.defineSlideMaster({
    title: "Title (dark)",
    background: { color: HEX.dk1 },
    objects: [
      { image: { x: M + 0.1, y: 0.7, w: 0.85, h: 0.85, data: logo } },
      { text: { text: "A T L A S", options: { x: M + 1.15, y: 0.78, w: 4, h: 0.38, fontSize: 16, bold: true, color: C.accent2, margin: 0 } } },
      { text: { text: "NAVIGATE THE COMPLEXITY OF DATA", options: { x: M + 1.15, y: 1.14, w: 5, h: 0.3, fontSize: 10, color: C.text2, charSpacing: 3, margin: 0 } } },
      { placeholder: { options: { name: "title", type: "title", x: M + 0.1, y: 2.55, w: 8.2, h: 1.5, fontSize: 54, bold: true, color: C.background1, valign: "bottom", align: "left", margin: 0 }, text: "" } },
      { placeholder: { options: { name: "body", type: "body", x: M + 0.1, y: 4.2, w: 8.2, h: 0.9, fontSize: 22, color: C.accent2, valign: "top", align: "left", margin: 0 }, text: "" } },
      { placeholder: { options: { name: "meta", type: "body", x: M + 0.1, y: 6.35, w: 8.2, h: 0.45, fontSize: 12, color: C.text2, valign: "top", align: "left", margin: 0 }, text: "" } },
    ],
  });
  pres.defineSlideMaster({
    title: "Section (dark)",
    background: { color: HEX.dk1 },
    objects: [
      { placeholder: { options: { name: "kicker", type: "body", x: M + 0.1, y: 2.35, w: 6, h: 0.5, fontSize: 16, bold: true, color: C.accent2, charSpacing: 4, align: "left", margin: 0 }, text: "" } },
      { placeholder: { options: { name: "title", type: "title", x: M + 0.1, y: 2.85, w: 10.5, h: 1.2, fontSize: 48, bold: true, color: C.background1, valign: "top", align: "left", margin: 0 }, text: "" } },
      { placeholder: { options: { name: "body", type: "body", x: M + 0.1, y: 4.15, w: 9.5, h: 1.0, fontSize: 20, color: C.background2, valign: "top", align: "left", margin: 0 }, text: "" } },
    ],
  });
  const footer = [
    { text: { text: "PROJECT ATLAS  ·  Technical overview  ·  v0.2.0", options: { x: M, y: 7.02, w: 6, h: 0.3, fontSize: 10, color: C.text2, margin: 0 } } },
  ];
  pres.defineSlideMaster({
    title: "Content",
    background: { color: HEX.lt1 },
    margin: [0.5, 0.6, 0.6, 0.6],
    slideNumber: { x: W - M - 0.6, y: 7.0, w: 0.6, h: 0.3, fontSize: 10, color: C.text2, align: "right" },
    objects: [
      ...footer,
      { placeholder: { options: { name: "title", type: "title", x: M, y: 0.38, w: W - 2 * M, h: 0.85, fontSize: 36, bold: true, color: C.text1, valign: "middle", align: "left", margin: 0 }, text: "" } },
    ],
  });
  pres.defineSlideMaster({
    title: "Content (tint)",
    background: { color: HEX.lt2 },
    slideNumber: { x: W - M - 0.6, y: 7.0, w: 0.6, h: 0.3, fontSize: 10, color: C.text2, align: "right" },
    objects: [
      ...footer,
      { placeholder: { options: { name: "title", type: "title", x: M, y: 0.38, w: W - 2 * M, h: 0.85, fontSize: 36, bold: true, color: C.text1, valign: "middle", align: "left", margin: 0 }, text: "" } },
    ],
  });
}

// ------------------------------------------------------------------------------------------- helpers
let SECTION = "";
function slide(master, title) {
  const s = pres.addSlide({ masterName: master, sectionTitle: SECTION });
  if (title) s.addText(title, { placeholder: "title" });
  return s;
}
function section(title) {
  SECTION = title;
  pres.addSection({ title });
}
function txt(s, text, o) {
  s.addText(text, { isTextBox: true, margin: 0, valign: "top", fontSize: 14, color: C.text1, ...o });
}
function card(s, x, y, w, h, fill = C.background2, name = "card") {
  s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x, y, w, h, rectRadius: 0.08, fill: { color: fill }, line: { color: fill, width: 0 }, objectName: name });
}
function tintCard(s, x, y, w, h, color, transparency = 88, name = "tint card") {
  s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x, y, w, h, rectRadius: 0.08, fill: { color, transparency }, line: { color, width: 0, transparency: 100 }, objectName: name });
}
function iconCircle(s, data, x, y, d, color, name = "icon") {
  s.addShape(pres.shapes.OVAL, { x, y, w: d, h: d, fill: { color }, line: { color, width: 0 }, objectName: name + " circle" });
  const p = d * 0.25;
  s.addImage({ data, x: x + p, y: y + p, w: d - 2 * p, h: d - 2 * p, objectName: name });
}
function arrow(s, x1, y1, x2, y2, color = C.text2, width = 1.5) {
  s.addShape(pres.shapes.LINE, {
    x: Math.min(x1, x2), y: Math.min(y1, y2), w: Math.abs(x2 - x1) || 0.001, h: Math.abs(y2 - y1) || 0.001,
    flipH: x2 < x1, flipV: y2 < y1, line: { color, width, endArrowType: "triangle" }, objectName: "arrow",
  });
}
function bullets(items, o = {}) {
  return items.map((t, i) => {
    const runs = Array.isArray(t) ? t : [{ text: t }];
    return runs.map((r, k) => ({
      text: r.text,
      options: { ...(r.options || {}), ...(k === 0 ? { bullet: { indent: 16 }, paraSpaceAfter: o.space ?? 8 } : {}), ...(k === runs.length - 1 && i < items.length - 1 ? { breakLine: true } : {}) },
    }));
  }).flat();
}
function shot(s, file, x, y, w, name) {
  const h = w * 900 / 1440;
  s.addShape(pres.shapes.RECTANGLE, { x: x - 0.02, y: y - 0.02, w: w + 0.04, h: h + 0.04, fill: { color: C.background1 }, line: { color: C.text2, width: 0.75, transparency: 60 }, objectName: name + " frame" });
  s.addImage({ path: path.join(SHOTS, file), x, y, w, h, objectName: name, altText: name });
  return h;
}


// pptxgenjs writes Office's stock palette into the theme; replace it with the Atlas colours so scheme
// colours resolve correctly, mend <c:crossesAt val="autoZero"/>, and drop folder entries from the zip.
async function writeTheme(file, theme) {
  const JSZip = require(require.resolve("jszip", { paths: [require.resolve("pptxgenjs")] }));
  const zip = await JSZip.loadAsync(fs.readFileSync(file));
  const slots = ["dk1", "lt1", "dk2", "lt2", "accent1", "accent2", "accent3", "accent4", "accent5", "accent6", "hlink", "folHlink"];
  const scheme = `<a:clrScheme name="${theme.name}">` + slots.map((k) => `<a:${k}><a:srgbClr val="${theme.colors[k]}"/></a:${k}>`).join("") + "</a:clrScheme>";
  const part = "ppt/theme/theme1.xml";
  let xml = await zip.file(part).async("string");
  xml = xml.replace(/<a:clrScheme\b[\s\S]*?<\/a:clrScheme>/, () => scheme)
    .replace(/(<a:(?:theme|fontScheme)\b[^>]*?\bname=")[^"]*"/g, (_, head) => `${head}${theme.name}"`);
  zip.file(part, xml);
  for (const name of Object.keys(zip.files)) {
    if (zip.files[name].dir) { delete zip.files[name]; continue; }
    if (!name.endsWith(".xml")) continue;
    const x = await zip.file(name).async("string");
    if (/<a:srgbClr val="(?![0-9A-Fa-f]{6}")/.test(x)) throw new Error(`${name}: a scheme colour was passed to a hex-only option`);
    if (x.includes('<c:crossesAt val="autoZero"/>')) zip.file(name, x.replaceAll('<c:crossesAt val="autoZero"/>', '<c:crosses val="autoZero"/>'));
  }
  fs.writeFileSync(file, await zip.generateAsync({ type: "nodebuffer", compression: "DEFLATE" }));
}

// ------------------------------------------------------------------------------------------- build
(async () => {
  const logo = await logoPng();
  const stars = await constellationPng(900, 760, 17);
  const I = {};
  const iconNames = ["FaFileImport", "FaClipboardCheck", "FaUserFriends", "FaProjectDiagram", "FaChartLine", "FaFolderOpen",
    "FaFileSignature", "FaWifi", "FaFingerprint", "FaBalanceScale", "FaUserCheck", "FaRedo", "FaLink", "FaShieldAlt",
    "FaTable", "FaLock", "FaHistory", "FaDatabase", "FaDesktop", "FaServer", "FaPlane", "FaRobot", "FaSearch",
    "FaExclamationTriangle", "FaCheck", "FaHourglassHalf", "FaPause", "FaFileAlt", "FaSitemap", "FaArchive", "FaBan"];
  for (const n of iconNames) I[n] = await icon(n, "FFFFFF");
  defineLayouts(logo);

  // ======================================================================================= 1 title
  section("Introduction");
  let s = slide("Title (dark)");
  s.addImage({ data: stars, x: 7.75, y: 1.75, w: 5.2, h: 4.39, objectName: "constellation", transparency: 10 });
  s.addText("Project Atlas", { placeholder: "title" });
  s.addText("Offline Intelligence and Data Operations Platform", { placeholder: "body" });
  s.addText("Technical overview  ·  Version 0.2.0  ·  November 2026", { placeholder: "meta" });
  s.addNotes("Welcome. This deck walks through Project Atlas end to end: what problem it solves, how it is built, " +
    "what each capability does, why it can be trusted, how it is deployed, and its honest status. " +
    "Everything here comes from the repository: code, docs and recorded test, acceptance and benchmark results for release 0.2.0.");

  // ======================================================================================= 2 one slide
  s = slide("Content", "Atlas in one slide");
  txt(s, [
    { text: "An offline-first platform that turns authorized datasets and documents into ", options: {} },
    { text: "evidence-backed, auditable analysis", options: { bold: true, color: C.accent1 } },
    { text: " — with no cloud dependency at install time or at run time.", options: {} },
  ], { x: M, y: 1.6, w: 5.1, h: 2.2, fontSize: 24 });
  txt(s, bullets([
    "Import, validate, resolve, explore, analyse, report",
    "Every step keeps a pointer back to the source bytes",
    "Software proposes; people decide — and are recorded",
  ], { space: 10 }), { x: M, y: 4.1, w: 5.1, h: 2.3, fontSize: 16, color: C.text1 });
  const stats = [["167", "REST API operations"], ["16", "UI modules"], ["111", "backend tests passing"],
    ["13", "file formats supported"], ["13", "data-quality checks"], ["0", "cloud services or telemetry"]];
  stats.forEach(([v, l], i) => {
    const c = i % 2, r = Math.floor(i / 2);
    const x = 6.35 + c * 3.25, y = 1.6 + r * 1.68, w = 3.0, h = 1.45;
    tintCard(s, x, y, w, h, C.accent1, 90, "stat card");
    txt(s, v, { x: x + 0.3, y: y + 0.18, w: w - 0.5, h: 0.75, fontSize: 40, bold: true, color: C.accent1 });
    txt(s, l, { x: x + 0.3, y: y + 0.92, w: w - 0.5, h: 0.4, fontSize: 13, color: C.text2 });
  });
  s.addNotes("The one-sentence pitch is on the left. The numbers on the right are all verifiable in the repo: " +
    "167 operations in docs/api.md, 16 navigation modules in the UI, 111 backend tests passing in the engineering report, " +
    "8 tabular plus 5 document formats, 13 quality checks, and no telemetry at all — enabling it is rejected at startup.");

  // ======================================================================================= 3 problem
  s = slide("Content", "The problem Atlas solves");
  const probs = [
    ["FaFolderOpen", C.accent1, "Messy inputs", "Staff lists in CSV, suppliers in Excel, payments from a database, audit reports as PDF, e-mails. The same person is “Dr. Amelia Okafor” in one file and “Amelia Okafor” in another."],
    ["FaWifi", C.accent4, "Hard constraints", "Sensitive data and air-gapped networks rule out cloud analytics. Ad-hoc scripts and spreadsheets lose provenance."],
    ["FaBalanceScale", C.accent3, "Accountability", "Conclusions will be challenged. Every number, link and finding must be traceable, reproducible and independently reviewed."],
  ];
  probs.forEach(([ic, col, t, b], i) => {
    const x = M + i * 4.1, y = 1.65, w = 3.85, h = 4.15;
    card(s, x, y, w, h, C.background2, "problem card");
    iconCircle(s, I[ic], x + 0.35, y + 0.4, 0.85, col, t);
    txt(s, t, { x: x + 0.35, y: y + 1.45, w: w - 0.7, h: 0.5, fontSize: 22, bold: true });
    txt(s, b, { x: x + 0.35, y: y + 2.05, w: w - 0.7, h: 1.9, fontSize: 15, color: C.text2 });
  });
  txt(s, [{ text: "Atlas covers the whole chain — import to auditable report — in one installable product.", options: { bold: true } }],
    { x: M, y: 6.1, w: W - 2 * M, h: 0.5, fontSize: 18, color: C.accent1 });
  s.addNotes("Three forces shape the design. Data arrives messy and inconsistent; the environment often forbids the cloud; " +
    "and the output must survive scrutiny. General BI tools lack row-level provenance and entity resolution, cloud platforms " +
    "are off the table for sensitive or air-gapped work, and scripts cannot show a reviewer how a conclusion was reached.");

  // ======================================================================================= 4 section
  section("How it works");
  s = slide("Section (dark)");
  s.addText("SECTION 01", { placeholder: "kicker" });
  s.addText("How it works", { placeholder: "title" });
  s.addText("The end-to-end flow, the architecture and the principles behind it", { placeholder: "body" });
  s.addNotes("First, how the platform fits together.");

  // ======================================================================================= 5 flow
  s = slide("Content", "From raw files to defensible findings");
  const flow = [
    ["FaFileImport", "Import", "8 tabular formats, documents, originals hashed"],
    ["FaClipboardCheck", "Validate", "Dry run, 13 quality checks, nothing written"],
    ["FaUserFriends", "Resolve", "Explainable matching, human review, revertible merges"],
    ["FaProjectDiagram", "Explore", "Graph, search, timeline, offline maps"],
    ["FaChartLine", "Analyse", "Reproducible runs, sandboxed SQL"],
    ["FaFileSignature", "Investigate", "Verbatim evidence, reviewed findings"],
    ["FaShieldAlt", "Report & audit", "Manifests, hash-chained audit log"],
  ];
  const fw = (W - 2 * M) / flow.length;
  flow.forEach(([ic, t, b], i) => {
    const cx = M + i * fw + fw / 2;
    const col = i < 2 ? C.accent1 : i < 5 ? C.accent2 : C.accent3;
    iconCircle(s, I[ic], cx - 0.55, 2.0, 1.1, col, t);
    if (i < flow.length - 1) arrow(s, cx + 0.65, 2.55, cx + fw - 0.65, 2.55, C.text2, 1.5);
    txt(s, `${i + 1}`, { x: cx - 0.6, y: 3.3, w: 1.2, h: 0.35, fontSize: 13, bold: true, color: C.text2, align: "center" });
    txt(s, t, { x: cx - 0.85, y: 3.62, w: 1.7, h: 0.45, fontSize: 17, bold: true, align: "center" });
    txt(s, b, { x: cx - 0.82, y: 4.1, w: 1.64, h: 1.3, fontSize: 13, color: C.text2, align: "center" });
  });
  tintCard(s, M, 5.65, W - 2 * M, 0.9, C.accent1, 90, "provenance strip");
  txt(s, [{ text: "Provenance at every hop:  ", options: { bold: true, color: C.accent1 } },
    { text: "source file SHA-256 → dataset version → records (raw + normalized) → entities → relationships → analyses → report manifest" }],
  { x: M + 0.3, y: 5.85, w: W - 2 * M - 0.6, h: 0.55, fontSize: 15, valign: "middle" });
  s.addNotes("This is the spine of the product. Data enters through a controlled import with a mandatory dry run, " +
    "records are resolved into entities with human review, then explored and analysed, and finally turned into evidence, " +
    "findings and reports. The strip at the bottom is the key idea: each object keeps a pointer to where it came from.");

  // ======================================================================================= 6 architecture
  s = slide("Content", "One process, five stores");
  card(s, 2.6, 1.5, 8.1, 0.6, C.text1, "client");
  txt(s, "Browser or desktop window — React UI, same origin, strict CSP", { x: 2.6, y: 1.5, w: 8.1, h: 0.6, fontSize: 14, bold: true, color: C.background1, align: "center", valign: "middle" });
  arrow(s, W / 2, 2.12, W / 2, 2.5, C.text2, 1.5);
  tintCard(s, M, 2.55, W - 2 * M, 2.45, C.accent1, 92, "api box");
  s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: M, y: 2.55, w: W - 2 * M, h: 2.45, rectRadius: 0.08, fill: { type: "none" }, line: { color: C.accent1, width: 1.25 }, objectName: "api outline" });
  txt(s, "atlas-api — one Python process (FastAPI + uvicorn)", { x: M + 0.3, y: 2.7, w: 7, h: 0.4, fontSize: 16, bold: true, color: C.accent1 });
  const rows = [
    ["API routers", "auth · admin · projects · data & jobs · entities + graph · search · documents · analysis · investigations · workflows · reports · ai · workspace"],
    ["Cross-cutting", "Argon2id · sessions · TOTP · RBAC · rate limits · config validation · job runner · network guard"],
    ["Domain services", "ingestion · ontology · entities · graph · search · documents · temporal · geospatial · analytics · ai · workflows · reporting · audit · backup"],
  ];
  rows.forEach(([k, v], i) => {
    txt(s, k, { x: M + 0.3, y: 3.2 + i * 0.58, w: 1.9, h: 0.5, fontSize: 13, bold: true });
    txt(s, v, { x: M + 2.2, y: 3.2 + i * 0.58, w: W - 2 * M - 2.5, h: 0.55, fontSize: 13, color: C.text2 });
  });
  const stores = [["SQLite / PostgreSQL", "system of record"], ["Search index", "FTS5 / tsvector, BM25"], ["Parquet per version", "analytics & SQL"],
    ["Files on disk", "originals, exports"], ["Local model runtime", "optional, loopback/LAN"]];
  const sw = (W - 2 * M - 4 * 0.25) / 5;
  stores.forEach(([t, b], i) => {
    const x = M + i * (sw + 0.25);
    const opt = i === 4;
    arrow(s, x + sw / 2, 5.02, x + sw / 2, 5.45, opt ? C.accent5 : C.text2, 1.5);
    if (opt) tintCard(s, x, 5.5, sw, 1.15, C.accent5, 85, "store"); else card(s, x, 5.5, sw, 1.15, C.background2, "store");
    txt(s, t, { x: x + 0.15, y: 5.62, w: sw - 0.3, h: 0.4, fontSize: 15, bold: true, align: "center", color: opt ? C.accent5 : C.text1 });
    txt(s, b, { x: x + 0.15, y: 6.05, w: sw - 0.3, h: 0.45, fontSize: 13, color: C.text2, align: "center" });
  });
  s.addNotes("Atlas is a modular monolith: one process serves the API, runs background jobs and serves the UI. That keeps " +
    "installation, upgrades and the security boundary simple — one place for authorization, one audit log. " +
    "SQLite (or PostgreSQL on a LAN) is the system of record; FTS5 handles search; each dataset version gets an immutable " +
    "Parquet copy for fast analytics; originals stay byte-identical on disk. The only external process is an optional local model.");

  // ======================================================================================= 7 principles
  s = slide("Content (tint)", "Design principles you can see in the code");
  const pr = [
    ["FaWifi", C.accent1, "Offline-first", "Network guard blocks non-local connections; no telemetry; bundled maps and fonts"],
    ["FaFingerprint", C.accent1, "Evidence first", "Raw values kept beside normalized ones; hashes and record links everywhere"],
    ["FaSearch", C.accent2, "Explainable", "Versioned, deterministic algorithms with visible inputs and evidence"],
    ["FaUserCheck", C.accent3, "Human in the loop", "Merges, findings, AI suggestions and generated SQL need a person"],
    ["FaRedo", C.accent3, "Reproducible", "Every analysis re-runs on recorded inputs and is checked by hash"],
    ["FaHistory", C.accent5, "Tamper-evident", "Append-only audit log, hash chain, signed checkpoints"],
  ];
  pr.forEach(([ic, col, t, b], i) => {
    const c = i % 3, r = Math.floor(i / 3);
    const x = M + c * 4.1, y = 1.6 + r * 2.55, w = 3.85, h = 2.3;
    card(s, x, y, w, h, C.background1, "principle card");
    iconCircle(s, I[ic], x + 0.3, y + 0.32, 0.75, col, t);
    txt(s, t, { x: x + 1.25, y: y + 0.42, w: w - 1.5, h: 0.55, fontSize: 20, bold: true, valign: "middle" });
    txt(s, b, { x: x + 0.3, y: y + 1.25, w: w - 0.6, h: 0.95, fontSize: 15, color: C.text2 });
  });
  s.addNotes("These six principles are enforced in code, not just stated. For example, offline mode patches socket " +
    "connections inside the process; matching is a versioned algorithm called er-1.1; analysis runs store input hashes; " +
    "and the audit table has database triggers that reject updates and deletes.");

  // ======================================================================================= 8 section
  section("Capabilities");
  s = slide("Section (dark)");
  s.addText("SECTION 02", { placeholder: "kicker" });
  s.addText("Capabilities", { placeholder: "title" });
  s.addText("Ingestion, entity resolution, graph, search, analytics, AI and case work", { placeholder: "body" });
  s.addNotes("Now the capabilities, in the order data flows through them.");

  // ======================================================================================= 9 ingestion
  s = slide("Content", "Every import gets a dry run first");
  const steps = [["Upload", "type allow-list, magic bytes, SHA-256"], ["Inspect", "encoding, delimiter, column types"],
    ["Map", "types, time zones, sensitive fields, entities"], ["Dry run", "13 quality checks over the whole file"], ["Commit", "background job, one transaction"]];
  steps.forEach(([t, b], i) => {
    const y = 1.6 + i * 0.98;
    const last = i === steps.length - 1;
    if (last) card(s, M, y, 4.9, 0.8, C.accent1, "step"); else tintCard(s, M, y, 4.9, 0.8, C.accent1, 90, "step");
    txt(s, `${i + 1}`, { x: M + 0.2, y, w: 0.4, h: 0.8, fontSize: 20, bold: true, color: last ? C.background1 : C.accent1, valign: "middle" });
    txt(s, t, { x: M + 0.7, y: y + 0.08, w: 4.0, h: 0.35, fontSize: 16, bold: true, color: last ? C.background1 : C.text1 });
    txt(s, b, { x: M + 0.7, y: y + 0.42, w: 4.1, h: 0.33, fontSize: 13, color: last ? C.background1 : C.text2 });
  });
  const sh = shot(s, "01-ingest-dryrun.png", 6.13, 1.6, 6.6, "Ingestion dry run screenshot");
  txt(s, "Synthetic transactions: timestamp and coordinate errors found, nothing written.",
    { x: 6.13, y: 1.6 + sh + 0.1, w: 6.6, h: 0.3, fontSize: 12, color: C.text2, italic: true });
  txt(s, [{ text: "Originals are kept beside normalized values ", options: { bold: true } }, { text: "— reviewers always see what the source said." }],
    { x: 6.13, y: 6.25, w: 6.6, h: 0.5, fontSize: 14 });
  s.addNotes("Import is a five-step pipeline. The dry run validates the entire file and runs 13 quality checks — parse errors, " +
    "encoding and mojibake, invalid formats, timestamp and coordinate errors, duplicates, referential integrity, mixed units and schema drift — " +
    "without writing anything. The commit is a background job inside one transaction, so failure leaves no partial data. " +
    "Rows with invalid coordinates never get a map point: Atlas never invents data.");

  // ======================================================================================= 10 entity resolution
  s = slide("Content", "Entity resolution that explains itself");
  const er = [["Blocking", "shared name token or identifier"], ["Compare", "only fields both records have"],
    ["Score", "name .45 · identifier .35 · attribute .20"], ["Band", "strong ≥ .90 + agreeing identifier"], ["Review", "a person accepts or rejects"]];
  er.forEach(([t, b], i) => {
    const y = 1.6 + i * 0.95;
    const human = i === 4;
    tintCard(s, M, y, 5.0, 0.8, human ? C.accent3 : C.accent1, 88, "er step");
    txt(s, t, { x: M + 0.25, y: y + 0.08, w: 4.5, h: 0.35, fontSize: 16, bold: true, color: human ? C.accent3 : C.accent1 });
    txt(s, b, { x: M + 0.25, y: y + 0.42, w: 4.6, h: 0.33, fontSize: 13, color: C.text1 });
  });
  txt(s, "Missing data is never treated as agreement. Scores are similarity, not probability. Merges are fully revertible.",
    { x: M, y: 6.4, w: 5.0, h: 0.5, fontSize: 12, color: C.text2, italic: true });
  const hdr = { bold: true, color: C.text2, fontSize: 12, fill: { color: C.background2 } };
  const band = (t, col) => ({ text: t, options: { bold: true, color: col, fontSize: 14 } });
  s.addTable([
    [{ text: "DEMO PAIR", options: hdr }, { text: "OUTCOME", options: hdr }, { text: "WHY", options: hdr }],
    [{ text: "Dr. Amelia Okafor ↔ Amelia Okafor" }, band("strong", C.accent3), { text: "same e-mail identifier" }],
    [{ text: "Jon Mercer ↔ Jonathan Mercer" }, band("strong", C.accent3), { text: "same phone identifier" }],
    [{ text: "Lena Fisher ↔ Lena Fischer" }, band("ambiguous", C.accent4), { text: "names only — human judgement" }],
    [{ text: "Rafael Ortiz ↔ Rafael Ortiz" }, band("not strong", C.accent6), { text: "phone identifiers conflict" }],
    [{ text: "Gunnar Thorsen" }, band("no match", C.text2), { text: "nothing shared" }],
  ], { x: 6.0, y: 1.6, w: 6.73, colW: [3.0, 1.35, 2.38], fontSize: 14, color: C.text1, border: { type: "solid", color: "D0D8E0", pt: 0.75 }, rowH: 0.62, valign: "middle", margin: [0.06, 0.1, 0.06, 0.1], objectName: "demo results table" });
  txt(s, "Exactly the outcomes in sample-data/expected_results.json — asserted by the test suite.",
    { x: 6.0, y: 5.6, w: 6.73, h: 0.4, fontSize: 13, color: C.text2 });
  s.addNotes("Algorithm er-1.1 is deterministic and versioned. It only compares pairs that share a name token or identifier, " +
    "only scores fields present on both sides, and can only call a match strong when an identifier agrees and none conflicts. " +
    "The table shows the demo data: two strong matches, one ambiguous pair left to a person, and a same-name pair that is " +
    "correctly not strong because the phone numbers conflict. Every merge stores a snapshot and can be reverted.");

  // ======================================================================================= 11 graph
  s = slide("Content", "A knowledge graph honest about its sources");
  const gh = shot(s, "07-graph.png", M, 1.6, 7.3, "Knowledge graph screenshot");
  const bases = [[C.accent1, "observed", "stated directly by a source record"], [C.accent2, "inferred", "deterministic rule over data"],
    [C.accent5, "model hypothesis", "hidden until a reviewer verifies it"], [C.accent4, "manual", "created by a named user"]];
  txt(s, "Every edge carries its basis", { x: 8.3, y: 1.6, w: 4.4, h: 0.45, fontSize: 18, bold: true });
  bases.forEach(([col, t, b], i) => {
    const y = 2.2 + i * 0.72;
    s.addShape(pres.shapes.OVAL, { x: 8.3, y: y + 0.08, w: 0.26, h: 0.26, fill: { color: col }, line: { color: col, width: 0 }, objectName: "basis dot" });
    txt(s, t, { x: 8.75, y, w: 3.9, h: 0.35, fontSize: 15, bold: true });
    txt(s, b, { x: 8.75, y: y + 0.33, w: 3.9, h: 0.33, fontSize: 13, color: C.text2 });
  });
  txt(s, bullets(["Degree, PageRank, betweenness, Louvain communities, paths", "Explain connection: per-hop evidence", "Snapshots; GraphML, GEXF, JSON export"], { space: 6 }),
    { x: 8.3, y: 5.2, w: 4.43, h: 1.5, fontSize: 14 });
  txt(s, "Confidence stays empty unless it was actually measured. A path shows recorded links — not intent.",
    { x: M, y: 1.6 + gh + 0.15, w: 7.3, h: 0.5, fontSize: 12, color: C.text2, italic: true });
  s.addNotes("The graph labels every relationship with how it was created, and the UI encodes that basis in line style. " +
    "Model-suggested relationships are stored as unverified and hidden until a reviewer accepts them. The overview loads " +
    "the best-connected nodes first, which brought it from 6.6 to 0.9 seconds on about 100,000 edges. Explain connection " +
    "lists every hop with its basis and a redacted evidence sample.");

  // ======================================================================================= 12 search & docs
  s = slide("Content", "Search, documents and a grounded assistant");
  txt(s, "Unified search", { x: M, y: 1.6, w: 5.3, h: 0.45, fontSize: 18, bold: true });
  const q = [['"Bluefjord Freight"', "phrase"], ["Okaf*", "prefix"], ["Mercer AND payment", "Boolean"], ["type:entity Okafor", "type filter"], ["amount>50000", "field filter"]];
  q.forEach(([code, lab], i) => {
    const y = 2.12 + i * 0.5;
    card(s, M, y, 3.1, 0.4, C.background2, "query chip");
    txt(s, code, { x: M + 0.12, y, w: 2.9, h: 0.4, fontSize: 13, fontFace: "Courier New", color: C.accent1, valign: "middle" });
    txt(s, lab, { x: M + 3.3, y, w: 2.0, h: 0.4, fontSize: 13, color: C.text2, valign: "middle" });
  });
  txt(s, "Document intelligence", { x: M, y: 4.75, w: 5.3, h: 0.45, fontSize: 18, bold: true });
  txt(s, bullets(["PDF, DOCX, TXT, Markdown, EML with page-level evidence", "Answers quote and cite pages — or decline", "Embedded instructions flagged, never followed"], { space: 6 }),
    { x: M, y: 5.25, w: 5.4, h: 1.5, fontSize: 14 });
  const dh = shot(s, "21-document-assistant.png", 6.2, 1.6, 6.53, "Document assistant screenshot");
  txt(s, "“Who approved the large payments?” — answered by quoting the synthetic audit report, page 2.",
    { x: 6.2, y: 1.6 + dh + 0.12, w: 6.53, h: 0.5, fontSize: 12, color: C.text2, italic: true });
  s.addNotes("Search uses SQLite FTS5 with BM25 ranking; the query language is parsed and re-emitted, never passed raw, and " +
    "restricted or sensitive content never enters results for users who may not see it. Documents are split into page-level " +
    "passages; the assistant only answers from retrieved passages with citations and declines when there is no evidence. " +
    "The sample data includes a prompt-injection note to prove embedded instructions are flagged and ignored.");

  // ======================================================================================= 13 analytics
  s = slide("Content", "Analytics you can reproduce — and SQL you can trust");
  txt(s, "Reproducibility by hash", { x: M, y: 1.6, w: 6, h: 0.45, fontSize: 18, bold: true });
  const rp = [["Recorded inputs", "version ids + content hashes, parameters, software versions"], ["Run", "describe · frequency · trend · correlation · outliers · missing · time series"],
    ["Result SHA-256", "hash of the canonical result, stored with the run"], ["Reproduce", "re-run and compare: identical, or changed inputs reported"]];
  rp.forEach(([t, b], i) => {
    const y = 2.15 + i * 1.02;
    const last = i === 3;
    tintCard(s, M, y, 5.9, 0.85, last ? C.accent3 : C.accent1, 88, "repro step");
    txt(s, t, { x: M + 0.25, y: y + 0.08, w: 5.4, h: 0.35, fontSize: 16, bold: true, color: last ? C.accent3 : C.accent1 });
    txt(s, b, { x: M + 0.25, y: y + 0.44, w: 5.5, h: 0.35, fontSize: 13 });
    if (i < 3) arrow(s, M + 2.95, y + 0.86, M + 2.95, y + 1.01, C.text2, 1.25);
  });
  txt(s, "Demo: outliers T-5007 and T-5023 flagged — with the not-evidence-of-wrongdoing disclaimer — and the reproduced hash is identical.",
    { x: M, y: 6.25, w: 5.9, h: 0.6, fontSize: 12, color: C.text2, italic: true });
  txt(s, "SQL console: four independent layers", { x: 7.0, y: 1.6, w: 5.7, h: 0.45, fontSize: 18, bold: true });
  const layers = [[C.accent1, "1  Static validation", "one SELECT/WITH statement; file, extension and config functions denied"],
    [C.accent3, "2  Permitted tables only", "only readable datasets loaded; sensitive columns dropped"],
    [C.accent4, "3  Locked engine", "in-memory DuckDB; external access off, configuration locked first"],
    [C.accent6, "4  Resource limits", "rows, memory, threads and a wall-clock interrupt"]];
  layers.forEach(([col, t, b], i) => {
    const y = 2.15 + i * 1.02;
    tintCard(s, 7.0, y, 5.73, 0.85, col, 85, "sql layer");
    txt(s, t, { x: 7.25, y: y + 0.08, w: 5.3, h: 0.35, fontSize: 16, bold: true, color: col });
    txt(s, b, { x: 7.25, y: y + 0.44, w: 5.35, h: 0.35, fontSize: 13 });
  });
  txt(s, "A test proves file access fails even with the validator deliberately bypassed.",
    { x: 7.0, y: 6.25, w: 5.73, h: 0.6, fontSize: 12, color: C.text2, italic: true });
  s.addNotes("Each analysis run records exactly what it read and a hash of its result, so anyone can reproduce it months later " +
    "and get either an identical hash or a report that inputs changed. The SQL console is defended in depth: even if the " +
    "static validator missed something, the in-memory DuckDB has external access disabled and its configuration locked " +
    "before the user's query runs, and resource limits stop runaway queries.");

  // ======================================================================================= 14 AI
  s = slide("Content (tint)", "Optional local AI, under strict rules");
  const ai = [[C.accent1, "You ask", "plain-language question"], [C.accent5, "Model drafts SQL", "validated, never auto-run"],
    [C.accent3, "You review & run", "explicit click, sandboxed"], [C.accent1, "Atlas computes", "deterministic table"], [C.accent5, "Model describes", "labelled as model output"]];
  const aw = (W - 2 * M - 4 * 0.35) / 5;
  txt(s, "“Ask your data”", { x: M, y: 1.55, w: 6, h: 0.45, fontSize: 18, bold: true });
  ai.forEach(([col, t, b], i) => {
    const x = M + i * (aw + 0.35);
    card(s, x, 2.1, aw, 1.35, C.background1, "ai step");
    txt(s, t, { x: x + 0.2, y: 2.25, w: aw - 0.4, h: 0.45, fontSize: 16, bold: true, color: col });
    txt(s, b, { x: x + 0.2, y: 2.72, w: aw - 0.4, h: 0.6, fontSize: 13, color: C.text2 });
    if (i < 4) arrow(s, x + aw + 0.04, 2.78, x + aw + 0.31, 2.78, C.text2, 1.25);
  });
  const rules = [["FaServer", C.accent1, "Local endpoint only", "Loopback or private address enforced at startup and on every call. No hosted fallback."],
    ["FaLink", C.accent5, "Cited and validated", "Answers without valid citations are withheld; SQL is validated; hypotheses are stored unverified."],
    ["FaUserCheck", C.accent3, "A person decides", "Merges, relationship hypotheses, SQL execution and report text all require explicit action."]];
  rules.forEach(([ic, col, t, b], i) => {
    const x = M + i * 4.1, y = 3.85, w = 3.85, h = 2.75;
    card(s, x, y, w, h, C.background1, "rule card");
    iconCircle(s, I[ic], x + 0.3, y + 0.3, 0.75, col, t);
    txt(s, t, { x: x + 0.3, y: y + 1.2, w: w - 0.6, h: 0.45, fontSize: 18, bold: true });
    txt(s, b, { x: x + 0.3, y: y + 1.7, w: w - 0.6, h: 0.95, fontSize: 14, color: C.text2 });
  });
  s.addNotes("Every feature works without a model. If an organization runs one locally, Atlas uses it only for drafting and " +
    "describing — computation stays deterministic. Note the status honestly: all AI paths are tested against a mock " +
    "Ollama-compatible runtime, but have not yet been exercised against a real model.");

  // ======================================================================================= 15 case work
  s = slide("Content", "Investigations, workflows and reports");
  const cw = [
    ["FaFileSignature", C.accent1, "Investigations", ["Objective, scope and authorization basis", "Verbatim evidence with revisions", "Findings: draft → review → confirmed / disputed / rejected", "No self-review; confirmation needs evidence"]],
    ["FaSitemap", C.accent4, "Workflows", ["16 typed node types, validated ports", "Preview on 200 rows, no side effects", "Side effects need confirmation", "Failure rolls back data writes"]],
    ["FaFileAlt", C.accent3, "Reports", ["PDF, HTML, XLSX, CSV, JSON", "Manifest: versions, parameters, redactions", "SHA-256 of every export", "Formula-injection protection"]],
  ];
  cw.forEach(([ic, col, t, items], i) => {
    const x = M + i * 4.1, y = 1.6, w = 3.85, h = 3.95;
    card(s, x, y, w, h, C.background2, "case card");
    iconCircle(s, I[ic], x + 0.3, y + 0.32, 0.8, col, t);
    txt(s, t, { x: x + 1.25, y: y + 0.42, w: w - 1.45, h: 0.6, fontSize: 21, bold: true, valign: "middle" });
    txt(s, bullets(items, { space: 10 }), { x: x + 0.3, y: y + 1.45, w: w - 0.55, h: 3.4, fontSize: 15 });
  });
  tintCard(s, M, 5.8, W - 2 * M, 0.85, C.accent1, 88, "takeaway strip");
  txt(s, 'In the acceptance run, the downloaded PDF bytes matched the manifest SHA-256 exactly.', { x: M + 0.3, y: 5.8, w: W - 2 * M - 0.6, h: 0.85, fontSize: 16, bold: true, color: C.accent1, valign: "middle" });
  s.addNotes("The final stages make work accountable. Evidence must be a verbatim excerpt from its source and keeps a revision " +
    "history. Findings follow a state machine where someone other than the author must confirm, with supporting evidence. " +
    "Workflows are typed and versioned, previewable without side effects. Reports carry a manifest and hash; in the " +
    "acceptance run the downloaded PDF bytes matched the manifest hash exactly.");

  // ======================================================================================= 16 section
  section("Trust and operations");
  s = slide("Section (dark)");
  s.addText("SECTION 03", { placeholder: "kicker" });
  s.addText("Trust and operations", { placeholder: "title" });
  s.addText("Security, audit, offline assurance, deployment, testing and status", { placeholder: "body" });
  s.addNotes("Why the platform can be trusted, and how it is run.");

  // ======================================================================================= 17 security
  s = slide("Content", "Security enforced on every request");
  const sec = [["Argon2id passwords", "≥ 12 chars, rehash on parameter change"], ["No default account", "one-time setup token, deleted after use"],
    ["Sessions", "256-bit tokens, only hashes stored, sliding expiry"], ["Brute force", "rate limits + 15-minute lockout after 5 failures"],
    ["Optional TOTP MFA", "admin-issued one-time recovery tokens"], ["404 for non-members", "other projects’ existence never revealed"]];
  sec.forEach(([t, b], i) => {
    const y = 1.6 + i * 0.82;
    iconCircle(s, I.FaLock, M, y + 0.06, 0.5, C.accent1, "lock");
    txt(s, t, { x: M + 0.7, y, w: 4.7, h: 0.35, fontSize: 16, bold: true });
    txt(s, b, { x: M + 0.7, y: y + 0.34, w: 4.8, h: 0.35, fontSize: 13, color: C.text2 });
  });
  const ck = { text: "✓", options: { color: C.accent3, bold: true, align: "center", fontSize: 16 } };
  const no = { text: "·", options: { color: C.text2, align: "center", fontSize: 16 } };
  const h2 = { bold: true, color: C.text2, fontSize: 11, fill: { color: C.background2 }, align: "center" };
  s.addTable([
    [{ text: "PERMISSION", options: { ...h2, align: "left" } }, { text: "READ-ONLY", options: h2 }, { text: "REVIEWER", options: h2 }, { text: "ANALYST", options: h2 }, { text: "DATA ENG.", options: h2 }, { text: "PROJ. ADMIN", options: h2 }],
    [{ text: "Read and search" }, ck, ck, ck, ck, ck],
    [{ text: "Review matches" }, no, ck, no, ck, ck],
    [{ text: "Analyses and SQL" }, no, ck, ck, ck, ck],
    [{ text: "Reports, workflows, AI" }, no, no, ck, ck, ck],
    [{ text: "Import, resolve, restricted data" }, no, no, no, ck, ck],
    [{ text: "Sensitive fields, members" }, no, no, no, no, ck],
  ], { x: 6.1, y: 1.6, w: 6.63, colW: [2.33, 0.86, 0.86, 0.86, 0.86, 0.86], fontSize: 13, color: C.text1, border: { type: "solid", color: "D0D8E0", pt: 0.75 }, rowH: 0.55, valign: "middle", margin: [0.04, 0.08, 0.04, 0.08], objectName: "role matrix" });
  txt(s, "System administrators do not automatically see project data. Sensitive fields are redacted in records, SQL, analytics and exports.",
    { x: 6.1, y: 5.65, w: 6.63, h: 0.8, fontSize: 13, color: C.text2 });
  s.addNotes("Authentication uses Argon2id, single-use setup tokens, hashed session tokens, lockout and optional TOTP. " +
    "Authorization has two independent layers: global roles for administration and project roles for data — so a system " +
    "administrator cannot read project data without membership. Input handling adds magic-byte checks, XML entity rejection, " +
    "formula-injection protection, and a strict Content Security Policy. Limitations: host administrators remain trusted, " +
    "data at rest relies on disk encryption, and no independent penetration test has been done yet.");

  // ======================================================================================= 18 audit backup offline
  s = slide("Content (tint)", "Audit, backup and offline assurance");
  const abo = [
    ["FaHistory", C.accent5, "Hash-chained audit", ["SHA-256 over previous hash + canonical event", "Triggers block UPDATE and DELETE", "HMAC-signed checkpoints off-database", "Verify reports the first broken sequence"]],
    ["FaArchive", C.accent1, "Verified backups", ["Online SQLite snapshot + workspace files", "Optional AES-256-GCM (scrypt key)", "Verify: hashes, integrity, row counts", "Restore moves current data aside first"]],
    ["FaBan", C.accent3, "Offline by design", ["Socket and DNS guard inside the process", "No telemetry; no external assets", "offline-check with a live probe", "Workflow repeated in a no-network namespace"]],
  ];
  abo.forEach(([ic, col, t, items], i) => {
    const x = M + i * 4.1, y = 1.6, w = 3.85, h = 3.95;
    card(s, x, y, w, h, C.background1, "assurance card");
    iconCircle(s, I[ic], x + 0.3, y + 0.32, 0.8, col, t);
    txt(s, t, { x: x + 1.25, y: y + 0.42, w: w - 1.45, h: 0.6, fontSize: 20, bold: true, valign: "middle" });
    txt(s, bullets(items, { space: 10 }), { x: x + 0.3, y: y + 1.45, w: w - 0.55, h: 3.4, fontSize: 15 });
  });
  tintCard(s, M, 5.8, W - 2 * M, 0.85, C.accent5, 88, "takeaway strip");
  txt(s, 'A test drops the trigger and edits a row: verification reports the exact broken sequence number.', { x: M + 0.3, y: 5.8, w: W - 2 * M - 0.6, h: 0.85, fontSize: 16, bold: true, color: C.accent5, valign: "middle" });
  s.addNotes("Three mechanisms provide assurance after the fact. The audit log is tamper-evident — a test drops the trigger, " +
    "edits a row and verification pinpoints the exact sequence. Backups are verified before you need them and restores never " +
    "delete current data. The network guard blocks non-local connections inside the process; for real air-gap assurance it " +
    "must be combined with OS and network controls, which the docs state plainly.");

  // ======================================================================================= 19 deployment
  s = slide("Content", "Three ways to deploy the same code");
  const dep = [
    ["FaDesktop", C.accent1, "Standalone desktop", "PyInstaller app; random loopback port; opens a chromeless browser window; SQLite in the user data folder"],
    ["FaPlane", C.accent3, "Air-gapped workstation", "Offline bundle with every wheel and SHA256SUMS; install.sh verifies and installs with --no-index"],
    ["FaServer", C.accent4, "Private LAN server", "Behind a TLS reverse proxy; LAN opt-in and TLS required in production; PostgreSQL in preview"],
  ];
  dep.forEach(([ic, col, t, b], i) => {
    const x = M + i * 4.1, y = 1.6, w = 3.85, h = 3.25;
    tintCard(s, x, y, w, h, col, 88, "deploy card");
    iconCircle(s, I[ic], x + 0.3, y + 0.32, 0.8, col, t);
    txt(s, t, { x: x + 0.3, y: y + 1.3, w: w - 0.6, h: 0.45, fontSize: 19, bold: true, color: col });
    txt(s, b, { x: x + 0.3, y: y + 1.8, w: w - 0.6, h: 1.35, fontSize: 14 });
  });
  card(s, M, 5.15, W - 2 * M, 1.5, C.text1, "code card");
  txt(s, [
    { text: "pip install -e backend  &&  (cd frontend && npm ci && npm run build)  &&  atlas serve", options: { breakLine: true } },
    { text: "atlas offline-check      atlas backup --encrypt      atlas verify-backup <file>" },
  ], { x: M + 0.35, y: 5.3, w: W - 2 * M - 0.7, h: 1.2, fontSize: 14, fontFace: "Courier New", color: C.background1, valign: "middle", paraSpaceAfter: 10 });
  s.addNotes("The same code serves three profiles, and startup validation refuses unsafe combinations such as a LAN binding " +
    "without opt-in, LAN production without TLS, a non-local AI endpoint in offline mode, or telemetry. Configuration is a set " +
    "of ATLAS_ environment variables. Linux bundles were verified; Windows and macOS packages still need to be built on those systems.");

  // ======================================================================================= 20 testing
  s = slide("Content", "Tested, measured and verified offline");
  const ts = [["111", "backend tests passing"], ["11", "frontend unit tests"], ["14/14", "acceptance steps, incl. no-network phase"], ["E2E", "Playwright run across all modules"]];
  ts.forEach(([v, l], i) => {
    const y = 1.6 + i * 1.25;
    tintCard(s, M, y, 4.6, 1.05, C.accent3, 88, "test stat");
    txt(s, v, { x: M + 0.25, y: y + 0.12, w: 1.8, h: 0.8, fontSize: 32, bold: true, color: C.accent3, valign: "middle" });
    txt(s, l, { x: M + 2.05, y: y + 0.12, w: 2.4, h: 0.8, fontSize: 14, valign: "middle" });
  });
  const bench = [["Import 100k rows (full)", 109.4], ["Entity resolution, 5.5k", 29.8], ["Import 100k rows (plain)", 15.8], ["Louvain communities", 8.7],
    ["PageRank", 6.1], ["PDF report, 2k rows", 2.9], ["Graph overview", 0.9], ["SQL aggregate, 100k", 0.5]];
  s.addChart(pres.charts.BAR, [{ name: "Seconds", labels: bench.map((b) => b[0]), values: bench.map((b) => b[1]) }], {
    x: 5.6, y: 1.5, w: 7.13, h: 4.6, barDir: "bar", catAxisOrientation: "maxMin",
    chartColors: [HEX.accent1], showValue: true, dataLabelPosition: "outEnd", dataLabelFormatCode: "0.0", dataLabelFontSize: 12,
    dataLabelColor: HEX.dk1, dataLabelFontFace: "+mn-lt",
    catAxisLabelColor: HEX.dk1, catAxisLabelFontSize: 12, catAxisLabelFontFace: "+mn-lt",
    valAxisHidden: true, valGridLine: { style: "none" }, catGridLine: { style: "none" }, showLegend: false,
    showTitle: true, title: "Benchmark timings (seconds, 4 vCPU, SQLite)", titleFontSize: 14, titleColor: HEX.dk1, titleFontFace: "+mn-lt",
    barGapWidthPct: 45, objectName: "benchmark chart",
  });
  txt(s, "205k records · 5.5k entities · 100k relationships · search p95 374 ms · peak 1.29 GB",
    { x: 5.6, y: 6.2, w: 7.13, h: 0.5, fontSize: 13, color: C.text2 });
  s.addNotes("All suites pass for 0.2.0. The acceptance scenario installs, creates the first admin, imports, resolves, " +
    "analyses, reports, restarts, verifies the audit chain, backs up, then removes the network entirely and repeats the core " +
    "workflow. The benchmark used 100,000 transactions and 5,000 people; measurements drove real fixes — import throughput " +
    "roughly doubled and the graph overview went from 6.6 to 0.9 seconds.");

  // ======================================================================================= 21 demo
  s = slide("Content", "Guided demo: Northwind Harbor");
  const hh = shot(s, "23-demo-home.png", M, 1.6, 7.2, "Demo home screenshot");
  txt(s, "All demo data is synthetic (seed 20251027, example.invalid e-mails).", { x: M, y: 1.6 + hh + 0.12, w: 7.2, h: 0.4, fontSize: 12, color: C.text2, italic: true });
  const demo = ["Projects → Create demo workspace", "Ctrl/⌘ K to jump anywhere", "See the planted quality defects", "Merge Dr. Amelia Okafor (strong match)",
    "Explain a connection in the graph", "Flag T-5007 and T-5023 as outliers", "Ask the assistant; export a PDF report"];
  demo.forEach((t, i) => {
    const y = 1.6 + i * 0.7;
    s.addShape(pres.shapes.OVAL, { x: 8.2, y: y + 0.04, w: 0.42, h: 0.42, fill: { color: C.accent1 }, line: { color: C.accent1, width: 0 }, objectName: "step dot" });
    txt(s, `${i + 1}`, { x: 8.2, y: y + 0.04, w: 0.42, h: 0.42, fontSize: 13, bold: true, color: C.background1, align: "center", valign: "middle" });
    txt(s, t, { x: 8.8, y, w: 3.95, h: 0.5, fontSize: 15, valign: "middle" });
  });
  s.addNotes("The fastest way to understand Atlas: create the demo workspace — four datasets, 106 records and five documents " +
    "loaded through the normal audited pipelines in seconds — then follow these seven steps. Each one exercises a different " +
    "module and has a known expected result documented in sample-data/expected_results.json.");

  // ======================================================================================= 22 status
  s = slide("Content", "Honest status of release 0.2.0");
  const st = [
    ["FaCheck", C.accent3, "Complete and tested", ["All 16 modules and their APIs", "Ingestion, resolution, graph, search", "Analytics, SQL sandbox, reports", "Audit, backup/restore, offline check", "Linux offline bundle and desktop app"]],
    ["FaHourglassHalf", C.accent4, "Partial", ["AI tested against a mock runtime", "OCR path untested here", "Language detection: 7 languages", "No per-field or per-model grants", "Workflow parameters edited as JSON"]],
    ["FaPause", C.text2, "Deferred or untested", ["PostgreSQL (implemented, untested)", "Windows and macOS packages", "Native Tauri/Electron shell", "Multi-process job workers", "Independent penetration test"]],
  ];
  st.forEach(([ic, col, t, items], i) => {
    const x = M + i * 4.1, y = 1.6, w = 3.85, h = 3.95;
    card(s, x, y, w, h, C.background2, "status card");
    iconCircle(s, I[ic], x + 0.3, y + 0.32, 0.8, col, t);
    txt(s, t, { x: x + 1.25, y: y + 0.42, w: w - 1.45, h: 0.6, fontSize: 20, bold: true, color: col, valign: "middle" });
    txt(s, bullets(items, { space: 10 }), { x: x + 0.3, y: y + 1.45, w: w - 0.55, h: 3.4, fontSize: 15 });
  });
  tintCard(s, M, 5.8, W - 2 * M, 0.85, C.accent4, 88, "takeaway strip");
  txt(s, 'Biggest adoption gates for team use: PostgreSQL validation and an independent penetration test.', { x: M + 0.3, y: 5.8, w: W - 2 * M - 0.6, h: 0.85, fontSize: 16, bold: true, color: C.accent4, valign: "middle" });
  s.addNotes("Atlas documents its own gaps. The core product is complete and tested. Partial items are mostly about breadth — " +
    "AI against a real model, OCR, more languages and finer permissions. The deferred column is what an adopter must weigh " +
    "for multi-user or high-assurance deployments: PostgreSQL validation and an independent penetration test.");

  // ======================================================================================= 23 roadmap
  s = slide("Content (tint)", "Suggested roadmap");
  const rm = [["Next release", C.accent1, ["Validate PostgreSQL end to end, add it to CI", "Run the AI assistants against a real local model", "Test OCR; build Windows and macOS packages"]],
    ["Following", C.accent2, ["Independent penetration test", "Per-project model allow-lists", "Finer field permissions; workflow parameter forms"]],
    ["Later", C.accent5, ["Multi-process job workers", "Resumable mid-file imports", "Polygon operations, richer offline basemaps"]]];
  s.addShape(pres.shapes.LINE, { x: M + 0.4, y: 2.25, w: W - 2 * M - 0.8, h: 0, line: { color: C.text2, width: 1.5, transparency: 40 }, objectName: "timeline" });
  rm.forEach(([t, col, items], i) => {
    const x = M + i * 4.1;
    s.addShape(pres.shapes.OVAL, { x: x + 0.25, y: 2.05, w: 0.4, h: 0.4, fill: { color: col }, line: { color: C.background1, width: 3 }, objectName: "milestone" });
    txt(s, t, { x: x + 0.25, y: 2.65, w: 3.6, h: 0.5, fontSize: 21, bold: true, color: col });
    card(s, x + 0.25, 3.3, 3.6, 2.6, C.background1, "roadmap card");
    txt(s, bullets(items, { space: 12 }), { x: x + 0.5, y: 3.55, w: 3.15, h: 2.6, fontSize: 15 });
  });
  txt(s, "Recommendations derived from the engineering report’s partial, deferred and risk items — not recorded commitments.",
    { x: M, y: 6.5, w: W - 2 * M, h: 0.4, fontSize: 12, color: C.text2, italic: true });
  s.addNotes("These priorities follow directly from the status matrix and risk list. The first horizon removes the biggest " +
    "adoption blockers for team deployments; the second raises assurance; the third improves scale. They are suggestions for " +
    "discussion, not commitments recorded in the repository.");

  // ======================================================================================= 24 closing
  section("Close");
  s = slide("Title (dark)");
  s.addImage({ data: stars, x: 7.75, y: 1.75, w: 5.2, h: 4.39, objectName: "constellation", transparency: 10 });
  s.addText("Offline. Explainable. Auditable.", { placeholder: "title" });
  s.addText("Try it: atlas serve  →  Projects  →  Create demo workspace", { placeholder: "body" });
  s.addText("Full detail: docs/overview/Project-Atlas-Technical-Overview.pdf  ·  docs/ in the repository", { placeholder: "meta" });
  s.addNotes("To close: Atlas keeps control local, keeps the evidence, explains every automated step and leaves judgement to " +
    "people. The fastest next step is the demo workspace. The 46-page technical overview PDF in docs/overview has every " +
    "detail behind these slides. Questions?");

  await pres.writeFile({ fileName: OUT });
  await writeTheme(OUT, THEME);
  console.log("wrote", OUT);
})().catch((e) => { console.error(e); process.exit(1); });
