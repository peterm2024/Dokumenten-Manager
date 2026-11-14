import os
import datetime
import tempfile
import unittest

import scan_date


class TestParsePdfDate(unittest.TestCase):
    def test_full_precision_with_timezone(self):
        # Echtes Beispiel aus der Sammlung: "D:20220505185907+01'00'"
        self.assertEqual(scan_date.parse_pdf_date("D:20220505185907+01'00'"),
                          datetime.datetime(2022, 5, 5, 18, 59, 7))

    def test_date_only(self):
        self.assertEqual(scan_date.parse_pdf_date("D:20260413"), datetime.datetime(2026, 4, 13, 0, 0, 0))

    def test_missing_d_prefix_returns_none(self):
        self.assertIsNone(scan_date.parse_pdf_date("20260413185907"))

    def test_empty_returns_none(self):
        self.assertIsNone(scan_date.parse_pdf_date(""))

    def test_invalid_calendar_date_returns_none(self):
        self.assertIsNone(scan_date.parse_pdf_date("D:20261301000000"))


class TestResolveScanTimestamp(unittest.TestCase):
    def test_prefers_pdf_creation_date_over_ctime(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "test.pdf")
            with open(path, "w") as f:
                f.write("x")
            dt = scan_date.resolve_scan_timestamp("D:20220505185907+01'00'", path)
            self.assertEqual(dt, datetime.datetime(2022, 5, 5, 18, 59, 7))

    def test_falls_back_to_ctime_without_creation_date(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "test.pdf")
            with open(path, "w") as f:
                f.write("x")
            dt = scan_date.resolve_scan_timestamp("", path)
            self.assertEqual(dt, datetime.datetime.fromtimestamp(os.path.getctime(path)))

    def test_missing_file_and_no_creation_date_returns_none(self):
        self.assertIsNone(scan_date.resolve_scan_timestamp("", r"C:\does\not\exist.pdf"))


class TestStorageRoundtrip(unittest.TestCase):
    def test_to_storage(self):
        dt = datetime.datetime(2026, 4, 13, 14, 32)
        self.assertEqual(scan_date.to_storage(dt), "2026-04-13 14:32")

    def test_format_storage_value(self):
        self.assertEqual(scan_date.format_storage_value("2026-04-13 14:32"), "13.04.2026 14:32")

    def test_format_storage_value_reads_legacy_date_only_format(self):
        # Werte, die vor der Vereinfachung ohne Uhrzeit gespeichert wurden, bleiben lesbar
        self.assertEqual(scan_date.format_storage_value("2026-04-13"), "13.04.2026")

    def test_format_storage_value_unparseable_shown_raw(self):
        self.assertEqual(scan_date.format_storage_value("kaputt"), "kaputt")

    def test_format_storage_value_empty(self):
        self.assertEqual(scan_date.format_storage_value(""), "")


class TestFormatScanTimestamp(unittest.TestCase):
    def test_embedded_value_takes_precedence(self):
        result = scan_date.format_scan_timestamp(r"C:\does\not\exist.pdf",
                                                  creation_date_raw="D:20220505185907+01'00'",
                                                  embedded="2019-12-31 08:15")
        self.assertEqual(result, "31.12.2019 08:15")

    def test_falls_back_to_pdf_creation_date_without_embedded(self):
        result = scan_date.format_scan_timestamp(r"C:\does\not\exist.pdf",
                                                  creation_date_raw="D:20220505185907+01'00'")
        self.assertEqual(result, "05.05.2022 18:59")

    def test_falls_back_to_creation_time_without_anything_else(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "test.pdf")
            with open(path, "w") as f:
                f.write("x")
            expected = datetime.datetime.fromtimestamp(os.path.getctime(path)).strftime("%d.%m.%Y %H:%M")
            self.assertEqual(scan_date.format_scan_timestamp(path), expected)

    def test_empty_string_when_unresolvable(self):
        self.assertEqual(scan_date.format_scan_timestamp(r"C:\does\not\exist.pdf"), "")


if __name__ == "__main__":
    unittest.main()
