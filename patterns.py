"""
patterns.py -- SINGLE SOURCE OF TRUTH for every shared regex and id-registry.

Nothing that matches identifiers, data-sharing verbs, or data-cue words should be defined anywhere
else: detect_union (detection), verify (verification) and classify (provenance) all import from
here, so a format or word is edited in ONE place and the modules stay in sync. In particular the
ACCESSIONS registry drives BOTH detection (the union regex) AND verification (archive routing),
so they can never drift apart.

Pattern sources:
  - DOIs / Swedish-Nordic DataCite prefixes / repo URLs -> our own (public DOI spec + facts).
  - Accession formats -> Bioregistry (bioregistry.io), pattern data CC0 1.0.
  - OWN_VERBS / DATA_CUE -> our own short, generic word lists.
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
    ("GEO",          r"G(?:PL|SM|SE|DS)\d+",     "geo"),         # bioregistry: geo
    ("SRA",          r"[SED]R[APRSXZ]\d+",       "sra"),         # bioregistry: insdc.sra
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
OWN_VERBS = re.compile(r"\b(we\s|our\s|this study|present(ed)? (here|in this)|"
                       r"submitted|deposited|generated|produced|collected|created|"
                       r"made available by the authors|data are provided)\b", re.I)

# --- LLM body-scan: broad data-cue net (URLs/DOIs/accessions + a short, generic data vocabulary) -
DATA_CUE = re.compile(
    r"https?://\S+"
    r"|10\.\d{4,}/\S+"
    r"|\b(?:data|dataset|datasets|code|software|repositor(?:y|ies)|deposit(?:ed|s)?|archiv(?:e|ed)|"
    r"available|availability|accession|underlying|supplementary|supporting\s+information|"
    r"made\s+available|openly\s+available|figshare|zenodo|dryad|osf|github|gitlab|genbank|"
    r"proteomexchange|pride|metabolights|biostudies|arrayexpress)\b", re.I)

def clean_doi(d):
    d = re.sub(r"[.,);:>\]]+$", "", d.strip())
    d = re.sub(r"\.[A-Za-z]{2,}$", "", d)   # strip a trailing glued word, any case (keeps .v3)
    return d.lower()
