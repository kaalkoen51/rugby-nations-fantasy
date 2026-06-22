#!/usr/bin/env python3
"""Tests for the API-Football -> FIFA squad-list id mapping in daily_pull.

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
    extract_player_rows,
    featured,
    normalize_name,
    parse_league_ids,
    surname_key,
)

# A fully-populated match_stats source row for upsert tests.
daily_pull_ROW = {
    "player_id": "arg_10", "match_label": "Argentina vs Scotland (2026-06-15)",
    "minutes": 90, "conceded": 0, "goals": 1, "assists": 0,
    "yellow_cards": 0, "red_cards": 0, "saves": 0, "motm": True,
    "penalty_saved": 0, "penalty_missed": 0, "defensive_actions": 2,
    "home_score": 1, "away_score": 0,
}

ROSTER = [
    {"player_id": "sco_1", "name": "Angus Gunn", "position": "GK", "team": "Scotland", "team_code": "SCO"},
    {"player_id": "sco_8", "name": "Scott McTominay", "position": "MID", "team": "Scotland", "team_code": "SCO"},
    {"player_id": "kor_7", "name": "Son Heung-Min", "position": "FWD", "team": "Korea Republic", "team_code": "KOR"},
    {"player_id": "arg_10", "name": "Lionel Messi", "position": "FWD", "team": "Argentina", "team_code": "ARG"},
    {"player_id": "arg_19", "name": "Nicolás Otamendi", "position": "DEF", "team": "Argentina", "team_code": "ARG"},
    {"player_id": "bra_4", "name": "Carlos Silva", "position": "DEF", "team": "Brazil", "team_code": "BRA"},
    {"player_id": "bra_14", "name": "Eduardo Silva", "position": "MID", "team": "Brazil", "team_code": "BRA"},
]


class TestNormalize(unittest.TestCase):
    def test_accents_and_punctuation(self):
        self.assertEqual(normalize_name("N'Golo Kanté"), "n golo kante")

    def test_initials_and_case(self):
        self.assertEqual(normalize_name("S. McTominay"), "s mctominay")

    def test_surname_key_is_last_token(self):
        self.assertEqual(surname_key("Kevin De Bruyne"), "bruyne")
        self.assertEqual(surname_key("Son Heung-Min"), "min")


class TestFeatured(unittest.TestCase):
    """A player is kept if they have minutes OR any stat, so a scorer with
    API-Football's occasional minutes:null isn't dropped (the regression that
    made goals vanish for whole matchdays)."""

    def test_played_minutes(self):
        self.assertTrue(featured({"minutes": 90}))

    def test_scorer_with_blank_minutes_is_kept(self):
        self.assertTrue(featured({"minutes": 0, "goals": 1}))
        self.assertTrue(featured({"minutes": 0, "assists": 1}))
        self.assertTrue(featured({"minutes": 0, "defensive_actions": 3}))

    def test_true_non_participant_is_dropped(self):
        self.assertFalse(featured({"minutes": 0, "goals": 0, "assists": 0}))
        self.assertFalse(featured({"minutes": 0}))


class TestPlayerMatcher(unittest.TestCase):
    def setUp(self):
        self.m = PlayerMatcher(ROSTER)

    def assert_match(self, expected_id, expected_how, *args, **kwargs):
        player, how = self.m.match(*args, **kwargs)
        self.assertIsNotNone(player, f"expected a match, got reason: {how}")
        self.assertEqual(player["player_id"], expected_id)
        self.assertIn(expected_how, how)

    def test_exact_name(self):
        self.assert_match("arg_10", "exact name", "Lionel Messi", "Argentina")

    def test_abbreviated_first_name_matches_surname(self):
        self.assert_match("sco_8", "surname", "S. McTominay", "Scotland")

    def test_accented_surname(self):
        self.assert_match("arg_19", "surname", "N. Otamendi", "Argentina")

    def test_team_name_fix_applied(self):
        # API-Football says "South Korea"; players.json says "Korea Republic".
        self.assert_match("kor_7", "exact name", "Son Heung-Min", "South Korea")

    def test_fuzzy_match_on_typo(self):
        self.assert_match("arg_10", "fuzzy", "Lionel Mesi", "Argentina")

    def test_ambiguous_surname_resolved_by_shirt_number(self):
        self.assert_match(
            "bra_14", "shirt number", "E. Silva", "Brazil", shirt_number=14
        )

    def test_ambiguous_surname_resolved_by_first_initial(self):
        self.assert_match("bra_14", "first initial", "E. Silva", "Brazil")

    def test_ambiguous_surname_without_number_is_unmatched(self):
        player, reason = self.m.match("Silva", "Brazil")
        self.assertIsNone(player)
        self.assertIn("ambiguous", reason)

    def test_shirt_number_fallback_when_name_unknown(self):
        self.assert_match(
            "arg_10", "shirt number only", "Pulga", "Argentina", shirt_number=10
        )

    def test_unknown_team(self):
        player, reason = self.m.match("Lionel Messi", "Atlantis")
        self.assertIsNone(player)
        self.assertIn("not in players.json", reason)

    def test_no_match_at_all(self):
        player, reason = self.m.match("Zinedine Zidane", "Argentina")
        self.assertIsNone(player)
        self.assertEqual(reason, "no name match")


class TestExtractPlayerRows(unittest.TestCase):
    def make_fixture(self):
        return {
            "fixture": {"id": 1, "date": "2026-06-15T18:00:00+00:00"},
            "teams": {
                "home": {"id": 26, "name": "Argentina"},
                "away": {"id": 1108, "name": "Scotland"},
            },
            "goals": {"home": 2, "away": 0},
        }

    def make_teams_data(self):
        def entry(api_id, name, minutes, position, number=None):
            return {
                "player": {"id": api_id, "name": name},
                "statistics": [
                    {
                        "games": {
                            "minutes": minutes,
                            "position": position,
                            "number": number,
                            "rating": "7.0",
                        },
                        "goals": {}, "cards": {}, "penalty": {},
                        "tackles": {"total": 3, "blocks": 1, "interceptions": 2},
                    }
                ],
            }

        return [
            {
                "team": {"id": 26, "name": "Argentina"},
                "players": [
                    entry(154, "L. Messi", 90, "Attacker", 10),
                    entry(999, "Total Stranger", 12, "Midfielder"),
                ],
            },
            {
                "team": {"id": 1108, "name": "Scotland"},
                "players": [entry(284, "S. McTominay", 90, "Midfielder", 8)],
            },
        ]

    def test_rows_carry_fifa_ids_and_unmatched_is_none(self):
        rows = extract_player_rows(
            self.make_fixture(), self.make_teams_data(), PlayerMatcher(ROSTER)
        )
        by_api = {r["api_player_id"]: r for r in rows}

        self.assertEqual(by_api["154"]["player_id"], "arg_10")
        self.assertEqual(by_api["154"]["player_name"], "Lionel Messi")
        self.assertEqual(by_api["284"]["player_id"], "sco_8")
        # squad-list position wins over the API one
        self.assertEqual(by_api["284"]["position"], "MID")

        self.assertIsNone(by_api["999"]["player_id"])
        self.assertEqual(by_api["999"]["match_note"], "no name match")

        # tackles + blocks + interceptions roll up into defensive_actions
        self.assertEqual(by_api["154"]["defensive_actions"], 6)

        # official score from fixture["goals"] is stored per row
        self.assertEqual(by_api["154"]["home_score"], 2)
        self.assertEqual(by_api["154"]["away_score"], 0)
        self.assertEqual(by_api["284"]["home_score"], 2)
        self.assertEqual(by_api["284"]["away_score"], 0)

        self.assertEqual(
            by_api["154"]["match_label"],
            "Argentina vs Scotland (2026-06-15)",
        )


class TestMultiLeague(unittest.TestCase):
    """FANTASY_LEAGUE_ID can allowlist several leagues; the same rows are
    upserted once per league, with no extra API-Football calls."""

    ROW = {
        "player_id": "arg_10", "match_label": "Argentina vs Scotland (2026-06-15)",
        "minutes": 90, "conceded": 0, "goals": 1, "assists": 0,
        "yellow_cards": 0, "red_cards": 0, "saves": 0, "motm": True,
        "penalty_saved": 0, "penalty_missed": 0, "defensive_actions": 2,
        "home_score": 1, "away_score": 0,
    }

    def test_parse_league_ids(self):
        self.assertEqual(parse_league_ids("aaa"), ["aaa"])
        self.assertEqual(parse_league_ids(" aaa , bbb ,"), ["aaa", "bbb"])
        self.assertEqual(parse_league_ids(""), [])
        self.assertEqual(parse_league_ids(None), [])

    def test_payload_fans_out_per_league(self):
        payload = build_stats_payload([self.ROW, dict(self.ROW, player_id="sco_8")],
                                      ["league-a", "league-b"])
        self.assertEqual(len(payload), 4)
        self.assertEqual(sorted({p["league_id"] for p in payload}),
                         ["league-a", "league-b"])
        # same stats in every league's copy
        for p in payload:
            if p["player_id"] == "arg_10":
                self.assertEqual(p["goals"], 1)
                self.assertTrue(p["clean_sheet"])

    def test_single_league_string_still_works(self):
        payload = build_stats_payload([self.ROW], "league-a")
        self.assertEqual(len(payload), 1)
        self.assertEqual(payload[0]["league_id"], "league-a")

    def test_comma_string_fans_out(self):
        payload = build_stats_payload([self.ROW], "league-a,league-b")
        self.assertEqual({p["league_id"] for p in payload},
                         {"league-a", "league-b"})


class TestUpsertGracefulDegradation(unittest.TestCase):
    """An unapplied additive migration (missing optional column) must not
    kill the whole pull: the offending column is dropped and the write
    retried. Scoring never depends on these columns."""

    class FakeResp:
        def __init__(self, status_code, text=""):
            self.status_code = status_code
            self.text = text

    def setUp(self):
        os.environ["SUPABASE_URL"] = "https://example.supabase.co"
        os.environ["SUPABASE_SERVICE_KEY"] = "service-key"
        self.posts = []

    def _patch_post(self, responses):
        """Each call pops the next FakeResp; records the payload sent."""
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
        # Three attempts; the final payload has both optional cols stripped.
        self.assertEqual(len(self.posts), 3)
        final = self.posts[-1][0]
        self.assertNotIn("away_score", final)
        self.assertNotIn("home_score", final)
        self.assertEqual(final["goals"], 1)  # real stats survive

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
