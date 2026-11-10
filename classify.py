"""
CLASSIFY - assign provenance (own/reused) and openness (open/restricted) to each
VERIFIED dataset.

own vs reused, in priority order:
  1a. ORCID overlap - a dataset creator's ORCID is one of the paper authors' ORCIDs -> own.
      (No overlap proves nothing -- not every author has an ORCID -- so it falls through to 1b.)
  1b. creator name overlap (deterministic) - dataset's DataCite creator surnames found in the
      paper's first page. Catches LLM mistakes.
  2. own-verb in the evidence/DAS sentence ("we submitted/deposited ...")
  3. the LLM's created_by_authors judgment (carried from the detect stage)
  4. in-text location (references-only -> reused)
  5. unknown  (flag, don't guess)

openness:
  - LLM said is_open == False               -> restricted
  - DataCite access right says closed / restricted / embargoed -> restricted
  - registry-verified dataset               -> open (controlled-access repos -> restricted)
  - a live github/osf/url deposit           -> open
  - else                                     -> unknown
"""
import json, os, time, re
from patterns import OWN_VERBS   # own-provenance verbs ("we submitted/deposited ..."), single source
from registry_lookup import orcid
from fields import dataset_subjects
from net import S                # shared HTTP session (User-Agent with contact address)

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

def _datacite(doi):
    """Full DataCite record (rights, ORCIDs) + the name of the repository that registered it
    (the DataCite client, e.g. 'Swedish National Data Service', 'SciLifeLab Data Repository').
    `publisher` is the responsible institution and often hides the repository, so both are kept.
    None for non-DataCite DOIs (e.g. Crossref)."""
    try:
        r = S.get(f"https://api.datacite.org/dois/{doi}", params={"include": "client"}, timeout=15)
        if r.status_code == 200:
            j = r.json()
            a = dict(j["data"]["attributes"])
            cl = [x for x in j.get("included") or [] if x.get("type") in ("clients", "repositories")]
            a["_repository"] = (cl[0].get("attributes") or {}).get("name", "") if cl else ""
            return a
    except Exception:
        pass
    return None

def _rights(rights_list):
    """DataCite rightsList -> (licence, access). access = open / restricted / '' from the
    info:eu-repo/semantics/*Access vocabulary; licence = the first non-access entry."""
    lic, access = "", ""
    for r in rights_list or []:
        uri = (r.get("rightsUri") or "").lower()
        m = re.search(r"semantics/(open|closed|restricted|embargoed|metadataonly)access", uri)
        if m:
            access = access or ("open" if m.group(1) == "open" else "restricted")
        elif not lic:
            lic = r.get("rightsIdentifier") or r.get("rightsUri") or r.get("rights") or ""
    return lic, access

class MetaCache:
    """Cached registry lookups per DOI: creators (+ORCIDs), publisher, repository, licence, access.
    DataCite's own API first (it carries rights + ORCIDs); doi.org CSL as the fallback (Crossref)."""
    def __init__(self, path=".meta_cache.json"):
        self.path, self.d = path, {}
        if os.path.exists(path):
            try: self.d = json.load(open(path, encoding="utf-8"))
            except Exception: self.d = {}
    def record(self, doi):
        empty = {"creators": [], "orcids": [], "publisher": "", "repository": "", "license": "", "access": "",
                 "subjects": [], "url": "", "type": ""}
        if not doi: return empty
        k = "rec6|" + doi.lower()                            # rec6: + resource type (Dataset / Software ...)
        if k not in self.d:
            a = _datacite(doi)
            if a:
                cr = a.get("creators") or []
                lic, access = _rights(a.get("rightsList"))
                self.d[k] = {
                    "creators":  [(c.get("familyName") or c.get("name") or "").split(",")[0].strip().lower().split()[-1]
                                  for c in cr if (c.get("familyName") or c.get("name") or "").strip()],
                    "orcids":    sorted({orcid(n.get("nameIdentifier")) for c in cr
                                         for n in c.get("nameIdentifiers") or [] if orcid(n.get("nameIdentifier"))}),
                    "publisher": a.get("publisher") or "", "repository": a.get("_repository") or "",
                    "license": lic, "access": access, "url": a.get("url") or "",   # landing page
                    "subjects":  dataset_subjects(a),                # SSIF / FOS, for the field cross-check
                    "type":      (a.get("types") or {}).get("resourceTypeGeneral") or ""}
            else:
                m = _csl(doi) or {}
                lic, L = "", m.get("license")
                if isinstance(L, list) and L:
                    lic = L[0].get("URL", "") if isinstance(L[0], dict) else str(L[0])
                self.d[k] = {**empty, "creators": _surnames(m), "publisher": m.get("publisher", "") or "",
                             "license": lic, "type": "Software" if m.get("type") == "software" else ""}
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
    v = cand.get("verdict", ""); in_das = cand.get("in_das")
    if v.startswith("data-verified"):              return "confirmed"
    if v.startswith("not-data"):                   return "not-data"     # registry says cited article
    if in_das:                                                           # declared, but unconfirmed
        if v.startswith("dead") or "not-found" in v: return "likely-broken-link"
        if v.startswith("resolves"):                 return "likely-no-doi"
        return "likely-unchecked"
    return "noise"                                                       # not declared + unconfirmed = reference

def _das_window(ident, das_text):
    """The DAS text around this id (sentence-ish context for the own-verb check)."""
    das = das_text or ""
    i = das.lower().find((ident or "").lower())
    return das[max(0, i - 160):i + 60] if i >= 0 else ""

def classify(cand, dataset_creators, paper_header, das_text="", found_in="",
             dataset_orcids=(), paper_orcids=(), access=""):
    """paper_header: the paper's first-page text (author block). das_text: optional DAS text.
    found_in: coarse in-text location (das/body/supplement/references) -- a weak provenance nudge.
    dataset_orcids / paper_orcids: creator / author ORCIDs (either may be partial or empty).
    access: DataCite access right ('open' / 'restricted' / '')."""
    hdr = (paper_header or "").lower()
    dc  = [s for s in (dataset_creators or []) if len(s) >= 3]
    ctx = cand.get("evidence") or _das_window(cand.get("identifier", ""), das_text)
    orcid_hit = bool(set(dataset_orcids or ()) & set(paper_orcids or ()))
    overlap  = ("own" if any(s in hdr for s in dc) else "reused") if (dc and hdr) else None
    flag     = cand.get("created_by_authors")
    flag_sig = "own" if flag is True else ("reused" if flag is False else None)
    # --- provenance: deterministic signals only, in priority order; never a guess.
    if orcid_hit:                                      # same person, by ORCID -- strongest signal
        prov, by = "own", "orcid-overlap"
    elif overlap:                                      # DataCite creators vs the paper's authors ==
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
    elif access == "restricted":                   openness = "restricted"   # DataCite access right
    elif v.startswith("data-verified"):            openness = "restricted" if "EGA" in v else "open"
    elif v.startswith("resolves"):                 openness = "open"
    else:                                          openness = "unknown"
    return prov, openness
