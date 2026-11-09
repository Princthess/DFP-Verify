"""
FIELD - anchor each paper to a research field, for field normalisation.

The anchor must exist for EVERY paper (also papers with no data -- they are the denominator), so it
comes from the paper, not from its datasets. Sources, in order:
  1. swepub   -- the paper's own SSIF codes in Swepub (set by the Swedish university: author / library;
                 several universities may each have a record -> codes are pooled). Looked up by DOI.
  2. swepub classify -- Swepub's own automatic SSIF classifier (bibliometri.swepub.kb.se/api/v1/classify)
                 on the paper's title + abstract (abstract from OpenAlex). SSIF, 3-digit level. For papers
                 not in Swepub (e.g. non-Swedish, or not yet registered).
  3. openalex -- OpenAlex primary topic's field > subfield (automatic, ASJC-based, not SSIF; retrained
                 over time). Last resort, when there is no abstract to classify.
Datasets' own subjects (DataCite `subjects`: SSIF from SND, FOS from many repositories) are reported
alongside as a cross-check, never as the anchor. SSIF code names come from Swepub's own subject list,
so there is no table to maintain here.

Public API:
  FieldCache(path)
  paper_field(doi, cache) -> {"field", "field_source"}
  dataset_subjects(datacite_attributes) -> [{"scheme": "ssif"|"fos", "code", "label"}]
  format_subjects(subjects, cache) -> str   (one dataset's subjects, for per_dataset.csv)
"""
import json, os, re, time, requests

UA = {"User-Agent": f"dfp-verify/0.1 (mailto:{os.environ.get('DV_CONTACT_EMAIL', 'your-contact@example.org')})"}
S = requests.Session(); S.headers.update(UA)
XSEARCH  = "http://libris.kb.se/xsearch"
OAIPMH   = "http://api.libris.kb.se/swepub/oaipmh/"
SUBJECTS = "https://bibliometri.swepub.kb.se/api/v1/info/research-subjects"
CLASSIFY = "https://bibliometri.swepub.kb.se/api/v1/classify"

class FieldCache:
    def __init__(self, path=".field_cache.json"):
        self.path, self.d, self._mem = path, {}, {}
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

    def _openalex_work(self, doi):
        """OpenAlex work record (fetched once per run; the cached parts are stored separately)."""
        k = "_oawork|" + doi.lower()
        if k not in self._mem:
            try:
                r = S.get("https://api.openalex.org/works/doi:" + doi, timeout=30)
                self._mem[k] = r.json() if r.status_code == 200 else {}
            except Exception:
                return None                                   # network error: don't remember
        return self._mem[k]

    def work_type(self, doi):
        """OpenAlex work type ('article', 'review', 'editorial', ...), '' if unknown. For nodata.py."""
        k = "oatype|" + doi.lower()
        if k not in self.d:
            j = self._openalex_work(doi)
            if j is None: return ""
            self.d[k] = j.get("type") or ""
        return self.d[k]

    def openalex(self, doi):
        k = "openalex|" + doi.lower()
        if k not in self.d:
            j = self._openalex_work(doi)
            if j is None: return {}
            t = j.get("primary_topic")
            self.d[k] = ({"field": t["field"]["display_name"], "subfield": t["subfield"]["display_name"],
                          "domain": t["domain"]["display_name"]} if t else {})
        return self.d[k]

    def classify(self, doi):
        """Automatic SSIF codes (3-digit level) from Swepub's own classifier, given the paper's title and
        abstract (from OpenAlex). For papers not in Swepub. [] when there is no abstract or no match.
        Checked on the 16 corpus papers that do have Swepub codes: the top suggestion fell in one of the
        paper's own SSIF areas every time it suggested anything (14/16; 2 'no match')."""
        k = "classify|" + doi.lower()
        if k not in self.d:
            j = self._openalex_work(doi)
            if j is None: return []
            inv = j.get("abstract_inverted_index") or {}
            abstract = " ".join(w for _, w in sorted((p, w) for w, ps in inv.items() for p in ps))
            if len(abstract) < 200:                           # too little text to classify on
                self.d[k] = []; return []
            try:
                r = S.post(CLASSIFY, json={"title": j.get("title") or "", "abstract": abstract, "keywords": [],
                                           "level": 3, "classes": 3}, timeout=60).json()
            except Exception:
                return []                                     # network error: don't cache
            sug = [(s["@id"].rsplit("/", 1)[-1], s.get("_score", 0)) for s in r.get("suggestions") or []]
            # keep the top suggestion, plus any other reasonably strong one (score >= 0.2)
            self.d[k] = [c for i, (c, sc) in enumerate(sug) if i == 0 or sc >= 0.2]
        return self.d[k]

def _label(code, names):
    """'20301 Applied Mechanics'. Codes missing from Swepub's current list are mostly from the older
    SSIF 2011 standard (still present in older records) -- say so rather than show a bare code."""
    return f"{code} {names[code]}" if code in names else f"{code} (not in current SSIF; older standard?)"

def paper_field(doi, cache):
    """The SSIF area (6 top-level areas) is just the code's first digit -- derive it at analysis time."""
    empty = {"field": "", "field_source": ""}
    if not doi: return empty
    codes = cache.swepub_codes(doi)
    if codes:
        names = cache.ssif()
        return {"field": "; ".join(_label(c, names) for c in codes), "field_source": "swepub (SSIF)"}
    codes = cache.classify(doi)
    if codes:
        names = cache.ssif()
        return {"field": "; ".join(_label(c, names) for c in codes),
                "field_source": "swepub classify (SSIF, automatic)"}
    oa = cache.openalex(doi)
    if oa:
        return {"field": f"{oa['field']} > {oa['subfield']}", "field_source": "openalex (ASJC, automatic)"}
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

def format_subjects(subjects, cache):
    """One dataset's SSIF codes (named) + FOS labels, e.g. 'SSIF 10608 Zoology; FOS Biological sciences'."""
    names = cache.ssif()
    return "; ".join([f"SSIF {_label(s['code'], names)}" for s in subjects or [] if s["scheme"] == "ssif"] +
                     [f"FOS {s['label']}" for s in subjects or [] if s["scheme"] == "fos"])
