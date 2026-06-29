#!/usr/bin/env python3
"""Tests for daily_pull: the provider -> squad-list id mapping, rugby
scoring, and the multi-league upsert fan-out.

Run:
    python -m unittest test_daily_pull -v
"""

import json
import os
import unittest

import daily_pull
from daily_pull import (
    PLAYERS_JSON,
    PlayerMatcher,
    build_stats_payload,
    calculate_points,
    extract_player_rows,
    featured,
    normalize_name,
    parse_league_ids,
    surname_key,
)

# A fully-populated match_stats source row for upsert tests.
daily_pull_ROW = {
    "player_id": "fra_9", "match_label": "France vs South Africa (2026-07-04)",
    "role": "SH", "minutes": 80, "tries": 1, "metres": 40, "runs": 5,
    "defenders_beaten": 2, "clean_breaks": 1, "passes": 60, "offloads": 1,
    "turnovers_conceded": 0, "try_assists": 1, "tackles": 6, "missed_tackles": 0,
    "turnovers_won": 1, "conversions": 0, "conversions_missed": 0, "penalties": 0,
    "penalties_missed": 0, "drop_goals": 0, "drop_goals_missed": 0,
    "lineout_throws_won": 0, "lineouts_taken": 0, "lineout_steals": 0,
    "penalties_conceded": 0, "red_cards": 0, "yellow_cards": 0, "scrums_won": 0,
    "scrums_lost": 0, "lineouts_lost": 0, "home_score": 27, "away_score": 24,
}

ROSTER = [
    {"player_id": "eng_1", "name": "Ellis Genge", "position": "FR", "role": "PR", "team": "England", "team_code": "ENG"},
    {"player_id": "eng_8", "name": "Ben Earl", "position": "BR", "role": "LF", "team": "England", "team_code": "ENG"},
    {"player_id": "eng_10", "name": "Marcus Smith", "position": "HB", "role": "FH", "team": "England", "team_code": "ENG"},
    {"player_id": "eng_22", "name": "Fin Smith", "position": "HB", "role": "FH", "team": "England", "team_code": "ENG"},
    {"player_id": "fra_9", "name": "Antoine Dupont", "position": "HB", "role": "SH", "team": "France", "team_code": "FRA"},
    {"player_id": "rsa_10", "name": "Handré Pollard", "position": "HB", "role": "FH", "team": "South Africa", "team_code": "RSA"},
]


class TestNormalize(unittest.TestCase):
    def test_accents_and_punctuation(self):
        self.assertEqual(normalize_name("Handré Pollard"), "handre pollard")

    def test_initials_and_case(self):
        self.assertEqual(normalize_name("M. Smith"), "m smith")

    def test_surname_key_is_last_token(self):
        self.assertEqual(surname_key("Antoine Dupont"), "dupont")
        self.assertEqual(surname_key("Marcus Smith"), "smith")


class TestFeatured(unittest.TestCase):
    """Kept if minutes OR any counting stat, so a scorer with a blank
    minute isn't dropped. True non-participants are excluded."""

    def test_played_minutes(self):
        self.assertTrue(featured({"minutes": 80}))

    def test_scorer_with_blank_minutes_is_kept(self):
        self.assertTrue(featured({"minutes": 0, "tries": 1}))
        self.assertTrue(featured({"minutes": 0, "tackles": 4}))

    def test_true_non_participant_is_dropped(self):
        self.assertFalse(featured({"minutes": 0, "tries": 0, "tackles": 0}))
        self.assertFalse(featured({"minutes": 0}))


class TestScoring(unittest.TestCase):
    """Rugby scoring — role-dependent; must match scoringRow() in
    index.html. Every scored row includes the minutes points (60+ -> 2)."""

    def base(self, **o):
        row = {"minutes": 80, "role": "OB"}
        row.update(o)
        return row

    def test_minutes(self):
        self.assertEqual(calculate_points(self.base(minutes=40)), 1)
        self.assertEqual(calculate_points(self.base(minutes=80)), 2)
        self.assertEqual(calculate_points(self.base(minutes=0, tries=3)), 0)

    def test_try_by_role(self):
        self.assertEqual(calculate_points(self.base(role="PR", tries=1)), 2 + 15)
        self.assertEqual(calculate_points(self.base(role="HK", tries=1)), 2 + 12)
        self.assertEqual(calculate_points(self.base(role="CE", tries=1)), 2 + 10)

    def test_metres_and_runs_by_role(self):
        self.assertEqual(calculate_points(self.base(role="PR", metres=5)), 2 + 1)
        self.assertEqual(calculate_points(self.base(role="OB", metres=25)), 2 + 2)
        self.assertEqual(calculate_points(self.base(role="PR", runs=2)), 2 + 4)

    def test_passes_and_tackles_by_role(self):
        self.assertEqual(calculate_points(self.base(role="SH", passes=10)), 2 + 2)
        self.assertEqual(calculate_points(self.base(role="FH", passes=10)), 2 + 1)
        self.assertEqual(calculate_points(self.base(role="PR", tackles=3)), 2 + 6)
        self.assertEqual(calculate_points(self.base(role="OB", tackles=3)), 2 + 3)

    def test_kicking_and_lineouts(self):
        self.assertEqual(calculate_points(
            self.base(role="FH", conversions=2, conversions_missed=1)), 2 + 4 - 2)
        self.assertEqual(calculate_points(self.base(role="LK", lineout_steals=1)), 2 + 4)
        self.assertEqual(calculate_points(self.base(role="LK", lineouts_taken=3)), 2 + 6)

    def test_negatives_and_scrums_by_role(self):
        self.assertEqual(calculate_points(self.base(role="PR", penalties_conceded=1)), 2 - 3)
        self.assertEqual(calculate_points(self.base(role="OB", penalties_conceded=1)), 2 - 4)
        self.assertEqual(calculate_points(self.base(role="PR", red_cards=1)), 2 - 20)
        self.assertEqual(calculate_points(self.base(role="PR", scrums_won=2)), 2 + 3)
        self.assertEqual(calculate_points(self.base(role="LF", scrums_won=2)), 2 + 1)


class TestPlayerMatcher(unittest.TestCase):
    def setUp(self):
        self.m = PlayerMatcher(ROSTER)

    def assert_match(self, expected_id, expected_how, *args, **kwargs):
        player, how = self.m.match(*args, **kwargs)
        self.assertIsNotNone(player, f"expected a match, got reason: {how}")
        self.assertEqual(player["player_id"], expected_id)
        self.assertIn(expected_how, how)

    def test_exact_name(self):
        self.assert_match("fra_9", "exact name", "Antoine Dupont", "France")

    def test_abbreviated_first_name_matches_surname(self):
        self.assert_match("eng_8", "surname", "B. Earl", "England")

    def test_accented_surname(self):
        self.assert_match("rsa_10", "exact name", "Handré Pollard", "South Africa")

    def test_team_name_fix_applied(self):
        # Provider says "RSA"; players.json says "South Africa".
        self.assert_match("rsa_10", "exact name", "Handré Pollard", "RSA")

    def test_fuzzy_match_on_typo(self):
        self.assert_match("fra_9", "fuzzy", "Antoine Dupon", "France")

    def test_ambiguous_surname_resolved_by_number(self):
        self.assert_match("eng_22", "shirt number", "Smith", "England", shirt_number=22)

    def test_ambiguous_surname_resolved_by_first_initial(self):
        self.assert_match("eng_10", "first initial", "M. Smith", "England")

    def test_ambiguous_surname_without_number_is_unmatched(self):
        player, reason = self.m.match("Smith", "England")
        self.assertIsNone(player)
        self.assertIn("ambiguous", reason)

    def test_number_fallback_when_name_unknown(self):
        self.assert_match("eng_1", "shirt number only", "Nickname", "England", shirt_number=1)

    def test_unknown_team(self):
        player, reason = self.m.match("Antoine Dupont", "Atlantis")
        self.assertIsNone(player)
        self.assertIn("not in players.json", reason)

    def test_no_match_at_all(self):
        player, reason = self.m.match("Zinedine Zidane", "France")
        self.assertIsNone(player)
        self.assertEqual(reason, "no name match")


class TestExtractPlayerRows(unittest.TestCase):
    def make_fixture(self):
        return {
            "fixture": {"id": 1, "date": "2026-07-04T14:00:00+00:00"},
            "teams": {
                "home": {"id": 1, "name": "France"},
                "away": {"id": 2, "name": "England"},
            },
            "goals": {"home": 27, "away": 24},
        }

    def make_teams_data(self):
        def entry(api_id, name, minutes, position, number=None, **stats):
            st = {"games": {"minutes": minutes, "position": position,
                            "number": number, "rating": "7.0"}}
            st.update(stats)
            return {"player": {"id": api_id, "name": name}, "statistics": [st]}

        return [
            {
                "team": {"id": 1, "name": "France"},
                "players": [
                    entry(154, "A. Dupont", 80, "Scrum-half", 9, tries=1, tackles=5),
                    entry(999, "Total Stranger", 12, "Wing"),
                ],
            },
            {
                "team": {"id": 2, "name": "England"},
                "players": [entry(284, "B. Earl", 80, "Flanker", 8, tackles=12)],
            },
        ]

    def test_rows_carry_squad_ids_and_unmatched_is_none(self):
        rows = extract_player_rows(
            self.make_fixture(), self.make_teams_data(), PlayerMatcher(ROSTER)
        )
        by_api = {r["api_player_id"]: r for r in rows}

        self.assertEqual(by_api["154"]["player_id"], "fra_9")
        self.assertEqual(by_api["154"]["player_name"], "Antoine Dupont")
        self.assertEqual(by_api["154"]["tries"], 1)
        # squad-list role + group win over the provider's position string
        self.assertEqual(by_api["154"]["role"], "SH")
        self.assertEqual(by_api["284"]["player_id"], "eng_8")
        self.assertEqual(by_api["284"]["role"], "LF")
        self.assertEqual(by_api["284"]["position"], "BR")
        self.assertEqual(by_api["284"]["tackles"], 12)

        self.assertIsNone(by_api["999"]["player_id"])
        self.assertEqual(by_api["999"]["match_note"], "no name match")

        # official score is stored per row
        self.assertEqual(by_api["154"]["home_score"], 27)
        self.assertEqual(by_api["154"]["away_score"], 24)
        self.assertEqual(
            by_api["154"]["match_label"], "France vs England (2026-07-04)"
        )


class TestMultiLeague(unittest.TestCase):
    """FANTASY_LEAGUE_ID can allowlist several leagues; the same rows are
    upserted once per league, with no extra provider calls."""

    def test_parse_league_ids(self):
        self.assertEqual(parse_league_ids("aaa"), ["aaa"])
        self.assertEqual(parse_league_ids(" aaa , bbb ,"), ["aaa", "bbb"])
        self.assertEqual(parse_league_ids(""), [])
        self.assertEqual(parse_league_ids(None), [])

    def test_payload_fans_out_per_league(self):
        payload = build_stats_payload(
            [daily_pull_ROW, dict(daily_pull_ROW, player_id="eng_8")],
            ["league-a", "league-b"])
        self.assertEqual(len(payload), 4)
        self.assertEqual(sorted({p["league_id"] for p in payload}),
                         ["league-a", "league-b"])
        for p in payload:
            if p["player_id"] == "fra_9":
                self.assertEqual(p["tries"], 1)
                self.assertEqual(p["tackles"], 6)
                self.assertNotIn("motm", p)

    def test_single_league_string_still_works(self):
        payload = build_stats_payload([daily_pull_ROW], "league-a")
        self.assertEqual(len(payload), 1)
        self.assertEqual(payload[0]["league_id"], "league-a")


class TestUpsertGracefulDegradation(unittest.TestCase):
    """An unapplied additive migration (missing optional column) must not
    kill the whole pull: the offending column is dropped and retried."""

    class FakeResp:
        def __init__(self, status_code, text=""):
            self.status_code = status_code
            self.text = text

    def setUp(self):
        os.environ["SUPABASE_URL"] = "https://example.supabase.co"
        os.environ["SUPABASE_SERVICE_KEY"] = "service-key"
        self.posts = []

    def _patch_post(self, responses):
        seq = list(responses)

        def fake_post(url, params=None, headers=None, json=None, timeout=None):
            self.posts.append(json)
            return seq.pop(0)
        return fake_post

    def test_missing_column_is_dropped_and_retried(self):
        rows = [dict(daily_pull_ROW)]
        responses = [
            self.FakeResp(400, '{"code":"PGRST204","message":'
                          '"Could not find the \'away_score\' column of '
                          "'match_stats' in the schema cache\"}"),
            self.FakeResp(400, '{"code":"PGRST204","message":'
                          '"Could not find the \'home_score\' column of '
                          "'match_stats' in the schema cache\"}"),
            self.FakeResp(201),
        ]
        orig = daily_pull.requests.post
        daily_pull.requests.post = self._patch_post(responses)
        try:
            daily_pull.upsert_match_stats(rows, ["league-a"])
        finally:
            daily_pull.requests.post = orig
        self.assertEqual(len(self.posts), 3)
        final = self.posts[-1][0]
        self.assertNotIn("away_score", final)
        self.assertNotIn("home_score", final)
        self.assertEqual(final["tries"], 1)  # real stats survive

    def test_real_error_still_fails(self):
        orig = daily_pull.requests.post
        daily_pull.requests.post = self._patch_post(
            [self.FakeResp(401, '{"message":"bad key"}')])
        try:
            with self.assertRaises(SystemExit):
                daily_pull.upsert_match_stats([dict(daily_pull_ROW)], ["l"])
        finally:
            daily_pull.requests.post = orig


class TestRealPlayersJson(unittest.TestCase):
    """Smoke test against the actual players.json shipped with the app."""

    def test_every_player_matches_itself(self):
        players = json.loads(PLAYERS_JSON.read_text(encoding="utf-8"))
        matcher = PlayerMatcher(players)
        failures = []
        for p in players:
            shirt = int(p["player_id"].rsplit("_", 1)[-1])
            matched, how = matcher.match(p["name"], p["team"], shirt)
            if not matched or matched["player_id"] != p["player_id"]:
                failures.append(f"{p['player_id']} {p['name']}: {how}")
        self.assertEqual(failures, [], "\n".join(failures))


if __name__ == "__main__":
    unittest.main()
