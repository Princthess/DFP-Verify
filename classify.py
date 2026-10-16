"""
CLASSIFY - assign provenance (own/reused) and openness (open/restricted) to each
VERIFIED dataset.

own vs reused, in priority order:
  1. creator overlap (deterministic) - dataset's DataCite creators INTERSECT paper's
     authors (paper authors fetched via the paper's own DOI). Catches LLM mistakes.
  2. own-verb in the evidence/DAS sentence ("we submitted/deposited ...")
  3. the LLM's created_by_authors judgment (carried from the detect stage)
  4. in-text location (references-only -> reused)
  5. unknown  (flag, don't guess)

openness:
  - LLM said is_open == False               -> restricted
  - registry-verified dataset               -> open (controlled-access repos -> restricted)
  - a live github/osf/url deposit           -> open
  - else                                     -> unknown
"""
import json, os, time, re, requests
from patterns import OWN_VERBS   # own-provenance verbs ("we submitted/deposited ..."), single source

UA = {"User-Agent": f"dfp-verify/0.1 (mailto:{os.environ.get('DV_CONTACT_EMAIL', 'your-contact@example.org')})"}
S = requests.Session(); S.headers.update(UA)

def _surnames(meta):
    out = []
    for a in (meta.get("author") or []):
        fam = a.get("family") or a.get("literal") or ""
        if fam: out.append(fam.strip().lower().split()[-1])   # last token handles "Van Den Brink"
    return out

def _csl(doi):
    try:
        r = S.get("https://doi.org/" + doi, headers={"Accept": "application/vnd.citationstyles.csl+json"},
                  timeout=15, allow_redirects=True)
        if r.status_code == 200: return r.json()
    except Exception:
        pass
    return None

class MetaCache:
    """Cached DataCite/Crossref lookups per DOI: creators, publisher (repo), licence."""
    def __init__(self, path=".meta_cache.json"):
        self.path, self.d = path, {}
        if os.path.exists(path):
            try: self.d = json.load(open(path, encoding="utf-8"))
            except Exception: self.d = {}
    def record(self, doi):
        empty = {"creators": [], "publisher": "", "license": ""}
        if not doi: return empty
        k = "rec|" + doi.lower()
        if k not in self.d:
            m = _csl(doi) or {}
            lic, L = "", m.get("license")
            if isinstance(L, list) and L:
                lic = L[0].get("URL", "") if isinstance(L[0], dict) else str(L[0])
            self.d[k] = {"creators": _surnames(m), "publisher": m.get("publisher", "") or "", "license": lic}
            time.sleep(0.05)
        return self.d[k]
    def save(self):
        json.dump(self.d, open(self.path, "w", encoding="utf-8"), ensure_ascii=False)

# NOTE: an optional LLM referee once sat here (last-resort own/reused via a local/HPC model).
# It was tested on a 31B model over the full corpus and changed no correct call, so it was removed;
# provenance is now fully deterministic. The experiment is kept in a private archive, not this repo.

def status(cand):
    """Confidence bucket for a candidate, using the verify verdict + whether it's in the DAS.
    A candidate the authors *declared* in the DAS but we couldn't confirm is 'likely', not noise."""
    if cand.get("kind") == "mention":              return "mention"   # LLM found implicit, id-less data
    v = cand.get("verdict", ""); in_das = cand.get("in_das")
    if v.startswith("data-verified"):              return "confirmed"
    if v.startswith("not-data"):                   return "not-data"     # registry says cited article
    if in_das:                                                           # declared, but unconfirmed
        if v.startswith("dead") or "not-found" in v: return "likely-broken-link"
        if v.startswith("resolves"):                 return "likely-no-doi"
        return "likely-unchecked"
    return "noise"                                                       # not declared + unconfirmed = reference

def _das_window(ident, das_text):
    """The DAS text around this id (sentence-ish context for the LLM / keyword check)."""
    das = das_text or ""
    i = das.lower().find((ident or "").lower())
    return das[max(0, i - 160):i + 60] if i >= 0 else ""

def _das_says_own(ident, das_text):
    """Offline fallback: is there an own-verb ('submitted/deposited/...') near this id in the DAS?"""
    return bool(OWN_VERBS.search(_das_window(ident, das_text)))

def classify(cand, dataset_creators, paper_header, das_text="", found_in=""):
    """paper_header: the paper's first-page text (author block). das_text: optional DAS text.
    found_in: coarse in-text location (das/body/supplement/references) -- a weak provenance nudge."""
    hdr = (paper_header or "").lower()
    dc  = [s for s in (dataset_creators or []) if len(s) >= 3]
    ctx = cand.get("evidence") or _das_window(cand.get("identifier", ""), das_text)
    overlap  = ("own" if any(s in hdr for s in dc) else "reused") if (dc and hdr) else None
    flag     = cand.get("created_by_authors")
    flag_sig = "own" if flag is True else ("reused" if flag is False else None)
    # --- provenance: deterministic signals only, in priority order; never a guess.
    if overlap:                                        # DataCite creators vs the paper's authors ==
        prov, by = overlap, "creator-overlap"          # authoritative; nothing overrides it.
    else:                                              # no creator metadata (e.g. accessions) -> ladder
        # own-verb on ctx (= DFP's evidence sentence, else the DAS window): "we submitted/deposited".
        if   ctx and OWN_VERBS.search(ctx):            prov, by = "own", "own-verb"
        elif flag_sig:                                 prov, by = flag_sig, "dfp-flag"
        elif found_in == "references":                 prov, by = "reused", "location"
        else:                                          # every deterministic signal silent
            prov, by = "unknown", ""                   # flagged honestly, never guessed
    cand["provenance_by"] = by
    # --- openness ---
    v = cand.get("verdict", "")
    if cand.get("is_open") is False:               openness = "restricted"
    elif v.startswith("data-verified"):            openness = "restricted" if "EGA" in v else "open"
    elif v.startswith("resolves"):                 openness = "open"
    else:                                          openness = "unknown"
    return prov, openness
