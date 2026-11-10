"""
NO DATA - does the paper say it has no data of its own? Splits "no data found" (not shared, OR no data)
into a part the paper itself explains.

The deterministic half (pattern search). An LLM judgment can be added next to it later (summary column
`no_data_llm`) and compared, as DFP and the pattern search are compared for datasets.
  statement(text) -- an explicit sentence such as "No new data were generated", "Data sharing is not
  applicable to this article". Generic phrasings from data-availability policy templates (Springer
  Nature, BMC, Wiley, Taylor & Francis, MDPI, Royal Society, Elsevier), not per-journal lists.
Article type is deliberately NOT a signal: reviews (systematic reviews, meta-analyses) do produce data,
and OpenAlex's `review` type is partly inferred; editorials, errata etc. are not research articles at
all, which is a denominator question, not "the paper says it has no data". The type is reported
separately (summary `work_type`).
A statement doesn't prove the absence of data, and a paper can say "no new data" and still reuse data --
reuse wins in the verdict (fuse._summary_label). A paper that says "no data" but cites its own dataset
is listed on the dashboard's Tool check page.
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
