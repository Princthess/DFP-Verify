# DFP-Verify

A deterministic **verification layer** for open-data detection. It takes the dataset candidates a
detector found in a paper and checks them against authoritative registries — confirming real datasets,
flagging cited articles mislabelled as data, and deciding own-vs-reused and open-vs-restricted. Per
paper it answers: **did the authors share their own data, and is it open?**

It sits on top of **[datasets-from-pdf (DFP)](https://github.com/ChalmersLibrary/datasets-from-pdf)** —
a separate LLM-based detector in its own repo. **None of DFP's code is in here;** this repo is only the
verification layer. Two ways to use it:

- **Version A — verify an existing DFP run.** You already have DFP's output CSV; DFP-Verify just
  verifies it, and nothing from DFP runs. *This is the core.*
- **Version B — one command.** DFP-Verify also runs DFP for you (it shells out to DFP's CLI via
  `dfp_live.py`, our adapter) and then verifies. Needs DFP installed; the verification is identical.

## How it works

DFP's LLM reads the data-availability and references sections; a regex pass covers the rest of the
full text, and everything is then **verified against registries** — which confirms the real datasets
and filters the false positives any LLM detector produces (e.g. a cited article read as data).
DataCite is also asked the reverse question — which datasets point at this paper? — to corroborate
ids, repair malformed ones, and report linked datasets the paper itself doesn't cite.
Candidates are graded by how much the detectors agree:

1. **detect** (`detect_union.py`) — DFP's ids ∪ regex (DOIs, Swedish SND / SciLifeLab / DORIS
   prefixes, accessions, Zenodo / GitHub / OSF / data-repo URLs, split-line repair). Max recall.
2. **verify** (`verify.py`) — DOI → DataCite type-check, accession → archive API, URL → resolve.
   Deterministic, disk-cached.
3. **registry links** (`registry_lookup.py`) — the reverse direction: which datasets does DataCite
   tie to *this paper*? The paper DOI is first checked (its record's title must match the first page;
   else DOIs on the first page, else a Crossref title search). Then DataCite records pointing at it are
   merged in: an id already in the text is corroborated (`linked`), a declared id that didn't resolve
   but is a near-miss of a linked DOI is repaired (`repaired`), a dataset whose landing page is cited
   instead of its DOI (e.g. an SND catalogue URL) is found by the identifier-like end of that URL
   (`linked (landing page in text)`), and the rest are reported as `not in text` — **not counted as
   shared** (see Output). Version/concept DOIs of one dataset are collapsed. Nothing here is
   repository-specific: what to look for comes from each DataCite record. Disk-cached.
4. **classify** (`classify.py`) — provenance (own/reused) + openness. Own/reused priority: ORCID
   overlap between dataset creators and paper authors → creator surnames on the paper's first page
   → own-verb in the evidence/DAS sentence → DFP's flag → references-location; otherwise `unknown`
   (never guessed). Licence and access right (open / restricted) come from the DataCite record;
   a `restrictedAccess` dataset is `restricted`.
   **field** (`fields.py`) — anchors each paper to a research field: its SSIF codes in Swepub (found by
   DOI; names from Swepub's own subject list), else OpenAlex's primary topic. Cached.
5. **fuse** (`fuse.py`) — roll up to per-paper verdicts: the headline `summary.csv` plus the audit
   files `per_dataset.csv` and `merged_output.csv`.

`sections.py` locates each id (das / body / supplement / references) with a regex heading locator —
the DAS-membership signal and a cheap provenance nudge.

## First-time setup

Do this once. Everything runs **inside the `DFP-Verify` folder** unless noted.

**1 — Get this repo + a Python environment**
```
git clone https://github.com/Princthess/DFP-Verify
cd DFP-Verify
python -m venv .venv
.venv\Scripts\activate            # Windows   (macOS/Linux: source .venv/bin/activate)
pip install -r requirements.txt
```

**2 — Make your config file.** Copy `.env.example` → `.env` and set `DV_CONTACT_EMAIL` to your email
(used politely in registry API calls). You'll add paths below.

**3 — Point it at DFP.** DFP is a *separate* tool — pick the path for what you'll run:

- **Only Version A** (verify an existing DFP output): you just need DFP's **output CSV** + its `.txt`
  texts. In `.env` set `DV_DFP_CSV` and `DV_TEXT_DIR` to those files. **Done — skip the rest.**
- **Version B** (run DFP yourself): clone DFP into a folder of your choice (anywhere, *outside* this repo):
  ```
  git clone https://github.com/ChalmersLibrary/datasets-from-pdf
  ```
  Then in `.env` set:
  - `DV_DFP_DIR` = the folder that contains DFP's `main.py`
  - `DV_PDF_DIR` = your folder of PDFs
  - and make sure **DFP's own `.env`** (the LiteLLM endpoint: `LITELLM_BASE_URL` / `VLM_MODEL` /
    optional `LITELLM_API_KEY`) sits *inside* `DV_DFP_DIR` — see DFP's own README.

## Running it

Once set up, activate the venv per session (`.venv\Scripts\activate`), then just:

```
python run_pipeline.py        # Version A — verify an existing DFP run   (no VPN)
python run_integrated.py      # Version B — run DFP + verify             (VPN on for the HPC endpoint)
```
(`run_integrated.py` also takes a PDF folder as an argument, overriding `DV_PDF_DIR`.)

**Results** land in `DV_OUT_DIR` (default `output/` for A, `output_integrated/` for B):
`summary.csv` (the headline — one row per paper, plain verdict), `per_dataset.csv` and
`merged_output.csv` (detail / audit), `selfcheck.csv` (detector self-test), and `dfp_output.csv`
(vanilla DFP). Registry lookups cache to
disk, so re-runs only do new work. Version B's most common failure is the LLM endpoint being
unreachable (VPN off) or a wrong model tag; DFP continues past any PDF that fails.

### Config variables (all live in `.env`; a shell `set DV_...` overrides)
| variable | required? | what |
|---|---|---|
| `DV_CONTACT_EMAIL` | recommended | your email, sent politely in registry API requests |
| `DV_DFP_CSV` / `DV_TEXT_DIR` | **yes (A)** | DFP's output CSV / folder of paper `.txt` |
| `DV_PDF_DIR` / `DV_DFP_DIR` | **yes (B)** | your PDFs / DFP install (the folder with `main.py`). `DV_PDF_DIR` is optional in A: used only to tell *why* a dataset id was broken |
| DFP's own `.env` (in `DV_DFP_DIR`) | **yes (B, litellm)** | `LITELLM_BASE_URL`, `VLM_MODEL` (+ `LITELLM_API_KEY` if needed) |
| `DV_BACKEND` | no | `litellm` (default) or `ollama` |
| `DV_MODEL` · `DV_OUT_DIR` · `DV_NO_REFS` | no | model override · output dir · skip DFP's references pass |

## Output

**`summary.csv` — the headline.** One row per paper, the *combined* verdict (no DFP-vs-regex
breadcrumbs — just the answer). Columns:

| column | what |
|---|---|
| `paper` · `doi` | the file, and its title-checked paper DOI (`note` says if it was corrected or unconfirmed) |
| `year` | publication year from the paper DOI's own metadata (blank when the DOI is unconfirmed) |
| `data_verdict` | one of the verdicts below |
| `openness` | for the authors' own data: open / restricted / unknown / mixed |
| `datasets` | every confirmed dataset the paper cites, tagged `own:` / `reused:`, plus `declared?:` for declared ids that didn't verify |
| `linked_via_datacite_not_in_paper` | datasets DataCite links to the paper that the paper does **not** cite — reported, **not counted** |
| `reuses_data` | yes / no |
| `field` · `field_source` | the paper's research field, for field normalisation: SSIF codes from the paper's Swepub record(s) (`swepub (SSIF)`); else SSIF codes from Swepub's own automatic classifier run on the title + abstract from OpenAlex (`swepub classify (SSIF, automatic)`, 3-digit level; on the corpus its top suggestion matched the manual Swepub area every time it suggested one, 14/16); else OpenAlex's automatic topic (`openalex (ASJC, automatic)`). Set for every paper with a checked DOI, with or without data. The SSIF area is the code's first digit |
| `note` | dead declared links, repaired ids, DataCite-only links, paper-DOI corrections |

`data_verdict`, in priority order:
- **`shared own data (open)`** — the paper points to its own data, and DataCite says it is open.
- **`shared own data (restricted access)`** — the paper points to its own data, deposited with a DOI
  and metadata but with access on conditions (e.g. personal data); also used when some of the
  paper's datasets are open and some restricted (`openness` = `mixed`). **Counts as shared**
  ("as open as possible, as closed as necessary"), but is never reported as open. Data "available on
  request" without a deposit do not count.
- **`shared own data (access unknown)`** — no access information in the metadata.
- **`declared, unverifiable`** — stated in the data-availability statement but the id doesn't resolve
  (a dead dataset DOI is itself a FAIR red flag).
- **`reuses data only`**
- **`no data in paper; dataset linked via DataCite`** — the paper cites no data, but DataCite links
  datasets to it. **Not counted as shared**: sharing means the paper tells the reader where its data is.
- **`no data found`**

A dataset id that *is* in the paper but didn't resolve as written (typo, PDF line-break) and matches a
DataCite-linked DOI **does** count, with a `note` showing the id as written and the registered DOI.

**`per_dataset.csv`** — one row per candidate, all of them incl. regex noise (the audit dump).
`repository` is the repository that registered the DOI (the DataCite client, e.g. *Swedish National
Data Service*, *Chalmers University of Technology / DORIS repository*, *SciLifeLab Data Repository*,
*Zenodo*); `publisher` is DataCite's publisher field, the responsible institution (e.g. *Chalmers
University of Technology* for all three Chalmers cases). The summary's `datasets` cell and
`dv_repository` use the repository. Its
`subject` column holds the dataset's own subjects from DataCite (SSIF from SND, FOS from many
repositories) — a cross-check against the paper's `field`, never the anchor.

**`merged_output.csv` — the reconciliation / audit view.** A strict superset of a DFP row: DFP's 16
columns verbatim (`file … vlm`), then DFP-Verify's `dv_` columns. A blank DFP column = the id came from
the regex pass or DataCite, not DFP (`dv_detected_by` says which). `dv_disagreement` names where the two tools differ and which signal decided
(e.g. `isdata: DFP=dataset, registry=not-data`); `dv_provenance_by` records the deciding signal per row.
`dv_paper_doi` is the title-checked paper DOI (= summary's `doi`; DFP's own `paper_doi` stays verbatim),
with `dv_paper_doi_check` = confirmed / corrected / found / unconfirmed. `dv_year`, `dv_field` /
`dv_field_source` repeat the paper's year and field on each row (same as summary's `year`, `field` /
`field_source`).
`dv_registry` shows the DataCite reverse-lookup result per row: `linked` (in the text and linked in
DataCite) · `repaired (text had …)` · `linked (landing page in text)` (cited by its landing-page URL;
counts) · `not in text` (found only via DataCite; status `datacite-only`, not counted) · blank (no link).
`dv_provenance_by` = `orcid-overlap` / `creator-overlap` / `own-verb` / `dfp-flag` / `location`.
Open this when you want to see *why* a verdict came out the way it did.

**`selfcheck.csv` — how well the text detectors did, measured automatically.** Datasets that DataCite
links to the paper *and* that the paper cites (DOI, malformed DOI, or landing page) are a small free
answer key: a detector should have found them. One row per such dataset: `cited_as`, `result` (`found`
/ `found, id broken` / `not found by text detectors`), `found_by` (DFP / regex), and for broken ids
`broken_id_cause`: `pdf-extraction` (the PDF itself has the right DOI — link target or text — and the
`.txt` extraction broke it) or `as-printed` (the published PDF prints a wrong id). The cause check reads
the PDFs, so set `DV_PDF_DIR` (optional in Version A). A summary also prints after each run. Biased to
data with DataCite backlinks (SND / Chalmers deposits); "on request" statements are not measured.

**Status tiers** (inside the detail files): `confirmed` (registry says dataset/software) · `likely-*`
(declared in the DAS but unverifiable) · `datacite-only` (linked to the paper in DataCite, not cited in
it; not counted) · `duplicate` (a web link to a dataset the same paper already cites by DOI, e.g.
`zenodo.org/records/N` next to `10.5281/zenodo.N`; matched on the link's id-like end against the DOI
and its DataCite landing page, so no per-repository rules) · `not-data` (registry says cited article)
· `noise` (unverified reference). Detect is
deliberately noisy — "15 confirmed of ~470 candidates" is the filter working, not failing.

### Dashboard (optional)

`dashboard/dashboard.qmd` is a Quarto + Plotly dashboard over `summary.csv` and `per_dataset.csv`. It
recomputes nothing and makes no lookups. It has three pages:
- **Overview**: share of papers sharing their own data, verdicts per publication year (count /
  percent), verdicts per SSIF area (a paper with codes in two areas counts in both; papers not in
  Swepub are grouped as *No SSIF field*, since OpenAlex topics don't map 1:1 onto SSIF), papers
  per year by access to their own data (open / restricted / mixed, plus DataCite-only and *no data
  found* so the denominator stays visible; count or percent), a heatmap of SSIF area × year whose
  cells show the share of papers sharing their own data (openly, or open + restricted; text "k/n",
  hover for the full breakdown), where own datasets are deposited, and (if `field_norm.csv` exists)
  own datasets vs all of DataCite per SSIF area — see *DataCite reference* below.
- **Tool check**: monitoring the tool itself. Which source found each dataset (DFP and regex, one of
  them, or only DataCite), the self-check score, and a to-do list of what to check by hand: broken
  ids (repaired, dead declared links, data statements without an id), rows where DFP and DFP-Verify
  differ, known datasets the text detectors didn't find, and paper-DOI corrections. Each row says
  what the issue means and what to do. Built from `per_dataset.csv`, `merged_output.csv` and
  `selfcheck.csv`.
- **Papers**: the summary table.

Every chart card has a **Data** tab next to the chart: the rows behind it as a table, plus CSV
downloads of the counts (as plotted) and of the rows. The tabs stay available when a card is
expanded. The to-do list and the papers table have the same CSV download.

```
pip install -r requirements-dashboard.txt          # plotly, pandas, jupyter (+ install Quarto)
QUARTO_PYTHON=.venv/bin/python quarto render dashboard/dashboard.qmd   # reads output/, or DV_OUT_DIR
```
The result is a self-contained `dashboard/dashboard.html` (not committed). Run on a whole
institution's full texts, the year chart shows the trend over time.

### DataCite reference per field (optional)

`python field_norm.py` asks DataCite for counts (no records are downloaded; about 40 requests) and
writes `output/field_norm.csv`: per SSIF area and publication year, how many DataCite datasets there
are, how many have restricted access (closed / restricted / embargoed access right) and how many state
a licence. Datasets get an area from their OECD Fields of Science subjects (SSIF is built on OECD FOS;
names come from Swepub's SSIF list, with the few OECD wordings that differ in `FOS_NAME`). Every area
is counted twice: all datasets, and without the area's largest repository.

It is a reference for **dataset openness**, not a field norm for **sharing**: DataCite holds datasets,
not the papers that shared nothing, so it can't give a share of papers. Other limits: only datasets
with a FOS subject count (many repositories, e.g. Zenodo, set none), and single registrants dominate
(figshare 46–92 % of five areas, the specimen registry DiSSCo 68 % of Natural sciences, at
2026-11-09). The dashboard shows the comparison on the Overview page when the file exists.

## Status & scope

Early-stage / experimental. Tested end-to-end on a 20-paper corpus (DFP with a 31B model,
cross-checked against Version A and a small local model).
Limits: identifier-less data ("on request", bare repo names) can only be *categorised*, not *verified*;
licences/access rights come from DataCite, so they're blank for data registered elsewhere (e.g.
accessions); ORCID matching only helps where both sides recorded ORCIDs; open code is out of scope.
Fields: a paper often has several SSIF codes (and several universities may classify it differently,
pooled here) — how to count multi-field papers is left to the analysis. Older records may carry SSIF
2011 codes. Paper and dataset subjects can disagree; both are shown with their source.
The DataCite reverse lookup needs the paper's own DOI (reports without one are skipped) and only sees
links a repository recorded in the dataset's metadata — SND and Chalmers' repository usually do,
Zenodo/figshare deposits often don't. No link found is not evidence of no data.
The wrapper changes no DFP code.

## Credits

The approach builds on ideas from open-data detection tools like **ODDPub**, with accession formats
from the **Bioregistry** (CC0). An optional LLM layer
(body-scan + provenance referee) was tested on a 31B model, added nothing over the deterministic core,
and was removed. Built with **AI assistance** (Anthropic Claude) under human review.
