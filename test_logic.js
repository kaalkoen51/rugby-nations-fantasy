const fs = require("fs");
const src = fs.readFileSync("index.html", "utf8")
  .match(/<script>\n("use strict";[\s\S]*)<\/script>/)[1];

const stubDoc = {
  getElementById: () => null,
  querySelectorAll: () => [],
  querySelector: () => null,
  addEventListener: () => {},
};
const api = new Function(
  "document", "localStorage", "window", "crypto", "navigator",
  src + "\nreturn { S, pickInfo, calcPlayerPoints, calcTeamPoints, computeScores, slotGroup, pairValid, tradeError, quotaLeft, slotForNewPick, posQuota, picksPerManager, totalPicks, playerBreakdown, playerPoints, suspendedNext };"
)(stubDoc, { getItem: () => null, setItem: () => {}, removeItem: () => {} }, {}, {}, {});

const { S, pickInfo, calcPlayerPoints, calcTeamPoints, computeScores,
        slotGroup, pairValid, tradeError, quotaLeft, slotForNewPick,
        posQuota, picksPerManager, totalPicks,
        playerBreakdown, playerPoints, suspendedNext } = api;
let fails = 0;
const check = (label, got, want) => {
  const ok = JSON.stringify(got) === JSON.stringify(want);
  if (!ok) { fails++; console.log(`FAIL ${label}: got ${JSON.stringify(got)}, want ${JSON.stringify(want)}`); }
  else console.log(`ok   ${label}`);
};

/* snake order: 4 managers */
S.managers = [1, 2, 3, 4].map((i) => ({ id: "m" + i, name: "M" + i, draft_position: i }));
S.league = { num_managers: 4 };
check("pick 1 -> M1", pickInfo(1).manager.name, "M1");
check("pick 4 -> M4", pickInfo(4).manager.name, "M4");
check("pick 5 -> M4 (snake)", pickInfo(5).manager.name, "M4");
check("pick 8 -> M1", pickInfo(8).manager.name, "M1");
check("pick 9 -> M1 (snake back)", pickInfo(9).manager.name, "M1");
check("pick 37 round 10", pickInfo(37).round, 10);
check("pick 56 last -> M1", pickInfo(56).manager.name, "M1");

/* position quotas & default starter/sub slotting */
const roster = [];
const draftOne = (pos) => {
  const slot = slotForNewPick(roster, pos);
  roster.push({ position: pos, slot });
  return slot;
};
check("quota sums to 14", Object.values(posQuota()).reduce((a, b) => a + b, 0), 14);
check("1st GK is starter", draftOne("GK"), "GK");
check("2nd GK is sub", draftOne("GK"), "SUB_GK");
check("GK quota now 0", quotaLeft(roster, "GK"), 0);
check("DEF 1-3 start", [draftOne("DEF"), draftOne("DEF"), draftOne("DEF")], ["DEF", "DEF", "DEF"]);
check("4th DEF is sub", draftOne("DEF"), "SUB_DEF");
check("TEAM slot is TEAM", draftOne("TEAM"), "TEAM");
check("MID quota untouched", quotaLeft(roster, "MID"), 4);

/* scoring */
const row = (o) => ({ appeared: true, goals: 0, assists: 0, clean_sheet: false,
  yellow_cards: 0, red_cards: 0, saves: 0, motm: false, penalty_saved: 0,
  penalty_missed: 0, defensive_actions: 0, ...o });
check("GK: cs + 5 saves + pen save", calcPlayerPoints(row({ clean_sheet: true, saves: 5, penalty_saved: 1 }), "GK"), 6 + 2 + 5);
check("FWD: 2 goals + motm + yellow", calcPlayerPoints(row({ goals: 2, motm: true, yellow_cards: 1 }), "FWD"), 8 + 3 - 1);
check("DNP scores 0", calcPlayerPoints(row({ appeared: false, goals: 3 }), "MID"), 0);
check("DEF: cs + 5 def actions", calcPlayerPoints(row({ clean_sheet: true, defensive_actions: 5 }), "DEF"), 4 + 2);
check("GK def actions don't score", calcPlayerPoints(row({ defensive_actions: 8 }), "GK"), 0);
check("rows without def actions still score", calcPlayerPoints({ ...row({ goals: 1 }), defensive_actions: undefined }, "MID"), 5);

/* sub activation */
S.managers = [{ id: "m1", name: "M1", draft_position: 1 }];
S.picks = [
  { manager_id: "m1", player_id: "fra_5", player_name: "Starter Def", position: "DEF", team: "France", slot: "DEF", is_sub: false, pick_number: 2 },
  { manager_id: "m1", player_id: "arg_3", player_name: "Sub Def", position: "DEF", team: "Argentina", slot: "SUB_DEF", is_sub: true, pick_number: 12 },
];
// Day 1: France played (others' rows exist), starter has no row -> sub's day-1 match counts.
// Day 2: starter appeared -> sub's day-2 match doesn't count.
S.stats = [
  { player_id: "fra_9", match_label: "France vs Brazil (2026-06-15)", appeared: true, goals: 0 },
  { player_id: "arg_3", match_label: "Argentina vs Chile (2026-06-15)", appeared: true, goals: 1, clean_sheet: true },
  { player_id: "fra_5", match_label: "France vs Spain (2026-06-18)", appeared: true, clean_sheet: true },
  { player_id: "arg_3", match_label: "Argentina vs Peru (2026-06-18)", appeared: true, goals: 1 },
].map((r) => row(r));
const sc = computeScores()[0];
const subItem = sc.items.find((i) => i.pick.is_sub);
const startItem = sc.items.find((i) => !i.pick.is_sub);
check("starter DEF cs pts", startItem.pts, 4);
check("sub active only day 1 (goal 6 + cs 4)", [subItem.pts, subItem.note], [10, "sub"]);
check("manager total", sc.total, 14);

/* team stage bonuses */
check("stage group = 0", calcTeamPoints("group"), 0);
check("stage r32 = 5", calcTeamPoints("r32"), 5);
check("stage qf = 5+10+15", calcTeamPoints("qf"), 30);
check("stage final = 75", calcTeamPoints("final"), 75);
check("stage winner = 90", calcTeamPoints("winner"), 90);
check("unknown stage = 0", calcTeamPoints("nonsense"), 0);

/* TEAM pick in leaderboard total */
S.picks.push({ manager_id: "m1", player_id: "team:France", player_name: "France",
  position: "TEAM", team: "France", slot: "TEAM", is_sub: false, pick_number: 10 });
S.stages = [{ team: "France", stage: "sf" }];
const sc2 = computeScores()[0];
const teamItem = sc2.items.find((i) => i.pick.slot === "TEAM");
check("TEAM pick sf = 50", [teamItem.pts, teamItem.note], [50, "sf"]);
check("total includes stage bonus", sc2.total, 14 + 50);
S.stages = [];
const teamItem0 = computeScores()[0].items.find((i) => i.pick.slot === "TEAM");
check("no stage row = group = 0", [teamItem0.pts, teamItem0.note], [0, "group"]);

/* lineup locks: each matchday scores against the snapshot in effect */
S.managers = [{ id: "m1", name: "M1", draft_position: 1 }];
S.picks = [{ id: "p1", manager_id: "m1", player_id: "bra_2", player_name: "New Def",
  position: "DEF", team: "Brazil", slot: "DEF", is_sub: false, pick_number: 1 }];
S.stats = [
  row({ player_id: "fra_5", match_label: "France vs Chile (2026-06-12)", goals: 1 }),
  row({ player_id: "fra_5", match_label: "France vs Spain (2026-06-16)", goals: 1 }),
  row({ player_id: "bra_2", match_label: "Brazil vs Peru (2026-06-16)", clean_sheet: true }),
];
S.snapshots = [
  { manager_id: "m1", effective_from: "2026-06-10T08:00:00+00:00",
    roster: [{ player_id: "fra_5", player_name: "Old Def", position: "DEF",
               team: "France", is_sub: false, slot: "DEF" }] },
  { manager_id: "m1", effective_from: "2026-06-15T08:00:00+00:00",
    roster: [{ player_id: "bra_2", player_name: "New Def", position: "DEF",
               team: "Brazil", is_sub: false, slot: "DEF" }] },
];
const hist = computeScores()[0];
check("pre-trade points banked, post-trade not credited", hist.total, 6 + 4);
check("current pick scores from lock date only",
  hist.items.find((i) => i.pick.player_id === "bra_2").pts, 4);
check("former player line shows banked points",
  hist.items.find((i) => i.pick.player_id === "__former__").pts, 6);
S.snapshots = [];

/* player stats breakdown: per-category points sum to the player total */
S.stats = [
  row({ player_id: "ger_1", match_label: "Germany vs X (2026-06-20)", saves: 5, clean_sheet: true }),
  row({ player_id: "ger_1", match_label: "Germany vs Y (2026-06-24)", saves: 3 }),
  row({ player_id: "ger_5", match_label: "Germany vs X (2026-06-20)", defensive_actions: 5, goals: 1, yellow_cards: 1 }),
];
check("GK breakdown sums to playerPoints",
  playerBreakdown("ger_1", "GK").reduce((s, r) => s + r.pts, 0),
  playerPoints("ger_1", "GK"));
check("GK saves floor per match (2+1, not 4)",
  playerBreakdown("ger_1", "GK").find((r) => r.label.startsWith("Saves")).pts, 3);
check("DEF breakdown categories", playerBreakdown("ger_5", "DEF")
  .map((r) => [r.label, r.count, r.pts]),
  [["Goals", 1, 6], ["Defensive actions (per 2)", 5, 2], ["Yellow cards", 1, -1]]);

/* trading: slot position groups */
check("SUB_GK and GK same group", slotGroup("SUB_GK"), slotGroup("GK"));
check("SUB_FWD group is FWD", slotGroup("SUB_FWD"), "FWD");
check("DEF and MID differ", slotGroup("DEF") === slotGroup("MID"), false);

/* trading: pair validity */
const pick = (id, slot) => ({ id, slot, player_name: id });
check("GK ⇄ SUB_GK valid", pairValid(pick("a", "GK"), pick("b", "SUB_GK")), true);
check("SUB_DEF ⇄ SUB_DEF valid", pairValid(pick("a", "SUB_DEF"), pick("b", "SUB_DEF")), true);
check("DEF ⇄ MID invalid", pairValid(pick("a", "DEF"), pick("b", "MID")), false);
check("TEAM never tradable", pairValid(pick("a", "TEAM"), pick("b", "TEAM")), false);

/* trading: whole-trade validity */
const P = (id, slot) => pick(id, slot);
check("empty trade rejected", tradeError([]) !== null, true);
check("valid single pair", tradeError([{ mine: P("a", "MID"), theirs: P("b", "SUB_MID") }]), null);
check("valid multi pair", tradeError([
  { mine: P("a", "GK"), theirs: P("b", "GK") },
  { mine: P("c", "FWD"), theirs: P("d", "SUB_FWD") },
]), null);
check("mismatched pair rejected", tradeError([
  { mine: P("a", "DEF"), theirs: P("b", "FWD") },
]) !== null, true);
check("incomplete pair rejected", tradeError([
  { mine: P("a", "DEF"), theirs: null },
]) !== null, true);
check("same pick twice rejected", tradeError([
  { mine: P("a", "DEF"), theirs: P("b", "DEF") },
  { mine: P("a", "DEF"), theirs: P("c", "SUB_DEF") },
]) !== null, true);

/* redraft phases: admin quota, kept players, eliminated managers */
S.league = { num_managers: 4, phase: 2,
  phase_quota: { GK: 1, DEF: 2, MID: 2, FWD: 2 },
  phase_starters: { GK: 1, DEF: 2, MID: 2, FWD: 1 } };
S.managers = [
  { id: "m1", name: "M1", draft_position: 1 },
  { id: "m2", name: "M2", draft_position: 2 },
  { id: "m3", name: "M3", draft_position: 3, eliminated: true, frozen_points: 42 },
];
check("phase 2 quota has no TEAM", posQuota().TEAM, 0);
check("picks per manager from phase quota", picksPerManager(), 7);
check("totalPicks counts active managers only", totalPicks(), 14);
check("kept player rides outside the quota",
  quotaLeft([{ position: "DEF", kept: true }, { position: "DEF" }], "DEF"), 1);
check("kept player still fills a starter slot",
  slotForNewPick([{ position: "DEF", kept: true }, { position: "DEF" }], "DEF"), "SUB_DEF");
check("draft order skips eliminated managers",
  [pickInfo(1).manager.name, pickInfo(2).manager.name, pickInfo(3).manager.name],
  ["M1", "M2", "M2"]);

/* frozen totals & champion picks in scoring */
S.picks = []; S.stats = []; S.snapshots = [];
S.stages = [{ team: "France", stage: "winner" }];
S.managers = [
  { id: "m1", name: "M1", final_pick: "France" },
  { id: "m2", name: "M2", final_pick: "Brazil" },
  { id: "m3", name: "M3", eliminated: true, frozen_points: 42 },
];
const fin = computeScores();
check("correct champion pick +5", fin[0].total, 5);
check("wrong champion pick scores 0", fin[1].total, 0);
check("eliminated manager shows frozen points",
  [fin[2].total, fin[2].items.length], [42, 0]);
S.stages = [];
check("champion pick pending = 0", computeScores()[0].total, 0);

/* suspension indicator (best-effort, from our own card data) */
S.stats = [
  row({ player_id: "x1", match_label: "A vs B (2026-06-15)", red_cards: 1 }),
  row({ player_id: "x2", match_label: "A vs B (2026-06-15)", yellow_cards: 1 }),
  row({ player_id: "x2", match_label: "A vs C (2026-06-20)", yellow_cards: 1 }),
  row({ player_id: "x3", match_label: "A vs B (2026-06-15)", yellow_cards: 1 }),
  row({ player_id: "x4", match_label: "A vs B (2026-06-15)", red_cards: 1 }),
  row({ player_id: "x4", match_label: "A vs C (2026-06-20)" }),
  row({ player_id: "x5", match_label: "A vs B (2026-07-08)", yellow_cards: 1 }),
  row({ player_id: "x5", match_label: "A vs C (2026-07-14)", yellow_cards: 1 }),
  row({ player_id: "x6", match_label: "A vs B (2026-06-15)", yellow_cards: 2, red_cards: 1 }),
  row({ player_id: "x6", match_label: "A vs C (2026-06-20)", yellow_cards: 1 }),
];
check("red card -> suspended next match", suspendedNext("x1"), "red card");
check("2nd yellow -> suspended next match", suspendedNext("x2"), "2 yellows");
check("single yellow -> fine", suspendedNext("x3"), null);
check("ban cleared after playing again", suspendedNext("x4"), null);
check("yellow slate wiped after the QFs", suspendedNext("x5"), null);
check("two-yellow red doesn't count toward accumulation", suspendedNext("x6"), null);
check("no stats -> no flag", suspendedNext("x7"), null);

process.exit(fails ? 1 : 0);
