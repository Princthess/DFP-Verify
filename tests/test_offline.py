"""
Offline tests: the parts of the tool that read text and apply rules, checked on small made-up snippets.
No internet, no corpus, no LLM. Takes about a second.

    python -m unittest discover tests

A failure means a change altered how the tool reads papers or decides a verdict. That can be intended
(then update the test and say why in the commit) or a bug. For whether the live registries still answer
as expected, run `python check_apis.py` instead.
"""
import os, sys, unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import detect_union, statements, classify, registry_lookup, fuse, sections
from run_pipeline import _homepage


def ids(text):
    """Identifiers found by pattern search in a text, as {identifier: kind}."""
    return {c["identifier"]: c["kind"] for c in detect_union.detect_regex(text)}


class FindingIdentifiers(unittest.TestCase):
    def test_plain_dataset_doi(self):
        self.assertEqual(ids("Data are available at https://doi.org/10.5878/z57e-3j96.").get("10.5878/z57e-3j96"), "doi")

    def test_doi_split_over_two_lines_is_rejoined(self):
        # PDF text extraction often breaks a DOI after a dot or slash
        self.assertIn("10.5281/zenodo.5034182", ids("deposited at 10.5281/zenodo.\n5034182 under CC-BY"))

    def test_complete_doi_does_not_swallow_next_number(self):
        # a full DOI followed by a reference number on the next line must stay as it is
        found = ids("see 10.5281/zenodo.13683462\n 53. Smith et al.")
        self.assertIn("10.5281/zenodo.13683462", found)
        self.assertNotIn("10.5281/zenodo.1368346253", found)

    def test_zenodo_record_link_becomes_its_doi(self):
        self.assertIn("10.5281/zenodo.8368205", ids("Code and data: https://zenodo.org/records/8368205"))

    def test_accessions(self):
        found = ids("Reads were deposited in ENA under PRJEB84056; proteomics data in PRIDE as PXD061695.")
        self.assertEqual(found.get("PRJEB84056"), "accession")
        self.assertEqual(found.get("PXD061695"), "accession")

    def test_short_number_in_prose_is_not_an_accession(self):
        self.assertNotIn("SRA3", ids("We used the SRA3 protocol described earlier."))

    def test_code_link(self):
        self.assertEqual(ids("Scripts: https://github.com/example/analysis").get("https://github.com/example/analysis"), "code")


class ReadingStatements(unittest.TestCase):
    def test_no_data_generated(self):
        self.assertTrue(statements.statement("Data sharing is not applicable to this article as no new data were created or analyzed in this study."))

    def test_no_data_sentence_split_over_lines(self):
        self.assertTrue(statements.statement("No new data were\ngenerated in this\nstudy."))

    def test_ordinary_text_is_not_a_no_data_statement(self):
        self.assertFalse(statements.statement("We collected new data from 40 participants in 2023."))

    def test_on_request(self):
        self.assertTrue(statements.on_request("The data that support the findings of this study are available from the corresponding author upon reasonable request."))

    def test_deposit_with_access_on_request_is_not_on_request_only(self):
        # restricted access through a repository counts as shared, so it must not land in "on request"
        self.assertFalse(statements.on_request("The data are deposited at the Swedish National Data Service (https://doi.org/10.5878/cnaf-v548) and available upon request."))

    def test_supplement(self):
        self.assertTrue(statements.supplement("All data is provided within the article and supplementary material."))

    def test_generic_supplement_note_does_not_count(self):
        self.assertFalse(statements.supplement("Supplementary material is available online."))

    def test_data_availability_heading(self):
        self.assertTrue(statements.das_heading("Results were robust.\n\nData Availability Statement\nThe data are openly available."))

    def test_data_availability_in_prose_is_not_a_heading(self):
        self.assertFalse(statements.das_heading("Open science improves data availability for everyone."))

    def test_statement_of_data_heading(self):
        self.assertTrue(statements.das_heading("Online content\nStatements of data and code availability\nData are at Zenodo."))
        self.assertTrue(statements.das_heading("Results were robust.\n\nData statement: the data are at SND."))
        self.assertTrue(statements.das_heading("Results were robust. ■DATA AND SOFTWARE AVAILABILITY The data are in Zenodo."))

    def test_on_request_in_prose_is_not_a_statement(self):
        self.assertFalse(statements.das_statement("Before, sharing data was generally limited to sending it on request, but now data can be shared instantly."))

    def test_template_sentence_without_heading(self):
        self.assertTrue(statements.das_statement("We thank the farmers. The data that support the findings of this study are openly available in Zenodo at https://doi.org/10.5281/zenodo.1."))
        self.assertTrue(statements.das_statement("Online content Any methods and statements of data and code availability are available at https://doi.org/10.1038/x."))

    def test_ordinary_text_is_not_a_statement(self):
        self.assertFalse(statements.das_statement("Data are available for 40 countries. The data support our hypothesis."))


class DecidingOpenness(unittest.TestCase):
    def test_open_access_right(self):
        lic, access = classify._rights([{"rightsUri": "info:eu-repo/semantics/openAccess"},
                                        {"rightsIdentifier": "cc-by-4.0"}])
        self.assertEqual((lic, access), ("cc-by-4.0", "open"))

    def test_restricted_and_embargoed_count_as_restricted(self):
        for word in ("restricted", "closed", "embargoed"):
            self.assertEqual(classify._rights([{"rightsUri": f"info:eu-repo/semantics/{word}Access"}])[1], "restricted")

    def test_no_access_right_stated(self):
        self.assertEqual(classify._rights([])[1], "")


class CheckingPaperDoi(unittest.TestCase):
    def test_title_must_match_first_page(self):
        title = "Machine learning of dairy cow behaviour from accelerometer data"
        page = "Animal 2026. Machine learning of dairy cow behaviour from accelerometer data. A. Author, B. Author"
        self.assertTrue(registry_lookup._title_matches(title, page))
        self.assertFalse(registry_lookup._title_matches(title, "An entirely different paper about bridges and concrete"))


class LinksAndDuplicates(unittest.TestCase):
    def test_repository_front_page(self):
        self.assertTrue(_homepage("https://snd.gu.se/en"))
        self.assertFalse(_homepage("https://snd.gu.se/en/catalogue/dataset/2023-205"))

    def test_record_link_matches_its_doi(self):
        self.assertTrue(registry_lookup.same_record("https://zenodo.org/records/8368205", "10.5281/zenodo.8368205"))


class FindingSections(unittest.TestCase):
    def test_id_in_data_availability_section(self):
        text = ("Introduction\nWe studied cows on three farms over two summers.\n\n"
                "Data availability\nData are at 10.5878/z57e-3j96 (Swedish National Data Service)\n\n"
                "Acknowledgements\nWe thank the farmers.\n\n"
                "References\n1. Smith J. 2020. 10.1000/xyz123")
        ntext = detect_union.normalize_text(text)
        bounds = sections.segment(ntext, with_das=True)
        primary, _ = sections.locate(sections.find_positions(ntext.lower(), "10.5878/z57e-3j96", "doi"), bounds)
        self.assertEqual(primary, "das")
        primary, _ = sections.locate(sections.find_positions(ntext.lower(), "10.1000/xyz123", "doi"), bounds)
        self.assertEqual(primary, "references")

    def test_id_in_template_sentence_without_heading(self):
        text = ("Introduction\nWe studied cows on three farms.\n\nWe thank the farmers. The data that support the "
                "findings of this study are openly available at https://doi.org/10.5878/z57e-3j96. Funding was from X.\n\n"
                "Results\nSee 10.5281/zenodo.42 for the code.")
        ntext = detect_union.normalize_text(text)
        bounds = sections.segment(ntext, with_das=True)
        primary, _ = sections.locate(sections.find_positions(ntext.lower(), "10.5878/z57e-3j96", "doi"), bounds)
        self.assertEqual(primary, "das")
        primary, _ = sections.locate(sections.find_positions(ntext.lower(), "10.5281/zenodo.42", "doi"), bounds)
        self.assertEqual(primary, "body")


class VerdictRules(unittest.TestCase):
    """The order of the verdicts: own shared data wins, then a declared but dead id, and so on."""
    def label(self, **kw):
        base = dict(own=[], likely=[], reused=[])
        base.update(kw)
        return fuse._summary_label(**base)

    def test_own_open(self):
        self.assertEqual(self.label(own=["x"], openness="open"), "shared own data (open)")

    def test_own_restricted_counts_as_shared(self):
        self.assertEqual(self.label(own=["x"], openness="restricted"), "shared own data (restricted access)")

    def test_own_data_beats_everything_else(self):
        self.assertTrue(self.label(own=["x"], openness="open", likely=["y"], reused=["z"],
                                   on_request="q", no_data="q").startswith("shared own data"))

    def test_declared_dead_id_beats_reuse(self):
        self.assertEqual(self.label(likely=["y"], reused=["z"]), "declared, unverifiable")

    def test_supplement_beats_on_request(self):
        self.assertEqual(self.label(supplement="q", on_request="q"), fuse.IN_SUPPLEMENT)

    def test_on_request_is_not_shared(self):
        self.assertEqual(self.label(on_request="q"), fuse.ON_REQUEST)

    def test_datacite_only_link_does_not_change_verdict(self):
        self.assertEqual(self.label(reg_only=["d"]), "no data found")

    def test_no_data_stated(self):
        self.assertEqual(self.label(no_data="q"), fuse.NO_DATA_STATED)

    def test_nothing_found(self):
        self.assertEqual(self.label(), "no data found")


if __name__ == "__main__":
    unittest.main()
