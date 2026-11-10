"""
STAGE 3 - FUSE.

Rolls classified, verified datasets up to per-paper buckets:
  own_open  /  own_restricted  /  reused  /  own_unknown
Writes three tables:
  summary.csv        -- THE HEADLINE. One row per paper, plain combined verdict:
                        did the authors share their own data, is it open, which datasets.
                        No DFP-vs-regex breadcrumbs -- just the answer. Read this one.
                        `linked_via_datacite_not_in_paper` lists datasets DataCite ties to the paper
                        that the paper doesn't cite -- reported for transparency, NOT counted as
                        shared (verdict "no data in paper; dataset linked via DataCite").
  per_dataset.csv    -- one row per candidate, ALL of them incl. regex noise (audit dump).
  merged_output.csv  -- the audit view: DFP's own CSV columns verbatim, plus dv_* columns
                        DFP-Verify adds. A strict superset of a DFP row, so it drops straight
                        into a DFP-shaped workflow. Rows DFP found keep DFP's columns; rows
                        only the regex pass found leave them blank (= regex-only, not in DFP).
                        dv_disagreement fires only when the two tools disagree, and says on
                        what + who decided -- open this when you want the reconciliation.
"""
import os, csv

# DFP's own per-dataset columns, in DFP's order (new LiteLLM DFP: cli.py `_CSV_COLUMNS`).
DFP_COLS = ["file", "paper_doi", "das_found", "ocr_page_count", "name", "repository",
            "identifier", "url", "license", "created_by_authors", "source_section",
            "notes", "is_open", "is_code", "is_supplementary", "vlm"]
# what the wrapper adds on top (dv_ = DFP-Verify; obvious at a glance).
DV_COLS  = ["dv_paper_doi", "dv_paper_doi_check", "dv_year", "dv_field", "dv_field_source", "dv_detected_by", "dv_registry", "dv_found_in", "dv_found_in_all", "dv_in_das", "dv_verdict",
            "dv_status", "dv_confidence", "dv_is_data", "dv_provenance", "dv_provenance_by",
            "dv_openness", "dv_repository", "dv_license", "dv_disagreement"]

def _confidence(c):
    """3-way detector agreement -> confidence. Found by >1 detector or declared in the DAS = stronger."""
    if c.get("status") == "confirmed":
        return "high" if ("+" in c.get("source", "") or c.get("in_das")) else "medium"
    if str(c.get("status", "")).startswith("likely"):
        return "low"
    return ""

def _disagreement(c):
    """Human-readable audit string: empty when DFP and DFP-Verify agree, else names
    each axis they differ on and WHO resolved it. This is the column you scan to spot-check."""
    parts = []
    dfp_found = c.get("_dfp") is not None
    st = c.get("status", "")
    reg = c.get("registry", "")
    src = c.get("source", "regex")
    if not dfp_found and src != "datacite":                 # detection disagreement (DataCite-only
        only = "regex-only, " if src == "regex" else ""     # rows are shown in dv_registry instead)
        parts.append(f"detect: {only}not in DFP (found by {src})")
    if reg.startswith("repaired"):                          # text id didn't resolve; registry DOI used
        parts.append(f"id: {reg}, registered DOI used")
    if dfp_found and st == "not-data":                      # is-it-data disagreement (our registry gate)
        parts.append("isdata: DFP=dataset, registry=not-data")
    flag = c.get("created_by_authors")                      # provenance disagreement
    dfp_prov = "own" if flag is True else ("reused" if flag is False else "")
    dv_prov  = c.get("provenance", "")
    if dfp_found and dfp_prov and dv_prov in ("own", "reused") and dfp_prov != dv_prov:
        parts.append(f"prov: DFP={dfp_prov}, DV={dv_prov} (by {c.get('provenance_by', '?')})")
    dfp_open = c.get("is_open")                             # openness disagreement
    dv_open  = c.get("openness", "")
    if dfp_found and dfp_open is not None and dv_open in ("open", "restricted"):
        dfp_o = "open" if dfp_open else "restricted"
        if dfp_o != dv_open:
            parts.append(f"open: DFP={dfp_o}, DV={dv_open}")
    return "; ".join(parts)

# ---- summary.csv: the plain per-paper verdict (the combined answer, no tool breadcrumbs) ----

REG_ONLY_VERDICT = "no data in paper; dataset linked via DataCite"
NO_DATA_STATED = "no data generated (paper says so)"
ON_REQUEST = "own data on request only (not shared)"

SHARED_ACCESS = {"open": "open", "restricted": "restricted access", "mixed": "restricted access",
                 "unknown": "access unknown"}

def _summary_label(own, likely, reused, reg_only=(), openness="", no_data="", on_request=""):
    """One per-paper verdict. The authors' own data is the headline question, so it wins;
    a declared-but-dead link ranks above pure reuse (an unverifiable DAS claim is itself a signal).
    DataCite-only links never count as sharing; they only replace a bare 'no data found'.
    A no-data statement (nodata.py: the paper says no data were generated) also only replaces a bare
    'no data found' -- it splits "not shared, or no data" in two.
    "Available on request" (nodata.on_request) means the authors have data but did not deposit it: not
    shared, but about their OWN data, so it ranks above reuse; shared own data and a declared id win.
    Shared data with restricted access (deposited, access on conditions -- e.g. personal data) still
    counts as shared, but the verdict always says so: 'shared own data (restricted access)'.
    'mixed' (some open, some restricted) is labelled restricted access; `openness` says mixed."""
    if own:      return f"shared own data ({SHARED_ACCESS.get(openness, 'access unknown')})"
    if likely:   return "declared, unverifiable"
    if on_request: return ON_REQUEST
    if reused:   return "reuses data only"
    if reg_only: return REG_ONLY_VERDICT
    if no_data:  return NO_DATA_STATED
    return "no data found"

def _own_openness(own_open, own_restr, unknown):
    """Openness of the authors' OWN data (blank when they shared none)."""
    if own_open and (own_restr or unknown): return "mixed"
    if own_open:  return "open"
    if own_restr: return "restricted"
    if unknown:   return "unknown"
    return ""

def _dataset_cell(confirmed, likely):
    """Compact, provenance-tagged list for the summary cell, e.g.
    'own: Zenodo:10.5281/zenodo.123; reused: GEO:GSE456; declared?: 10.x/dead'."""
    def fmt(tag, c):
        repo = c.get("repository") or c.get("kind", "")
        idv  = c.get("identifier", "")
        return f"{tag}: {repo}:{idv}" if repo else f"{tag}: {idv}"
    tag = {"own": "own", "reused": "reused"}
    parts =  [fmt(tag.get(c.get("provenance", ""), "?"), c) for c in confirmed]
    parts += [fmt("declared?", c) for c in likely]
    return "; ".join(parts)

def _summary_row(paper, paper_meta, confirmed, own_open, own_restr, unknown, reused, likely, reg_only):
    """reg_only = datasets DataCite ties to the paper but the paper doesn't cite. Listed in their
    own column and NOT counted in the verdict -- the paper itself doesn't share them."""
    pm = (paper_meta or {}).get(paper, {})
    own = own_open or own_restr or unknown
    notes = []
    # surface a dead declared link even when the headline verdict is something else
    if likely and (own or reused): notes.append(f"{len(likely)} declared id(s) did not resolve")
    for c in confirmed:
        if c.get("registry", "").startswith("repaired"):
            written, reg = c["registry"][len("repaired (text had "):-1], c["identifier"]
            cause = c.get("id_cause", "")
            if cause == "as-printed":
                notes.append(f"the paper itself prints a wrong dataset id ({written}); registered DOI is {reg}")
            elif cause == "pdf-extraction":
                notes.append(f"dataset id broken by PDF text extraction ({written}); the PDF itself has {reg}")
            else:
                notes.append(f"id in paper did not resolve as written ({written}), matched to registered {reg}")
    if reg_only:
        n = len(reg_only)
        notes.append(f"Not counted as shared: DataCite links {n} dataset{'s' if n > 1 else ''} to this paper, "
                     f"but the paper does not cite {'them' if n > 1 else 'it'}")
    nd = pm.get("no_data_signal", "")
    if nd and (own or likely):
        notes.append("check: the paper says it has no data of its own, yet cites own/declared data")
    st = pm.get("doi_status", "")
    if st == "corrected":   notes.append(f"paper DOI corrected by title check (given: {pm.get('paper_doi') or 'none'})")
    if st == "found":       notes.append("paper DOI found by title check (none given)")
    if st == "unconfirmed": notes.append("paper DOI not confirmed by title check; DataCite links not looked up")
    return {
        "paper":         pm.get("file") or paper,
        "doi":           _paper_doi_cols(pm)["dv_paper_doi"],
        "year":          pm.get("year", ""),
        "data_verdict":  _summary_label(own, likely, reused, reg_only,
                                        openness=_own_openness(own_open, own_restr, unknown), no_data=nd,
                                        on_request=pm.get("on_request_signal", "")),
        "openness":      _own_openness(own_open, own_restr, unknown),
        "datasets":      _dataset_cell(confirmed, likely),
        "linked_via_datacite_not_in_paper": "; ".join(f"{c.get('provenance') or '?'}: {c.get('repository') or 'DataCite'}:"
                                   f"{c['identifier']}" for c in reg_only),
        "reuses_data":   "yes" if reused else "no",
        "field":         pm.get("field", ""),
        "field_source":  pm.get("field_source", ""),
        "work_type":     pm.get("work_type", ""),
        # pattern search now; an LLM's own judgment goes in no_data_llm (empty for now)
        "no_data_signal": nd,
        "no_data_llm":   pm.get("no_data_llm", ""),
        # filled for every paper that says it, also when it shares other data (partial sharing)
        "on_request_signal": pm.get("on_request_signal", ""),
        "note":          "; ".join(notes),
    }

def _placeholder_row(paper, paper_meta):
    """A 1:1 DFP-style row for a paper where nothing was surfaced -- DFP writes one such row
    per empty paper, so we mirror it (paper-level fields filled, dataset + dv_ fields blank)."""
    row = {col: "" for col in DFP_COLS + DV_COLS}
    pm = (paper_meta or {}).get(paper, {})
    for col in ("file", "paper_doi", "das_found", "ocr_page_count"):
        row[col] = pm.get(col, "") or ""
    if not row["file"]:
        row["file"] = paper
    row.update(_paper_doi_cols(pm))
    return row

def _paper_doi_cols(pm):
    """The title-checked paper DOI (same value as summary.csv's `doi`), next to DFP's verbatim
    paper_doi column. check: confirmed / corrected / found / unconfirmed."""
    st = pm.get("doi_status", "")
    doi = pm.get("dv_paper_doi") if st in ("confirmed", "corrected", "found") else pm.get("paper_doi")
    return {"dv_paper_doi": doi or "", "dv_paper_doi_check": st,          # paper-level, repeated per row
            "dv_year": pm.get("year", ""), "dv_field": pm.get("field", ""), "dv_field_source": pm.get("field_source", "")}

def _merged_row(c, paper, paper_meta):
    """One DFP-superset row for a candidate: DFP's columns verbatim (blank if the id is regex-only)
    + the dv_ additions."""
    dfp = c.get("_dfp")
    row = {col: "" for col in DFP_COLS}
    if dfp:
        for col in DFP_COLS:
            v = dfp.get(col, "")
            row[col] = "" if v is None else v
    row["identifier"] = c["identifier"]                     # always the row key, even for regex-only rows
    pm = (paper_meta or {}).get(paper, {})
    if not row["file"]:      row["file"] = pm.get("file") or paper
    if not row["paper_doi"]: row["paper_doi"] = pm.get("paper_doi") or ""
    # For rows DFP didn't produce (regex / llm-body mentions), surface whatever the candidate carries
    # -- notably `evidence` = the sentence that triggered an id-less mention, mirroring DFP's column.
    if not row["name"]:       row["name"] = c.get("name", "")
    if not row["repository"]: row["repository"] = c.get("repo_hint", "")
    if not row["license"]:    row["license"] = c.get("license_hint", "")
    if not row["notes"]:      row["notes"] = c.get("evidence", "")   # DFP's evidence col is 'notes'
    if row["created_by_authors"] == "" and c.get("created_by_authors") is not None:
        row["created_by_authors"] = c["created_by_authors"]
    row.update(_paper_doi_cols(pm))
    row["dv_detected_by"]   = c.get("source", "")
    row["dv_registry"]      = c.get("registry", "")
    row["dv_found_in"]     = c.get("found_in", "")
    row["dv_found_in_all"]  = c.get("found_in_all", "")
    row["dv_in_das"]        = c.get("in_das", False)
    row["dv_verdict"]       = c.get("verdict", "")
    row["dv_status"]        = c.get("status", "")
    row["dv_confidence"]    = _confidence(c)
    row["dv_is_data"]       = c.get("status") in ("confirmed", "datacite-only")   # registry: it IS data
    row["dv_provenance"]    = c.get("provenance", "")
    row["dv_provenance_by"] = c.get("provenance_by", "")
    row["dv_openness"]      = c.get("openness", "")
    row["dv_repository"]    = c.get("repository", "")
    row["dv_license"]       = c.get("license", "")
    row["dv_disagreement"]  = _disagreement(c)
    return row

def fuse(per_paper, paper_meta=None):
    paper_meta = paper_meta or {}
    papers = set(per_paper) | set(paper_meta)              # every paper DFP saw, for 1:1 placeholders
    dataset_rows, paper_rows, merged_rows, summary_rows = [], [], [], []
    for p in sorted(papers):
        cands = per_paper.get(p, [])
        confirmed = [c for c in cands if c.get("status") == "confirmed"]
        likely    = [c for c in cands if str(c.get("status", "")).startswith("likely")]
        reg_only  = [c for c in cands if c.get("status") == "datacite-only"]   # reported, not counted
        own_open  = [c for c in confirmed if c.get("provenance") == "own" and c.get("openness") == "open"]
        own_restr = [c for c in confirmed if c.get("provenance") == "own" and c.get("openness") != "open"]
        reused    = [c for c in confirmed if c.get("provenance") == "reused"]
        unknown   = [c for c in confirmed if c.get("provenance") == "unknown"]
        paper_merged = []
        for c in cands:
            dataset_rows.append({"paper": p, "identifier": c["identifier"], "kind": c["kind"],
                                 "source": c["source"], "registry": c.get("registry", ""),
                                 "found_in": c.get("found_in", ""),
                                 "found_in_all": c.get("found_in_all", ""), "in_das": c.get("in_das", False),
                                 "status": c.get("status", ""), "confidence": _confidence(c),
                                 "verdict": c.get("verdict", ""), "provenance": c.get("provenance", ""),
                                 "openness": c.get("openness", ""), "repository": c.get("repository", ""),
                                 "publisher": c.get("publisher", ""), "license": c.get("license", ""), "subject": c.get("subject", "")})
            # the DFP-shaped output carries DFP's rows + DFP-Verify's genuine additions,
            # but NOT pure regex noise (ref-list DOIs we neither confirmed nor saw declared).
            st = c.get("status", "")
            if c.get("_dfp") is not None or st in ("confirmed", "datacite-only") or st.startswith("likely"):
                paper_merged.append(_merged_row(c, p, paper_meta))
        # 1:1 with DFP: every paper gets at least one row -- a placeholder when nothing surfaced.
        merged_rows.extend(paper_merged or [_placeholder_row(p, paper_meta)])
        paper_rows.append({"paper": p, "has_own_open": len(own_open) > 0,
                           "own_open": len(own_open), "own_restricted": len(own_restr),
                           "reused": len(reused), "own_unknown": len(unknown),
                           "likely_unconfirmed": len(likely), "datacite_only": len(reg_only),
                           "n_confirmed": len(confirmed), "n_candidates": len(cands)})
        summary_rows.append(_summary_row(p, paper_meta, confirmed,
                                         own_open, own_restr, unknown, reused, likely, reg_only))
    return summary_rows, paper_rows, dataset_rows, merged_rows

def write_outputs(summary_rows, dataset_rows, merged_rows, out_dir):
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "summary.csv"), "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["paper", "doi", "year", "data_verdict", "openness",
                                          "datasets", "linked_via_datacite_not_in_paper",
                                          "reuses_data", "field", "field_source", "work_type", "no_data_signal",
                                          "no_data_llm", "on_request_signal", "note"])
        w.writeheader(); w.writerows(summary_rows)
    with open(os.path.join(out_dir, "per_dataset.csv"), "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["paper", "identifier", "kind", "source", "registry", "found_in",
                                          "found_in_all", "in_das", "status",
                                          "confidence", "verdict", "provenance", "openness",
                                          "repository", "publisher", "license", "subject"])
        w.writeheader(); w.writerows(dataset_rows)
    with open(os.path.join(out_dir, "merged_output.csv"), "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=DFP_COLS + DV_COLS)
        w.writeheader(); w.writerows(merged_rows)
