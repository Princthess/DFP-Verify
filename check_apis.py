"""
Check that the outside services the tool depends on still answer the way it expects.

    python check_apis.py

For each service it asks one question whose answer we know (examples from a real run), through the
tool's own code, with the caches bypassed. So it checks both that the service is up and that its answer
still has the shape the tool reads. Takes about 15 seconds; needs internet, no corpus, no LLM.

When a check fails: run it again later (services have bad days). If it keeps failing, the service has
probably changed its API, and the step named in "used for" needs a fix. The pipeline itself does not
crash when a service is down: lookups that fail are not cached and are tried again on the next run.
"""
import os, sys, tempfile, time
import config; config.load_env()          # the contact email in .env goes into every request
import verify, classify, registry_lookup, fields

TMP = tempfile.mkdtemp(prefix="dv_check_")   # fresh, empty caches: every answer comes from the service


def fresh(cls, name):
    return cls(os.path.join(TMP, name))


# Known answers, from the 20-paper test corpus (all public records).
PAPER       = "10.1016/j.animal.2026.101843"    # paper with an SND dataset linked in DataCite and a Swepub record
DATASET     = "10.5878/z57e-3j96"               # that dataset (SND, open)
RESTRICTED  = "10.5878/cnaf-v548"               # an SND dataset with restricted access
ZENODO      = "10.5281/zenodo.5034182"          # a Zenodo dataset in a Chalmers community
NO_SWEPUB   = "10.1371/journal.pone.0302426"    # a paper not in Swepub: field comes from the automatic classifier


def check_doi_org():
    v = verify._check_doi(DATASET)
    assert v.startswith("data-verified"), f"dataset DOI answered {v!r}"
    v = verify._check_doi(PAPER)
    assert v.startswith("not-data"), f"paper DOI answered {v!r} (should be recognised as not data)"
    return "dataset DOI recognised as data, paper DOI as not data"

def check_datacite_record():
    meta = fresh(classify.MetaCache, "meta.json")
    rec = meta.record(DATASET)
    assert rec["repository"] == "Swedish National Data Service", f"repository = {rec['repository']!r}"
    assert rec["access"] == "open", f"access = {rec['access']!r}"
    assert rec["creators"], "no creators"
    rec = meta.record(RESTRICTED)
    assert rec["access"] == "restricted", f"restricted dataset gave access = {rec['access']!r}"
    return "repository, creators and open / restricted access read correctly"

def check_datacite_links():
    reg = fresh(registry_lookup.RegistryCache, "reg.json")
    found = [l["identifier"] for l in registry_lookup.reverse_links(PAPER, reg)]
    assert DATASET in found, f"links found: {found}"
    return f"{len(found)} dataset(s) linked to the test paper, including the known one"

def check_paper_metadata():
    reg = fresh(registry_lookup.RegistryCache, "reg.json")
    title = reg.title(PAPER)
    assert len(title) > 20, f"title = {title!r}"
    assert reg.year(PAPER) == "2026", f"year = {reg.year(PAPER)!r}"
    assert reg.publisher(PAPER), "no publisher"
    return f"title, year and publisher read ({reg.publisher(PAPER)})"

def check_crossref():
    reg = fresh(registry_lookup.RegistryCache, "reg.json")
    title = reg.title(PAPER)
    hits = [d for d, _ in reg.crossref_search(title)]
    assert PAPER in hits, f"searching the title gave {hits}"
    return "title search finds the paper"

def check_ena():
    v = verify._check_accession("PRJEB84056")
    assert v.startswith("data-verified"), f"PRJEB84056 answered {v!r}"
    studies = fresh(classify.MetaCache, "meta.json").run_study("ERR1995253")
    assert "ERP022986" in studies, f"run ERR1995253 gave studies {studies}"
    return "project found; run linked to its study"

def check_pride():
    v = verify._check_accession("PXD061695")
    assert v.startswith("data-verified"), f"PXD061695 answered {v!r}"
    return "proteomics project found"

def check_ncbi():
    v = verify._check_accession("GSE2034")
    assert v.startswith("data-verified"), f"GSE2034 answered {v!r}"
    return "GEO series found"

def check_zenodo():
    comms = fresh(classify.MetaCache, "meta.json").zenodo_communities(ZENODO)
    assert any(slug == "materialsmodeling" for slug, _ in comms), f"communities = {comms}"
    return "communities of a Zenodo record read"

def check_swepub():
    fc = fresh(fields.FieldCache, "field.json")
    codes = fc.swepub_codes(PAPER)
    assert codes, "no SSIF codes found for the test paper"
    names = fc.ssif()
    assert len(names) > 100 and codes[0] in names, f"subject list has {len(names)} entries"
    return f"SSIF codes found ({codes[0]} {names.get(codes[0], '')})"

def check_openalex_and_classifier():
    fc = fresh(fields.FieldCache, "field.json")
    assert fc.openalex(NO_SWEPUB), "no OpenAlex topic"
    assert fc.work_type(NO_SWEPUB) == "article", f"work type = {fc.work_type(NO_SWEPUB)!r}"
    codes = fc.classify(NO_SWEPUB)
    assert codes, "Swepub's classifier suggested nothing"
    return "topic, work type and automatic SSIF codes read"


# (service, what the tool uses it for, check). Order: the core steps first.
CHECKS = [
    ("doi.org",            "checking that a DOI exists and is data",              check_doi_org),
    ("DataCite record",    "repository, creators, open / restricted access",      check_datacite_record),
    ("DataCite links",     "datasets linked to a paper; repairing broken ids",    check_datacite_links),
    ("doi.org metadata",   "paper title check, year, journal, publisher",         check_paper_metadata),
    ("Crossref",           "finding a paper's DOI when none was given",           check_crossref),
    ("ENA",                "checking ENA accessions; runs -> studies",            check_ena),
    ("PRIDE",              "checking proteomics accessions",                      check_pride),
    ("NCBI (GEO / SRA)",   "checking GEO and SRA accessions",                     check_ncbi),
    ("Zenodo",             "Zenodo communities (report only)",                    check_zenodo),
    ("Swepub",             "research field (SSIF) -- skipped with DV_FIELDS=off", check_swepub),
    ("OpenAlex + Swepub classifier", "field for papers not in Swepub; work type", check_openalex_and_classifier),
]


def main():
    print(f"Checking {len(CHECKS)} services (needs internet; about 15 seconds)\n")
    failed = []
    for name, used_for, check in CHECKS:
        t = time.time()
        try:
            detail, ok = check(), True
        except AssertionError as e:
            detail, ok = f"unexpected answer: {e}", False
        except Exception as e:
            detail, ok = f"error: {type(e).__name__}: {e}", False
        mark = "OK  " if ok else "FAIL"
        print(f"  {mark} {name:<30} {time.time() - t:4.1f}s  {detail}")
        if not ok:
            failed.append((name, used_for))
    print()
    if failed:
        print("Failed -- these steps may give empty or wrong values until fixed:")
        for name, used_for in failed:
            print(f"  {name}: {used_for}")
        print("Try again later first; a service that keeps failing has probably changed.")
        sys.exit(1)
    print("All services answer as expected.")


if __name__ == "__main__":
    main()
