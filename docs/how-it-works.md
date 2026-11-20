# How it works

The steps the pipeline runs, in order. Back to the [README](../README.md).

DFP's LLM reads the data-availability and references sections; a regex pass covers the rest of the
full text, and everything is then **verified against registries** — which confirms the real datasets
and filters the false positives any LLM detector produces (e.g. a cited article read as data).
DataCite is also asked the reverse question — which datasets point at this paper? — to corroborate
ids, repair malformed ones, and report linked datasets the paper itself doesn't cite.
Candidates are graded by how much the detectors agree:

1. **detect** (`detect_union.py`) — DFP's ids ∪ regex (DOIs, Swedish SND / SciLifeLab / DORIS
   prefixes, accessions, Zenodo / GitHub / OSF / data-repo URLs, split-line repair). Max recall.
2. **verify** (`verify.py`) — DOI → DataCite type-check, accession → archive API, URL → resolve.
   Only 404/410 count as a dead link; bot protection (e.g. figshare's AWS WAF challenge, HTTP 202) or
   no answer gives `unchecked link` (status `likely-unchecked`), to open by hand. A DOI is dead only
   when doi.org says 404/410; a rate limit or server error is retried next run, never cached as dead.
   An id that is dead as written but resolves without a glued tail (a footnote number or the next
   word: `bath-00739.28`, `…/tree/main.Rece`) is used without it, noted like a repair.
   A Zenodo record URL from the LLM is turned into its DOI, as the regex pass already does.
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
   → an explicit own-data phrase in the evidence/DAS sentence ("we deposited", "generated in this
   study", "our data"; not when the sentence names an outside source: "obtained from", "provided by")
   → DFP's flag → references-location; otherwise `unknown`
   (never guessed). Licence and access right (open / restricted) come from the DataCite record;
   a `restrictedAccess` dataset is `restricted`.
   **field** (`fields.py`) — anchors each paper to a research field: its SSIF codes in Swepub (found by
   DOI; names from Swepub's own subject list), else OpenAlex's primary topic. Cached.
5. **fuse** (`fuse.py`) — roll up to per-paper verdicts: the headline `summary.csv` plus the audit
   files `per_dataset.csv` and `merged_output.csv`.

`sections.py` locates each id (das / body / supplement / references) with a regex heading locator —
the DAS-membership signal and a cheap provenance nudge. `statements.py` finds what the paper itself
says about its data (no data generated, on request, in the supplement, reuse, the data-availability
heading) — the `*_signal` / `das_pattern` columns. `patterns.py` holds the identifier patterns shared
between steps; `net.py` the one HTTP session (User-Agent with your contact address) every registry call
uses; `selfcheck.py` the recall check against DataCite links.

## More limits

- ORCID matching only helps where both the paper and the dataset record carry ORCIDs; otherwise names on the first page decide.
- Fields: a paper often has several SSIF codes (and several universities may classify it differently, pooled here). How to count multi-field papers is left to the analysis. Older records may carry SSIF 2011 codes. Paper and dataset subjects can disagree; both are shown with their source.
- The DataCite reverse lookup skips reports without a DOI of their own.