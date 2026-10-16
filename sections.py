"""
SECTION LOCATION - where in the paper each identifier sits ("in-text provenance").

A deliberately COARSE, robust 4-way split -- das / supplement / references / body --
which is all the provenance question needs. We do NOT attempt fine sectioning
(intro vs methods vs results): that is unreliable from flat extracted text and needs a
PDF-structure parser (GROBID), which is too heavy for a laptop tool.

Each boundary is one landmark, not a classifier:
  das         -> ODDPub's extracted DAS text (the validated DAS detector) -- authoritative.
  references  -> the 'References'/'Bibliography' heading in the latter part of the doc.
  supplement  -> a 'Supplementary'/'Supporting information' heading.
  body        -> everything else (where implicit, no-id mentions live).

Why location matters: it is the single best *cheap* provenance signal --
  references-only -> leans reused (cited);  das/body/supplement -> leans declared/own --
so it reduces how often the LLM referee has to fire.
"""
import re
from detect_union import normalize_text  # noqa: F401  (re-exported for callers)

# references section heading, on its own line (optionally numbered: "6. References")
REF_HEAD = re.compile(
    r"(?im)^[\s\d.]*(references|bibliography|literature cited|references and notes|works cited)\s*:?\s*$")
# supplement section heading, on its own line -- NOT inline cross-refs ("see Suppl. Fig. 1"),
# which appear throughout the body and would drag the boundary far too early.
SUPP_HEAD = re.compile(
    r"(?im)^[\s\d.]*(supplementary\s+(information|materials?(\s+and\s+methods)?|data|appendix)|"
    r"supporting\s+information|appendix|appendices)\s*:?\s*$")
# data-availability heading -- locates the DAS region (where declared ids live).
# A structural heading locator, same family as find_references (matches headings, not keyword lists).
DAS_HEAD = re.compile(
    r"(?im)^[\s\d.]*(data\s+availability(\s+statement)?|availability\s+of\s+data(\s+and\s+materials?)?|"
    r"data\s+and\s+code\s+availability|code\s+and\s+data\s+availability|"
    r"data\s+access(ibility)?(\s+statement)?)\b[:.\s]*$")
# headings that end the DAS region
DAS_END = re.compile(
    r"(?im)^[\s\d.]*(acknowledg(e)?ments?|author\s+contributions?|funding|"
    r"competing\s+interests?|conflict\s+of\s+interest|references?|bibliography|"
    r"supplementary|appendix|ethics)\b[:.\s]*$")

# when an id appears in several places, the primary is the most informative one
PRIORITY = {"das": 0, "supplement": 1, "body": 2, "references": 3}


def _refs_start(text):
    """Char offset where the reference list begins, or None. Heuristic, biased to the tail."""
    n = len(text)
    anchored = [m.start() for m in REF_HEAD.finditer(text) if m.start() > n * 0.40]
    if anchored:
        return min(anchored)                       # first heading-like 'References' in the tail
    loose = [m.start() for m in re.finditer(r"(?i)\breferences\b", text) if m.start() > n * 0.55]
    return min(loose) if loose else None


def _supp_start(text):
    # a genuine supplement section sits in the tail (appended, or just before/after references)
    n = len(text)
    hits = [m.start() for m in SUPP_HEAD.finditer(text) if m.start() > n * 0.40]
    return min(hits) if hits else None


def _das_region(text):
    """(start, end) of the Data Availability section via its heading, or None.
    Only used as the DAS signal when ODDPub is OFF."""
    m = DAS_HEAD.search(text)
    if not m:
        return None
    start = m.end()
    e = DAS_END.search(text, pos=start)
    end = e.start() if e else min(start + 1500, len(text))
    return (m.start(), end)


def segment(text, with_das=False):
    """Section landmarks (char offsets into `text`). `text` must be normalize_text()'d.
    with_das=True also locates the DAS region by heading (for the no-ODDPub fallback)."""
    b = {"refs": _refs_start(text), "supp": _supp_start(text)}
    if with_das:
        b["das"] = _das_region(text)
    return b


def find_positions(text_lc, ident, kind="", limit=20):
    """All offsets where `ident` occurs in the (already lowercased) text."""
    probes = []
    il = (ident or "").lower()
    if il:
        probes.append(il)
    if kind == "doi" and il.startswith("10.") and "/" in il:
        probes.append(il[3:])                       # orphan form, e.g. '71870/xyz' without the '10.'
    out = []
    for pr in probes:
        i = text_lc.find(pr)
        while i >= 0 and len(out) < limit:
            out.append(i)
            i = text_lc.find(pr, i + 1)
        if out:
            break
    return out


def _from_dfp_section(sec):
    """Map DFP's source_section string to our coarse label (fallback when the id isn't in the .txt)."""
    s = (sec or "").lower()
    if not s:
        return ""
    if "availab" in s:                              return "das"
    if "referen" in s or "biblio" in s:            return "references"
    if "supplement" in s or "supporting" in s:     return "supplement"
    return "body"


def locate(positions, bounds, in_das=False, dfp_section=""):
    """Return (primary_label, all_labels_set) for one identifier.

    DAS membership comes from ODDPub (`in_das`) when it's on; otherwise from the DAS heading
    region in `bounds["das"]` and/or DFP's own `source_section`. refs/supplement/body from position.
    """
    labels = set()
    if in_das:
        labels.add("das")
    refs, supp, das = bounds.get("refs"), bounds.get("supp"), bounds.get("das")
    for pos in positions:
        if das is not None and das[0] <= pos < das[1]: labels.add("das")
        elif supp is not None and pos >= supp:      labels.add("supplement")
        elif refs is not None and pos >= refs:      labels.add("references")
        else:                                       labels.add("body")
    if not labels:                                  # id not found literally -> trust DFP's own tag
        lab = _from_dfp_section(dfp_section)
        if lab:
            labels.add(lab)
    if not labels:
        labels.add("body")
    primary = min(labels, key=lambda x: PRIORITY.get(x, 9))
    return primary, labels
