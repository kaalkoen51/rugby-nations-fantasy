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
  src + "\nreturn { S, pickInfo, calcPlayerPoints, calcTeamPoints, computeScores, slotGroup, pairValid, tradeError, quotaLeft, slotForNewPick, POSITION_QUOTA };"
)(stubDoc, { getItem: () => null, setItem: () => {}, removeItem: () => {} }, {}, {}, {});

const { S, pickInfo, calcPlayerPoints, calcTeamPoints, computeScores,
        slotGroup, pairValid, tradeError, quotaLeft, slotForNewPick, POSITION_QUOTA } = api;
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
check("quota sums to 14", Object.values(POSITION_QUOTA).reduce((a, b) => a + b, 0), 14);
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
  penalty_missed: 0, ...o });
check("GK: cs + 5 saves + pen save", calcPlayerPoints(row({ clean_sheet: true, saves: 5, penalty_saved: 1 }), "GK"), 6 + 2 + 5);
check("FWD: 2 goals + motm + yellow", calcPlayerPoints(row({ goals: 2, motm: true, yellow_cards: 1 }), "FWD"), 8 + 3 - 1);
check("DNP scores 0", calcPlayerPoints(row({ appeared: false, goals: 3 }), "MID"), 0);

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
check("sub active only day 1 (goal 6 + cs 4)", [subItem.pts, subItem.note], [10, "active 1×"]);
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

process.exit(fails ? 1 : 0);
