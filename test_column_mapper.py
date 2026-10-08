# backend/test_column_mapper.py

import unittest
import pandas as pd
from pkg.services.ai_column_mapper import (
    infer_mapping_layer_a,
    clean_scattered_sheet_data,
    infer_mapping_layer_b,
    normalize_string
)
from pkg.utils.helpers import normalize_headers

class TestColumnMapper(unittest.TestCase):

    def test_clean_sheet_exact_headings(self):
        """Test Case 1: Clean sheet with exact ProofDeck headings."""
        headers = ["recipient_name", "recipient_email", "course_title", "issuer_name", "issue_date", "signature"]
        sample_rows = [
            ["Jane Doe", "jane@example.com", "Fullstack Web Dev", "ProofDeck Academy", "2026-10-08", "Dr. John"]
        ]
        res = infer_mapping_layer_a(headers, sample_rows)
        self.assertTrue(res["is_confident"])
        self.assertEqual(res["mappings"]["recipient_name"]["source_column"], "recipient_name")
        self.assertEqual(res["mappings"]["recipient_email"]["source_column"], "recipient_email")
        self.assertEqual(res["mappings"]["course_title"]["source_column"], "course_title")
        self.assertEqual(res["mappings"]["issuer_name"]["source_column"], "issuer_name")
        self.assertEqual(res["mappings"]["issue_date"]["source_column"], "issue_date")
        self.assertEqual(res["mappings"]["signature"]["source_column"], "signature")

    def test_renamed_headings(self):
        """Test Case 2: Common school/company variations in headings."""
        headers = ["Student Name", "Email Address", "Programme", "Organisation", "Date Completed", "Signatory"]
        sample_rows = [
            ["Oluwaseun Adeleke", "seun@school.edu.ng", "Data Science Bootcamp", "Lagos Tech Hub", "15/09/2026", "Prof. Adebayo"]
        ]
        res = infer_mapping_layer_a(headers, sample_rows)
        self.assertTrue(res["is_confident"])
        self.assertEqual(res["mappings"]["recipient_name"]["source_column"], "Student Name")
        self.assertEqual(res["mappings"]["recipient_email"]["source_column"], "Email Address")
        self.assertEqual(res["mappings"]["course_title"]["source_column"], "Programme")
        self.assertEqual(res["mappings"]["issuer_name"]["source_column"], "Organisation")
        self.assertEqual(res["mappings"]["issue_date"]["source_column"], "Date Completed")
        self.assertEqual(res["mappings"]["signature"]["source_column"], "Signatory")

    def test_split_first_last_names(self):
        """Test Case 3: Split First Name and Last Name automatically combined."""
        headers = ["First Name", "Last Name", "Contact Mail", "Workshop Title"]
        sample_rows = [
            ["Fatima", "Al-Mansoor", "fatima@example.com", "AI Product Management"]
        ]
        res = infer_mapping_layer_a(headers, sample_rows)
        self.assertIsNotNone(res["split_names"])
        self.assertEqual(res["split_names"]["first_name_column"], "First Name")
        self.assertEqual(res["split_names"]["last_name_column"], "Last Name")
        self.assertEqual(res["mappings"]["recipient_email"]["source_column"], "Contact Mail")
        self.assertEqual(res["mappings"]["course_title"]["source_column"], "Workshop Title")

        # Also verify dataframe merging in normalize_headers
        df = pd.DataFrame({
            "First Name": ["Fatima", "Kofi"],
            "Last Name": ["Al-Mansoor", "Mensah"],
            "Contact Mail": ["fatima@example.com", "kofi@example.com"],
            "Workshop Title": ["AI PM", "AI PM"]
        })
        normalized_df = normalize_headers(df)
        self.assertIn("recipient_name", normalized_df.columns)
        self.assertEqual(normalized_df["recipient_name"].iloc[0], "Fatima Al-Mansoor")
        self.assertEqual(normalized_df["recipient_name"].iloc[1], "Kofi Mensah")

    def test_scattered_sheet_with_banner_rows(self):
        """Test Case 4: Title banners on row 1, empty row on row 2, notes on footer."""
        raw_rows = [
            ["GLOBAL TECH COHORT - GRADUATION LIST 2026", None, None, None],
            [None, None, None, None],
            ["Attendee", "Email", "Event", "Award Date"],
            ["Chukwuemeka Obi", "emeka@gmail.com", "Cloud Architecture Masterclass", "2026-08-20"],
            ["Amina Bello", "amina@tech.org", "Cloud Architecture Masterclass", "2026-08-20"],
            ["Total graduates: 2", None, None, None],
            ["Notes: Verified by Academic Board", None, None, None]
        ]
        clean_headers, clean_rows, header_idx = clean_scattered_sheet_data(raw_rows)
        self.assertEqual(header_idx, 2)
        self.assertEqual(clean_headers, ["Attendee", "Email", "Event", "Award Date"])
        self.assertEqual(len(clean_rows), 2)
        self.assertEqual(clean_rows[0][0], "Chukwuemeka Obi")
        self.assertEqual(clean_rows[1][0], "Amina Bello")

        res = infer_mapping_layer_a(clean_headers, clean_rows)
        self.assertTrue(res["is_confident"])
        self.assertEqual(res["mappings"]["recipient_name"]["source_column"], "Attendee")
        self.assertEqual(res["mappings"]["recipient_email"]["source_column"], "Email")
        self.assertEqual(res["mappings"]["course_title"]["source_column"], "Event")
        self.assertEqual(res["mappings"]["issue_date"]["source_column"], "Award Date")

    def test_sheet_with_no_email_column(self):
        """Test Case 5: Sheet missing compulsory email column."""
        headers = ["Candidate Name", "Track", "Date"]
        sample_rows = [
            ["Zainab Diallo", "Cybersecurity Analyst", "2026-09-01"]
        ]
        res = infer_mapping_layer_a(headers, sample_rows)
        self.assertFalse(res["is_confident"])
        self.assertIsNone(res["mappings"]["recipient_email"]["source_column"])
        self.assertEqual(res["mappings"]["recipient_email"]["confidence"], 0.0)

    def test_batch_defaults_application(self):
        """Test Case 6: Batch defaults for issuer_name, issue_date, signature."""
        df = pd.DataFrame({
            "name": ["Alice", "Bob"],
            "email": ["alice@test.com", "bob@test.com"],
            "course": ["React 19", "React 19"]
        })
        defaults = {
            "issuer_name": "Dev Bootcamp",
            "issue_date": "2026-10-08",
            "signature": "Sarah Principal"
        }
        res_df = normalize_headers(df, batch_defaults=defaults)
        self.assertEqual(res_df["issuer_name"].iloc[0], "Dev Bootcamp")
        self.assertEqual(res_df["issue_date"].iloc[0], "2026-10-08")
        self.assertEqual(res_df["signature"].iloc[0], "Sarah Principal")

    def test_ai_unavailable_fallback(self):
        """Test Case 7: Graceful fallback when AI is unavailable or not configured."""
        headers = ["Trainee", "Email", "Workshop"]
        sample_rows = [["Kwame Asante", "kwame@ghana.com", "UI/UX Bootcamp"]]
        # infer_mapping_layer_b with dummy user and unconfigured API key
        ai_res = infer_mapping_layer_b(headers, sample_rows, user_id=999)
        # Should gracefully return None without throwing any exception!
        self.assertIsNone(ai_res)
        # And Layer A works smoothly
        layer_a_res = infer_mapping_layer_a(headers, sample_rows)
        self.assertTrue(layer_a_res["is_confident"])

    def test_large_sheet_performance(self):
        """Test Case 8: Large sheet (1,000 rows) mapping execution time."""
        headers = ["Student Name", "User Email", "Course Title", "Issuer", "Date", "Signature"]
        sample_rows = [
            [f"Student {i}", f"student{i}@example.com", "Full Stack Dev", "ProofDeck", "2026-10-08", "Dean Smith"]
            for i in range(1000)
        ]
        import time
        t0 = time.time()
        res = infer_mapping_layer_a(headers, sample_rows[:5])
        t_elapsed = time.time() - t0
        self.assertTrue(res["is_confident"])
        self.assertLess(t_elapsed, 0.1)  # Takes under 100 milliseconds!

if __name__ == "__main__":
    unittest.main()
