"""
ROAGG COMPARE - DFP-Verify's OWN datasets next to RoAgg's list for the same organisation (optional).

RoAgg (SND, https://github.com/snd-sweden/roagg) harvests an organisation's research outputs from DataCite
(+ OpenAIRE / OpenAlex / Crossref) by ROR and name variants: metadata-first, organisation level.
DFP-Verify reads the papers: full-text first, paper level. Both see the organisation's own datasets, from
opposite sides, so each is a free check of the other:

  in both                      both layers work for this dataset
  only in the paper            RoAgg doesn't list it -> WHY (from the dataset's own DataCite record):
                               not a DOI (archive accession) / DOI not in DataCite / no organisation
                               name or ROR in publisher, creator or contributor affiliations / the
                               record has it, but RoAgg's list doesn't (version, harvest date ...)
  only in RoAgg, linked to     RoAgg's record names one of our papers (referencedByDoi) but our tool has
  one of our papers            no own dataset for it -> WHY (our status for that DOI)

Only the authors' own datasets (status confirmed, provenance own) -- reuse and other organisations' data
are not RoAgg's business. Run after run_pipeline.py:

  python roagg_compare.py path/to/roagg.csv            (reads DV_OUT_DIR, else output/)
  DV_ORG_NAME=Chalmers DV_ORG_ROR=https://ror.org/040wg7k59 ...   (for the "why" check)

Writes OUT/roagg_compare.csv. No pandas, no RoAgg install needed: it reads RoAgg's CSV.
"""
import csv, json, os, re, sys, time
import config; config.load_env()
from net import S

def _doi(x): return (x or "").strip().lower().replace("https://doi.org/", "")

def _stem(s): return os.path.splitext(os.path.basename(str(s)))[0].lower()

def load_roagg(path):
    """RoAgg rows by DOI, plus version groups (conceptDoi; older exports lack it) and referencedByDoi."""
    rows = {}
    for r in csv.DictReader(open(path, encoding="utf-8-sig")):
        d = _doi(r.get("doi"))
        if d: rows[d] = r
    concept = {}
    for d, r in rows.items():
        c = _doi(r.get("conceptDoi"))
        if c: concept.setdefault(c, set()).update({c, d})
    for d in rows:                      # figshare: "<doi>" and "<doi>.v1" are one item (no conceptDoi given)
        b = re.sub(r"\.v\d+$", "", d)
        if b != d: concept.setdefault(b, set()).update({b, d})
    group = {}
    for members in concept.values():
        for m in members: group[m] = members
    return rows, group

def _refs(r):
    try: return {_doi(x) for x in json.loads(r.get("referencedByDoi") or "[]")}
    except Exception: return set()

_paper_org = {}
def paper_is_org(doi, org, ror):
    """Is the paper the organisation's? An author's institution in OpenAlex has its ROR (or name).
    'yes' / 'no' / '' (no DOI or no answer). RoAgg lists the organisation's outputs only, so an own
    dataset of someone else's paper is not a RoAgg gap."""
    doi = _doi(doi)
    if not doi or not (org or ror): return ""
    if doi not in _paper_org:
        try:
            r = S.get(f"https://api.openalex.org/works/doi:{doi}", timeout=30)
            inst = [i for a in (r.json().get("authorships") or []) for i in (a.get("institutions") or [])] \
                if r.status_code == 200 else None
        except Exception:
            inst = None
        if inst is None:
            _paper_org[doi] = ""
        else:
            hit = any((ror and (i.get("ror") or "").rstrip("/").endswith(ror.split("/")[-1])) or
                      (org and org.lower() in (i.get("display_name") or "").lower()) for i in inst)
            _paper_org[doi] = "yes" if hit else "no"
        time.sleep(0.1)
    return _paper_org[doi]

def why_missing(c, org, ror):
    """Why RoAgg doesn't list one of our own datasets -- read from the dataset's DataCite record."""
    if c["kind"] != "doi":
        return "not a DOI (archive accession: RoAgg harvests DOIs)"
    r = S.get(f"https://api.datacite.org/dois/{c['identifier']}", params={"affiliation": "true"}, timeout=30)
    if r.status_code == 404:
        return "DOI not in DataCite (e.g. Crossref)"
    if r.status_code != 200:
        return f"not checked (DataCite HTTP {r.status_code})"
    a = r.json()["data"]["attributes"]; time.sleep(0.1)
    def names(people):
        out = []
        for p in people or []:
            for af in p.get("affiliation") or []:
                out.append(af if isinstance(af, str) else f"{af.get('name','')} {af.get('affiliationIdentifier','')}")
        return out
    pub = a.get("publisher")
    pub = pub.get("name", "") if isinstance(pub, dict) else (pub or "")
    found = [w for w, txt in (("publisher", pub), ("creator affiliation", " ".join(names(a.get("creators")))),
                              ("contributor affiliation", " ".join(names(a.get("contributors")))),
                              ("funder", json.dumps(a.get("fundingReferences") or [])))
             if (org and org.lower() in txt.lower()) or (ror and ror.split("/")[-1] in txt)]
    if not found:
        return "no organisation name or ROR in the record (publisher, affiliations, funder)"
    return "record names the organisation (" + ", ".join(found) + "), but RoAgg's list lacks it"

def main(roagg_csv, out_dir=None):
    out_dir = out_dir or os.environ.get("DV_OUT_DIR") or "output"
    org, ror = os.environ.get("DV_ORG_NAME", ""), os.environ.get("DV_ORG_ROR", "")
    rows, group = load_roagg(roagg_csv)
    D = list(csv.DictReader(open(os.path.join(out_dir, "per_dataset.csv"), encoding="utf-8-sig")))
    S_ = list(csv.DictReader(open(os.path.join(out_dir, "summary.csv"), encoding="utf-8-sig")))
    # only title-checked paper DOIs: an unconfirmed DOI may be another paper's, and its datasets aren't ours
    M = list(csv.DictReader(open(os.path.join(out_dir, "merged_output.csv"), encoding="utf-8-sig")))
    ok = {_stem(m["file"]) for m in M if m.get("dv_paper_doi_check") in ("confirmed", "corrected", "found")}
    paper_of_doi = {_doi(s["doi"]): _stem(s["paper"]) for s in S_ if s.get("doi") and _stem(s["paper"]) in ok}
    doi_of_paper = {v: k for k, v in paper_of_doi.items()}
    own = [c for c in D if c["status"] == "confirmed" and c["provenance"] == "own"]
    out = []
    for c in own:                                            # 1. our own datasets: does RoAgg list them?
        d = _doi(c["identifier"]) if c["kind"] == "doi" else ""
        hit = d if d in rows else next((m for m in group.get(d, ()) if m in rows), "")
        r = rows.get(hit, {})
        via = [k for k, f in (("publisher", "isPublisher"), ("creator", "haveCreatorAffiliation"),
                              ("contributor", "haveContributorAffiliation"), ("funder", "isFunder"))
               if str(r.get(f, "")).strip().lower() in ("true", "1")]       # older exports True/False, newer 1/0
        porg = paper_is_org(doi_of_paper.get(c["paper"], ""), org, ror)
        why = "" if hit else ("paper is not the organisation's (no author affiliated in OpenAlex)" if porg == "no"
                              else why_missing(c, org, ror))
        out.append({"direction": "own dataset in paper", "paper": c["paper"], "paper_is_org": porg,
                    "identifier": c["identifier"], "repository": c["repository"],
                    "in_roagg": ("yes" if hit == d else "yes (another version)") if hit else "no",
                    "roagg_matched_via": ", ".join(via), "why": why})
    ours = {_doi(c["identifier"]) for c in own if c["kind"] == "doi"}
    ours |= {m for d in list(ours) for m in group.get(d, ())}
    status = {(c["paper"], _doi(c["identifier"])): c for c in D}
    seen = set()                                            # one row per dataset: RoAgg lists every version
    for d, r in rows.items():                               # 2. RoAgg's datasets linked to our papers
        if (r.get("resourceType") or "").lower() not in ("dataset", "collection") or d in ours:
            continue
        members = group.get(d, {d})
        for ref in _refs(r):
            p = paper_of_doi.get(ref)
            if not p: continue
            key = (p, min(members))
            if key in seen: continue
            seen.add(key)
            if members & ours: continue                     # another version is one of our own datasets
            c = next((status[(p, m)] for m in members if (p, m) in status), None)
            why = ("not in the paper's text, only linked in DataCite" if c and c["status"] == "datacite-only" else
                   f"found, but classed as {c['provenance'] or c['status']}" if c else
                   "not found: the paper may not cite it, or cites it in a form the tool doesn't read")
            out.append({"direction": "RoAgg dataset linked to our paper", "paper": p, "paper_is_org": "",
                        "identifier": d,
                        "repository": r.get("dataCiteClientName", ""), "in_roagg": "yes",
                        "roagg_matched_via": "", "why": why})
    path = os.path.join(out_dir, "roagg_compare.csv")
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(out[0]) if out else ["direction"]); w.writeheader(); w.writerows(out)
    a = [o for o in out if o["direction"] == "own dataset in paper"]
    from collections import Counter
    print(f"RoAgg vs DFP-Verify ({os.path.basename(roagg_csv)}, {len(rows)} RoAgg records)")
    print(f"  own datasets in the papers: {len(a)}; in RoAgg: {sum(1 for o in a if o['in_roagg'] != 'no')}")
    for k, n in Counter(o["why"] for o in a if o["in_roagg"] == "no").most_common():
        print(f"    not in RoAgg - {k}: {n}")
    b = [o for o in out if o["direction"] != "own dataset in paper"]
    print(f"  RoAgg datasets linked to our papers but not an own dataset here: {len(b)}")
    for k, n in Counter(o["why"] for o in b).most_common():
        print(f"    {k}: {n}")
    print(f"  wrote {path}")

if __name__ == "__main__":
    if len(sys.argv) < 2: sys.exit(__doc__)
    main(sys.argv[1])
