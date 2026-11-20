# Output files

What each output file and column means. Back to the [README](../README.md).

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
| `work_type` | OpenAlex work type of the checked paper DOI (article, review, editorial …). Reported only: not used as a no-data signal (reviews and meta-analyses do produce data; editorials etc. are a question of what to count as a research article) |
| `no_data_signal` | the paper says it has no data of its own: the sentence found by pattern search (`stated in paper: "No new data were generated…"`; generic data-policy template phrasings). Empty otherwise |
| `no_data_llm` | reserved for an LLM's own judgment of the same question, to compare with `no_data_signal`; empty for now |
| `on_request_signal` | the paper says its data are available on request (`stated in paper: "Data will be made available on request."`): the data exist but are not deposited. Filled for every paper that says it, also papers that deposit some of their data. The sentence must be about giving out data, and not name a repository or identifier (a deposit with access on request is restricted access, i.e. shared) |
| `journal` | the journal the paper appeared in (CSL `container-title` of the paper DOI); blank for reports, blogs, papers without a confirmed DOI |
| `publisher` | the publisher (CSL `publisher` of the paper DOI), legal-form suffixes dropped ("Elsevier BV" → "Elsevier"); as the registry names it, no publisher list |
| `has_das` | `yes` if the paper has a data availability statement, by either `das_pattern` or `das_llm` |
| `das_pattern` | the statement's heading as written, found by pattern search (`statements.das_heading`): "Data availability (statement)", "Data accessibility", "Data and model availability statement", "Availability of data and materials", "Open Research" … written as a heading (capitalised, then a colon, a new sentence or a line end), so prose like "improves data availability" does not count |
| `das_llm` | DFP's own `das_found` (`yes` / `no`). Where the two differ, the report's Tool check lists the paper |
| `supplement_signal` | the paper says its data are in the article or its supplementary files (`stated in paper: "All data is provided within the article and supplementary material …"`). Monitored, **not counted as shared**: a supplement has no DOI of its own and is often a PDF, and journals and FAIR guidance advise a data repository instead (PLOS Open Science Indicators also report supplements separately from repositories). The sentence must say the *data* are in the article / supplement; a bare "supplementary material is available online" (attached to every supplement, figures included) does not count, nor a sentence that also names a repository |
| `supplement_llm` | the LLM's view of the same thing: names of the items DFP marked as supplementary material (`is_supplementary`). Broader than `supplement_signal` (it also lists supplements of figures or methods), shown side by side for comparison |
| `reuse_signal` | the paper says it uses data from elsewhere, by pattern search (`statements.reuse`): "we use data from two studies", "using data originally reported in …", "data were obtained / downloaded from …" (not from participants, measurements, samples …), "publicly available dataset", "secondary data". A signal only: `reuses_data` / the verdict count verified reuse |
| `reuse_llm` | the LLM's view: names of data DFP says the authors did not create (`created_by_authors` = false), software (`is_code`) left out. Often cited without an id (a benchmark, a public data file), so not verifiable; shown side by side with `reuse_signal` |
| `note` | dead declared links, repaired ids, DataCite-only links, paper-DOI corrections, a no-data statement in a paper that cites own data |

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
- **`own data in article / supplement only (not deposited)`** — the paper deposits nothing but says its
  data are in the article or its supplementary files (`supplement_signal`). **Not counted as shared**
  (no DOI of its own, often PDF); ranks above "on request" because the reader can download the files.
- **`own data on request only (not shared)`** — the paper deposits nothing but says its data are
  available on request (`on_request_signal`). **Not counted as shared.**
- **`reuses data only`**
- **`no data generated (paper says so)`** — no data found, and `no_data_signal` is set: the paper
  itself says it generated no data ("data sharing is not applicable …").
- **`cites data, own or reused unclear`** — the paper cites a verified dataset, but no signal says whose
  it is (no creator metadata or ORCID, no clear own/reuse sentence, no LLM judgement). Not counted as
  own; listed on Tool check. A sequencing run (ERR…/SRR…) whose study the paper also cites gets that
  study's own/reused first (ENA says which study a run belongs to).
- **`no data found`** — everything else without data: not shared, *or* no data; the tool can't tell
  which.

Datasets that DataCite links to the paper but the paper does not cite are **not part of the verdict**:
the verdict is about what the paper itself says. They are listed in `linked_via_datacite_not_in_paper`
and in `note`, and on the report's Tool check page.

A dataset id that *is* in the paper but didn't resolve as written (typo, PDF line-break) and matches a
DataCite-linked DOI **does** count, with a `note` showing the id as written and the registered DOI.

**`per_dataset.csv`** — one row per candidate, all of them incl. regex noise (the audit dump).
`repository` is the repository that registered the DOI (the DataCite client, e.g. *Swedish National
Data Service*, *Chalmers University of Technology / DORIS repository*, *SciLifeLab Data Repository*,
*Zenodo*); `publisher` is DataCite's publisher field, the responsible institution (e.g. *Chalmers
University of Technology* for all three Chalmers cases). The summary's `datasets` cell and
`dv_repository` use the repository. Its
`subject` column holds the dataset's own subjects from DataCite (SSIF from SND, FOS from many
repositories) — a cross-check against the paper's `field`, never the anchor. `zenodo_community` lists
the Zenodo communities of an own Zenodo dataset (`slug: title`, from Zenodo's API). The report counts a
community as the organisation's own when its title contains `DV_ORG_NAME` (e.g. `DV_ORG_NAME=Chalmers` in
`.env`), so department communities count too; there is no list of communities.

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
(declared in the DAS but unverifiable; `likely-wrong-type` = the paper's data statement gives it as its
data, but the registry types it as something else, e.g. a Zenodo upload typed "Journal article" or an OSF
project) · `software` also covers declared GitHub / GitLab / Bitbucket links whose description and path
don't mention data · `datacite-only` (linked to the paper in DataCite, not cited in
it; not counted) · `duplicate` (a web link to a dataset the same paper already cites by DOI, e.g.
`zenodo.org/records/N` next to `10.5281/zenodo.N`; matched on the link's id-like end against the DOI
and its DataCite landing page, so no per-repository rules) · `homepage` (a link to a repository's
front page, e.g. `https://snd.gu.se/en`, in a paper that also gives a confirmed record of its own data:
almost always the repository named next to its record. Only applied when an own record is confirmed, so
it never changes the verdict; listed on the report's Tool check page) · `software` (the registry types the record as Software and the paper's words about it don't mention
data, e.g. "Source code for: …": code, not data, so not counted and not in the summary. A Software record
the paper describes as holding data — "All code and associated data files are available from Zenodo",
typical for GitHub releases on Zenodo — stays `confirmed`) · `not-data` (registry says cited article)
· `noise` (unverified reference). Detect is
deliberately noisy — "15 confirmed of ~470 candidates" is the filter working, not failing.
