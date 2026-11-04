"""
SELF-CHECK - how many of the datasets we KNOW are cited in the text did the text detectors find?

"Known" = DataCite links the dataset to the paper AND the paper cites it (its DOI, a malformed form of
its DOI, or its landing page). For those, the right answer is certain without manual checking, so
they act as a small free answer key. Written to selfcheck.csv + a console summary after every run.
Biased toward data with DataCite backlinks (e.g. SND / Chalmers); "available on request" style
statements are not measured.

Also: when an id in the text didn't resolve but matched a registered DOI ("repaired"), look in the PDF
itself to tell WHY -- the clickable link targets and the PDF's own text blocks:
  pdf-extraction : the PDF has the correct DOI; the .txt extraction broke it (e.g. column interleave)
  as-printed     : the published PDF itself prints the wrong id
  unknown        : no PDF available, or neither form found in it

Public API:
  id_cause(pdf_path, written, registered) -> "pdf-extraction" / "as-printed" / "unknown"
  pdf_index(pdf_dir)                      -> {lowercase stem: path}
  run(per_paper, paper_meta, out_dir)     -> writes selfcheck.csv, returns the summary lines
"""
import csv, os, re, glob

def pdf_index(pdf_dir):
    if not pdf_dir or not os.path.isdir(pdf_dir): return {}
    return {os.path.splitext(os.path.basename(p))[0].lower(): p for p in glob.glob(os.path.join(pdf_dir, "*.pdf"))}

def id_cause(pdf_path, written, registered):
    if not pdf_path: return "unknown"
    try:
        import pymupdf
        doc = pymupdf.open(pdf_path)
        links = " ".join(l.get("uri") or "" for page in doc for l in page.get_links()).lower()
        # the PDF's own text, block by block (no column interleaving); re-join ids split at a line end
        blocks = " ".join(b[4] for page in doc for b in page.get_text("blocks"))
        text = re.sub(r"([/._-])\s+", r"\1", re.sub(r"[‐-―−]", "-", blocks)).lower()
    except Exception:
        return "unknown"
    if registered.lower() in links or registered.lower() in text: return "pdf-extraction"
    if written.lower() in links or written.lower() in text:       return "as-printed"
    return "unknown"

def _cited_as(c):
    r = c.get("registry", "")
    if r.startswith("repaired"):        return "doi (malformed)"
    if r.startswith("linked (landing"): return "landing page"
    return "doi"

def _found_by(src):
    s = set(src.split("+"))
    return {(True, True): "DFP + regex", (True, False): "DFP", (False, True): "regex"}.get(
        ("llm" in s, "regex" in s), "")

def run(per_paper, paper_meta, out_dir):
    rows = []
    for p, cands in sorted(per_paper.items()):
        for c in cands:
            r = c.get("registry", "")
            if not (r == "linked" or r.startswith("repaired") or r.startswith("linked (landing")):
                continue
            by = _found_by(c.get("source", ""))
            result = ("not found by text detectors" if not by else
                      "found, id broken" if r.startswith("repaired") else "found")
            rows.append({"paper": (paper_meta.get(p, {}) or {}).get("file") or p,
                         "identifier": c["identifier"], "cited_as": _cited_as(c),
                         "result": result, "found_by": by or "-",
                         "broken_id_cause": c.get("id_cause", "") if r.startswith("repaired") else ""})
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "selfcheck.csv"), "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["paper", "identifier", "cited_as", "result", "found_by", "broken_id_cause"])
        w.writeheader(); w.writerows(rows)
    n = len(rows)
    found = [x for x in rows if x["result"] != "not found by text detectors"]
    lines = [f"SELF-CHECK vs DataCite: {n} datasets known to be cited in the text (answer key; see selfcheck.csv)"]
    if n:
        dfp = sum("DFP" in x["found_by"] for x in rows); rx = sum("regex" in x["found_by"] for x in rows)
        lines.append(f"  found by the text detectors: {len(found)}/{n}  (DFP {dfp}, regex {rx})")
        for x in rows:
            if x["result"] != "found":
                extra = f", cause: {x['broken_id_cause']}" if x["broken_id_cause"] else ""
                lines.append(f"  {x['result']}: {x['paper'][:45]} - {x['identifier']} (cited as {x['cited_as']}{extra})")
    return lines
