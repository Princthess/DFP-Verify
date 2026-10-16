"""
ORCHESTRATOR - detect-union -> verify -> fuse/tier, end to end.

Edit the CONFIG block for your corpus. Inputs:
  TEXT_DIR    folder of paper .txt files   (drives the regex detector)
  DFP_CSV     the LLM detector's output     (optional; adds LLM candidates)
Outputs: OUT_DIR/per_paper.csv, per_dataset.csv, merged_output.csv ; DOI/accession checks cached.
"""
import os, re, csv, glob
import config; config.load_env()   # read a local .env into os.environ before the core modules read it
import detect_union, verify, fuse, classify, sections

# ----------------------------------- CONFIG -----------------------------------
TEXT_DIR   = r"path/to/paper_txt"            # folder of per-paper .txt (the regex detector's input)
DFP_CSV    = r"path/to/dfp_output.csv"       # DFP's own output CSV
OUT_DIR    = os.path.join(os.path.dirname(__file__), "output")
CACHE      = os.path.join(os.path.dirname(__file__), ".verify_cache.json")
# ----------------------------------------------------------------------------------

def stem(s): return os.path.splitext(os.path.basename(str(s).replace("\\", "/")))[0].lower()

def main(text_dir=None, dfp_csv=None, out_dir=None, cache=None):
    """Run the shared core. Paths resolve: explicit arg > env (DV_TEXT_DIR / DV_DFP_CSV /
    DV_OUT_DIR, e.g. from a .env) > the CONFIG block. So `python run_pipeline.py` works with a
    .env or an edited CONFIG; the integrated wrapper (run_integrated.py) passes its own paths."""
    TEXT_DIR   = text_dir or os.environ.get("DV_TEXT_DIR") or globals()["TEXT_DIR"]
    DFP_CSV    = dfp_csv   or os.environ.get("DV_DFP_CSV") or globals()["DFP_CSV"]
    OUT_DIR    = out_dir   or os.environ.get("DV_OUT_DIR") or globals()["OUT_DIR"]
    CACHE      = cache     if cache is not None else globals()["CACHE"]
    # LLM source grouped by paper; paper_doi for author lookup; paper_meta carries DFP's
    # paper-level fields (incl. das_found) so the DFP-superset can emit a 1:1 placeholder
    # row for every paper DFP saw, even one where nothing was found.
    dfp_by, paper_doi, paper_meta = {}, {}, {}
    if DFP_CSV and os.path.exists(DFP_CSV):
        for r in csv.DictReader(open(DFP_CSV, encoding="utf-8-sig", newline="")):
            # The new (LiteLLM) DFP renamed columns: pdf->file, ocr_pages->ocr_page_count, +vlm.
            # Normalise so BOTH the old and new DFP CSVs feed the rest of the pipeline unchanged.
            r.setdefault("file", r.get("pdf") or r.get("source_json") or "")
            r.setdefault("ocr_page_count", r.get("ocr_pages") or "")
            r.setdefault("vlm", "")
            p = stem(r.get("file") or r.get("pdf") or r.get("source_json"))
            dfp_by.setdefault(p, []).append(r)
            pd = (r.get("paper_doi") or "").strip()
            if pd and p not in paper_doi: paper_doi[p] = pd
            if p not in paper_meta:
                paper_meta[p] = {k: (r.get(k) or "") for k in
                                 ("file", "paper_doi", "das_found", "ocr_page_count")}
    # DAS signal comes from DFP's source_section + a DAS-heading locator (sections.py) -- no R, no ODDPub.

    # STAGE 1: detect-union per paper (carries each detector's own/reused + open attrs)
    per_paper, all_cands, header = {}, [], {}
    for txt in glob.glob(os.path.join(TEXT_DIR, "*.txt")):
        p = stem(txt)
        text = open(txt, encoding="utf-8", errors="ignore").read()
        header[p] = text[:2500]                       # first-page author block (for own/reused)
        cands = detect_union.union_detect(text=text, dfp_rows=dfp_by.get(p, []))
        # in-text provenance: locate each id against the DAS / reference / supplement landmarks.
        # DAS region is found by the heading locator; DFP's own source_section also counts.
        ntext = detect_union.normalize_text(text); ntext_lc = ntext.lower()
        bounds = sections.segment(ntext, with_das=True)
        for c in cands:
            pos = sections.find_positions(ntext_lc, c["identifier"], c.get("kind", ""))
            primary, alllab = sections.locate(pos, bounds, dfp_section=c.get("location", ""))
            c["found_in"] = primary
            c["found_in_all"] = ";".join(sorted(alllab, key=lambda x: sections.PRIORITY.get(x, 9)))
            # DAS membership: the heading locator OR DFP's own source_section, so a DAS-declared-
            # but-dead DOI is tiered 'likely-broken', not 'noise'.
            dfp_das = c.get("location", "") == "data_availability_statement"
            c["in_das"] = ("das" in alllab) or dfp_das
        per_paper[p] = cands; all_cands.extend(cands)
    n_das = sum(1 for c in all_cands if c.get("in_das"))
    from collections import Counter
    loc = Counter(c.get("found_in", "") for c in all_cands)
    print(f"STAGE 1 detect-union: {len(per_paper)} papers, {len(all_cands)} candidates ({n_das} in DAS)")
    print(f"  in-text location: " + " | ".join(f"{k}:{v}" for k, v in loc.most_common()))

    # STAGE 2: verify (cached)
    print("STAGE 2 verify:")
    verify.verify_candidates(all_cands, cache_path=CACHE)   # mutates candidate dicts in place

    # STAGE 2b/3a: classify each VERIFIED dataset -> provenance + openness
    print("STAGE classify:")
    meta = classify.MetaCache(os.path.join(os.path.dirname(__file__), ".meta_cache.json"))
    n = 0
    for p, cands in per_paper.items():
        hdr = header.get(p, "")
        for c in cands:
            c["status"] = classify.status(c)
            if c["status"] == "confirmed" or c["status"].startswith("likely"):
                rec = meta.record(c["identifier"]) if c["kind"] == "doi" else {}
                c["provenance"], c["openness"] = classify.classify(
                    c, rec.get("creators", []), hdr, found_in=c.get("found_in", ""))
                c["repository"] = rec.get("publisher") or c.get("repo_hint", "")   # DataCite, else DFP guess
                c["license"]    = rec.get("license") or c.get("license_hint", "")
                n += 1
    meta.save()
    print(f"  labelled {n} datasets (confirmed + likely)")

    # STAGE 3: fuse -> buckets (+ the DFP-superset merged_output.csv)
    paper_rows, dataset_rows, merged_rows = fuse.fuse(per_paper, paper_meta=paper_meta)
    fuse.write_outputs(paper_rows, dataset_rows, merged_rows, OUT_DIR)

    own_open_papers = [r for r in paper_rows if r["has_own_open"]]
    print(f"\nRESULT ({len(per_paper)} papers):")
    print(f"  papers with OWN OPEN data : {len(own_open_papers)}")
    print(f"  datasets -> own-open: {sum(r['own_open'] for r in paper_rows)}"
          f" | own-restricted: {sum(r['own_restricted'] for r in paper_rows)}"
          f" | reused: {sum(r['reused'] for r in paper_rows)}"
          f" | own-unknown: {sum(r['own_unknown'] for r in paper_rows)}")
    print(f"  likely-but-unconfirmed (declared in DAS, no verifiable id): "
          f"{sum(r['likely_unconfirmed'] for r in paper_rows)}")
    n_disagree = sum(1 for r in merged_rows if r["dv_disagreement"])
    print(f"  merged_output.csv: {len(merged_rows)} rows (DFP cols + dv_), "
          f"{n_disagree} with a tool disagreement")
    print(f"  wrote {OUT_DIR}\\per_paper.csv, per_dataset.csv, merged_output.csv")

if __name__ == "__main__":
    main()
