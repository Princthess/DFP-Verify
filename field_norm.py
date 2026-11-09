"""
FIELD NORM - a DataCite reference for the openness of the corpus's own datasets, compared within the
same repository and research area.

Optional and separate from the pipeline: run it after run_pipeline.py (it reads output/per_dataset.csv
and summary.csv) and the dashboard shows the comparison.

Why within the same repository: in DataCite as a whole, field subjects are set by only a few
repositories (figshare, the specimen registry DiSSCo), so an all-of-DataCite "field norm" mostly
measures those repositories. Here each own dataset is compared with the other datasets in ITS
repository, in the area of the paper that cites it:
  1. same repository + same SSIF area -- when the repository puts SSIF (or OECD FOS) subjects on its
     datasets (SND, DORIS) and the area has at least MIN_AREA datasets;
  2. else the whole repository (e.g. Zenodo, which sets no subjects).

What is compared (dataset level, same rules on both sides, from DataCite's own rights):
  open            -- access right info:eu-repo/semantics/openAccess, stated explicitly
  restricted      -- access right info:eu-repo/semantics/{restricted,closed,embargoed,metadataonly}Access
  licence_stated  -- a licence in the rights (as classify._rights reads it). Separate from access: SND
                     has many open datasets without a licence, SciLifeLab licences but states no access.
  The rest have no access right stated (access_not_stated) -- not counted as open.
Versions and duplicate DOIs count once (DOIs marked IsVersionOf / IsIdenticalTo another are skipped),
as the pipeline collapses versions. Accessions (ENA, PRIDE ...) are not in DataCite -> not compared.

It is a reference for DATASET openness, not a norm for the share of PAPERS that share data.

Usage:  python field_norm.py
  -> output/field_norm.csv           reference per repository x area (and the whole repository)
  -> output/field_norm_datasets.csv  each own dataset with its reference values
"""
import csv, datetime, os, re, time, requests
import config; config.load_env()   # .env before the modules below read DV_CONTACT_EMAIL
from fields import FieldCache, dataset_subjects
from classify import _rights

API = "https://api.datacite.org"
UA = {"User-Agent": f"dfp-verify/0.1 (mailto:{os.environ.get('DV_CONTACT_EMAIL', 'your-contact@example.org')})"}
MIN_AREA = 20          # fewer datasets than this in repository x area -> use the whole repository
PAGE_LIMIT = 20000     # repositories up to this size are read record by record (sparse fields, 1000/page)

# OECD FOS wording where it differs from the SSIF name (SSIF code -> FOS label). Fixed standard.
FOS_NAME = {"4": "Agricultural sciences", "6": "Humanities", "101": "Mathematics",
            "305": "Other medical sciences", "604": "Arts (arts, history of arts, performing arts, music)"}
SKIP_REL = {"IsVersionOf", "IsIdenticalTo"}
ONE_PER_DATASET = "NOT relatedIdentifiers.relationType:(IsVersionOf OR IsIdenticalTo)"
RESTRICTED = ("rightsList.rightsUri:(*restrictedAccess OR *closedAccess OR *embargoedAccess "
              "OR *metadataonlyAccess)")
OPEN = "rightsList.rightsUri:*openAccess"
LICENCE = "(rightsList.rightsIdentifier:* OR rightsList.rightsUri:(*creativecommons* OR *opendatacommons*))"

def _get(path, **params):
    for attempt in range(3):
        try:
            r = requests.get(API + path, headers=UA, params=params, timeout=180)
            if r.status_code == 200: return r.json()
            if r.status_code == 404: return None
        except requests.RequestException:
            pass
        time.sleep(2 * (attempt + 1))
    raise SystemExit(f"DataCite did not answer: {path}")

def fos_areas(ssif):
    """lower-case FOS label -> SSIF area digit (FOS subjects carry no code)."""
    m = {}
    for c, n in ssif.items():
        if len(c) in (1, 3):
            m[FOS_NAME.get(c, n).lower()] = c[0]
    return m

def record_areas(attrs, fos_map):
    out = set()
    for s in dataset_subjects(attrs):
        if s["scheme"] == "ssif" and s["code"][:1] in "123456":
            out.add(s["code"][0])
        elif s["scheme"] == "fos" and s["label"].lower() in fos_map:
            out.add(fos_map[s["label"].lower()])
    return out

def is_version(attrs):
    return any(r.get("relationType") in SKIP_REL for r in attrs.get("relatedIdentifiers") or [])

def counts_by_paging(client, fos_map):
    """{area or 'all': [datasets, restricted, licence]}, reading every dataset record of the repository."""
    c = {"all": [0, 0, 0, 0]}
    url, params = API + "/dois", {"client-id": client, "resource-type-id": "dataset", "page[size]": 1000,
                                  "page[cursor]": 1, "fields[dois]": "subjects,rightsList,relatedIdentifiers"}
    while url:
        j = requests.get(url, headers=UA, params=params, timeout=180).json()
        for d in j.get("data", []):
            a = d["attributes"]
            if is_version(a): continue
            lic, acc = _rights(a.get("rightsList"))
            v = (1, int(acc == "restricted"), int(bool(lic)), int(acc == "open"))
            for k in ["all"] + sorted(record_areas(a, fos_map)):
                row = c.setdefault(k, [0, 0, 0, 0])
                for i in range(4): row[i] += v[i]
        url, params = j.get("links", {}).get("next"), None
    return c

def counts_by_query(client, ssif):
    """Same counts from DataCite's search, for big repositories (FOS subjects only; SSIF codes can't be
    matched safely in a query because other schemes' codes may start with the same digits)."""
    def n(q):
        return _get("/dois", **{"client-id": client, "resource-type-id": "dataset", "query": q,
                                "page[size]": 0})["meta"]["total"]
    c = {"all": [n(ONE_PER_DATASET), n(f"{ONE_PER_DATASET} AND {RESTRICTED}"), n(f"{ONE_PER_DATASET} AND {LICENCE}"),
                 n(f"{ONE_PER_DATASET} AND {OPEN}")]}
    for a in "123456":
        labels = [FOS_NAME.get(a, ssif[a])] + [FOS_NAME.get(k, v) for k, v in ssif.items() if len(k) == 3 and k[0] == a]
        q = "subjects.subject:(" + " OR ".join(f'"FOS: {l}"' for l in labels) + f") AND {ONE_PER_DATASET}"
        total = n(q)
        if total:
            c[a] = [total, n(f"({q}) AND {RESTRICTED}"), n(f"({q}) AND {LICENCE}"), n(f"({q}) AND {OPEN}")]
    return c

def paper_areas(field, source):
    """SSIF areas of a paper (summary field), only when the field is SSIF (Swepub / Swepub classify)."""
    if not source.startswith("swepub"): return []
    return sorted({c[0] for c in re.findall(r"(?:^|; )(\d{1,5})\b", field) if c[0] in "123456"})

def main():
    out_dir = os.environ.get("DV_OUT_DIR", "output")
    ssif = FieldCache().ssif()
    if not ssif: raise SystemExit("Could not read the SSIF list from Swepub.")
    fos_map, today = fos_areas(ssif), datetime.date.today().isoformat()

    summ = list(csv.DictReader(open(os.path.join(out_dir, "summary.csv"), encoding="utf-8-sig")))
    areas = {re.sub(r"\.[^.]+$", "", s["paper"]).lower(): paper_areas(s["field"], s["field_source"]) for s in summ}
    own = [r for r in csv.DictReader(open(os.path.join(out_dir, "per_dataset.csv"), encoding="utf-8-sig"))
           if r["status"] == "confirmed" and r["provenance"] == "own"]

    # own datasets: repository (DataCite client) + rights straight from DataCite
    mine, clients = [], {}
    for r in own:
        j = _get("/dois/" + r["identifier"], include="client") if r["identifier"].startswith("10.") else None
        if not j:
            mine.append({**r, "client": "", "note": "not in DataCite (accession or other registry): not compared"})
            continue
        a = j["data"]["attributes"]
        cid = j["data"]["relationships"]["client"]["data"]["id"]
        cname = next((x["attributes"]["name"] for x in j.get("included", []) if x["id"] == cid), cid)
        lic, acc = _rights(a.get("rightsList"))
        clients[cid] = cname
        mine.append({**r, "client": cid, "client_name": cname, "dc_restricted": int(acc == "restricted"),
                     "dc_licence": int(bool(lic)), "dc_open": int(acc == "open"), "note": ""})

    ref = {}
    for cid, cname in clients.items():
        total = _get("/dois", **{"client-id": cid, "resource-type-id": "dataset", "page[size]": 0})["meta"]["total"]
        how = "records" if total <= PAGE_LIMIT else "search"
        ref[cid] = counts_by_paging(cid, fos_map) if how == "records" else counts_by_query(cid, ssif)
        a = ref[cid]["all"]
        print(f"  {cname}: {a[0]:,} datasets ({how}), {a[3]/max(a[0],1):.1%} open, {a[1]/max(a[0],1):.1%} restricted, "
              f"{a[2]/max(a[0],1):.1%} licence; areas with >= {MIN_AREA}: "
              + (", ".join(k for k, v in ref[cid].items() if k != "all" and v[0] >= MIN_AREA) or "none"))

    rows = []
    for cid, c in ref.items():
        for k, (n, res, lic, opn) in sorted(c.items()):
            rows.append({"client_id": cid, "repository": clients[cid], "ssif_area": k,
                         "area": "whole repository" if k == "all" else ssif.get(k, k),
                         "datasets": n, "open": opn, "restricted": res, "access_not_stated": n - opn - res,
                         "licence_stated": lic,
                         "share_open": round(opn / n, 4) if n else "",
                         "share_restricted": round(res / n, 4) if n else "",
                         "share_licence_stated": round(lic / n, 4) if n else "",
                         "fetched": today})
    cols = list(rows[0]) if rows else []
    with open(os.path.join(out_dir, "field_norm.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols); w.writeheader(); w.writerows(rows)

    # one row per own dataset x paper area, with the reference it is compared to
    drows = []
    for m in mine:
        for a in areas.get(m["paper"], []) or ["-"]:
            base = {"paper": m["paper"], "identifier": m["identifier"], "repository": m.get("client_name", m["repository"]),
                    "ssif_area": a, "area": ssif.get(a, "no SSIF field")}
            if not m["client"]:
                drows.append({**base, "open": "", "restricted": "", "licence_stated": "", "reference": "",
                              "ref_datasets": "", "ref_share_open": "", "ref_share_restricted": "", "ref_share_licence_stated": "", "note": m["note"]})
                continue
            c = ref[m["client"]]
            k = a if a in c and c[a][0] >= MIN_AREA else "all"
            n, res, lic, opn = c[k]
            drows.append({**base, "open": m["dc_open"], "restricted": m["dc_restricted"],
                          "licence_stated": m["dc_licence"],
                          "reference": "same repository, same area" if k != "all" else "whole repository",
                          "ref_datasets": n, "ref_share_open": round(opn / n, 4) if n else "",
                          "ref_share_restricted": round(res / n, 4) if n else "",
                          "ref_share_licence_stated": round(lic / n, 4) if n else "", "note": ""})
    with open(os.path.join(out_dir, "field_norm_datasets.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(drows[0])); w.writeheader(); w.writerows(drows)
    print(f"Wrote field_norm.csv ({len(rows)} rows) and field_norm_datasets.csv ({len(drows)} rows) in {out_dir}")

if __name__ == "__main__":
    main()
