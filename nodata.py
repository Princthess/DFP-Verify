"""
NO DATA - does the paper say it has no data of its own? Splits "no data found" (not shared, OR no data)
into a part the paper itself explains.

Two deterministic signals (pattern search + metadata). An LLM judgment can be added next to them later
(summary column `no_data_llm`) and compared, as DFP and the pattern search are compared for datasets.
  1. statement(text) -- an explicit sentence such as "No new data were generated", "Data sharing is not
     applicable to this article". Generic phrasings from data-availability policies (Springer Nature,
     Wiley, PLOS, Taylor & Francis templates), not per-journal lists.
  2. NO_DATA_TYPES -- OpenAlex work types that carry no data of their own (review, editorial, erratum ...).
     The type comes from the checked paper DOI (fields.FieldCache.work_type).
Neither proves the absence of data, and a paper can say "no new data" and still reuse data -- reuse
wins in the verdict (fuse._summary_label). A paper that says "no data" but cites its own dataset is
listed on the dashboard's Tool check page.
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
    r")")

NO_DATA_TYPES = {"review", "editorial", "erratum", "paratext", "retraction", "peer-review"}

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

def signal(quote, work_type):
    """Summary text for `no_data_signal`: the paper's own words first, else the article type."""
    if quote:
        return f'stated in paper: "{quote}"'
    if (work_type or "").lower() in NO_DATA_TYPES:
        return f"article type: {work_type.lower()} (OpenAlex)"
    return ""
