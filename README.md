# DFP-Verify

Answers, per paper: **did the authors share their own data, and is it open?**

Takes the dataset candidates that **[datasets-from-pdf (DFP)](https://github.com/ChalmersLibrary/datasets-from-pdf)**
found, adds a pattern search of the full text, and checks each candidate against public registries (DataCite,
doi.org, Crossref, ENA, PRIDE, NCBI): real dataset or not, the authors' own or reused, open or restricted.
No LLM runs here, and none of DFP's code is in this repo.

**Requirements**

- Python 3 (tested on 3.14)
- DFP's output CSV and the papers as `.txt` files (DFP writes both)

**Installation**

    git clone https://github.com/Princthess/DFP-Verify
    cd DFP-Verify
    python -m venv .venv
    .venv\Scripts\activate              (macOS/Linux: source .venv/bin/activate)
    pip install -r requirements.txt

Copy `.env.example` to `.env` and fill in the three lines at the top. The other settings are explained there.

**Usage**

- Verify a DFP run: `python run_pipeline.py`
- Run DFP first, then verify: `python run_integrated.py` (needs DFP and its LLM endpoint; see below)

Results go to `output/`. `summary.csv` has one row per paper with its verdict, e.g. `shared own data (open)`,
`own data on request only (not shared)` or `no data found`. Registry answers are cached, so a second run only
looks up what is new. All files and columns: [docs/output.md](docs/output.md). The steps: [docs/how-it-works.md](docs/how-it-works.md).

**Optional**

| | needs |
|---|---|
| Research field per paper (Swepub, OpenAlex). On by default; `DV_FIELDS=off` skips it | — |
| HTML report: `dashboard/dashboard.qmd` | Quarto, `requirements-dashboard.txt` |
| Comparison with RoAgg: `roagg_compare.py`. Work in progress: left out of the report unless rendered with `-M roagg:true` | RoAgg |
| Openness compared with the rest of each repository: `field_norm.py` | — |

How to run these: [docs/optional-extras.md](docs/optional-extras.md).

**Running DFP too**

Clone DFP outside this folder, then set `DV_DFP_DIR` (the folder with DFP's `main.py`) and `DV_PDF_DIR` in
`.env`. DFP needs its own `.env` with its LLM endpoint; see DFP's README. The most common failure is the
endpoint being unreachable (VPN off) or a wrong model name.

**Checking it works**

| | checks |
|---|---|
| `python -m unittest discover tests` | text reading and verdict rules, on made-up examples (no internet, 1 s) |
| `python check_apis.py` | that each outside service still answers as expected; names the step a failure affects (~15 s) |
| `python tests/compare_runs.py <before> <after>` | whether a code change moved any paper's result |

A service being down does not crash a run: failed lookups are not cached and are tried again next time.

**Status**

Early-stage. Tested on a 20-paper and a 78-paper corpus. Known limits:

- Data without an identifier ("on request", a repository name only) can be categorised, not verified.
- Licence and access come from DataCite, so they are blank for data registered elsewhere (e.g. accessions).
- The DataCite lookup needs the paper's DOI, and only sees links a repository recorded. SND and Chalmers'
  repository usually record them, Zenodo and figshare deposits often don't. No link is not evidence of no data.
- Open code is out of scope.

**Credits**

Builds on ideas from **ODDPub**; accession formats from the **Bioregistry** (CC0). An LLM layer (body scan +
provenance referee) was tested on a 31B model, added nothing over the deterministic core, and was removed.
Built with AI assistance (Anthropic Claude) under human review.
