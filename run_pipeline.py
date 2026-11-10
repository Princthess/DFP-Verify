"""
ORCHESTRATOR - detect-union -> verify -> registry links (DataCite reverse) -> classify -> fuse, end to end.

Edit the CONFIG block for your corpus. Inputs:
  TEXT_DIR    folder of paper .txt files   (drives the regex detector)
  DFP_CSV     the LLM detector's output     (optional; adds LLM candidates)
Outputs: OUT_DIR/summary.csv (headline), per_dataset.csv, merged_output.csv ; registry lookups cached.
"""
import os, re, csv, glob
import config; config.load_env()   # read a local .env into os.environ before the core modules read it
import detect_union, verify, fuse, classify, sections, registry_lookup, selfcheck, fields, nodata

# ----------------------------------- CONFIG -----------------------------------
TEXT_DIR   = r"path/to/paper_txt"            # folder of per-paper .txt (the regex detector's input)
DFP_CSV    = r"path/to/dfp_output.csv"       # DFP's own output CSV
OUT_DIR    = os.path.join(os.path.dirname(__file__), "output")
CACHE      = os.path.join(os.path.dirname(__file__), ".verify_cache.json")
# ----------------------------------------------------------------------------------

def stem(s): return os.path.splitext(os.path.basename(str(s).replace("\\", "/")))[0].lower()

# "data", "data files", "datasets" -- not "metadata"
SAYS_DATA = re.compile(r"(?i)(?<!meta)\bdata(?:\s*sets?|\s+files?)?\b|\bdatasets?\b")

def _homepage(url):
    """A site's front page, not a record: no query, at most one path segment, and no digits in the path
    ("https://snd.gu.se/en", "https://www.ebi.ac.uk/pride/"). Records carry an id ("…/dataset/2023-205")."""
    from urllib.parse import urlsplit
    u = urlsplit(url if "://" in url else "https://" + url)
    segs = [s for s in u.path.split("/") if s]
    return not u.query and len(segs) <= 1 and not re.search(r"\d", u.path)

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
    per_paper, all_cands, header, heads, texts = {}, [], {}, {}, {}
    for txt in glob.glob(os.path.join(TEXT_DIR, "*.txt")):
        p = stem(txt)
        text = open(txt, encoding="utf-8", errors="ignore").read()
        header[p] = text[:2500]                       # first-page author block (for own/reused)
        heads[p]  = detect_union.normalize_text(text[:6000])   # first page(s), for the paper-DOI check
        pmeta = paper_meta.setdefault(p, {})
        pmeta["no_data_signal"]    = nodata.signal(nodata.statement(text))    # "no new data were generated"
        pmeta["on_request_signal"] = nodata.signal(nodata.on_request(text))   # "available on request"
        pmeta["supplement_signal"] = nodata.signal(nodata.supplement(text))   # "data are in the supplement"
        # reuse of other people's data: pattern search, next to the LLM's own judgement (DFP rows it says
        # the authors did not create, software left out). A signal only -- the verdict counts verified reuse.
        pmeta["reuse_signal"] = nodata.signal(nodata.reuse(text))
        pmeta["reuse_llm"] = "; ".join(dict.fromkeys(
            (r.get("name") or r.get("identifier") or "").strip() for r in dfp_by.get(p, [])
            if str(r.get("created_by_authors", "")).strip().lower() == "false"
            and str(r.get("is_code", "")).strip().lower() != "true"))
        # does the paper have a data-availability statement? pattern search (heading as written) next to
        # the LLM's own das_found, compared like the dataset searches
        pmeta["das_pattern"] = sections.das_heading(text)
        pmeta["das_llm"] = {"true": "yes", "false": "no"}.get(str(pmeta.get("das_found", "")).strip().lower(), "")
        # the LLM's view of the same thing: DFP rows it marked as supplementary material
        pmeta["supplement_llm"] = "; ".join(dict.fromkeys(
            (r.get("name") or r.get("identifier") or "").strip() for r in dfp_by.get(p, [])
            if str(r.get("is_supplementary", "")).strip().lower() == "true"))
        cands = detect_union.union_detect(text=text, dfp_rows=dfp_by.get(p, []))
        # in-text provenance: locate each id against the DAS / reference / supplement landmarks.
        # DAS region is found by the heading locator; DFP's own source_section also counts.
        ntext = detect_union.normalize_text(text); ntext_lc = ntext.lower()
        bounds = sections.segment(ntext, with_das=True)
        texts[p] = (ntext_lc, bounds)                 # kept for stage 2c (landing-page matches)
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

    # STAGE 2c: registry links -- datasets DataCite ties to the paper (reverse lookup, cached).
    # Corroborates ids found in the text, repairs near-miss ids, and adds datasets not in the text.
    print("STAGE 2c registry links (DataCite, reverse lookup):")
    reg = registry_lookup.RegistryCache(os.path.join(os.path.dirname(__file__), ".registry_cache.json"))
    doi_stat, reg_stat, orcids = Counter(), Counter(), {}
    pdfs = selfcheck.pdf_index(os.environ.get("DV_PDF_DIR"))   # optional: only to explain broken ids
    for p, cands in per_paper.items():
        pm = paper_meta.setdefault(p, {})
        doi, st = registry_lookup.check_paper_doi(paper_doi.get(p, ""), heads.get(p, ""), reg)
        pm["dv_paper_doi"], pm["doi_status"] = doi, st
        doi_stat[st] += 1
        if st == "unconfirmed" or not doi:
            continue
        pm["year"] = reg.year(doi)                     # publication year (trends over time)
        pm["journal"] = reg.journal(doi)               # journal name (DAS per journal)
        orcids[p] = reg.paper_orcids(doi)              # paper authors' ORCIDs (own/reused, step 1a)
        ntext_lc, bounds = texts.get(p, ("", {}))
        added = registry_lookup.attach(cands, registry_lookup.reverse_links(doi, reg), text_lc=ntext_lc)
        for c in added:                                # landing-page citations: locate them like any id
            if c.get("_probe"):
                primary, alllab = sections.locate(sections.find_positions(ntext_lc, c["_probe"]), bounds)
                c["found_in"] = primary
                c["found_in_all"] = ";".join(sorted(alllab, key=lambda x: sections.PRIORITY.get(x, 9)))
                c["in_das"] = "das" in alllab
        all_cands.extend(added)
        for c in cands:
            r = c.get("registry", "")
            if r: reg_stat[r.split(" (+")[0].split(" (text had")[0]] += 1
            if r.startswith("repaired"):              # why was it broken? look in the PDF itself
                written = r[len("repaired (text had "):-1]
                c["id_cause"] = selfcheck.id_cause(pdfs.get(p), written, c["identifier"])
    reg.save()
    print(f"  paper DOI: " + " | ".join(f"{k}:{v}" for k, v in doi_stat.most_common()))
    print(f"  DataCite links: " + " | ".join(f"{k}:{v}" for k, v in reg_stat.most_common()))

    # STAGE 2d: field anchor per paper (Swepub SSIF, else Swepub's automatic SSIF classifier on the
    # abstract, else OpenAlex) -- from the checked paper DOI only
    print("STAGE 2d field (Swepub SSIF, else automatic SSIF, else OpenAlex):")
    fc = fields.FieldCache(os.path.join(os.path.dirname(__file__), ".field_cache.json"))
    fstat = Counter()
    for p in per_paper:
        pm = paper_meta.setdefault(p, {})
        ok = pm.get("doi_status") in ("confirmed", "corrected", "found")
        pm.update(fields.paper_field(pm.get("dv_paper_doi") if ok else "", fc))
        fstat[pm.get("field_source") or "none"] += 1
        pm["work_type"] = fc.work_type(pm["dv_paper_doi"]) if ok else ""   # OpenAlex: article, review ...
    print("  " + " | ".join(f"{k}:{v}" for k, v in fstat.most_common()))
    n_nd = sum(1 for p in per_paper if paper_meta.get(p, {}).get("no_data_signal"))
    n_or = sum(1 for p in per_paper if paper_meta.get(p, {}).get("on_request_signal"))
    n_su = sum(1 for p in per_paper if paper_meta.get(p, {}).get("supplement_signal"))
    print(f"  data statements: {n_nd} say no data were generated, {n_or} say data are available on request, "
          f"{n_su} say data are in the article / supplement")

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
                    c, rec.get("creators", []), hdr, found_in=c.get("found_in", ""),
                    dataset_orcids=rec.get("orcids", []), paper_orcids=orcids.get(p, []),
                    access=rec.get("access", ""))
                c["subjects"]   = rec.get("subjects", [])
                # repository = the DataCite client that registered the DOI (SND, DORIS, SciLifeLab, Zenodo..);
                # publisher = the responsible institution. Fallbacks: publisher, then DFP's guess.
                c["repository"] = rec.get("repository") or rec.get("publisher") or c.get("repo_hint", "")
                c["publisher"]  = rec.get("publisher", "")
                c["landing"]    = rec.get("url", "")
                c["license"]    = rec.get("license") or c.get("license_hint", "")
                # Code is not data: a DOI the registry types as Software (e.g. a Zenodo "Source code
                # for: ...") is kept in per_dataset.csv as status `software`, but not counted, not in the
                # summary and not on the dashboard (user, 2026-11-10: the line is fluid, keep them apart).
                # The line IS fluid: GitHub releases on Zenodo are always typed Software, also when they
                # hold the data ("All code and associated data files are available from Zenodo"). So a
                # Software record still counts as data when the paper's own words about it mention data.
                if (c["status"] == "confirmed" and rec.get("type") == "Software"
                        and not SAYS_DATA.search(c.get("evidence") or "")):
                    c["status"] = "software"
                n += 1
    meta.save()
    # Datasets DataCite ties to the paper that the paper itself doesn't cite are reported, but NOT
    # counted as the paper sharing data: sharing = the paper tells the reader where its data is.
    n_reg = 0
    for cands in per_paper.values():
        for c in cands:
            if c.get("registry", "").startswith("not in text") and c.get("status") == "confirmed":
                c["status"] = "datacite-only"; n_reg += 1
    # A web link that points to a dataset already confirmed by its DOI in the same paper is the same
    # dataset written twice, not a second unverifiable one (e.g. zenodo.org/records/N next to 10.5281/zenodo.N).
    n_dup = 0
    for cands in per_paper.values():
        conf = [c for c in cands if c.get("status") == "confirmed" and c.get("kind") == "doi"]
        for c in cands:
            if c.get("kind") == "url" and c.get("status", "").startswith("likely"):
                hit = next((d for d in conf if registry_lookup.same_record(c["identifier"], d["identifier"],
                                                                           d.get("landing", ""))), None)
                if hit:
                    c["status"] = "duplicate"; c["verdict"] = f"same record as {hit['identifier']}"; n_dup += 1
    # A link to a repository's front page ("snd.gu.se/en", "ebi.ac.uk/pride/") is not a record. When the
    # paper also gives a confirmed record of its OWN data, the link is almost always that repository named
    # next to its record -- not a second dataset -- so it is marked `homepage` instead of "declared,
    # unverifiable". Only with a confirmed own record, so it can never change the paper's verdict; the
    # row stays on the Tool check page under a milder label (a second repository named only by its front
    # page would still be visible there).
    n_home = 0
    for cands in per_paper.values():
        if not any(c.get("status") == "confirmed" and c.get("provenance") == "own" for c in cands):
            continue
        for c in cands:
            if c.get("kind") == "url" and c.get("status", "").startswith("likely") and _homepage(c["identifier"]):
                c["status"] = "homepage"; n_home += 1
    print(f"  labelled {n} datasets (confirmed + likely), {n_reg} of them DataCite-only (not counted)"
          + (f", {n_dup} link(s) merged into a confirmed DOI" if n_dup else "")
          + (f", {n_home} repository front-page link(s) next to an own record" if n_home else ""))
    for cands in per_paper.values():                  # each dataset's own subjects -- cross-check only
        for c in cands:
            if c.get("subjects"): c["subject"] = fields.format_subjects(c["subjects"], fc)
    fc.save()

    # STAGE 3: fuse -> buckets (summary.csv headline + per_dataset + DFP-superset merged_output.csv)
    summary_rows, paper_rows, dataset_rows, merged_rows = fuse.fuse(per_paper, paper_meta=paper_meta)
    fuse.write_outputs(summary_rows, dataset_rows, merged_rows, OUT_DIR)

    own_open_papers = [r for r in paper_rows if r["has_own_open"]]
    print(f"\nRESULT ({len(per_paper)} papers):")
    print(f"  papers with OWN OPEN data : {len(own_open_papers)}")
    print(f"  datasets -> own-open: {sum(r['own_open'] for r in paper_rows)}"
          f" | own-restricted: {sum(r['own_restricted'] for r in paper_rows)}"
          f" | reused: {sum(r['reused'] for r in paper_rows)}"
          f" | own-unknown: {sum(r['own_unknown'] for r in paper_rows)}")
    print(f"  likely-but-unconfirmed (declared in DAS, no verifiable id): "
          f"{sum(r['likely_unconfirmed'] for r in paper_rows)}")
    print(f"  DataCite-only (linked to the paper, not cited in it; not counted): "
          f"{sum(r['datacite_only'] for r in paper_rows)} datasets in "
          f"{sum(1 for r in paper_rows if r['datacite_only'])} papers")
    print()
    for line in selfcheck.run(per_paper, paper_meta, OUT_DIR): print(line)
    print()
    n_disagree = sum(1 for r in merged_rows if r["dv_disagreement"])
    print(f"  merged_output.csv: {len(merged_rows)} rows (DFP cols + dv_), "
          f"{n_disagree} with a tool disagreement")
    print(f"  wrote {OUT_DIR}\\summary.csv (headline), per_dataset.csv, merged_output.csv")

if __name__ == "__main__":
    main()
