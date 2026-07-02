"""Tests for sheet_pull's CSV-record -> Supabase-row mapping (pure, no network)."""
import unittest

import sheet_pull as sp


VALID = {"eng_1", "eng_2", "nzl_1"}


class MatchLabelTests(unittest.TestCase):
    def test_builds_label(self):
        rec = {"date": "2026-07-04", "home_team": "England", "away_team": "New Zealand"}
        self.assertEqual(sp.match_label_of(rec), "England vs New Zealand (2026-07-04)")

    def test_missing_pieces_returns_none(self):
        self.assertIsNone(sp.match_label_of({"date": "2026-07-04", "home_team": "England"}))

    def test_applies_team_name_fix(self):
        rec = {"date": "2026-07-04", "home_team": "RSA", "away_team": "NZ"}
        self.assertEqual(sp.match_label_of(rec),
                         "South Africa vs New Zealand (2026-07-04)")


class StatsRowTests(unittest.TestCase):
    def base(self, **extra):
        rec = {"date": "2026-07-04", "home_team": "England",
               "away_team": "New Zealand", "team": "England",
               "player_id": "eng_1", "minutes": "0"}
        rec.update(extra)
        return rec

    def test_featured_row_maps_all_stats(self):
        rows, skipped = sp.stats_rows_from_records(
            [self.base(minutes="80", tries="1", tackles="12", metres="42")], VALID)
        self.assertEqual(skipped, [])
        self.assertEqual(len(rows), 1)
        r = rows[0]
        self.assertEqual(r["match_label"], "England vs New Zealand (2026-07-04)")
        self.assertEqual(r["minutes"], 80)
        self.assertEqual(r["tries"], 1)
        self.assertEqual(r["tackles"], 12)
        self.assertEqual(r["metres"], 42)
        # every counting stat is present (defaults to 0)
        for key in sp.COUNTING_STATS:
            self.assertIn(key, r)
        self.assertEqual(r["offloads"], 0)

    def test_non_participant_dropped(self):
        # 0 minutes and no stats -> not a scored row
        rows, _ = sp.stats_rows_from_records([self.base(minutes="0")], VALID)
        self.assertEqual(rows, [])

    def test_stat_without_minutes_still_counts(self):
        rows, _ = sp.stats_rows_from_records([self.base(minutes="", tries="1")], VALID)
        self.assertEqual(len(rows), 1)

    def test_blank_player_id_ignored_silently(self):
        rows, skipped = sp.stats_rows_from_records([self.base(player_id="")], VALID)
        self.assertEqual(rows, [])
        self.assertEqual(skipped, [])

    def test_unknown_player_id_skipped_with_note(self):
        rows, skipped = sp.stats_rows_from_records(
            [self.base(player_id="zzz_9", minutes="80")], VALID)
        self.assertEqual(rows, [])
        self.assertEqual(len(skipped), 1)

    def test_missing_match_columns_skipped(self):
        rows, skipped = sp.stats_rows_from_records(
            [{"player_id": "eng_1", "minutes": "80"}], VALID)
        self.assertEqual(rows, [])
        self.assertEqual(len(skipped), 1)

    def test_whitespace_and_bad_numbers_are_safe(self):
        rows, _ = sp.stats_rows_from_records(
            [self.base(minutes=" 60 ", tries="N/A", passes="10")], VALID)
        self.assertEqual(rows[0]["minutes"], 60)
        self.assertEqual(rows[0]["tries"], 0)   # "N/A" -> 0, no crash
        self.assertEqual(rows[0]["passes"], 10)


class LineupRowTests(unittest.TestCase):
    def rec(self, status, pid="eng_1", **extra):
        r = {"date": "2026-07-04", "home_team": "England",
             "away_team": "New Zealand", "team": "England",
             "player_id": pid, "status": status}
        r.update(extra)
        return r

    def test_status_normalisation(self):
        cases = {"Starting": "start", "start": "start", "XV": "start",
                 "Bench": "bench", "Sub": "bench",
                 "Not in squad": "out", "OUT": "out", "N/A": "out"}
        for raw, expected in cases.items():
            rows, skipped = sp.lineup_rows_from_records([self.rec(raw)], VALID)
            self.assertEqual(len(rows), 1, raw)
            self.assertEqual(rows[0]["status"], expected, raw)

    def test_jersey_and_label(self):
        rows, _ = sp.lineup_rows_from_records([self.rec("Starting", jersey="1")], VALID)
        self.assertEqual(rows[0]["jersey"], 1)
        self.assertEqual(rows[0]["match_label"], "England vs New Zealand (2026-07-04)")
        self.assertEqual(rows[0]["match_date"], "2026-07-04")

    def test_blank_jersey_is_none(self):
        rows, _ = sp.lineup_rows_from_records([self.rec("Bench")], VALID)
        self.assertIsNone(rows[0]["jersey"])

    def test_unknown_status_skipped(self):
        rows, skipped = sp.lineup_rows_from_records([self.rec("maybe")], VALID)
        self.assertEqual(rows, [])
        self.assertEqual(len(skipped), 1)

    def test_unknown_player_skipped(self):
        rows, skipped = sp.lineup_rows_from_records(
            [self.rec("Starting", pid="zzz_9")], VALID)
        self.assertEqual(rows, [])
        self.assertEqual(len(skipped), 1)

    def test_blank_row_ignored(self):
        rows, skipped = sp.lineup_rows_from_records(
            [{"player_id": "", "status": ""}], VALID)
        self.assertEqual(rows, [])
        self.assertEqual(skipped, [])


if __name__ == "__main__":
    unittest.main()
