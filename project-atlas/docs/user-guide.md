# User guide

This walkthrough uses the **synthetic** Northwind Harbor dataset in `sample-data/` (all people,
organizations, contact details, documents and coordinates are fictional; every row carries
`record_origin=SYNTHETIC`). Expected results are in `sample-data/expected_results.json`.

## 1. First start and sign-in

1. Start Atlas (`atlas serve` or the desktop app) and open the UI.
2. On first run, paste the setup token from `atlas-workspace/setup-token.txt`, choose a username and a
   strong password (≥ 12 characters, three character classes). This creates the System Administrator.
3. Optional: *Settings → Multi-factor authentication* to enrol a TOTP authenticator.

The top bar shows the active project, global search (`/` to focus), jobs, alerts, the offline badge
(green = outbound network guard active), local AI availability and your identity. `?` lists keyboard
shortcuts (`g` then a letter jumps to a module, e.g. `g g` graph, `g s` search). Visited pages appear
as tabs; panels with a divider can be resized; theme, tabs, panel sizes and recent projects are
remembered in this browser.

## 2. Create a workspace and invite people

*Projects → New project* (system administrators). The default ontology is created automatically.
*Administration → Users* creates accounts; *Administration → Project members* assigns project roles:

| Role | Typical use |
|---|---|
| Project Administrator | membership, access policies, sensitive data, deletes |
| Data Engineer | imports, ontology, restricted datasets, entity resolution, data-writing workflows |
| Analyst | analysis, SQL, graph/geo annotations, investigations, reports, AI |
| Reviewer | match review, finding review, read access |
| Read-Only User | browse and search only |

## 3. Import data (Ingestion)

1. *Ingestion* → choose a permitted data source → select `synthetic_people.csv`.
2. **Inspect**: detected format, encoding, delimiter, inferred column types, preview.
3. **Map fields**: rename targets, set types (e.g. `email`, `phone`, `date`, `datetime` with a time zone),
   mark `required` and `sensitive` columns (email, phone, date_of_birth). Unique key: `person_id`.
4. **Entities & links**: add *Person* with name `full_name`, identifier `person_id`, attributes
   `email, phone, date_of_birth, city`; add *Organization* with identifier `employer_id` and namespace
   `org_id`; add relationship *Works for* from entity #0 to #1.
5. **Validate (dry run)**: nothing is written. Expect 1 duplicate row, 1 duplicate key, 1 invalid email.
6. **Confirm import** — a background job (progress in *Jobs*; cancel/retry available).

Repeat for `synthetic_organizations.csv` (organization, identifier `org_id`), `synthetic_contacts.csv`
(person by name only, attributes email/phone/city) and `synthetic_transactions.csv` (sender person,
receiver organization, *Transacted with* valid from `event_time`, events on `event_time`, map points on
latitude/longitude). The transactions dry run reports the planted timestamp and coordinate errors; rows
with invalid coordinates produce no map point (coordinates are never invented).

## 4. Data Catalog

Each dataset shows versions, records (toggle *normalized* vs *original source values*), schema with
completeness, quality issues, lineage (source file hash → mapping → derived entities/relationships)
and the ingestion report. Data engineers can import a new version (schema drift is reported);
project administrators can switch the access policy to *restricted* or delete the dataset (type its name).

## 5. Entity resolution

*Entity Explorer → Match review → Run entity resolution*. For the demo data expect:

* **strong**: *Dr. Amelia Okafor ↔ Amelia Okafor* (same e-mail), *Jon Mercer ↔ Jonathan Mercer* (same phone);
* **ambiguous**: *Lena Fisher ↔ Lena Fischer* (name only — needs human judgement);
* not proposed: the *Rafael Ortiz* contact whose phone conflicts with the person record.

Each card lists compared features, similarity per feature, conflicting fields and fields **not compared**
because a side is missing them. Choose which record survives, give a reason (audited), or reject.
*Merge history* can revert any merge.

## 6. Knowledge graph

Overview loads the best-connected nodes first; double-click to focus a node, set depth, filter by
relationship type and basis (*observed*, *inferred*, *model hypothesis*, *manual*), include unverified
hypotheses explicitly. Line styles encode the basis. Run degree/PageRank/betweenness centrality,
communities, components, or select two nodes (shift-click) for *shortest path*. Save snapshots (with layout)
and export GraphML/GEXF/JSON. Click an edge to see how it was created and its evidence records.

## 7. Search

Use the top bar or *Global Search*: `"Bluefjord Freight"`, `Okaf*`, `Mercer AND payment`,
`type:entity Okafor`, `amount>50000`. Filter by type, scope (active project / all your projects) and
indexed date. Save searches; recent queries are kept for 90 days and can be cleared.

## 8. Documents and the assistant

*Documents → Add documents* (PDF, DOCX, TXT, Markdown, EML). Each document gets pages/sections,
language, classification (keyword rules), keywords, entity candidates (unverified) and duplicate
detection. Ask *"Who approved the large payments?"*: the assistant quotes the audit report, page 2, and
labels the answer *direct evidence*. Ask about something absent and it declines. Open
`synthetic_suspicious_note.txt` to see how embedded instructions are flagged and ignored.

## 9. Timeline and map

*Timeline* shows events in your chosen display time zone (stored in UTC with the original text and
zone), clustering by gap, relationships active in a window, and a two-entity comparison (temporal
proximity is descriptive, not proof of interaction). *Geospatial Explorer* shows the offline basemap;
toggle layers, heatmap and clustering, filter by time, click in *radius* or *measure* mode, add
annotations, import `synthetic_districts.geojson` and run a spatial join.

## 10. Analytics and SQL

*Analytics → New analysis*: pick the transactions dataset and *Outlier detection* on `amount` — the two
planted large payments are flagged, with the disclaimer that outliers are not evidence of wrongdoing.
Every run records inputs and a result hash; *Runs & reproducibility → Reproduce* re-executes and compares.
*SQL console*: read-only queries over current dataset versions, e.g.
`select receiver_org_id, count(*), sum(amount) from transactions group by 1`.

## 11. Investigations

Create an investigation (objective, scope/authorization basis, classification), add collaborators, link
datasets/entities/snapshots, capture evidence (records or document passages — excerpts must be verbatim),
and write findings. Findings move *draft → under review → confirmed by reviewer / disputed / rejected →
superseded*; a different person with the reviewer permission must confirm, and confirmation requires
supporting evidence.

## 12. Workflows

Add nodes from the palette (dataset input, filter, join, dedupe, statistics, quality check, graph build,
document retrieval, entity resolution, export CSV, save as dataset, export report …), connect typed
ports, *Validate*, *Save* (new version each time), *Preview* (≤ 200 rows, no side effects) and *Run*
(side effects need confirmation; a failure rolls back data writes). Node results and logs are shown.

## 13. Reports

Compose sections (summary, methodology, dataset table, analysis, graph snapshot, timeline, map, findings,
evidence register, limitations, appendix), *Preview*, then export PDF/HTML/XLSX/CSV/JSON. Every export
includes a manifest (dataset versions and hashes, analysis parameters, software versions, timestamps,
redactions) and its SHA-256.

## 14. Audit and administration

*Audit Center*: filter events, verify the hash chain, write signed checkpoints, export CSV.
*Administration*: system status and offline verification, users (disable, reset tokens, revoke
sessions), members, ontology editor, backups (create/verify/restore preview/restore) and local AI models.
