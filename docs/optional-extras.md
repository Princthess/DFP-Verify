# Optional extras

None of these is needed for the main results (`summary.csv`). Each is a separate step you run only if you want it. Back to the [README](../README.md).

## Report (optional)

`dashboard/dashboard.qmd` builds a **report**: a static HTML page (Quarto dashboard layout + Plotly)
over one run's `summary.csv`, `per_dataset.csv`, `merged_output.csv` and `selfcheck.csv`. It is a
snapshot, not live data: it recomputes nothing and makes no lookups, and it changes only when the
pipeline runs again and the page is rendered again. The top line says which run it shows — date,
corpus and tool version, from `run_info.json`, which the pipeline writes next to the outputs (set
`DV_CORPUS` to name the corpus; otherwise the text folder's name is used). That is what makes yearly
reports comparable: keep each year's output folder and report, and note method changes between tool
versions.

Pages:
- **Overview**: a context line, value boxes (all percent of the papers that may have data of their
  own; papers saying they generated no data are left out), the data verdict per publication year,
  for all papers and per SSIF area (count / percent), licences of own datasets, papers that reuse
  others' data, and (if `field_norm.py` has run) own datasets vs what is usual in their repositories.
- **Infrastructure**: under which policies, in which repositories, and does the metadata reach the
  data? Data availability statement by verdict and per publisher, the verdict per publisher
  (publishers with fewer than 4 papers pooled), repositories with open / restricted datasets, whether
  each dataset's record links back to the paper, Zenodo communities, and (if `roagg_compare.py` has
  run) which own datasets RoAgg finds, why the others are missing, and what could improve for whom.
- **Tool check**: how far to trust the numbers. Which source found each dataset, the self-check score,
  and a to-do list of what to check by hand. Each row has a **possible cause** — the paper, the
  dataset's record, the paper list (given DOI), this tool, or **Unclear** (named only with evidence: the
  PDF, the registry record, two methods disagreeing) — who can act, and what it means / what to do.
- **Papers**: the summary table.

Every chart card has a **Data** tab next to the chart: the rows behind it as a table, plus CSV
downloads of the counts (as plotted) and of the rows.

```
pip install -r requirements-dashboard.txt          # plotly, pandas, jupyter (+ install Quarto)
QUARTO_PYTHON=.venv/bin/python quarto render dashboard/dashboard.qmd   # reads output/, or DV_OUT_DIR
# a second corpus into its own file:
DV_OUT_DIR=$PWD/output_mycorpus quarto render dashboard/dashboard.qmd --output dashboard_mycorpus.html
```
The result is `dashboard/dashboard.html` (not committed). Quarto writes an `--output` file to the repo
root; move it into `dashboard/`, next to `dashboard_files/`, which it shares.
## Comparison with RoAgg (optional)

[RoAgg](https://github.com/snd-sweden/roagg) (SND) lists an organisation's research outputs from DataCite
(+ OpenAIRE, Crossref) by ROR and name variants — metadata first, organisation level. DFP-Verify reads
the papers. `roagg_compare.py` puts the two side by side for the authors' **own** datasets only:

```
pip install roagg      # in its own environment; no dependencies
roagg --ror https://ror.org/040wg7k59 --name-txt chalmers.txt --source datacite --source openaire --source crossref --output roagg.csv
DV_ORG_NAME=Chalmers DV_ORG_ROR=https://ror.org/040wg7k59 python roagg_compare.py roagg.csv   # reads DV_OUT_DIR
```
→ `roagg_compare.csv`: each own dataset found in the papers, whether RoAgg lists it (and through what:
publisher / creator / contributor / funder), and if not, why — read from the dataset's DataCite record
(no organisation name or ROR in it; not a DOI; not in DataCite) or because the paper isn't the
organisation's (no affiliated author in OpenAlex). The other way round: RoAgg datasets whose record names
one of the papers but that the tool has no own dataset for, and why. Versions are counted once
(`conceptDoi`, figshare `.vN`). (`--source openalex` currently needs an OpenAlex API key for paging,
which RoAgg 2026.0.4 can't pass, so the run stops — leave it out.)

## Repository reference for dataset openness (optional)

`python field_norm.py` (after the pipeline) compares each own DataCite dataset with **the other
datasets in its own repository**, in the SSIF area of the paper that cites it. One measure, with
the pipeline's own rule on both sides: the share of datasets with **restricted access** (DataCite
access right closed / restricted / embargoed / metadata-only); everything else counts as open, also
when no access right is stated (recent Zenodo records, SciLifeLab). Licences are left out on purpose:
they answer what you may do with the data, not whether it is shared or open.
- The reference is the same repository + same SSIF area when the repository puts SSIF or OECD FOS
  subjects on its datasets (SND, DORIS; FOS names come from Swepub's SSIF list, with the few OECD
  wordings that differ in `FOS_NAME`) and has at least 20 datasets there; otherwise the whole
  repository (e.g. SciLifeLab, which uses ANZSRC subjects).
- Repositories up to 20,000 datasets are read record by record (sparse fields, 1,000 per page, so SSIF
  codes are matched exactly); bigger ones (Zenodo) are counted with DataCite's search on FOS subjects.
- Each dataset counts once: DOIs marked as a version of (*IsVersionOf*) or identical to
  (*IsIdenticalTo*, figshare's `.v1` twins) another DOI are left out, as the pipeline collapses versions.
- Accessions (ENA, PRIDE …) are not in DataCite and are not compared.

Writes `output/field_norm.csv` (reference per repository × area, and per whole repository) and
`output/field_norm_datasets.csv` (each own dataset with the reference it is compared to). The
report shows own vs usual per SSIF area on the Overview page when the files exist.

Why not all of DataCite: only a few registrants put field subjects on datasets (figshare is 44–90 %
of five areas, the specimen registry DiSSCo 74 % of Natural sciences, at 2026-11-09), so an
all-of-DataCite field figure mostly describes them. It is a reference for **dataset openness**, not a
norm for the share of **papers** that share data: DataCite holds no papers that shared nothing.
