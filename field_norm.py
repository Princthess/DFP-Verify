"""
FIELD NORM - a reference for dataset openness per research area, counted over all of DataCite.

Optional and separate from the pipeline: run it now and then (it asks DataCite for counts, it does not
download records) and the dashboard compares the corpus's own datasets with it.

What it measures (dataset level, DataCite resource type "dataset"):
  restricted      -- rightsList has info:eu-repo/semantics/{restricted,closed,embargoed,metadataonly}Access
                     (the same rule classify.py uses for our own datasets)
  licence_stated  -- rightsList has a licence (SPDX id, or a Creative Commons / Open Data Commons URI)
per SSIF area (1-6) and publication year.

How datasets get an area: their DataCite subjects in the OECD Fields of Science scheme ("FOS: ...").
SSIF is built on OECD FOS, so the six areas and most subjects share names; the names come from Swepub's
SSIF list (via fields.FieldCache), and FOS_NAME holds the few places where the OECD wording differs.
A dataset with FOS subjects in two areas counts in both; within an area it counts once.

Limits, stated in the output too:
  - only datasets that have a FOS subject are counted (a small share of DataCite; Zenodo sets none);
  - big bulk registrants can dominate an area (e.g. DiSSCo specimen records in Biological sciences), so
    top_repository / top_repository_share are written per area;
  - this is NOT a norm for "papers that share data": DataCite has no denominator of papers.

Usage:  python field_norm.py            -> output/field_norm.csv  (or DV_OUT_DIR)
"""
import csv, datetime, os, requests
import config; config.load_env()   # .env before fields.py reads DV_CONTACT_EMAIL
from fields import FieldCache

API = "https://api.datacite.org"
UA = {"User-Agent": f"dfp-verify/0.1 (mailto:{os.environ.get('DV_CONTACT_EMAIL', 'your-contact@example.org')})"}
FIRST_YEAR = 2015

# OECD FOS wording where it differs from the SSIF name (SSIF code -> FOS label). Fixed standard.
FOS_NAME = {"4": "Agricultural sciences", "6": "Humanities", "101": "Mathematics",
            "305": "Other medical sciences", "604": "Arts (arts, history of arts, performing arts, music)"}
RESTRICTED = ("rightsList.rightsUri:(*restrictedAccess OR *closedAccess OR *embargoedAccess "
              "OR *metadataonlyAccess)")
LICENCE = "(rightsList.rightsIdentifier:* OR rightsList.rightsUri:(*creativecommons* OR *opendatacommons*))"

def _meta(query):
    r = requests.get(API + "/dois", headers=UA, timeout=180,
                     params={"resource-type-id": "dataset", "query": query,
                             "page[size]": 1, "disable-facets": "false"})
    r.raise_for_status()
    return r.json()["meta"]

def _per_year(meta):
    return {int(x["id"]): x["count"] for x in meta.get("published", []) if x["id"].isdigit()}

def _client_name(cid):
    try:
        return requests.get(f"{API}/clients/{cid}", headers=UA, timeout=60).json()["data"]["attributes"]["name"]
    except Exception:
        return cid

def area_queries(ssif):
    """{area code: (area name, [FOS labels], query)} from Swepub's SSIF list."""
    out = {}
    for a in "123456":
        labels = [FOS_NAME.get(a, ssif[a])] + [FOS_NAME.get(c, n) for c, n in sorted(ssif.items())
                                              if len(c) == 3 and c[0] == a]
        q = "subjects.subject:(" + " OR ".join(f'"FOS: {l}"' for l in labels) + ")"
        out[a] = (ssif[a], labels, q)
    return out

def main():
    ssif = FieldCache().ssif()
    if not ssif:
        raise SystemExit("Could not read the SSIF list from Swepub.")
    out_dir = os.environ.get("DV_OUT_DIR", "output")
    today = datetime.date.today().isoformat()
    rows = []
    for a, (name, labels, q) in area_queries(ssif).items():
        top, top_name, top_share = None, "", 0
        # variant "all", then the same counts without the area's largest repository (shows how much
        # one registrant drives the number)
        for variant in ("all", "without largest repository"):
            qq = q if variant == "all" else f"({q}) AND NOT client_id:\"{top['id']}\""
            allm, res, lic = _meta(qq), _meta(f"({qq}) AND {RESTRICTED}"), _meta(f"({qq}) AND {LICENCE}")
            if top is None:
                top = (allm.get("clients") or [{}])[0]
                top_share = round(top.get("count", 0) / allm["total"], 3) if allm["total"] else 0
                top_name = _client_name(top["id"]) if top.get("id") else ""
            ya, yr, yl = _per_year(allm), _per_year(res), _per_year(lic)
            base = {"ssif_area": a, "area": name, "variant": variant, "top_repository": top_name,
                    "top_repository_share": top_share, "fos_subjects": "; ".join(labels),
                    "source": "DataCite REST API, resource type dataset", "fetched": today}
            rows.append({**base, "year": "all", "datasets": allm["total"], "restricted": res["total"],
                         "licence_stated": lic["total"]})
            for y in sorted(y for y in ya if FIRST_YEAR <= y <= datetime.date.today().year):
                rows.append({**base, "year": y, "datasets": ya[y], "restricted": yr.get(y, 0),
                             "licence_stated": yl.get(y, 0)})
            print(f"  {a} {name} [{variant}]: {allm['total']:,} datasets, "
                  f"{res['total']/max(allm['total'],1):.1%} restricted, "
                  f"{lic['total']/max(allm['total'],1):.1%} licence stated"
                  + (f"; largest: {top_name} ({top_share:.0%})" if variant == "all" else ""))
            if not top.get("id"): break
    for r in rows:
        r["share_restricted"] = round(r["restricted"] / r["datasets"], 4) if r["datasets"] else ""
        r["share_licence_stated"] = round(r["licence_stated"] / r["datasets"], 4) if r["datasets"] else ""
    cols = ["ssif_area", "area", "variant", "year", "datasets", "restricted", "licence_stated", "share_restricted",
            "share_licence_stated", "top_repository", "top_repository_share", "fos_subjects", "source", "fetched"]
    path = os.path.join(out_dir, "field_norm.csv")
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols); w.writeheader(); w.writerows(rows)
    print(f"Wrote {path} ({len(rows)} rows)")

if __name__ == "__main__":
    main()
