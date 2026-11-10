"""
patterns.py -- SINGLE SOURCE OF TRUTH for every SHARED regex and id-registry.

Nothing that matches identifiers or own-data verbs should be defined anywhere else: detect_union (detection), verify (verification) and classify (provenance) all import from
here, so a format or word is edited in ONE place and the modules stay in sync. In particular the
ACCESSIONS registry drives BOTH detection (the union regex) AND verification (archive routing),
so they can never drift apart.
Not here: the paper-level statement patterns ("no new data were generated", "available on request" ...).
Each is used in one place only, next to the code that cuts out the sentence, so they live in
statements.py.

Pattern sources:
  - DOIs / Swedish-Nordic DataCite prefixes / repo URLs -> our own (public DOI spec + facts).
  - Accession formats -> Bioregistry (bioregistry.io), pattern data CC0 1.0.
  - OWN_VERBS / REUSE_CUE -> our own short, generic phrase lists.
"""
import re

# --- DOIs & repository URLs --------------------------------------------------------------------
DOI_RX  = re.compile(r"10\.\d{4,}/[^\s,);>\"'<(\[\]]+", re.I)
# Swedish/Nordic DataCite prefixes that often appear without the "10." (orphaned) in extracted text.
ORPHAN_PREFIX = r"(5878|71870|17044|25504|18160|5281|6084|5061|17632|7910|17605|15468|5334)"
ORPHAN_RX = re.compile(r"(?<![\d./])" + ORPHAN_PREFIX + r"/[^\s,);>\"'<(\[\]]{2,}", re.I)
ZEN_URL = re.compile(r"zenodo\.org/records?/(\d+)", re.I)
GH_RX   = re.compile(r"https?://(?:www\.)?(?:github|gitlab|bitbucket)\.[^\s,);>\"'<]+", re.I)
OSF_RX  = re.compile(r"https?://(?:www\.)?osf\.io/[^\s,);>\"'<]+", re.I)
# Other data-REPOSITORY URLs (deposit targets, not an agency list): Figshare, Dryad, any Dataverse
# instance, Mendeley Data. Caught as kind "url" and HTTP-resolve-checked in verify.
DATA_REPO_URL = re.compile(
    r"https?://(?:[\w.-]+\.)?(?:figshare\.com|datadryad\.org|data\.mendeley\.com|[\w.-]*dataverse[\w.-]*)"
    r"[^\s,);>\"'<]*", re.I)

# --- Accession registry: ONE source for detection AND verification -----------------------------
# (archive, core pattern [no ^$ anchors], check) -- patterns from the Bioregistry (CC0).
# `check` tells verify.py how to confirm the record exists; None = detected but not auto-checked.
# The archive name + check kind must stay consistent with verify.py's endpoint dispatch.
ACCESSIONS = [
    # GEO: series / samples / datasets. Not GPL: a platform record describes an array design, not data.
    ("GEO",          r"G(?:SM|SE|DS)\d+",        "geo"),         # bioregistry: geo
    # INSDC run/experiment/study accessions have at least 6 digits ("SRA3" in prose is not one)
    ("SRA",          r"[SED]R[APRSXZ]\d{6,}",    "sra"),         # bioregistry: insdc.sra (+ INSDC length)
    ("ENA",          r"PRJ[DEN][A-Z]\d+",        "ena"),         # bioregistry: bioproject
    ("BioSample",    r"SAM[NED]\w?\d+",          "ena"),         # bioregistry: biosample
    ("PRIDE",        r"P[XRA]D\d{6}",            "pride"),       # bioregistry: pride.project
    ("ArrayExpress", r"[AEP]-\w{4}-\d+",         "biostudies"),  # bioregistry: arrayexpress
    ("BioStudies",   r"S-[A-Z]{4}[-_A-Z\d]+",    "biostudies"),  # bioregistry: biostudies
    ("MetaboLights", r"MTBL[CS]\d+",             None),          # bioregistry: metabolights
    ("EGA",          r"EGA[SD]\d{11}",           None),          # bioregistry: ega.study/ega.dataset
    ("GCA",          r"GCA_\d{9}(?:\.\d+)?",     None),          # bioregistry: insdc.gca
]
# union, for detection (detect_union)
ACC_RX = re.compile(r"\b(?:" + "|".join(p for _, p, _ in ACCESSIONS) + r")\b", re.I)
# anchored per-archive matchers + check kind, for routing (verify)
ACC_ROUTES = [(arch, re.compile(r"^(?:" + pat + r")$", re.I), check) for arch, pat, check in ACCESSIONS]

# --- provenance: own-data verbs ("we submitted/deposited ...") ---------------------------------
# Explicit only: the authors put the data somewhere, or the data come from THIS study. Bare "we" / "our" /
# "collected" also occur in reuse sentences ("we obtained data from Statistics Sweden"), so they are not
# enough on their own (too loose on a 78-paper corpus: external data sources came out as "own").
OWN_VERBS = re.compile(
    r"\b(?:we|the\s+authors)\s+(?:have\s+)?(?:deposited|submitted|uploaded|archived|published|released|"
    r"shared|made\s+(?:\w+\s+){0,3}available)\b"
    r"|\b(?:generated|collected|produced|created|recorded|measured|acquired|obtained)\s+(?:in|during|for|within|by)\s+"
    r"(?:this|the\s+(?:present|current))\s+(?:study|work|project|research|paper|article)\b"
    r"|\b(?:data|datasets?|data\s*sets?)\s+(?:of|from|for|in|underlying|supporting)\s+(?:this|the\s+(?:present|current))\s+"
    r"(?:study|work|paper|article)\b"
    r"|\bour\s+(?:data|datasets?|data\s*sets?|raw\s+data|measurements?|recordings?|code\s+and\s+data)\b"
    r"|\bpresent(?:ed)?\s+(?:here|in\s+this)\b|\bmade\s+available\s+by\s+the\s+authors\b"
    r"|\b(?:submitted|deposited|uploaded)\s+(?:to|in|at)\b", re.I)
# ...and a sentence that names an outside source is about reuse, whatever verb it has
REUSE_CUE = re.compile(
    r"\b(?:obtained|retrieved|downloaded|sourced|acquired|taken|derived|extracted|accessed)\s+from\b"
    r"|\b(?:provided|supplied|made\s+available|collected|produced|published)\s+by\b(?!\s+the\s+authors)"
    r"|\bpublicly\s+available\b|\bthird[-\s]party\b|\bcourtesy\s+of\b", re.I)

def clean_doi(d):
    d = re.sub(r"[.,);:>\]]+$", "", d.strip())
    d = re.sub(r"\.[A-Za-z]{2,}$", "", d)   # strip a trailing glued word, any case (keeps .v3)
    return d.lower()
