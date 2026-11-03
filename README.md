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
Candidates are graded by how much the detectors agree:

1. **detect** (`detect_union.py`) — DFP's ids ∪ regex (DOIs, Swedish SND / SciLifeLab / DORIS
   prefixes, accessions, Zenodo / GitHub / OSF / data-repo URLs, split-line repair). Max recall.
2. **verify** (`verify.py`) — DOI → DataCite type-check, accession → archive API, URL → resolve.
   Deterministic, disk-cached.
   **registry links** (`registry_lookup.py`) — the reverse direction: which datasets does DataCite
   tie to *this paper*? The paper DOI is first checked (its record's title must match the first page;
   else DOIs on the first page, else a Crossref title search). Then DataCite records pointing at it are
   merged in: an id already in the text is corroborated (`linked`), a declared id that didn't resolve
   but is a near-miss of a linked DOI is repaired (`repaired`), and the rest are added as
   `not in text`. Version/concept DOIs of one dataset are collapsed. Disk-cached.
3. **classify** (`classify.py`) — provenance (own/reused) + openness. Own/reused priority: DataCite
   creators ∩ paper authors (authoritative) → own-verb in the evidence/DAS sentence → DFP's flag →
   references-location; otherwise `unknown` (never guessed).
4. **fuse** (`fuse.py`) — roll up to per-paper buckets + the headline `merged_output.csv`.

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
`merged_output.csv` (detail / audit), and `dfp_output.csv` (vanilla DFP). Registry lookups cache to
disk, so re-runs only do new work. Version B's most common failure is the LLM endpoint being
unreachable (VPN off) or a wrong model tag; DFP continues past any PDF that fails.

### Config variables (all live in `.env`; a shell `set DV_...` overrides)
| variable | required? | what |
|---|---|---|
| `DV_CONTACT_EMAIL` | recommended | your email, sent politely in registry API requests |
| `DV_DFP_CSV` / `DV_TEXT_DIR` | **yes (A)** | DFP's output CSV / folder of paper `.txt` |
| `DV_PDF_DIR` / `DV_DFP_DIR` | **yes (B)** | your PDFs / DFP install (the folder with `main.py`) |
| DFP's own `.env` (in `DV_DFP_DIR`) | **yes (B, litellm)** | `LITELLM_BASE_URL`, `VLM_MODEL` (+ `LITELLM_API_KEY` if needed) |
| `DV_BACKEND` | no | `litellm` (default) or `ollama` |
| `DV_MODEL` · `DV_OUT_DIR` · `DV_NO_REFS` | no | model override · output dir · skip DFP's references pass |

## Output

**`summary.csv` — the headline.** One row per paper, the *combined* verdict (no DFP-vs-regex
breadcrumbs — just the answer). Columns: `paper`, `doi`, `data_verdict`, `openness`, `datasets`,
`linked_via_datacite_not_in_paper`, `reuses_data`, `note`. `doi` is the title-checked paper DOI (the
`note` says when it was corrected or couldn't be confirmed). `linked_via_datacite_not_in_paper` lists
datasets that DataCite links to the paper but that the paper doesn't cite. They are reported for
transparency but **not counted as shared**: sharing means the paper tells the reader where its data
is. A paper with only such links gets the verdict **`no data in paper; dataset linked via DataCite`**. A dataset id
that *is* in the paper but didn't resolve as written (typo, PDF line-break) and matches a DataCite-linked
DOI does count, with a `note` saying so. `data_verdict` is one of **`shared own data`** (with `openness` = open /
restricted / unknown / mixed) · **`declared, unverifiable`** (stated in the data-availability statement
but the id doesn't resolve — a dead dataset DOI is itself a FAIR red flag) · **`reuses data only`** ·
**`no data in paper; dataset linked via DataCite`** (not counted as shared) · **`no data found`**. `datasets` lists every confirmed dataset tagged by provenance (`own:` / `reused:`),
plus `declared?:` for declared ids that didn't verify.

**`per_dataset.csv`** — one row per candidate, all of them incl. regex noise (the audit dump).

**`merged_output.csv` — the reconciliation / audit view.** A strict superset of a DFP row: DFP's 16
columns verbatim (`file … vlm`), then DFP-Verify's `dv_` columns. A blank DFP column = the id came from
the regex pass, not DFP. `dv_disagreement` names where the two tools differ and which signal decided
(e.g. `isdata: DFP=dataset, registry=not-data`); `dv_provenance_by` records the deciding signal per row.
`dv_paper_doi` is the title-checked paper DOI (= summary's `doi`; DFP's own `paper_doi` stays verbatim),
with `dv_paper_doi_check` = confirmed / corrected / found / unconfirmed.
`dv_registry` shows the DataCite reverse-lookup result per row: `linked` (in the text and linked in
DataCite) · `repaired (text had …)` · `not in text` (found only via DataCite; status `datacite-only`,
not counted) · blank (no link).
Open this when you want to see *why* a verdict came out the way it did.

**Status tiers** (inside the detail files): `confirmed` (registry says dataset/software) · `likely-*`
(declared in the DAS but unverifiable) · `not-data` (registry says cited article) · `noise` (unverified
reference). Detect is deliberately noisy — "14 verified of ~450 candidates" is the filter working, not
failing.

## Status & scope

Early-stage / experimental. Tested end-to-end on a 20-paper corpus (DFP with a 31B model,
cross-checked against Version A and a small local model).
Limits: identifier-less data ("on request", bare repo names) can only be *categorised*, not *verified*;
confirmed-dataset licences are often blank (DataCite's CSL feed omits them); open code is out of scope.
The wrapper changes no DFP code.

## Credits

The approach builds on ideas from open-data detection tools like **ODDPub**, with accession formats
from the **Bioregistry** (CC0). An optional LLM layer
(body-scan + provenance referee) was tested on a 31B model, added nothing over the deterministic core,
and was removed. Built with **AI assistance** (Anthropic Claude) under human review.
