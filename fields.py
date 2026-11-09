"""
FIELD - anchor each paper to a research field, for field normalisation.

The anchor must exist for EVERY paper (also papers with no data -- they are the denominator), so it
comes from the paper, not from its datasets. Sources, in order:
  1. swepub   -- the paper's own SSIF codes in Swepub (set by the Swedish university: author / library;
                 several universities may each have a record -> codes are pooled). Looked up by DOI.
  2. openalex -- OpenAlex primary topic's field > subfield (automatic, ASJC-based, not SSIF; retrained
                 over time). Fallback for papers not in Swepub.
Datasets' own subjects (DataCite `subjects`: SSIF from SND, FOS from many repositories) are reported
alongside as a cross-check, never as the anchor. SSIF code names come from Swepub's own subject list,
so there is no table to maintain here.

Public API:
  FieldCache(path)
  paper_field(doi, cache) -> {"field_area", "field", "field_source"}
  dataset_subjects(datacite_attributes) -> [{"scheme": "ssif"|"fos", "code", "label"}]
  format_dataset_field(subject_lists, cache) -> str
"""
import json, os, re, time, requests

UA = {"User-Agent": f"dfp-verify/0.1 (mailto:{os.environ.get('DV_CONTACT_EMAIL', 'your-contact@example.org')})"}
S = requests.Session(); S.headers.update(UA)
XSEARCH  = "http://libris.kb.se/xsearch"
OAIPMH   = "http://api.libris.kb.se/swepub/oaipmh/"
SUBJECTS = "https://bibliometri.swepub.kb.se/api/v1/info/research-subjects"

class FieldCache:
    def __init__(self, path=".field_cache.json"):
        self.path, self.d = path, {}
        if os.path.exists(path):
            try: self.d = json.load(open(path, encoding="utf-8"))
            except Exception: self.d = {}
    def save(self):
        json.dump(self.d, open(self.path, "w", encoding="utf-8"), ensure_ascii=False)

    def ssif(self):
        """{code: English name} for every SSIF level (1, 3 and 5 digits), from Swepub."""
        if "ssif" not in self.d:
            try:
                tree = S.get(SUBJECTS, timeout=30).json()
            except Exception:
                return {}
            flat = {}
            def walk(node):
                for code, v in (node or {}).items():
                    flat[code] = v.get("eng") or v.get("swe") or ""
                    walk(v.get("subcategories"))
            walk(tree)
            self.d["ssif"] = flat
        return self.d["ssif"]

    def swepub_codes(self, doi):
        """SSIF codes from every Swepub record with this DOI (pooled, most frequent first)."""
        k = "swepub|" + doi.lower()
        if k not in self.d:
            try:
                recs = S.get(XSEARCH, params={"query": doi, "database": "swepub", "format": "json", "n": 10},
                             timeout=30).json()["xsearch"]["list"]
                counts = {}
                for rec in recs:
                    oai = rec.get("identifier", "").split("swepub:", 1)[-1]
                    x = S.get(OAIPMH, params={"verb": "GetRecord", "metadataPrefix": "swepub_mods",
                                              "identifier": oai}, timeout=30).text
                    if "anubis" in x.lower(): return []      # bot check page -- don't cache, retry later
                    codes = set(re.findall(r'<classification authority="ssif">\s*(\d{1,5})\s*<', x))
                    codes |= set(re.findall(r'authority="uka\.se"[^>]*xlink:href="(\d{1,5})"', x))
                    for c in codes: counts[c] = counts.get(c, 0) + 1
                    time.sleep(0.1)
            except Exception:
                return []                                     # network error: don't cache
            self.d[k] = sorted(counts, key=lambda c: (-counts[c], c))
        return self.d[k]

    def openalex(self, doi):
        k = "openalex|" + doi.lower()
        if k not in self.d:
            try:
                r = S.get("https://api.openalex.org/works/doi:" + doi, timeout=30)
                t = r.json().get("primary_topic") if r.status_code == 200 else None
            except Exception:
                return {}
            self.d[k] = ({"field": t["field"]["display_name"], "subfield": t["subfield"]["display_name"],
                          "domain": t["domain"]["display_name"]} if t else {})
        return self.d[k]

def _label(code, names):
    """'20301 Applied Mechanics'. Codes missing from Swepub's current list are mostly from the older
    SSIF 2011 standard (still present in older records) -- say so rather than show a bare code."""
    return f"{code} {names[code]}" if code in names else f"{code} (not in current SSIF; older standard?)"

def paper_field(doi, cache):
    empty = {"field_area": "", "field": "", "field_source": ""}
    if not doi: return empty
    codes = cache.swepub_codes(doi)
    if codes:
        names = cache.ssif()
        areas = list(dict.fromkeys(names.get(c[0], c[0]) for c in codes))
        return {"field_area": "; ".join(areas), "field": "; ".join(_label(c, names) for c in codes),
                "field_source": "swepub (SSIF)"}
    oa = cache.openalex(doi)
    if oa:
        return {"field_area": oa["domain"], "field": f"{oa['field']} > {oa['subfield']}",
                "field_source": "openalex (ASJC, automatic)"}
    return empty

def dataset_subjects(attrs):
    """SSIF and FOS subjects from a DataCite record (other schemes -- keywords, NASA, YSO -- skipped)."""
    out, seen = [], set()
    for s in (attrs or {}).get("subjects") or []:
        scheme = (s.get("subjectScheme") or "").lower()
        subj = (s.get("subject") or "").strip()
        code = (s.get("classificationCode") or "").strip()
        if ("indelning" in scheme or "ssif" in scheme) and code.isdigit():
            key = ("ssif", code)
        elif "fos" in scheme or subj.lower().startswith("fos:"):
            subj = re.sub(r"(?i)^fos:\s*", "", subj); key = ("fos", subj.lower())
        else:
            continue
        if key not in seen:
            seen.add(key); out.append({"scheme": key[0], "code": code if key[0] == "ssif" else "", "label": subj})
    return out

def format_dataset_field(subject_lists, cache):
    """Union over a paper's datasets: SSIF codes (named) if any dataset has them, plus FOS labels."""
    names, ssif, fos = cache.ssif(), [], []
    for subs in subject_lists:
        for s in subs or []:
            if s["scheme"] == "ssif" and s["code"] not in ssif: ssif.append(s["code"])
            if s["scheme"] == "fos" and s["label"] not in fos: fos.append(s["label"])
    parts = [f"SSIF {_label(c, names)}" for c in ssif] + [f"FOS {f}" for f in fos]
    return "; ".join(parts)
