// Smoke tests for the rugby draft + scoring logic in index.html.
//   node test_logic.js
// Boots the app's <script> in a stubbed DOM and exercises the pure functions
// (draft order, position quotas, role scoring, sub activation, trades, H2H
// log points, waivers). Scoring parity with daily_pull.py is the key
// invariant — keep SCORING in the two files identical.
const fs = require("fs");
const src = fs.readFileSync("index.html", "utf8")
  .match(/<script>\n("use strict";[\s\S]*)<\/script>/)[1];

const stubDoc = { getElementById: () => null, querySelectorAll: () => [],
  querySelector: () => null, addEventListener: () => {} };
const winStub = { scrollTo: () => {} };
const _session = JSON.stringify({ leagueId: "L1", managerId: "m1" });
const lsStub = { getItem: (k) => k === "wcf_session" ? _session : null,
                 setItem: () => {}, removeItem: () => {} };
const api = new Function(
  "document", "localStorage", "window", "crypto", "navigator",
  src + "\nreturn { S, pickInfo, calcPlayerPoints, computeScores, slotGroup, pairValid, tradeError, quotaLeft, slotForNewPick, posQuota, picksPerManager, totalPicks, playerBreakdown, playerPoints, playerStatTotal, h2hResult, roundRobin, h2hTable, resolveFaClaims };"
)(stubDoc, lsStub, winStub, {}, {});

const { S, pickInfo, calcPlayerPoints, computeScores, slotGroup, pairValid,
        tradeError, quotaLeft, slotForNewPick, posQuota, picksPerManager,
        totalPicks, playerBreakdown, playerPoints,
        playerStatTotal, h2hResult, roundRobin, h2hTable, resolveFaClaims } = api;

let fails = 0;
const check = (label, got, want) => {
  const ok = JSON.stringify(got) === JSON.stringify(want);
  if (!ok) { fails++; console.log(`FAIL ${label}: got ${JSON.stringify(got)}, want ${JSON.stringify(want)}`); }
  else console.log(`ok   ${label}`);
};

/* ---------- snake draft order ---------- */
S.managers = [1, 2, 3, 4].map((i) => ({ id: "m" + i, name: "M" + i, draft_position: i }));
S.league = { num_managers: 4 };
check("pick 1 -> M1", pickInfo(1).manager.name, "M1");
check("pick 5 -> M4 (snake)", pickInfo(5).manager.name, "M4");
check("pick 9 -> M1 (snake back)", pickInfo(9).manager.name, "M1");

/* ---------- 23-man squad on the 8 positions ---------- */
check("quota sums to 23", Object.values(posQuota()).reduce((a, b) => a + b, 0), 23);
check("picks per manager = 23", picksPerManager(), 23);
const roster = [];
const draftOne = (pos) => {
  const slot = slotForNewPick(roster, pos);
  roster.push({ position: pos, slot });
  return slot;
};
check("PR 1-2 start, 3rd is sub", [draftOne("PR"), draftOne("PR"), draftOne("PR")], ["PR", "PR", "SUB_PR"]);
check("HK 1 starter then sub", [draftOne("HK"), draftOne("HK")], ["HK", "SUB_HK"]);
check("PR quota (3) left = 1 after 3", quotaLeft(roster, "PR"), 0);
check("OB quota untouched = 4", quotaLeft(roster, "OB"), 4);

/* ---------- scoring (role-based; mirrors calculate_points) ---------- */
const row = (o) => ({
  appeared: true, minutes: 80, tries: 0, metres: 0, runs: 0, defenders_beaten: 0,
  clean_breaks: 0, passes: 0, offloads: 0, turnovers_conceded: 0, try_assists: 0,
  tackles: 0, missed_tackles: 0, turnovers_won: 0, conversions: 0,
  conversions_missed: 0, penalties: 0, penalties_missed: 0, drop_goals: 0,
  drop_goals_missed: 0, lineout_throws_won: 0, lineouts_taken: 0, lineout_steals: 0,
  penalties_conceded: 0, red_cards: 0, yellow_cards: 0, scrums_won: 0,
  scrums_lost: 0, lineouts_lost: 0, ...o });
const cp = (o, role) => calcPlayerPoints(row(o), role);   // includes +2 minutes

check("minutes 60+ = 2", cp({}, "OB"), 2);
check("prop try = 15", cp({ tries: 1 }, "PR"), 2 + 15);
check("centre try = 10", cp({ tries: 1 }, "CE"), 2 + 10);
check("prop metres 1/5m", cp({ metres: 5 }, "PR"), 2 + 1);
check("back metres 1/10m", cp({ metres: 25 }, "OB"), 2 + 2);
check("prop tackle x2", cp({ tackles: 3 }, "PR"), 2 + 6);
check("SH passes 1/5", cp({ passes: 10 }, "SH"), 2 + 2);
check("prop scrums won 1.5", cp({ scrums_won: 2 }, "PR"), 2 + 3);
check("red card", cp({ red_cards: 1 }, "PR"), 2 - 20);
check("0 minutes scores 0", cp({ minutes: 0, tries: 3 }, "OB"), 0);

/* ---------- breakdown sums to player total ---------- */
S.stats = [
  row({ player_id: "eng_5", match_label: "England vs Fiji (2026-07-04)", tries: 1, tackles: 3 }),
];
check("breakdown sums to playerPoints", playerBreakdown("eng_5", "PR").reduce((s, r) => s + r.pts, 0),
  playerPoints("eng_5", "PR"));
check("season stat total (raw)", playerStatTotal("eng_5", "tackles"), 3);

/* ---------- sub activation covers a no-show starter, by round ---------- */
S.fixtures = []; S.snapshots = []; S.stages = [];
S.managers = [{ id: "m1", name: "M1", draft_position: 1 }];
S.league = { num_managers: 1 };
S.picks = [
  { manager_id: "m1", player_id: "fra_5", player_name: "Starter PR", position: "PR", team: "France", slot: "PR", is_sub: false, pick_number: 1 },
  { manager_id: "m1", player_id: "arg_3", player_name: "Sub PR", position: "PR", team: "Argentina", slot: "SUB_PR", is_sub: true, pick_number: 12 },
];
S.stats = [
  row({ player_id: "fra_9", match_label: "France vs New Zealand (2026-07-04)", appeared: true }),
  row({ player_id: "arg_3", match_label: "Argentina vs Italy (2026-07-04)", appeared: true, tries: 1 }),
  row({ player_id: "fra_5", match_label: "France vs South Africa (2026-07-11)", appeared: true, tackles: 3 }),
  row({ player_id: "arg_3", match_label: "Argentina vs Wales (2026-07-11)", appeared: true, tries: 1 }),
];
const sc = computeScores()[0];
check("starter R2 (2 min + 3 tackles x2)", sc.items.find((i) => !i.pick.is_sub).pts, 2 + 6);
check("sub active only R1 (2 min + try 15)",
  [sc.items.find((i) => i.pick.is_sub).pts, sc.items.find((i) => i.pick.is_sub).note], [2 + 15, "sub"]);
check("manager total", sc.total, 8 + 17);

/* ---------- trades: slot groups + validity (8 positions) ---------- */
check("SUB_PR and PR same group", slotGroup("SUB_PR"), slotGroup("PR"));
check("SUB_OB group is OB", slotGroup("SUB_OB"), "OB");
check("PR and HK differ", slotGroup("PR") === slotGroup("HK"), false);
const pick = (id, slot) => ({ id, slot, player_name: id });
check("PR <-> SUB_PR valid", pairValid(pick("a", "PR"), pick("b", "SUB_PR")), true);
check("PR <-> HK invalid", pairValid(pick("a", "PR"), pick("b", "HK")), false);
check("empty trade rejected", tradeError([]) !== null, true);
check("valid single pair", tradeError([{ mine: pick("a", "FH"), theirs: pick("b", "SUB_FH") }]), null);
check("mismatched pair rejected",
  tradeError([{ mine: pick("a", "CE"), theirs: pick("b", "OB") }]) !== null, true);

/* ---------- H2H: log points + independent bonuses ---------- */
const H = { win: 4, draw: 2, loss: 0, score_bonus: 450, losing_margin: 50 };
check("win, no bonus", h2hResult(300, 200, H), { ptsA: 4, ptsB: 0, bonusA: 0, bonusB: 0 });
check("win + score bonus (>=450)", h2hResult(460, 200, H), { ptsA: 4, ptsB: 0, bonusA: 1, bonusB: 0 });
check("loss but score bonus still earned", h2hResult(500, 600, H), { ptsA: 0, ptsB: 4, bonusA: 1, bonusB: 1 });
check("narrow loss = losing bonus", h2hResult(200, 240, H), { ptsA: 0, ptsB: 4, bonusA: 1, bonusB: 0 });
check("both bonuses possible", h2hResult(455, 470, H), { ptsA: 0, ptsB: 4, bonusA: 2, bonusB: 1 });
check("draw pays draw, no bonus", h2hResult(200, 200, H), { ptsA: 2, ptsB: 2, bonusA: 0, bonusB: 0 });

/* ---------- round-robin schedule ---------- */
const rr4 = roundRobin(["a", "b", "c", "d"]);
check("4 managers -> 3 rounds", rr4.length, 3);
check("every pair meets once", rr4.flat().map((p) => p.slice().sort().join("-")).sort(),
  ["a-b", "a-c", "a-d", "b-c", "b-d", "c-d"]);
check("odd count gives byes", roundRobin(["a", "b", "c"]).flat().filter((p) => p.includes(null)).length, 3);

/* ---------- H2H standings tabulation ---------- */
const h2hFx = [{ round: 1, home: "a", away: "b" }, { round: 2, home: "a", away: "b" }];
const tbl = h2hTable(["a", "b"], { a: [460, 100], b: [100, 200] }, h2hFx, H);
check("leader by log points", tbl[0].mgrId, "a");
check("leader logPts (win+bonus, then loss)", tbl[0].logPts, 5);   // R1 win+score bonus, R2 loss
check("leader record 1W 1L", [tbl[0].W, tbl[0].L], [1, 1]);
check("no byes when both play", [tbl[0].P, tbl[0].byes], [2, 0]);

// Odd manager count -> one bye per round. R1: a plays b, c has a bye. R2: a
// plays c, b has a bye. Each played manager counts P; the bye counts once the
// round is reached (a score exists), and never awards points.
const oddFx = [
  { round: 1, home: "a", away: "b" }, { round: 1, home: "c", away: null },
  { round: 2, home: "a", away: "c" }, { round: 2, home: "b", away: null },
];
const oddTbl = h2hTable(["a", "b", "c"], { a: [100, 100], b: [50, 50], c: [70, 40] }, oddFx, H);
const byId = (id) => oddTbl.find((r) => r.mgrId === id);
check("bye manager has fewer played games", [byId("c").P, byId("a").P], [1, 2]);
check("bye is counted and scoreless", [byId("c").byes, byId("b").byes], [1, 1]);
check("bye awards no log points", byId("c").logPts, byId("c").W * H.win);

// Tiebreak: equal log points -> head-to-head result between the tied pair.
// a & b both finish on 8 log points; a beat b when they met (R1) -> a ranks
// above b even though b has the higher points-for.
const tieFx = [
  { round: 1, home: "a", away: "b" },
  { round: 2, home: "a", away: "c" }, { round: 2, home: "b", away: "d" },
  { round: 3, home: "a", away: "d" }, { round: 3, home: "b", away: "c" },
];
const tieTbl = h2hTable(["a", "b", "c", "d"],
  { a: [300, 200, 200], b: [200, 300, 300], c: [0, 200, 200], d: [0, 200, 200] },
  tieFx, H);
check("tied log points: head-to-head winner ranks first",
  [tieTbl[0].mgrId, tieTbl[1].mgrId], ["a", "b"]);
check("tied pair really are level on log points", tieTbl[0].logPts, tieTbl[1].logPts);

// Tiebreak fallback: equal log points but the pair never met -> points-for.
const pfFx = [{ round: 1, home: "a", away: "c" }, { round: 1, home: "b", away: "d" }];
const pfTbl = h2hTable(["a", "b", "c", "d"],
  { a: [300], b: [250], c: [100], d: [100] }, pfFx, H);
check("tied log points, never met: higher points-for ranks first",
  [pfTbl[0].mgrId, pfTbl[1].mgrId], ["a", "b"]);

/* ---------- free-agent waivers (ordered preference lists) ---------- */
// claim(id, mgr, in, pick, out, rank, t): trade OUT `out` (held by `pick`) for
// free-agent `in`, ranked `rank` in the manager's preference list.
const claim = (id, mgr, pin, pick, pout, rank, t) =>
  ({ id, manager_id: mgr, in_player_id: pin, pick_id: pick, out_player_id: pout, rank, created_at: t });

// Uncontested pickup: awarded, priority unchanged.
const unc = resolveFaClaims([claim("c1", "m1", "p1", "pk1", "o1", 0, "t1")],
  { m1: 0, m2: 1 }, [], Infinity, { pk1: "o1" });
check("uncontested awarded, order unchanged", [unc.awards.map((a) => a.id), unc.order.m1], [["c1"], 0]);

// Contested: two managers list the same player — higher priority wins, loser
// fails, and the winner drops to the bottom of the waiver order.
const con = resolveFaClaims([
  claim("c1", "m1", "p1", "pk1", "o1", 0, "t1"),
  claim("c2", "m2", "p1", "pk2", "o2", 0, "t2"),
], { m1: 1, m2: 0 }, [], Infinity, { pk1: "o1", pk2: "o2" });
check("contested: lowest order wins", con.awards.map((a) => a.id), ["c2"]);
check("contested loser fails", con.failed, ["c1"]);
check("contested winner drops to bottom", con.order.m2, 2);

// Fallback: m1's #1 (p1) is taken by higher-priority m2, so m1 falls through to
// its #2 (p2, same slot/out-player), which is uncontested and awarded.
const fb = resolveFaClaims([
  claim("cx", "m2", "p1", "pkx", "ox", 0, "t0"),
  claim("c1", "m1", "p1", "pk1", "o1", 0, "t1"),
  claim("c2", "m1", "p2", "pk1", "o1", 1, "t2"),
], { m1: 1, m2: 0 }, [], Infinity, { pkx: "ox", pk1: "o1" });
check("fallback: m2 wins p1, m1 falls to p2", fb.awards.map((a) => a.id).sort(), ["c2", "cx"]);
check("fallback: m1's #1 fails", fb.failed, ["c1"]);
check("uncontested winner (m1) keeps priority", fb.order.m1, 1);

// Trade limit caps how many of a manager's claims execute (not how many listed).
const lim = resolveFaClaims([
  claim("c1", "m1", "p1", "pk1", "o1", 0, "t1"),
  claim("c2", "m1", "p2", "pk2", "o2", 1, "t2"),
  claim("c3", "m1", "p3", "pk3", "o3", 2, "t3"),
], { m1: 0 }, [], 2, { pk1: "o1", pk2: "o2", pk3: "o3" });
check("trade limit: only first two execute", lim.awards.map((a) => a.id), ["c1", "c2"]);
check("trade limit: rest fail", lim.failed, ["c3"]);

// Once a manager hits their cap, their remaining claims are IGNORED — they must
// not count as a competing claim on a player. m1 (cap 1) takes p1, so its p2
// claim is ignored; m2 then wins p2 uncontested and keeps its waiver priority.
const capd = resolveFaClaims([
  claim("c1", "m1", "p1", "pk1", "o1", 0, "t1"),
  claim("c2", "m1", "p2", "pk2", "o2", 1, "t2"),
  claim("c3", "m2", "p2", "pk3", "o3", 0, "t3"),
], { m1: 0, m2: 1 }, [], 1, { pk1: "o1", pk2: "o2", pk3: "o3" });
check("capped: only in-cap claims execute", capd.awards.map((a) => a.id).sort(), ["c1", "c3"]);
check("capped: over-cap claim fails", capd.failed, ["c2"]);
check("capped: ignored claim doesn't contest (winner keeps priority)", capd.order.m2, 1);

check("already-rostered player fails",
  resolveFaClaims([claim("c1", "m1", "p1", "pk1", "o1", 0, "t1")], { m1: 0 }, ["p1"], Infinity, { pk1: "o1" }).failed, ["c1"]);
check("stale out-player (no longer held) fails",
  resolveFaClaims([claim("c1", "m1", "p1", "pk1", "o1", 0, "t1")], { m1: 0 }, [], Infinity, { pk1: "SOMEONE_ELSE" }).failed, ["c1"]);

console.log(fails ? `\n${fails} check(s) FAILED` : "\nAll checks passed");
process.exit(fails ? 1 : 0);
