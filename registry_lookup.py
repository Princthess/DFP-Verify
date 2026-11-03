"""
STAGE 2c - REGISTRY LINKS (the reverse direction).

verify.py / classify.py ask DataCite about identifiers found IN the text ("what is this id?").
This module asks the opposite: "which datasets does DataCite tie to THIS paper?" -- i.e. dataset
records whose own metadata (relatedIdentifiers) point at the paper's DOI. Deterministic, cached.

Per paper it:
  1. checks the paper's DOI (title of the DOI record must match the paper's first page; if not,
     tries the DOIs printed on the first page). A wrong paper DOI would link the wrong datasets.
  2. fetches the DataCite records that point at that DOI (datasets/software/collections only),
     collapsing version + concept DOIs of the same dataset into one group.
  3. merges them into the paper's candidates:
       - group already found in the text        -> tagged registry="linked" (+datacite source)
       - a declared id that did NOT resolve and is a near-miss of a linked DOI (OCR/typo/
         line-break artefact)                     -> repaired to the registered DOI
       - otherwise                                -> NEW candidate, registry="not in text"

Public API:
  RegistryCache(path)                    -- disk cache (titles + reverse lookups)
  check_paper_doi(doi, head, cache)      -> (doi, status)  status: confirmed / corrected / unconfirmed
  reverse_links(doi, cache)              -> [link dicts]
  attach(cands, links)                   -> mutates cands in place, returns the new candidates
"""
import json, os, re, time, requests
from patterns import DOI_RX, clean_doi

UA = {"User-Agent": f"dfp-verify/0.1 (mailto:{os.environ.get('DV_CONTACT_EMAIL', 'your-contact@example.org')})"}
S = requests.Session(); S.headers.update(UA)
DATA_TYPES   = {"dataset", "software", "collection"}            # same set as verify.py
VERSION_RELS = {"hasversion", "isversionof", "isnewversionof", "ispreviousversionof"}
VERDICT      = "data-verified (DataCite link)"

def _bare(doi):
    """'https://doi.org/10.X/Y' / 'doi:10.X/Y' -> '10.x/y'."""
    return re.sub(r"^(https?://(dx\.)?doi\.org/|doi:)", "", (doi or "").strip(), flags=re.I).lower()

# ---------------------------------------------------------------- cache
class RegistryCache:
    def __init__(self, path=".registry_cache.json"):
        self.path, self.d = path, {}
        if os.path.exists(path):
            try: self.d = json.load(open(path, encoding="utf-8"))
            except Exception: self.d = {}
    def save(self):
        json.dump(self.d, open(self.path, "w", encoding="utf-8"), ensure_ascii=False)

    def title(self, doi):
        k = "title|" + doi.lower()
        if k not in self.d:
            try:
                r = S.get("https://doi.org/" + doi, headers={"Accept": "application/vnd.citationstyles.csl+json"},
                          timeout=15, allow_redirects=True)
                t = r.json().get("title", "") if r.status_code == 200 else ""
                if isinstance(t, list): t = t[0] if t else ""
                self.d[k] = t or ""
            except Exception:
                return ""                                   # network error: don't cache, retry next run
            time.sleep(0.05)
        return self.d[k]

    def crossref_search(self, head):
        """Top Crossref matches for the first page text -> [(doi, title)]. Only ever used through
        the title check, so a loose search hit can't slip through."""
        q = re.sub(r"\s+", " ", head or "").strip()[:300]
        k = "xref|" + q.lower()
        if not q: return []
        if k not in self.d:
            try:
                r = S.get("https://api.crossref.org/works",
                          params={"query.bibliographic": q, "rows": 3, "select": "DOI,title"}, timeout=30)
                r.raise_for_status()
                self.d[k] = [(it["DOI"].lower(), (it.get("title") or [""])[0])
                             for it in r.json()["message"]["items"]]
            except Exception:
                return []                                   # network error: don't cache, retry next run
            time.sleep(0.1)
        return self.d[k]

    def links(self, doi):
        k = "links|" + doi.lower()
        if k not in self.d:
            q = f'relatedIdentifiers.relatedIdentifier:("{doi}" OR "https://doi.org/{doi}")'
            try:
                r = S.get("https://api.datacite.org/dois", params={"query": q, "page[size]": 100}, timeout=30)
                r.raise_for_status()
                self.d[k] = [_link(x, doi) for x in r.json().get("data", [])]
            except Exception:
                return []                                   # network error: don't cache, retry next run
            time.sleep(0.1)
        return self.d[k]

def _link(rec, paper_doi):
    a = rec.get("attributes", {})
    rels = a.get("relatedIdentifiers") or []
    return {
        "identifier": rec.get("id", "").lower(),
        "type":       ((a.get("types") or {}).get("resourceTypeGeneral") or "").lower(),
        "publisher":  a.get("publisher") or "",
        "relation":   ",".join(sorted({r.get("relationType", "") for r in rels
                                       if _bare(r.get("relatedIdentifier")) == paper_doi.lower()})),
        "versions":   sorted({_bare(r.get("relatedIdentifier")) for r in rels
                              if (r.get("relationType") or "").lower() in VERSION_RELS
                              and (r.get("relatedIdentifierType") or "").upper() == "DOI"}),
        "is_concept": any((r.get("relationType") or "").lower() == "hasversion" for r in rels),
    }

# ---------------------------------------------------------------- 1. paper DOI check
def _words(s):
    return {w for w in re.findall(r"[a-z0-9]+", (s or "").lower()) if len(w) >= 4}

def _title_matches(title, head):
    tw = _words(title)
    return len(tw) >= 3 and len(tw & _words(head)) / len(tw) >= 0.7

def check_paper_doi(doi, head, cache):
    """doi: the paper DOI we were given (may be blank/wrong). head: the paper's first-page text.
    Returns (doi, status). The record's title must match the first page. Tried in order: the given
    DOI -> DOIs printed on the first page -> a Crossref bibliographic search on the first page.
    status: confirmed / corrected / found (none given) / unconfirmed (-> no reverse lookup)."""
    given = _bare(doi)
    tries = [given] if given else []
    for m in DOI_RX.finditer(head or ""):
        d = clean_doi(m.group(0))
        if d not in tries: tries.append(d)
    for d in tries:
        if _title_matches(cache.title(d), head):
            return d, ("confirmed" if d == given else "corrected" if given else "found")
    for d, t in cache.crossref_search(head):
        if _title_matches(t, head):
            return d, ("corrected" if given else "found")
    return given, "unconfirmed"

# ---------------------------------------------------------------- 2. reverse lookup
def reverse_links(doi, cache):
    """DataCite records that point at the paper DOI, data types only."""
    return [l for l in cache.links(doi) if l["type"] in DATA_TYPES and l["relation"]]

def _groups(links):
    """Union version/concept DOIs of the same dataset (HasVersion / IsVersionOf ...)."""
    links = [dict(l) for l in links]                        # copies: never write into the cache
    parent = {}
    def find(x):
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]; x = parent[x]
        return x
    for l in links:
        find(l["identifier"])
        for v in l["versions"]: parent[find(v)] = find(l["identifier"])
    base = {}                                               # figshare-style 'X' and 'X.v1' = same item
    for l in links:
        b = re.sub(r"\.v\d+$", "", l["identifier"])
        if b in base: parent[find(l["identifier"])] = find(base[b])
        else:         base[b] = l["identifier"]
    out = {}
    for l in links: out.setdefault(find(l["identifier"]), []).append(l)
    for root, ls in out.items():                            # carry the unlinked version ids too
        ids = {x for x in list(parent) if find(x) == root}
        for l in ls: l["_group"] = ids
    return list(out.values())

# ---------------------------------------------------------------- 3. merge into candidates
def _near(a, b):
    """a (from the text) is a near-miss of b (registered): same DOI prefix and either
    <=2 edits (OCR / typo) or b plus ONE glued-in chunk of <=8 chars (two-column line break)."""
    if a == b or a.split("/")[0] != b.split("/")[0]: return False
    if 0 < len(a) - len(b) <= 8:
        p = len(os.path.commonprefix([a, b])); s = len(os.path.commonprefix([a[::-1], b[::-1]]))
        if p + s >= len(b): return True
    if abs(len(a) - len(b)) > 2: return False
    prev = list(range(len(b) + 1))                          # Levenshtein, tiny strings
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1] <= 2

def _blank(ident, link):
    from detect_union import _blank_attrs
    return {"identifier": ident, "kind": "doi", "source": "datacite", **_blank_attrs(),
            "found_in": "", "found_in_all": "", "in_das": False, "verdict": VERDICT,
            "registry": "not in text", "registry_relation": link["relation"]}

def attach(cands, links):
    """Merge DataCite links into ONE paper's (already verified) candidates. Mutates in place;
    returns the list of new 'not in text' candidates (also appended to cands)."""
    by_id = {c["identifier"].lower(): c for c in cands if c.get("kind") == "doi"}
    added = []
    for group in _groups(links):
        ids = group[0]["_group"]
        rel = ",".join(sorted({l["relation"] for l in group}))
        in_text = [by_id[i] for i in ids if i in by_id]
        if in_text:                                         # already found -- corroborate it
            for c in in_text:
                c["registry"] = "linked"; c["registry_relation"] = rel
                if "datacite" not in c["source"]: c["source"] += "+datacite"
            continue
        # a declared id that didn't resolve but is a near-miss of a linked DOI -> repair it
        unresolved = [c for c in by_id.values() if not str(c.get("verdict", "")).startswith("data-verified")
                      and not c.get("registry")]
        hits = [(c, l) for c in unresolved for l in group if _near(c["identifier"].lower(), l["identifier"])]
        if len({id(c) for c, _ in hits}) == 1:              # exactly one text id -> unambiguous
            c, l = hits[0]
            c["registry"] = f"repaired (text had {c['identifier']})"; c["registry_relation"] = rel
            c["identifier"] = l["identifier"]; c["verdict"] = VERDICT
            if "datacite" not in c["source"]: c["source"] += "+datacite"
            continue
        # not in the text at all -> one new candidate per dataset (prefer the concept DOI)
        rep = next((l for l in group if l["is_concept"]), group[0])
        nc = _blank(rep["identifier"], rep); nc["registry_relation"] = rel
        others = len(ids) - 1
        if others: nc["registry"] += f" (+{others} version{'s' if others > 1 else ''})"
        added.append(nc)
    cands.extend(added)
    return added
