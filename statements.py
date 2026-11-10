"""
STATEMENTS - what the paper itself SAYS about its data, by pattern search. Paper-level signals, each the
paper's own sentence (summary.csv `*_signal` columns), next to the LLM's view where there is one.

  statement(text)  -- "No new data were generated", "Data sharing is not applicable"  -> no_data_signal
  on_request(text) -- "data are available from the corresponding author on request"   -> on_request_signal
  supplement(text) -- "all data are included in this article and its supplementary information"
                                                                                       -> supplement_signal
  reuse(text)      -- "we use data from two studies", "publicly available dataset"     -> reuse_signal
  das_heading(text)-- the data-availability statement's heading as written            -> das_pattern

Generic phrasings from publisher data-availability templates and ordinary scientific prose, never
per-journal or per-database lists. The patterns live here, next to the code that cuts out the sentence,
because each is used only here (patterns.py holds the identifier patterns shared between steps).

No data: article type is deliberately NOT a signal -- reviews (systematic reviews, meta-analyses) do
produce data, and OpenAlex's `review` type is partly inferred; editorials, errata etc. are a denominator
question. A statement doesn't prove the absence of data, and a paper can say "no new data" and still
reuse data. A paper that says "no data" but cites its own dataset is listed on the dashboard's Tool check.
An LLM judgment of the same question can be added later (summary column `no_data_llm`).
"""
import re

# "no (new|original) data were generated/collected/analysed", "data sharing is not applicable",
# "no datasets were generated or analysed", "this article does not contain/report any (new) data",
# "data availability: not applicable"
_NO = r"(?:new|original|primary|additional|empirical)\s+"
STATEMENT = re.compile(
    r"(?is)("
    rf"\bno\s+(?:{_NO})?(?:data(?:\s*sets?)?|datasets?)\s+(?:were|was|have\s+been|has\s+been)\s+"
    r"(?:generated|created|collected|produced|analy[sz]ed|used)\b"
    r"|\bdata\s+sharing\s+(?:is\s+)?not\s+applicable\b"
    r"|\bnot\s+applicable\s+to\s+this\s+(?:article|paper|study)\b[^.]{0,60}\bno\s+(?:new\s+)?data"
    rf"|\b(?:this|the)\s+(?:article|paper|study|manuscript)\s+(?:does\s+not|did\s+not)\s+"
    rf"(?:contain|include|report|generate|use)\s+(?:any\s+)?(?:{_NO})?data\b"
    r"|\bdata\s+availability(?:\s+statement)?\s*[:.]?\s*not\s+applicable\b"
    r"|\bavailability\s+of\s+data\s+and\s+materials?\s*[:.]?\s*not\s+applicable\b"        # BMC
    r"|\b(?:this|the)\s+(?:article|paper|study)\s+has\s+no\s+(?:additional\s+|supporting\s+)?data\b"  # Royal Society
    r"|\bthere\s+(?:are|is)\s+no\s+(?:data|datasets?)\s+associated\s+with\b"
    r")")

def statement(text):
    """The sentence where the paper says it has no data of its own, or ''. Text is flattened first
    (PDF line breaks, hyphenation) so a sentence split over lines still matches."""
    # rejoin hyphenated words only when the next line goes on in lower case ("restora-\ntion"), so a
    # column-interleaved "restora-   No original data ..." keeps its sentence start
    flat = re.sub(r"(\w)-[ \t]*\n\s*(?=[a-z])", r"\1", text or "")
    flat = re.sub(r"\s+", " ", flat)
    m = STATEMENT.search(flat)
    if not m:
        return ""
    # quote from the match to the end of its sentence (text before the match may be another column)
    e = flat.find(".", m.end())
    return flat[m.start(): e + 1 if 0 <= e < m.end() + 150 else m.end() + 80].strip()

def signal(quote):
    """Summary text for `no_data_signal` / `on_request_signal`: the paper's own words."""
    return f'stated in paper: "{quote}"' if quote else ""


# ---- "available on request": the paper says data exist but are only given out when asked ------------
# The other half of "no data found": data the authors HAVE but did not deposit. Not counted as shared
# (sharing = the paper tells the reader where the data is). Generic template phrasings:
#   "available from the corresponding author (up)on (reasonable) request"
#   "(up)on reasonable request to/from the authors", "can be obtained/provided by the authors on request"
#   "available (up)on (reasonable) request" when the sentence is about data
REQUEST = re.compile(
    r"(?is)\b(?:up)?on\s+(?:a\s+)?(?:reasonable|justified|written|formal)?\s*request\b"
    r"|\brequests?\s+(?:for|to\s+access)\s+(?:the\s+)?data(?:sets?)?\s+should\s+be\s+(?:directed|addressed|sent)\b"
    r"|\bcontact(?:ing)?\s+the\s+(?:corresponding\s+)?authors?\b")
ABOUT_DATA = re.compile(r"(?i)\b(?:data(?:\s*sets?)?|datasets?|raw\s+data|data\s+files?)\b")
# ...and about making them available (not "upon request, participants could withdraw their data")
GIVEN = re.compile(r"(?i)\b(?:available|provided|obtain(?:ed|able)?|shared|accessible|requests?\s+for)\b")
# a deposit with access on request (restricted access, e.g. "access upon request through SND") is
# shared, not "on request only": skip sentences that name a repository, an archive or an identifier
DEPOSIT = re.compile(r"(?i)\b(?:repositor(?:y|ies)|archive|data\s*service|deposited|doi\b|10\.\d{4,9}/|https?://)")

def on_request(text):
    """The sentence where the paper says its data are available on request, or ''. The sentence must be
    about giving out data (so "models are available from the authors on request" doesn't count) and
    not about a deposit with access on request."""
    flat = re.sub(r"(\w)-[ \t]*\n\s*(?=[a-z])", r"\1", text or "")
    flat = re.sub(r"\s+", " ", flat)
    for m in REQUEST.finditer(flat):
        dot = flat.rfind(". ", max(0, m.start() - 300), m.start())
        s = dot + 2 if dot >= 0 else max(0, m.start() - 300)
        e = flat.find(".", m.end())
        e = e + 1 if 0 <= e < m.end() + 200 else m.end() + 80
        # start after a column break ("perfor- Data will ...") or a "Data availability" heading, if any:
        # text before them is usually another column of the PDF
        cut = [x.end() for x in re.finditer(r"[a-z]- (?=[A-Z])|(?i:\bdata\s+availability(?:\s+statement)?\s*:?\s*)",
                                            flat[s:m.start()])]
        if cut: s += cut[-1]
        sent = flat[s:e].strip()
        if ABOUT_DATA.search(sent) and GIVEN.search(sent) and not DEPOSIT.search(sent):
            return sent
    return ""


# ---- "data are in the article / its supplement": shared with the paper, not deposited -------------------
# Monitored as a signal, not counted as shared (sharing = deposited somewhere, open or restricted). Journals
# and FAIR guidance discourage supplements for data (no own DOI, often PDF, often derived values only);
# PLOS Open Science Indicators report "data in Supporting Information" separately from repositories.
# Generic template phrasings:
#   "All data generated or analysed during this study are included in this published article (and its
#    supplementary information files)"                                           (Springer Nature / BMC)
#   "The data supporting this article have been included as part of the Supplementary Information"  (RSC)
#   "The data are provided in the supplementary material / Supporting Information"
# A bare mention of a supplement is NOT enough: Elsevier's "Supplementary data to this article can be found
# online" and SAGE's "Supplemental material for this article is available online" are attached to every
# supplement, figures included. So the pattern needs the order "data ... are included/provided ... in
# ... the article / supplement", within one sentence and close together (a long sentence that mentions a
# supplement and, elsewhere, a dataset is not enough).
_SUPP = (r"(?:supplementary|supplemental|supporting|additional|electronic\s+supplementary)\s+"
         r"(?:information|materials?|data|files?|tables?|datasets?)"
         r"|(?:this|the)\s+(?:published\s+)?(?:article|paper|manuscript)")
SUPPLEMENT = re.compile(
    r"(?i)\bdata(?:\s*sets?)?\b[^.]{0,120}?"
    # not "presented"/"reported": "the data presented in this article are available on request" (MDPI) and
    # "the work reported in this paper" are not about where the data are
    r"\b(?:included|provided|available|found|contained|given|listed)\b[^.]{0,40}?"
    rf"\b(?:in|within|with|as\s+part\s+of)\b[^.]{{0,30}}?\b(?:{_SUPP})\b")

# ---- "we used other people's data": a reuse statement ----------------------------------------------------
# Reuse is only counted in the verdict when a cited dataset is verified and not the authors' own. Most
# reuse is cited without an id (a database, a benchmark, a public data file), so this is a separate
# signal next to the LLM's own judgement (fuse: reuse_llm). Generic phrasings, no list of databases:
#   "publicly available data(set)", "data were obtained / retrieved / downloaded from ...",
#   "we used data from ...", "secondary data".
# "Data were obtained from the participants / measurements" is the authors' own collection: skipped.
_OWN_SOURCE = (r"(?:the\s+)?(?:participants?|patients?|subjects?|respondents?|interviews?|informants?|"
               r"experiments?|measurements?|simulations?|questionnaires?|surveys?\s+we|our\b|this\s+study|"
               r"field\s+(?:work|sites?)|samples?|animals?|pigs?|mice|rats?)")
REUSE = re.compile(
    r"(?i)(?<!\bour\s)(?<!\bthis\s)\b(?:publicly|openly|freely)\s+available\s+(?:data(?:\s*sets?)?|datasets?|"
    r"databases?|benchmarks?)\b"
    r"|\bdata(?:\s*sets?)?\s+(?:were|was|are|is|have\s+been)\s+(?:obtained|retrieved|downloaded|sourced|"
    rf"extracted|acquired|taken)\s+from\s+(?!{_OWN_SOURCE})"
    # "we use data from two studies", "using data originally reported in a study by ...", "re-analysed the
    # dataset of ..."
    r"|\b(?:use[sd]?|using|analy[sz](?:ed|ing)|re-?analy[sz](?:ed|ing)|re-?us(?:e[sd]?|ing))\s+(?:the\s+)?"
    r"(?:data(?:\s*sets?)?|datasets?)\s+(?:originally\s+)?"
    rf"(?:(?:from|of)\s+(?!{_OWN_SOURCE})|reported|published|provided\s+by|made\s+available\s+by|collected\s+by)"
    r"|\bsecondary\s+(?:data|analys[ie]s)\b")

def reuse(text):
    """The sentence where the paper says it uses data from elsewhere, or ''."""
    flat = re.sub(r"(\w)-[ \t]*\n\s*(?=[a-z])", r"\1", text or "")
    flat = re.sub(r"\s+", " ", flat)
    for m in REUSE.finditer(flat):
        dot = flat.rfind(". ", max(0, m.start() - 200), m.start())
        s = dot + 2 if dot >= 0 else m.start()
        cut = [x.end() for x in re.finditer(r"[a-z]- (?=[A-Z])", flat[s:m.start()])]
        if cut: s += cut[-1]
        e = flat.find(".", m.end())
        e = e + 1 if 0 <= e < m.end() + 200 else m.end() + 80
        return flat[s:e].strip()
    return ""


def supplement(text):
    """The sentence where the paper says its data are in the article or its supplement, or ''."""
    flat = re.sub(r"(\w)-[ \t]*\n\s*(?=[a-z])", r"\1", text or "")
    flat = re.sub(r"\s+", " ", flat)
    for m in SUPPLEMENT.finditer(flat):
        if DEPOSIT.search(m.group(0)):        # "deposited in Zenodo and included in the SI": shared anyway
            continue
        dot = flat.rfind(". ", max(0, m.start() - 200), m.start())
        s = dot + 2 if dot >= 0 else m.start()
        # the match itself may start at a "Data availability" heading: cut up to and including it
        cut = [x.end() for x in re.finditer(r"[a-z]- (?=[A-Z])|(?i:\bdata\s+availability(?:\s+statement)?\s*:?\s*)",
                                            flat[s:m.end()]) if x.start() <= m.start() - s]
        if cut: s += cut[-1]
        e = flat.find(".", m.end())
        e = e + 1 if 0 <= e < m.end() + 200 else m.end() + 80
        return flat[s:e].strip()
    return ""


# ---- the data-availability statement's heading -------------------------------------------------
# Paper-level: does the paper have a data-availability statement at all? The line-anchored DAS_HEAD
# rarely fires on PDF text (columns run together: "Data availabilityDownloaded ..."), so this looks for
# the heading words written as a heading -- capitalised, followed by a colon/full stop or a new sentence
# -- anywhere in the flattened text. Prose ("... improves data availability for ...") is lower case
# and does not match. Generic publisher wordings, not per-journal lists.
DAS_ANYWHERE = re.compile(
    r"(?:\b|(?<=[a-z]))(?:"
    # "Data availability", "Data and model availability statement" (Elsevier Animal), "Data, code and
    # materials availability"
    r"Data(?:,?\s+(?:and\s+)?(?:[Cc]ode|[Mm]odels?|[Ss]oftware|[Mm]aterials?))*\s+"
    r"(?:[Aa]vailability|[Aa]ccessibility|[Aa]ccess)(?:\s+[Ss]tatements?)?"
    r"|DATA\s+(?:AVAILABILITY|ACCESSIBILITY)(?:\s+STATEMENTS?)?"
    r"|Availability\s+of\s+(?:[Dd]ata|[Dd]ata\s+and\s+[Mm]aterials?|[Ss]upporting\s+[Dd]ata)"
    r"|(?:Data|Code)\s+and\s+(?:[Cc]ode|[Dd]ata)\s+[Aa]vailability(?:\s+[Ss]tatements?)?"
    r"|Open\s+[Rr]esearch(?:\s+[Ss]ection)?"                 # AGU: "Open Research" section
    # ...then a colon / full stop, a new sentence (also glued on by PDF columns: "availabilityDownloaded"),
    # or the end of the line (a heading in one column, the other column's text after it)
    r")(?=\s*[:.]|\s*[A-Z\d]|[ \t]*\r?\n)")

def das_heading(text):
    """The heading of the paper's data-availability statement as written, or ''."""
    m = DAS_ANYWHERE.search(text or "")
    return re.sub(r"\s+", " ", m.group(0)) if m else ""
