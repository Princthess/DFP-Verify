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
3. **classify** (`classify.py`) — provenance (own/reused) + openness. Own/reused priority: DataCite
   creators ∩ paper authors (authoritative) → own-verb in the evidence/DAS sentence → DFP's flag →
   references-location; otherwise `unknown` (never guessed).
4. **fuse** (`fuse.py`) — roll up to per-paper buckets + the headline `merged_output.csv`.

`sections.py` locates each id (das / body / supplement / references) with a regex heading locator —
the DAS-membership signal and a cheap provenance nudge.

## Run

**Version A — verify an existing DFP CSV** (just Python + `requests`; no DFP install):
```
pip install requests
# set TEXT_DIR (folder of .txt) and DFP_CSV (DFP's output) at the top of run_pipeline.py
python run_pipeline.py
```

**Version B — run DFP + verify, one command** (needs DFP installed + an LLM backend); run with DFP's own Python/venv:
```
set DV_PDF_DIR=C:\path\to\pdfs                 # REQUIRED: PDFs to process
set DV_DFP_DIR=C:\path\to\datasets-from-pdf    # REQUIRED: DFP's folder (the one with main.py)
python run_integrated.py                        # or: python run_integrated.py C:\path\to\pdfs
```
B extracts text with DFP's own extractor, runs DFP's CLI (**changes no DFP code**), then the identical
core. For the default `litellm` backend, DFP's own `.env` (`LITELLM_BASE_URL`, `VLM_MODEL`, optional
`LITELLM_API_KEY`) must point at a reachable endpoint — the same `.env` is all the LLM config. Most
common failure: endpoint unreachable (VPN) or a wrong model tag; DFP continues past any PDF that fails.

| variable | required? | what |
|---|---|---|
| `DV_PDF_DIR` / `DV_DFP_DIR` | **yes (B)** | PDF folder / DFP install (the folder with `main.py`) |
| DFP's `.env` | **yes (B, litellm)** | `LITELLM_BASE_URL`, `VLM_MODEL` (+ `LITELLM_API_KEY` if the endpoint needs one) |
| `TEXT_DIR` / `DFP_CSV` | **yes (A)** | the two CONFIG paths at the top of `run_pipeline.py` |
| `DV_BACKEND` | no | `litellm` (default) or `ollama` |
| `DV_MODEL` · `DV_OUT_DIR` · `DV_NO_REFS` · `DV_CONTACT_EMAIL` | no | model override · output dir · skip DFP's refs pass · registry-API contact email |

Tip: copy `.env.example` → `.env` to keep your email and paths in one file instead of setting them
each run (a shell variable still overrides the file).

Outputs in `DV_OUT_DIR`: `merged_output.csv` (headline), `per_paper.csv`, `per_dataset.csv`, and
`dfp_output.csv` (vanilla DFP). Registry/metadata lookups cache to disk, so re-runs only do new work.

## Output

`merged_output.csv` is the headline: **a strict superset of a DFP row** — DFP's 16 columns verbatim
(`file … vlm`), then DFP-Verify's `dv_` columns. At least one row per paper (a placeholder when empty).
A blank DFP column = the id came from the regex pass, not DFP's output. `dv_disagreement` names where
the two tools differ and which signal decided (e.g. `isdata: DFP=dataset, registry=not-data`);
`dv_provenance_by` records the deciding signal per row.

**Status tiers:** `confirmed` (registry says dataset/software) · `likely-*` (declared in the DAS but
unverifiable — a dead dataset DOI is itself a FAIR red flag) · `not-data` (registry says cited article)
· `noise` (unverified reference). Detect is deliberately noisy — "14 verified of ~450 candidates" is
the filter working, not failing.

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
