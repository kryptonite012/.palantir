// End-to-end UI smoke test for Project Atlas.
// Usage: ATLAS_URL=http://127.0.0.1:8765 ATLAS_SETUP_TOKEN_FILE=/path/setup-token.txt SAMPLE_DIR=../sample-data node tests/e2e/smoke.mjs
// Drives the real UI in Chromium: initial setup, project creation, ingestion wizard, then every module page.
import { readFileSync, mkdirSync } from "node:fs";
import { createRequire } from "node:module";
import path from "node:path";

const require = createRequire(import.meta.url);
const { chromium } = require("playwright");

const BASE = process.env.ATLAS_URL ?? "http://127.0.0.1:8765";
const SAMPLE = process.env.SAMPLE_DIR ?? path.resolve("../sample-data");
const SHOTS = process.env.SHOT_DIR ?? "test-results/screens";
const PASSWORD = "Atlas-E2E-Passw0rd!";
mkdirSync(SHOTS, { recursive: true });

const errors = [];
const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
page.on("pageerror", (e) => errors.push(`pageerror: ${e.message}`));
page.on("console", (m) => { if (m.type() === "error" && !m.text().includes("401")) errors.push(`console: ${m.text()}`); });
const step = (s) => console.log(`• ${s}`);

async function api(method, url, body, isForm = false) {
  return page.evaluate(async ({ method, url, body }) => {
    const t = sessionStorage.getItem("atlas.token");
    const r = await fetch(url, { method, headers: { Authorization: `Bearer ${t}`, ...(body ? { "Content-Type": "application/json" } : {}) }, body: body ? JSON.stringify(body) : undefined });
    return { status: r.status, json: await r.json().catch(() => null) };
  }, { method, url, body });
}

await page.goto(BASE);
const needsSetup = await page.getByText("Initial setup").isVisible({ timeout: 5000 }).catch(() => false);
if (needsSetup) {
  step("initial administrator setup");
  const token = readFileSync(process.env.ATLAS_SETUP_TOKEN_FILE, "utf8").trim();
  await page.getByLabel("Setup token").fill(token);
  await page.getByLabel("Username").fill("admin");
  await page.getByLabel("Display name").fill("Atlas Administrator");
  await page.getByLabel("Password", { exact: true }).fill(PASSWORD);
  await page.getByLabel("Confirm password").fill(PASSWORD);
  await page.getByRole("button", { name: "Create administrator" }).click();
} else {
  step("sign in");
  await page.getByLabel("Username").fill("admin");
  await page.getByLabel("Password").fill(PASSWORD);
  await page.getByRole("button", { name: "Sign in" }).click();
}
await page.waitForSelector("nav[aria-label=Primary]");
await page.screenshot({ path: `${SHOTS}/00-home-empty.png` });

step("create project");
await page.goto(`${BASE}/projects`);
await page.getByLabel("Name").fill("Northwind Harbor Review");
await page.getByRole("button", { name: "Create project" }).click();
await page.waitForURL(`${BASE}/`);
await page.getByText("This project has no data yet").waitFor();

step("ingestion wizard: synthetic_people.csv");
await page.goto(`${BASE}/ingestion`);
await page.locator("input[type=file]").setInputFiles(path.join(SAMPLE, "synthetic_people.csv"));
await page.getByRole("button", { name: "Continue to mapping" }).click();
await page.getByRole("button", { name: "Continue", exact: true }).click();
await page.getByRole("button", { name: "+ Entity mapping" }).click();
const entityRow = page.locator("div.grid.grid-cols-6").first();
await entityRow.locator("select").nth(1).selectOption("full_name");
await entityRow.locator("select").nth(2).selectOption("person_id");
await page.getByRole("button", { name: "Run validation (dry run)" }).click();
await page.getByText("Validation results (nothing has been written)").waitFor();
await page.screenshot({ path: `${SHOTS}/01-ingest-dryrun.png`, fullPage: true });
await page.getByRole("button", { name: "Confirm import" }).click();
await page.getByText(/Imported 33 records into/).waitFor({ timeout: 30000 });

step("load remaining synthetic data through the API");
const pid = (await api("GET", "/api/projects")).json[0].id;
for (const [file, cfg] of [
  ["synthetic_organizations.csv", { dataset_name: "organizations", entities: [{ entity_type: "organization", name_field: "name", id_field: "org_id" }] }],
  ["synthetic_contacts.csv", { dataset_name: "contacts", entities: [{ entity_type: "person", name_field: "name", attributes: ["email", "phone", "city"] }] }],
  ["synthetic_transactions.csv", { dataset_name: "transactions",
    mapping: { txn_id: { target: "txn_id", type: "identifier" }, sender_id: { target: "sender_id", type: "identifier" }, receiver_org_id: { target: "receiver_org_id", type: "identifier" },
      amount: { target: "amount", type: "float" }, timestamp: { target: "event_time", type: "datetime" }, latitude: { target: "latitude", type: "latitude" },
      longitude: { target: "longitude", type: "longitude" }, city: { target: "city", type: "string" } },
    entities: [{ entity_type: "person", id_field: "sender_id", id_namespace: "person_id" }, { entity_type: "organization", id_field: "receiver_org_id", id_namespace: "org_id" }],
    relationships: [{ source: 0, target: 1, rel_type: "transacted_with", valid_from_field: "event_time" }],
    events: { time_field: "event_time", title_template: "Payment {txn_id}", category: "payment", entity: 0 },
    geo: { lat_field: "latitude", lon_field: "longitude", label_field: "txn_id" } }],
]) {
  const up = await page.evaluate(async ({ pid, name, content }) => {
    const fd = new FormData();
    fd.append("file", new Blob([content]), name);
    const r = await fetch(`/api/projects/${pid}/files`, { method: "POST", headers: { Authorization: `Bearer ${sessionStorage.getItem("atlas.token")}` }, body: fd });
    return r.json();
  }, { pid, name: file, content: readFileSync(path.join(SAMPLE, file), "utf8") });
  const job = await api("POST", `/api/projects/${pid}/ingest/commit`, { config: { file_id: up.id, ...cfg } });
  if (job.status !== 200) throw new Error(`import ${file} failed: ${JSON.stringify(job.json)}`);
}
for (const doc of ["synthetic_harbor_audit_report.pdf", "synthetic_memo_cold_storage.txt", "synthetic_suspicious_note.txt"]) {
  const up = await page.evaluate(async ({ pid, name, b64 }) => {
    const bin = Uint8Array.from(atob(b64), (c) => c.charCodeAt(0));
    const fd = new FormData();
    fd.append("file", new Blob([bin]), name);
    const r = await fetch(`/api/projects/${pid}/files`, { method: "POST", headers: { Authorization: `Bearer ${sessionStorage.getItem("atlas.token")}` }, body: fd });
    return r.json();
  }, { pid, name: doc, b64: readFileSync(path.join(SAMPLE, doc)).toString("base64") });
  await api("POST", `/api/projects/${pid}/documents`, { file_id: up.id });
}
// wait for background jobs
for (let i = 0; i < 60; i++) {
  const jobs = (await api("GET", `/api/jobs?project_id=${pid}`)).json;
  if (jobs.every((j) => !["queued", "running"].includes(j.status))) break;
  await page.waitForTimeout(500);
}

step("entity resolution + review in UI");
await page.goto(`${BASE}/entities`);
await page.getByRole("tab", { name: "Match review" }).click();
await page.getByRole("button", { name: "Run entity resolution" }).click();
await page.getByText(/score/).first().waitFor({ timeout: 20000 });
await page.screenshot({ path: `${SHOTS}/02-match-review.png`, fullPage: true });
page.once("dialog", (d) => d.accept("same e-mail address"));
await page.getByRole("button", { name: /Merge into “Amelia Okafor”|Merge into “Dr. Amelia Okafor”/ }).first().click();
await page.waitForTimeout(800);

const pages = [
  ["/", "03-home"], ["/catalog", "04-catalog"], ["/search?q=Okafor", "05-search"], ["/entities", "06-entities"],
  ["/graph", "07-graph"], ["/timeline", "08-timeline"], ["/geo", "09-geo"], ["/analytics", "10-analytics"],
  ["/documents", "11-documents"], ["/investigations", "12-investigations"], ["/workflows", "13-workflows"],
  ["/reports", "14-reports"], ["/audit", "15-audit"], ["/admin", "16-admin"], ["/settings", "17-settings"],
];
for (const [url, name] of pages) {
  step(`visit ${url}`);
  await page.goto(`${BASE}${url}`);
  await page.waitForLoadState("networkidle");
  await page.waitForTimeout(url === "/graph" || url === "/geo" ? 2500 : 600);
  await page.screenshot({ path: `${SHOTS}/${name}.png` });
}

step("dataset detail, graph algorithm, analysis, assistant, report export");
const ds = (await api("GET", `/api/projects/${pid}/datasets`)).json.find((d) => d.name === "transactions");
await page.goto(`${BASE}/catalog/${ds.id}`);
await page.getByRole("tab", { name: "Quality" }).click();
await page.getByText("timestamp_error").first().waitFor();
await page.screenshot({ path: `${SHOTS}/18-dataset-quality.png` });
await page.goto(`${BASE}/graph`);
await page.waitForTimeout(1500);
await page.getByRole("button", { name: "degree centrality" }).click();
await page.getByText(/graph.degree_centrality/).waitFor();
await page.screenshot({ path: `${SHOTS}/19-graph-centrality.png` });
await page.goto(`${BASE}/analytics`);
await page.getByLabel("Dataset (current version)").selectOption(ds.id);
await page.getByLabel("Analysis").selectOption("outliers");
await page.getByLabel("field").selectOption("amount");
await page.getByRole("button", { name: "Run", exact: true }).click();
await page.getByText(/not evidence of fraud/).waitFor();
await page.screenshot({ path: `${SHOTS}/20-analysis-outliers.png`, fullPage: true });
await page.goto(`${BASE}/documents`);
await page.getByPlaceholder(/Ask a question/).fill("Who approved the large payments?");
await page.getByRole("button", { name: "Ask", exact: true }).click();
await page.getByText("direct evidence").waitFor();
await page.screenshot({ path: `${SHOTS}/21-document-assistant.png`, fullPage: true });
await page.goto(`${BASE}/reports`);
await page.getByLabel("Report title").fill("Northwind Harbor synthetic review");
await page.getByRole("button", { name: "Save" }).click();
await page.waitForTimeout(500);
const [dl] = await Promise.all([page.waitForEvent("download"), page.getByRole("button", { name: "PDF" }).click()]);
console.log(`  downloaded ${await dl.suggestedFilename()}`);
await page.screenshot({ path: `${SHOTS}/22-reports.png`, fullPage: true });

await browser.close();
if (errors.length) {
  console.error("Browser errors:\n" + errors.join("\n"));
  process.exit(1);
}
console.log("UI smoke test passed");
