"""
STAGE 2 - VERIFY (max precision).

Confirms each candidate identifier against authoritative registries, deterministically:
  - DOI       -> doi.org content negotiation (DataCite/Crossref): is it a dataset/software?
  - accession -> the archive's API (GEO/SRA/PRIDE/ENA/BioStudies): does the record exist?
  - code/osf/url -> HTTP resolve check (link lives; weak signal).

Results are cached to disk (.verify_cache.json) so re-runs are instant.

Public API:
  verify_candidates(cands, cache_path=...) -> same list, each with a "verdict" field
"""
import json, os, time, requests
from patterns import ACC_ROUTES   # (archive, anchored regex, check-kind) -- shared with detection

UA = {"User-Agent": f"dfp-verify/0.1 (mailto:{os.environ.get('DV_CONTACT_EMAIL', 'your-contact@example.org')})"}
DATA_TYPES = {"dataset", "software", "collection"}
S = requests.Session(); S.headers.update(UA)

def _http_status(url, head=True):
    try:
        r = S.request("HEAD" if head else "GET", url, timeout=10, allow_redirects=True, stream=True)
        if r.status_code in (403, 405, 501) and head:
            return _http_status(url, head=False)
        return r.status_code
    except Exception:
        return "ERR"

def _check_doi(doi):
    try:
        r = S.get("https://doi.org/" + doi, headers={"Accept": "application/vnd.citationstyles.csl+json"},
                  timeout=15, allow_redirects=True)
        if r.status_code != 200:
            return "dead/bad DOI"
        t = r.json().get("type")
        return "data-verified" if t in DATA_TYPES else f"not-data ({t})"
    except Exception:
        return "check-error"

def _check_accession(acc):
    hit = next(((arch, check) for arch, rx, check in ACC_ROUTES if rx.match(acc)), None)
    if not hit:
        return "accession-recognized (format not in registry)"
    arch, check = hit
    if check is None:                      # detected but no auto-check wired (EGA/GCA/MetaboLights)
        return "accession-recognized (archive not auto-checked)"
    try:
        if check == "geo":
            u = f"https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi?db=gds&term={acc}[ACCN]&retmode=json"
            cnt = S.get(u, timeout=15).json().get("esearchresult", {}).get("count", "0"); time.sleep(0.34)
            return "data-verified (GEO)" if cnt not in ("0", None) else "accession-not-found"
        if check == "sra":
            u = f"https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi?db=sra&term={acc}&retmode=json"
            cnt = S.get(u, timeout=15).json().get("esearchresult", {}).get("count", "0"); time.sleep(0.34)
            return "data-verified (SRA)" if cnt not in ("0", None) else "accession-not-found"
        if check == "pride":
            s = S.get(f"https://www.ebi.ac.uk/pride/ws/archive/v2/projects/{acc}", timeout=15).status_code
        elif check == "ena":
            s = S.get(f"https://www.ebi.ac.uk/ena/browser/api/summary/{acc}", timeout=15).status_code
        else:  # "biostudies" (ArrayExpress / BioStudies)
            s = S.get(f"https://www.ebi.ac.uk/biostudies/api/v1/studies/{acc}", timeout=15).status_code
        return f"data-verified ({arch})" if s == 200 else "accession-not-found"
    except Exception:
        return "check-error"

def _verify_one(ident, kind):
    if kind == "mention":    return "no-id mention"          # LLM body-scan, nothing to resolve
    if kind == "doi":        return _check_doi(ident)
    if kind == "accession":  return _check_accession(ident)
    s = _http_status(ident)                                   # code / osf / url
    return f"resolves ({kind})" if s in (200, 301, 302) else f"dead link ({s})"

def verify_candidates(cands, cache_path=".verify_cache.json", progress=True):
    cache = {}
    if os.path.exists(cache_path):
        try: cache = json.load(open(cache_path, encoding="utf-8"))
        except Exception: cache = {}
    uniq = {(c["kind"], c["identifier"].lower()) for c in cands}
    todo = [k for k in uniq if (k[0] + "|" + k[1]) not in cache]
    if progress: print(f"  verify: {len(uniq)} unique, {len(cache)} cached, {len(todo)} to check")
    for i, (kind, ident) in enumerate(todo, 1):
        cache[kind + "|" + ident] = _verify_one(ident, kind)
        if progress and i % 50 == 0: print(f"    {i}/{len(todo)}")
    json.dump(cache, open(cache_path, "w", encoding="utf-8"), ensure_ascii=False, indent=0)
    for c in cands:
        c["verdict"] = cache.get(c["kind"] + "|" + c["identifier"].lower(), "unchecked")
    return cands
