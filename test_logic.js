// Smoke tests for the rugby draft + scoring logic in index.html.
//   node test_logic.js
// Boots the app's <script> in a stubbed DOM and exercises the pure
// functions (draft order, position quotas, scoring, sub activation, stage
// bonuses, trades, redraft phases). Scoring parity with daily_pull.py is
// the key invariant — keep SCORING in the two files identical.
const fs = require("fs");
const src = fs.readFileSync("index.html", "utf8")
  .match(/<script>\n("use strict";[\s\S]*)<\/script>/)[1];

const stubDoc = {
  getElementById: () => null,
  querySelectorAll: () => [],
  querySelector: () => null,
  addEventListener: () => {},
};
const winStub = { scrollTo: () => {} };
const _session = JSON.stringify({ leagueId: "L1", managerId: "m1" });
const lsStub = { getItem: (k) => k === "wcf_session" ? _session : null,
                 setItem: () => {}, removeItem: () => {} };
const api = new Function(
  "document", "localStorage", "window", "crypto", "navigator",
  src + "\nreturn { S, pickInfo, calcPlayerPoints, calcTeamPoints, computeScores, slotGroup, pairValid, tradeError, quotaLeft, slotForNewPick, posQuota, picksPerManager, totalPicks, playerBreakdown, playerPoints, suspendedNext, playerStatTotal, isEliminated, h2hResult, roundRobin, h2hTable, resolveFaClaims };"
)(stubDoc, lsStub, winStub, {}, {});

const { S, pickInfo, calcPlayerPoints, calcTeamPoints, computeScores,
        slotGroup, pairValid, tradeError, quotaLeft, slotForNewPick,
        posQuota, picksPerManager, totalPicks, playerBreakdown, playerPoints,
        suspendedNext, playerStatTotal, isEliminated,
        h2hResult, roundRobin, h2hTable, resolveFaClaims } = api;

let fails = 0;
const check = (label, got, want) => {
  const ok = JSON.stringify(got) === JSON.stringify(want);
  if (!ok) { fails++; console.log(`FAIL ${label}: got ${JSON.stringify(got)}, want ${JSON.stringify(want)}`); }
  else console.log(`ok   ${label}`);
};

/* ---------- snake draft order: 4 managers ---------- */
S.managers = [1, 2, 3, 4].map((i) => ({ id: "m" + i, name: "M" + i, draft_position: i }));
S.league = { num_managers: 4 };
check("pick 1 -> M1", pickInfo(1).manager.name, "M1");
check("pick 4 -> M4", pickInfo(4).manager.name, "M4");
check("pick 5 -> M4 (snake)", pickInfo(5).manager.name, "M4");
check("pick 8 -> M1", pickInfo(8).manager.name, "M1");
check("pick 9 -> M1 (snake back)", pickInfo(9).manager.name, "M1");

/* ---------- position quotas & default starter/sub slotting ---------- */
// Phase-1 squad: FR4 SR3 BR4 HB3 CE3 B3:4 + TEAM1 = 22 picks; XV starts.
check("quota sums to 22", Object.values(posQuota()).reduce((a, b) => a + b, 0), 22);
check("picks per manager = 22", picksPerManager(), 22);
const roster = [];
const draftOne = (pos) => {
  const slot = slotForNewPick(roster, pos);
  roster.push({ position: pos, slot });
  return slot;
};
check("FR 1-3 start", [draftOne("FR"), draftOne("FR"), draftOne("FR")], ["FR", "FR", "FR"]);
check("4th FR is sub", draftOne("FR"), "SUB_FR");
check("FR quota now 0", quotaLeft(roster, "FR"), 0);
check("1st SR is starter", draftOne("SR"), "SR");
check("3rd SR is sub (2 starters)", [draftOne("SR"), draftOne("SR")], ["SR", "SUB_SR"]);
check("TEAM slot is TEAM", draftOne("TEAM"), "TEAM");
check("B3 quota untouched", quotaLeft(roster, "B3"), 4);

/* ---------- scoring (mirrors calculate_points in daily_pull.py) ----------
   Many values depend on the granular role; the 2nd arg to calcPlayerPoints
   is a role code (PR/HK/LK/LF/SH/FH/CE/OB) when the player isn't in
   S.players. minutes also score: 1-59 -> 1, 60+ -> 2. */
const row = (o) => ({
  appeared: true, minutes: 80, tries: 0, metres: 0, runs: 0, defenders_beaten: 0,
  clean_breaks: 0, passes: 0, offloads: 0, turnovers_conceded: 0, try_assists: 0,
  tackles: 0, missed_tackles: 0, turnovers_won: 0, conversions: 0,
  conversions_missed: 0, penalties: 0, penalties_missed: 0, drop_goals: 0,
  drop_goals_missed: 0, lineout_throws_won: 0, lineouts_taken: 0, lineout_steals: 0,
  penalties_conceded: 0, red_cards: 0, yellow_cards: 0, scrums_won: 0,
  scrums_lost: 0, lineouts_lost: 0, ...o });
const cp = (o, role) => calcPlayerPoints(row(o), role);  // includes +2 minutes

check("minutes 1-59 = 1", cp({ minutes: 40 }, "OB"), 1);
check("minutes 60+ = 2", cp({ minutes: 80 }, "OB"), 2);
check("0 minutes scores 0", cp({ minutes: 0, tries: 3 }, "OB"), 0);
check("DNP scores 0", cp({ appeared: false, tries: 3 }, "OB"), 0);
check("prop try = 15", cp({ tries: 1 }, "PR"), 2 + 15);
check("hooker try = 12", cp({ tries: 1 }, "HK"), 2 + 12);
check("centre try = 10", cp({ tries: 1 }, "CE"), 2 + 10);
check("prop metres 1/5m", cp({ metres: 5 }, "PR"), 2 + 1);
check("back metres 1/10m", cp({ metres: 25 }, "OB"), 2 + 2);
check("prop run x2", cp({ runs: 2 }, "PR"), 2 + 4);
check("back run x1", cp({ runs: 2 }, "OB"), 2 + 2);
check("scrum-half passes 1/5", cp({ passes: 10 }, "SH"), 2 + 2);
check("other passes 1/10", cp({ passes: 10 }, "FH"), 2 + 1);
check("prop try assist = 7", cp({ try_assists: 1 }, "PR"), 2 + 7);
check("back try assist = 5", cp({ try_assists: 1 }, "OB"), 2 + 5);
check("prop tackle x2", cp({ tackles: 3 }, "PR"), 2 + 6);
check("back tackle x1", cp({ tackles: 3 }, "OB"), 2 + 3);
check("clean break = 5", cp({ clean_breaks: 1 }, "OB"), 2 + 5);
check("defenders beaten = 2", cp({ defenders_beaten: 2 }, "OB"), 2 + 4);
check("offload = 3", cp({ offloads: 1 }, "OB"), 2 + 3);
check("turnover won = 3", cp({ turnovers_won: 1 }, "LF"), 2 + 3);
check("turnover conceded = -3", cp({ turnovers_conceded: 1 }, "OB"), 2 - 3);
check("conversions + missed", cp({ conversions: 2, conversions_missed: 1 }, "FH"), 2 + 4 - 2);
check("penalties + missed", cp({ penalties: 1, penalties_missed: 1 }, "FH"), 2 + 3 - 3);
check("drop goal", cp({ drop_goals: 1 }, "FH"), 2 + 3);
check("lineout steal = 4", cp({ lineout_steals: 1 }, "LK"), 2 + 4);
check("lineout throws won", cp({ lineout_throws_won: 2 }, "HK"), 2 + 2);
check("lineouts taken", cp({ lineouts_taken: 3 }, "LK"), 2 + 6);
check("lineouts lost = -2", cp({ lineouts_lost: 1 }, "LK"), 2 - 2);
check("prop penalty conceded = -3", cp({ penalties_conceded: 1 }, "PR"), 2 - 3);
check("back penalty conceded = -4", cp({ penalties_conceded: 1 }, "OB"), 2 - 4);
check("yellow card = -10", cp({ yellow_cards: 1 }, "OB"), 2 - 10);
check("red card = -20", cp({ red_cards: 1 }, "PR"), 2 - 20);
check("prop scrums won 1.5", cp({ scrums_won: 2 }, "PR"), 2 + 3);
check("loosie scrums won 0.5", cp({ scrums_won: 2 }, "LF"), 2 + 1);
check("prop scrums lost -3", cp({ scrums_lost: 1 }, "PR"), 2 - 3);

/* ---------- per-category breakdown sums to the player total ---------- */
S.stats = [
  row({ player_id: "eng_5", match_label: "England vs Fiji (2026-07-04)", tries: 1, tackles: 3, yellow_cards: 1 }),
  row({ player_id: "eng_9", match_label: "England vs Japan (2026-07-04)", metres: 25 }),
  row({ player_id: "eng_9", match_label: "England vs NZ (2026-07-11)", metres: 33 }),
];
check("breakdown sums to playerPoints (prop)",
  playerBreakdown("eng_5", "PR").reduce((s, r) => s + r.pts, 0),
  playerPoints("eng_5", "PR"));
check("prop breakdown categories", playerBreakdown("eng_5", "PR")
  .map((r) => [r.label, r.count, r.pts]),
  [["Minutes", 80, 2], ["Tries", 1, 15], ["Tackles", 3, 6], ["Yellow cards", 1, -10]]);
check("metres floor per match (2 + 3, not 5.8 -> 5)",
  playerBreakdown("eng_9", "OB").find((r) => r.label === "Metres made").pts, 5);
check("season stat total counts raw metres", playerStatTotal("eng_9", "metres"), 58);

/* ---------- sub activation: covers a no-show starter, by round ---------- */
S.fixtures = []; S.snapshots = []; S.stages = [];
S.managers = [{ id: "m1", name: "M1", draft_position: 1 }];
S.league = { num_managers: 1 };
S.picks = [
  { manager_id: "m1", player_id: "fra_5", player_name: "Starter FR", position: "FR", team: "France", slot: "FR", is_sub: false, pick_number: 1 },
  { manager_id: "m1", player_id: "arg_3", player_name: "Sub FR", position: "FR", team: "Argentina", slot: "SUB_FR", is_sub: true, pick_number: 12 },
];
S.stats = [
  // Round 1 (07-04): France played (fra_9), but the starter has no row -> the sub's R1 game counts.
  row({ player_id: "fra_9", match_label: "France vs New Zealand (2026-07-04)", appeared: true }),
  row({ player_id: "arg_3", match_label: "Argentina vs Italy (2026-07-04)", appeared: true, tries: 1 }),
  // Round 2 (07-11): the starter featured -> the sub's R2 game does not count.
  row({ player_id: "fra_5", match_label: "France vs South Africa (2026-07-11)", appeared: true, tackles: 3 }),
  row({ player_id: "arg_3", match_label: "Argentina vs Wales (2026-07-11)", appeared: true, tries: 1 }),
];
// FR group defaults to the prop role (no S.players here): minutes 2 + ...
const sc = computeScores()[0];
const subItem = sc.items.find((i) => i.pick.is_sub);
const startItem = sc.items.find((i) => !i.pick.is_sub);
check("starter R2 (2 min + 3 tackles x2)", startItem.pts, 2 + 6);
check("sub active only R1 (2 min + try 15)", [subItem.pts, subItem.note], [2 + 15, "sub"]);
check("manager total", sc.total, 8 + 17);

/* ---------- team stage bonuses (pool -> final -> winner) ---------- */
check("stage pool = 0", calcTeamPoints("pool"), 0);
check("stage final = 15", calcTeamPoints("final"), 15);
check("stage winner = 35", calcTeamPoints("winner"), 35);
check("unknown stage = 0", calcTeamPoints("nonsense"), 0);

/* ---------- TEAM pick in the leaderboard total ---------- */
S.picks.push({ manager_id: "m1", player_id: "team:France", player_name: "France",
  position: "TEAM", team: "France", slot: "TEAM", is_sub: false, pick_number: 10 });
S.stages = [{ team: "France", stage: "final" }];
const teamItem = computeScores()[0].items.find((i) => i.pick.slot === "TEAM");
check("TEAM pick final = 15", [teamItem.pts, teamItem.note], [15, "final"]);
S.stages = [];
const teamItem0 = computeScores()[0].items.find((i) => i.pick.slot === "TEAM");
check("no stage row = pool = 0", [teamItem0.pts, teamItem0.note], [0, "pool"]);

/* ---------- trades: slot position groups ---------- */
check("SUB_FR and FR same group", slotGroup("SUB_FR"), slotGroup("FR"));
check("SUB_B3 group is B3", slotGroup("SUB_B3"), "B3");
check("FR and SR differ", slotGroup("FR") === slotGroup("SR"), false);

/* ---------- trades: pair & whole-trade validity ---------- */
const pick = (id, slot) => ({ id, slot, player_name: id });
check("FR <-> SUB_FR valid", pairValid(pick("a", "FR"), pick("b", "SUB_FR")), true);
check("FR <-> SR invalid", pairValid(pick("a", "FR"), pick("b", "SR")), false);
check("TEAM never tradable", pairValid(pick("a", "TEAM"), pick("b", "TEAM")), false);
check("empty trade rejected", tradeError([]) !== null, true);
check("valid single pair", tradeError([{ mine: pick("a", "HB"), theirs: pick("b", "SUB_HB") }]), null);
check("mismatched pair rejected",
  tradeError([{ mine: pick("a", "CE"), theirs: pick("b", "B3") }]) !== null, true);
check("same pick twice rejected", tradeError([
  { mine: pick("a", "BR"), theirs: pick("b", "BR") },
  { mine: pick("a", "BR"), theirs: pick("c", "SUB_BR") },
]) !== null, true);

/* ---------- redraft phases: admin quota, kept players, eliminations ---------- */
S.league = { num_managers: 4, phase: 2,
  phase_quota: { FR: 1, SR: 1, BR: 1, HB: 1, CE: 1, B3: 1 },
  phase_starters: { FR: 1, SR: 1, BR: 1, HB: 1, CE: 1, B3: 1 } };
S.managers = [
  { id: "m1", name: "M1", draft_position: 1 },
  { id: "m2", name: "M2", draft_position: 2 },
  { id: "m3", name: "M3", draft_position: 3, eliminated: true, frozen_points: 42 },
];
S.picks = [];
check("phase 2 quota has no TEAM", posQuota().TEAM, 0);
check("picks per manager from phase quota", picksPerManager(), 6);
check("totalPicks counts active managers only", totalPicks(), 12);
check("kept player counts toward the quota",
  quotaLeft([{ position: "BR", kept: true }], "BR"), 0);
check("draft order skips eliminated managers",
  [pickInfo(1).manager.name, pickInfo(2).manager.name, pickInfo(3).manager.name],
  ["M1", "M2", "M2"]);

/* ---------- champion picks & frozen totals ---------- */
S.picks = []; S.stats = []; S.snapshots = [];
S.stages = [{ team: "France", stage: "winner" }];
S.managers = [
  { id: "m1", name: "M1", final_pick: "France" },
  { id: "m2", name: "M2", final_pick: "Ireland" },
  { id: "m3", name: "M3", eliminated: true, frozen_points: 42 },
];
const fin = computeScores();
check("correct champion pick +5", fin[0].total, 5);
check("wrong champion pick scores 0", fin[1].total, 0);
check("eliminated manager shows frozen points",
  [fin[2].total, fin[2].items.length], [42, 0]);
S.stages = [];

/* ---------- knocked-out teams & suspensions ---------- */
S.stages = [{ team: "Italy", stage: "pool", eliminated: true }];
check("eliminated team flagged", isEliminated("Italy"), true);
check("live team not flagged", isEliminated("Ireland"), false);
S.stages = [];
S.stats = [
  row({ player_id: "wal_7", match_label: "Wales vs Fiji (2026-07-04)", appeared: true, yellow_cards: 1 }),
  row({ player_id: "wal_7", match_label: "Wales vs Japan (2026-07-11)", appeared: true, red_cards: 1 }),
];
check("red card in latest game = suspended", suspendedNext("wal_7"), "red card");
S.stats = [row({ player_id: "wal_7", match_label: "Wales vs Fiji (2026-07-04)", appeared: true, yellow_cards: 1 })];
check("single yellow is not a ban (sin-bin only)", suspendedNext("wal_7"), null);

/* ---------- head-to-head log points & bonuses ---------- */
const H = { win: 4, draw: 2, loss: 0, attack_margin: 25, losing_margin: 7 };
check("big win = win + attack bonus", h2hResult(50, 10, H), { ptsA: 4, ptsB: 0, bonusA: 1, bonusB: 0 });
check("narrow win = win + losing bonus to loser", h2hResult(20, 15, H), { ptsA: 4, ptsB: 0, bonusA: 0, bonusB: 1 });
check("draw = draw both, no bonus", h2hResult(20, 20, H), { ptsA: 2, ptsB: 2, bonusA: 0, bonusB: 0 });
check("attack margin is inclusive", h2hResult(25, 0, H).bonusA, 1);
check("losing margin is inclusive", h2hResult(7, 0, H).bonusB, 1);
check("away big win mirrors", h2hResult(10, 50, H), { ptsA: 0, ptsB: 4, bonusA: 0, bonusB: 1 });

/* ---------- round-robin schedule ---------- */
const rr4 = roundRobin(["a", "b", "c", "d"]);
check("4 managers -> 3 rounds", rr4.length, 3);
const allPairs = rr4.flat().map((p) => p.slice().sort().join("-")).sort();
check("every pair meets exactly once", allPairs, ["a-b", "a-c", "a-d", "b-c", "b-d", "c-d"]);
const rr3 = roundRobin(["a", "b", "c"]);
check("odd count -> 3 rounds with byes", rr3.length, 3);
check("odd count gives each a bye", rr3.flat().filter((p) => p.includes(null)).length, 3);

/* ---------- H2H standings tabulation + ordering ---------- */
const h2hFx = [{ round: 1, home: "a", away: "b" }, { round: 2, home: "a", away: "b" }];
const tbl = h2hTable(["a", "b"],
  { a: [50, 10], b: [10, 20] }, h2hFx, H);
check("standings sorted by log points", tbl[0].mgrId, "a");
check("leader log points (win+attack, then loss)", tbl[0].logPts, 5);
check("leader has 1 bonus, 1W 1L", [tbl[0].bonus, tbl[0].W, tbl[0].L], [1, 1, 1]);
check("loser log points (win then loss)", tbl[1].logPts, 4);
check("tiebreak by points difference", h2hTable(["a", "b"],
  { a: [30, 10], b: [10, 20] }, h2hFx, H)[0].mgrId, "a");  // both 4 log pts, a diff +10
check("unplayed round is skipped", h2hTable(["a", "b"],
  { a: [30], b: [10] }, h2hFx, H)[0].P, 1);

/* ---------- free-agent waiver resolution ---------- */
const claim = (id, mgr, pid, t) => ({ id, manager_id: mgr, in_player_id: pid, created_at: t });
const uncontested = resolveFaClaims([claim("c1", "m1", "p1", "t1")], { m1: 0, m2: 1 }, []);
check("uncontested: claim awarded", uncontested.awards.map((a) => a.id), ["c1"]);
check("uncontested: priority unchanged", uncontested.order.m1, 0);
const contested = resolveFaClaims(
  [claim("c1", "m1", "p1", "t1"), claim("c2", "m2", "p1", "t2")], { m1: 1, m2: 0 }, []);
check("contested: lowest order wins", contested.awards.map((a) => a.id), ["c2"]);
check("contested: other claim fails", contested.failed, ["c1"]);
check("contested winner drops to bottom", contested.order.m2, 2);
const taken = resolveFaClaims([claim("c1", "m1", "p1", "t1")], { m1: 0 }, ["p1"]);
check("already-rostered player: claim fails", [taken.awards.length, taken.failed], [0, ["c1"]]);

console.log(fails ? `\n${fails} check(s) FAILED` : "\nAll checks passed");
process.exit(fails ? 1 : 0);
