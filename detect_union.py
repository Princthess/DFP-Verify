"""
STAGE 1 - DETECT (max recall).

LLM (DFP) UNION regex. Surfaces every candidate dataset identifier; precision is stage 2's job.
All identifier patterns live in patterns.py (single source of truth; see its header for provenance).

Public API:
  detect_regex(text)          -> candidates from full paper text
  detect_from_dfp(rows)       -> candidates from the LLM detector's output
  union_detect(text, rows)    -> merged + de-duped, with source attribution
Each candidate: {"identifier","kind"(doi/accession/code/osf/url),"source"(llm/regex/both)}
"""
import re
from patterns import DOI_RX, ORPHAN_PREFIX, ORPHAN_RX, ZEN_URL, GH_RX, OSF_RX, ACC_RX, DATA_REPO_URL, clean_doi

def _tri(v):
    s = str(v).strip().lower()
    if s in ("true", "1", "yes"):  return True
    if s in ("false", "0", "no"):  return False
    return None

# attributes every candidate carries (own/reused + open evidence from the detectors)
ATTRS = ("created_by_authors", "is_open", "location", "repo_hint", "name", "license_hint", "evidence")
def _blank_attrs():
    return {k: (None if k in ("created_by_authors", "is_open") else "") for k in ATTRS}

def normalize_text(t):
    """PDF-extraction artefact repair: fancy dashes + rejoin DOIs/URLs split across lines."""
    t = re.sub(r"[‐-―−]", "-", t)
    t = re.sub(r"\b(10\.?)\s+(\d{4,}/)", r"\1\2", t)
    # rejoin a DOI split across a line ONLY when the fragment ends in a continuation char
    # (/ . _ -); otherwise a COMPLETE doi would get the next token (e.g. a reference number)
    # glued onto it -- "10.5281/zenodo.13683462" + " 53." -> "...1368346253" (silent recall loss).
    t = re.sub(r"(10\.\d{4,}/[^\s]{1,30}[/._-])\s+([^\s,);>\"']{2,})", r"\1\2", t)
    t = re.sub(r"(https?://[^\s]{3,80}[/.=?&#_-])\s+([^\s,);>\"']{2,})", r"\1\2", t)
    return t

def detect_regex(text):
    text = normalize_text(text)
    c = {}
    def add(ident, kind):
        k = ident.lower()
        if k and k not in c:
            c[k] = {"identifier": ident, "kind": kind, "source": "regex", **_blank_attrs()}
    for m in DOI_RX.finditer(text):    add(clean_doi(m.group(0)), "doi")
    for m in ORPHAN_RX.finditer(text): add("10." + clean_doi(m.group(0)), "doi")
    for m in ZEN_URL.finditer(text):   add("10.5281/zenodo." + m.group(1), "doi")
    for m in ACC_RX.finditer(text):    add(m.group(0).upper(), "accession")
    for rx, kind in ((GH_RX, "code"), (OSF_RX, "osf"), (DATA_REPO_URL, "url")):
        for m in rx.finditer(text):    add(re.sub(r"[.,);:>\]/]+$", "", m.group(0)), kind)
    return [v for v in c.values()
            if v["kind"] != "doi" or re.match(r"^10\.\d{4,}/.{2,}$", v["identifier"])]

def detect_from_dfp(rows):
    """LLM source: identifiers PLUS the own/reused + open judgments DFP already made."""
    c = {}
    for r in rows:
        attrs = {"created_by_authors": _tri(r.get("created_by_authors")),
                 "is_open":            _tri(r.get("is_open")),
                 "location":           (r.get("source_section") or "").strip().lower(),
                 "repo_hint":          (r.get("repository") or "").strip(),
                 "name":               (r.get("name") or "").strip(),
                 "license_hint":       (r.get("license") or "").strip(),
                 "evidence":           (r.get("evidence") or r.get("notes") or "").strip()}
        for fld in ("identifier", "url"):
            v = (r.get(fld) or "").strip()
            if not v: continue
            m = DOI_RX.search(v)
            if m:   ident = clean_doi(m.group(0)); kind = "doi"
            elif ACC_RX.search(v):          ident = ACC_RX.search(v).group(0).upper(); kind = "accession"
            elif v.lower().startswith("http"): ident = v; kind = "url"
            else: continue
            k = ident.lower()
            if k not in c:
                # keep the raw DFP row so the wrapper can emit DFP's own columns verbatim
                c[k] = {"identifier": ident, "kind": kind, "source": "llm", **attrs, "_dfp": r}
    return list(c.values())

def union_detect(text=None, dfp_rows=None):
    merged = {}
    def ingest(cands, src):
        for x in cands:
            k = x["identifier"].lower()
            if k in merged:
                m = merged[k]
                if src not in m["source"]: m["source"] += "+" + src
                for a in ATTRS:                       # fill missing attrs from the other detector
                    if m.get(a) in (None, "") and x.get(a) not in (None, ""): m[a] = x[a]
            else:
                merged[k] = {**x, "source": src}
    if dfp_rows is not None: ingest(detect_from_dfp(dfp_rows), "llm")
    if text:                 ingest(detect_regex(text), "regex")
    return list(merged.values())
