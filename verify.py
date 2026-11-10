"""
STAGE 2 - VERIFY (max precision).

Confirms each candidate identifier against authoritative registries, deterministically:
  - DOI       -> doi.org content negotiation (DataCite/Crossref): is it a dataset/software?
  - accession -> the archive's API (GEO/SRA/PRIDE/ENA/BioStudies): does the record exist?
  - code/osf/url -> HTTP resolve check (link lives; weak signal). Only 404/410 count as dead; bot
    protection (AWS WAF / Cloudflare challenges, 403/429) or no answer -> "unchecked link", to check
    by hand -- a browser often opens these fine.

Results are cached to disk (.verify_cache.json) so re-runs are instant.

Public API:
  verify_candidates(cands, cache_path=...) -> same list, each with a "verdict" field
"""
import json, os, re, time
from patterns import ACC_ROUTES   # (archive, anchored regex, check-kind) -- shared with detection
from net import S                 # shared HTTP session (User-Agent with contact address)

DATA_TYPES = {"dataset", "software", "collection"}

# Answers that say "a bot check / rate limit stopped us", not "this page doesn't exist": 202 is AWS WAF's
# JavaScript challenge (figshare, Harvard Dataverse), 403/429/503 are blocks or limits. Only 404/410
# mean the link is dead.
BLOCKED = (202, 401, 403, 429, 503)
DEAD = (404, 410)
BOT_HEADERS = ("x-amzn-waf-action", "cf-mitigated")       # AWS WAF / Cloudflare challenge markers

def _http_status(url, head=True):
    """HTTP status, or 'blocked' (bot protection) / 'ERR' (no answer)."""
    try:
        r = S.request("HEAD" if head else "GET", url, timeout=15, allow_redirects=True, stream=True)
        if head and (r.status_code in (403, 405, 501) or r.status_code in BLOCKED):
            return _http_status(url, head=False)            # some sites only answer GET
        if any(h in r.headers for h in BOT_HEADERS):
            return "blocked"
        return r.status_code
    except Exception:
        return _http_status(url, head=False) if head else "ERR"

def _check_doi(doi):
    try:
        r = S.get("https://doi.org/" + doi, headers={"Accept": "application/vnd.citationstyles.csl+json"},
                  timeout=15, allow_redirects=True)
        if r.status_code in DEAD:                       # doi.org: no such DOI
            return "dead/bad DOI"
        if r.status_code != 200:                        # 429 / 5xx: try again next run, never cache as dead
            return f"check-error (HTTP {r.status_code})"
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

# Text extraction glues a footnote number or the next word onto an id at the end of a sentence:
# "bath-00739.28", "github.com/x/y.13", ".../tree/main.Rece(ived)". When the id as written is dead, the
# same id without that tail is tried -- the registry decides, no list of hosts.
GLUED_TAIL = re.compile(r"\.(?:\d{1,3}|[A-Z][a-z]{1,12})$")

def _dead(v):
    return v.startswith(("dead/bad DOI", "dead link", "accession-not-found"))

def _verify_one(ident, kind):
    v = _verify_one_as_is(ident, kind)
    m = GLUED_TAIL.search(ident)
    if _dead(v) and m:
        v2 = _verify_one_as_is(ident[:m.start()], kind)
        if not _dead(v2) and not v2.startswith(("check-error", "unchecked")):
            return f"{v2} [tail '{m.group(0)}' dropped]"
    return v

def _verify_one_as_is(ident, kind):
    if kind == "doi":        return _check_doi(ident)
    if kind == "accession":  return _check_accession(ident)
    s = _http_status(ident)                                   # code / osf / url
    if s in DEAD:                                  return f"dead link ({s})"
    if s == "blocked" or s in BLOCKED:             return f"unchecked link (site blocks automated checks, {s})"
    if s == "ERR":                                 return "unchecked link (no answer)"
    if isinstance(s, int) and 200 <= s < 400:      return f"resolves ({kind})"
    return f"unchecked link (HTTP {s})"

def verify_candidates(cands, cache_path=".verify_cache.json", progress=True):
    cache = {}
    if os.path.exists(cache_path):
        try: cache = json.load(open(cache_path, encoding="utf-8"))
        except Exception: cache = {}
    # cache keys are lower case, but the check uses the id as written: archives such as PRIDE and many
    # URL paths are case-sensitive ("pxd061695" is not found, "PXD061695" is)
    as_written = {}
    for c in cands:
        as_written.setdefault((c["kind"], c["identifier"].lower()), c["identifier"])
    uniq = set(as_written)
    todo = [k for k in uniq if (k[0] + "|" + k[1]) not in cache or _retry(cache[k[0] + "|" + k[1]])]
    if progress: print(f"  verify: {len(uniq)} unique, {len(cache)} cached, {len(todo)} to check")
    fresh = {}
    for i, (kind, ident) in enumerate(todo, 1):
        fresh[kind + "|" + ident] = _verify_one(as_written[(kind, ident)], kind)
        if progress and i % 50 == 0: print(f"    {i}/{len(todo)}")
    # Only lasting answers are cached. "Not found" / dead / unchecked can change -- data released after
    # the paper (PRIDE, ENA embargoes), a site that was down or blocked -- so they are asked again next run.
    cache.update({k: v for k, v in fresh.items() if not _retry(v)})
    json.dump(cache, open(cache_path, "w", encoding="utf-8"), ensure_ascii=False, indent=0)
    for c in cands:
        k = c["kind"] + "|" + c["identifier"].lower()
        c["verdict"] = fresh.get(k) or cache.get(k, "unchecked")
        m = re.search(r" \[tail '(.+)' dropped\]$", c["verdict"])
        if m:                         # use the id without the glued tail; say so like a DataCite repair
            written = c["identifier"]
            c["identifier"] = written[:-len(m.group(1))]
            c["verdict"] = c["verdict"][:m.start()]
            c.setdefault("registry", "")
            if not c["registry"]: c["registry"] = f"repaired (text had {written})"
    return cands

def _retry(verdict):
    # a malformed DOI string (mostly reference-list fragments) stays malformed, so "dead/bad DOI" is kept
    return verdict.startswith(("accession-not-found", "dead link", "unchecked", "check-error"))
