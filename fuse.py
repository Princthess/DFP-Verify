"""
STAGE 3 - FUSE.

Rolls classified, verified datasets up to per-paper buckets:
  own_open  /  own_restricted  /  reused  /  own_unknown
Writes three tables:
  per_paper.csv      -- one row per paper (the rollup / headline counts)
  per_dataset.csv    -- one row per candidate, ALL of them incl. regex noise (audit dump)
  merged_output.csv  -- the WRAPPER's headline output: DFP's own CSV columns verbatim,
                        plus dv_* columns DFP-Verify adds. A strict superset of a
                        DFP row, so it drops straight into a DFP-shaped workflow. Rows DFP
                        found keep DFP's columns; rows only the regex pass found leave them
                        blank (= the id is regex-only, not in DFP's output). dv_disagreement
                        fires only when the two tools disagree, and says on what + who decided.
"""
import os, csv

# DFP's own per-dataset columns, in DFP's order (new LiteLLM DFP: cli.py `_CSV_COLUMNS`).
DFP_COLS = ["file", "paper_doi", "das_found", "ocr_page_count", "name", "repository",
            "identifier", "url", "license", "created_by_authors", "source_section",
            "notes", "is_open", "is_code", "is_supplementary", "vlm"]
# what the wrapper adds on top (dv_ = DFP-Verify; obvious at a glance).
DV_COLS  = ["dv_detected_by", "dv_found_in", "dv_found_in_all", "dv_in_das", "dv_verdict",
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
    if not dfp_found:                                       # detection disagreement
        parts.append(f"detect: regex-only, not in DFP (found by {c.get('source', 'regex')})")
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

def _placeholder_row(paper, paper_meta):
    """A 1:1 DFP-style row for a paper where nothing was surfaced -- DFP writes one such row
    per empty paper, so we mirror it (paper-level fields filled, dataset + dv_ fields blank)."""
    row = {col: "" for col in DFP_COLS + DV_COLS}
    pm = (paper_meta or {}).get(paper, {})
    for col in ("file", "paper_doi", "das_found", "ocr_page_count"):
        row[col] = pm.get(col, "") or ""
    if not row["file"]:
        row["file"] = paper
    return row

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
    row["dv_detected_by"]   = c.get("source", "")
    row["dv_found_in"]      = c.get("found_in", "")
    row["dv_found_in_all"]  = c.get("found_in_all", "")
    row["dv_in_das"]        = c.get("in_das", False)
    row["dv_verdict"]       = c.get("verdict", "")
    row["dv_status"]        = c.get("status", "")
    row["dv_confidence"]    = _confidence(c)
    row["dv_is_data"]       = (c.get("status") == "confirmed")   # registry-confirmed it IS data
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
    dataset_rows, paper_rows, merged_rows = [], [], []
    for p in sorted(papers):
        cands = per_paper.get(p, [])
        confirmed = [c for c in cands if c.get("status") == "confirmed"]
        likely    = [c for c in cands if str(c.get("status", "")).startswith("likely")]
        own_open  = [c for c in confirmed if c.get("provenance") == "own" and c.get("openness") == "open"]
        own_restr = [c for c in confirmed if c.get("provenance") == "own" and c.get("openness") != "open"]
        reused    = [c for c in confirmed if c.get("provenance") == "reused"]
        unknown   = [c for c in confirmed if c.get("provenance") == "unknown"]
        paper_merged = []
        for c in cands:
            dataset_rows.append({"paper": p, "identifier": c["identifier"], "kind": c["kind"],
                                 "source": c["source"], "found_in": c.get("found_in", ""),
                                 "found_in_all": c.get("found_in_all", ""), "in_das": c.get("in_das", False),
                                 "status": c.get("status", ""), "confidence": _confidence(c),
                                 "verdict": c.get("verdict", ""), "provenance": c.get("provenance", ""),
                                 "openness": c.get("openness", ""), "repository": c.get("repository", ""),
                                 "license": c.get("license", "")})
            # the DFP-shaped output carries DFP's rows + DFP-Verify's genuine additions,
            # but NOT pure regex noise (ref-list DOIs we neither confirmed nor saw declared).
            st = c.get("status", "")
            if c.get("_dfp") is not None or st == "confirmed" or st.startswith("likely"):
                paper_merged.append(_merged_row(c, p, paper_meta))
        # 1:1 with DFP: every paper gets at least one row -- a placeholder when nothing surfaced.
        merged_rows.extend(paper_merged or [_placeholder_row(p, paper_meta)])
        paper_rows.append({"paper": p, "has_own_open": len(own_open) > 0,
                           "own_open": len(own_open), "own_restricted": len(own_restr),
                           "reused": len(reused), "own_unknown": len(unknown),
                           "likely_unconfirmed": len(likely),
                           "n_confirmed": len(confirmed), "n_candidates": len(cands)})
    return paper_rows, dataset_rows, merged_rows

def write_outputs(paper_rows, dataset_rows, merged_rows, out_dir):
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "per_paper.csv"), "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["paper", "has_own_open", "own_open", "own_restricted",
                                          "reused", "own_unknown", "likely_unconfirmed",
                                          "n_confirmed", "n_candidates"])
        w.writeheader(); w.writerows(paper_rows)
    with open(os.path.join(out_dir, "per_dataset.csv"), "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["paper", "identifier", "kind", "source", "found_in",
                                          "found_in_all", "in_das", "status",
                                          "confidence", "verdict", "provenance", "openness",
                                          "repository", "license"])
        w.writeheader(); w.writerows(dataset_rows)
    with open(os.path.join(out_dir, "merged_output.csv"), "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=DFP_COLS + DV_COLS)
        w.writeheader(); w.writerows(merged_rows)
