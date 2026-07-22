# Mechanics notes — waiver trading, H2H log, bonus points

A detailed description of how three subsystems currently work in the app
(`index.html`), written so they can be re-implemented elsewhere. All logic is
pure JavaScript in the single-file frontend; the pure cores (`resolveFaClaims`,
`h2hTable`, `h2hResult`) are unit-tested in `test_logic.js`.

Vocabulary: a **manager** is a fantasy team owner; a **pick** is one roster slot
holding one real player; a **round** is a scoring period; **PF/PA** = points
for / against (fantasy points).

---

## 1. Trading based on waiver order

### 1.1 Data model

`leagues` row (per-league config + window state):

| column | meaning |
|---|---|
| `trading_open` (bool) | is the trade window currently open |
| `window_opened_at` (timestamptz) | when the current window opened (set on open) |
| `fa_defer_to_close` (bool, default **true**) | free agents execute at window close via waiver order (true) vs. instantly (false) |
| `max_fa_per_window` (int, nullable) | cap on **successful** free-agent claims per manager per window; `null` = unlimited |
| `max_trades_per_window` (int, nullable) | analogous cap for manager-to-manager trades |

`managers.waiver_order` (int, nullable): **lower = higher priority = picks
first.** `null` until seeded. `0` is the top priority.

`fa_claims` table (one row per queued claim):

| column | meaning |
|---|---|
| `id` | claim id |
| `league_id`, `manager_id` | owners |
| `pick_id` | the roster slot to fill (the out-player's slot) |
| `rank` (int) | the manager's **own** preference order, ascending (0 first) |
| `out_player_id`, `out_player_name` | player being dropped from that pick |
| `in_player_id`, `in_player_name` | free agent being claimed |
| `status` | `pending` → `awarded` \| `failed` |

`picks`: each has `player_id` (currently held). A swap/award updates
`player_id`/`player_name`/`team`.

### 1.2 Two modes

`swapOrClaim()` branches on `fa_defer_to_close`:

- **Instant** (`false`): `doSwap()` updates the pick immediately. The update is
  guarded with `.eq("player_id", pick.player_id)` (optimistic concurrency): if
  the row no longer holds that player the update matches nothing, and a Postgres
  `23505` unique-violation means the incoming player was just taken. Logs a
  `swap` transaction.
- **Deferred / waiver** (`true`, the default): `submitFaClaim()` appends a row to
  `fa_claims` with `rank = max(existing pending ranks) + 1`. Managers build an
  **ordered preference list**; `reorderClaim()` swaps a claim's `rank` with its
  neighbour. Nothing is applied until the window closes.

### 1.3 Window open / close (`toggleTrading`, admin only)

- **Open**: set `trading_open = true`, `window_opened_at = now`.
- **Close**: **run `processFaClaims()` first**, then set `trading_open = false`.
  So all queued claims resolve at the moment of closing.

### 1.4 Waiver order seeding & reset

- `resetWaiverOrder()`: `worstFirst = standingsOrder().reverse()`, then assign
  `waiver_order = 0,1,2,…` down that list (worst-placed manager gets `0` = first
  pick). Called at **each round close** (`toggleLineupLock` when ending a round).
- `standingsOrder()`: if H2H is enabled and fixtures exist → H2H standings order
  (see §2); otherwise total-points descending.
- `processFaClaims()` also **seeds any still-unseeded manager** from reverse
  standings, appended after the stored orders, so everyone has a priority.

### 1.5 Resolution at close (`processFaClaims`)

Gathers:
- `pending` = `fa_claims` with `status = 'pending'`.
- `order` = each manager's stored `waiver_order`, plus unseeded managers appended
  by reverse standings.
- `taken` = every currently-rostered `player_id`.
- `pickHolds` = `{ pick_id → current player_id }`.
- `tradeLimit` = `max_fa_per_window || Infinity`.

Calls the pure `resolveFaClaims(claims, order, taken, tradeLimit, pickHolds)` →
`{ awards, failed, order }`, then:
- for each award, updates the `picks` row (guarded by `.eq("player_id",
  out_player_id)`), inserts a `waiver` transaction;
- marks `fa_claims` rows `awarded` / `failed`;
- writes back any changed `waiver_order`.

### 1.6 The core algorithm (`resolveFaClaims`) — pure

```
inputs: claims[], waiverOrder{mgr→order}, taken[], tradeLimit, pickHolds{pick→player}

order   = copy of waiverOrder
maxOrder= highest order value seen
rostered= set(taken)                       // player ids currently held
holds   = copy of pickHolds                // pick_id → player id (mutated as awards land)

byMgr   = claims grouped by manager, each list SORTED by (rank asc, created_at asc)
wanters = { in_player_id → set(managers who listed it) }
contested(pid) = wanters[pid].size > 1     // >1 distinct manager wants that player

ptr{}   = per-manager cursor into their list
count{} = per-manager number of SUCCESSFUL awards
done{}  = per-manager finished flag
prio(m) = order[m] (null/undefined → Infinity)
active()= managers not done

capOut(m):                                 // manager hit their cap → ignore the rest
    done[m] = true
    for each remaining claim c from ptr[m]..end:
        wanters[c.in_player_id].delete(m)  // ignored claim no longer contests anyone
        failed.push(c.id)
    ptr[m] = end

while active() not empty:
    m = active manager with smallest prio() (tie: manager id)   // highest priority first
    if count[m] >= tradeLimit: capOut(m); continue
    executed = null
    while ptr[m] < list length:
        c = list[ptr[m]]; ptr[m]++
        feasible = holds[c.pick_id] == c.out_player_id   // still holds the out-player
                   AND c.in_player_id not in rostered    // target still free
        if not feasible: failed.push(c.id); continue     // fallback → try next preference
        rostered.remove(c.out_player_id); rostered.add(c.in_player_id)
        holds[c.pick_id] = c.in_player_id
        count[m]++; awards.push(c); executed = c
        break
    if executed is null: done[m] = true; continue        // list exhausted, nothing landed
    if contested(executed.in_player_id):                 // CONTESTED WIN → yield
        maxOrder++; order[m] = maxOrder                  // drop winner to the bottom
    if count[m] >= tradeLimit: capOut(m)

any claim never reached → failed
return { awards, failed, order }
```

**Rules that matter (copy these exactly):**

1. **Priority**: managers are processed in ascending `waiver_order`; the top
   manager takes one claim, then priorities are re-evaluated and the loop repeats.
2. **One award per turn**: a manager executes at most the *first feasible* claim
   in their list per turn, then control returns to the priority queue.
3. **Fallback**: an infeasible claim (out-player no longer held, or target already
   taken) is skipped and marked `failed`, letting a lower-preference claim land.
4. **Cap = successful claims only**: `count` increments only on an award.
   Failures never count toward the cap.
5. **Contested win → drop to bottom**: if the player a manager just won was *also
   listed by another manager*, the winner's `order` is set past the current max
   (they yield to everyone for their remaining turns). An **uncontested** win keeps
   the manager's priority so they continue straight down their own list.
6. **Over-cap claims are ignored entirely**: once a manager reaches `tradeLimit`,
   every remaining claim of theirs is failed **and removed from `wanters`** — so
   an ignored claim can no longer make a player "contested" and cannot knock
   another manager down the waiver order. (This is the only interaction between the
   cap and the contested rule; the contested rule itself — "another manager also
   listed that player" — is unchanged.)

**Worked example** (cap = 1): M1 (order 0) lists [P1, then P2]; M2 (order 1) lists
[P2]. M1 wins P1 (only M1 wanted it → uncontested, keeps order 0) and hits the cap;
its P2 claim is ignored and removed from P2's wanters. M2 then wins P2 as an
**uncontested** win (M1's ignored claim no longer counts) and keeps order 1.

---

## 2. H2H log (the standings table)

### 2.1 Inputs

- `h2h_fixtures` table: `round` (1-based), `home_manager_id`, `away_manager_id`
  (`away = null` means a **bye**). Generated round-robin (circle method,
  `roundRobin()`), cycled across the tournament.
- **Per-manager round scores**: `h2hRoundScores()` builds
  `scoresByMgr[mgrId] = [round0Subtotal, round1Subtotal, …]`, where each subtotal is
  that manager's fantasy-point total for that round's starting lineup
  (`managerHistory(mgrId).rounds[].subtotal`). `maxRound` = the furthest round any
  manager has a score for.
- **Config** `h2hConfig()` (all league-overridable):
  `win = 4`, `draw = 2`, `loss = 0`, `score_bonus = 450`, `losing_margin = 50`.

### 2.2 Tabulation (`h2hTable(mgrIds, scoresByMgr, fixtures, cfg)`) — pure

Per manager accumulate `{ P, W, D, L, PF, PA, bonus, logPts, byes }`. For each
fixture:

- **Bye** (exactly one side present): if that manager already has a score for the
  round, `byes++`. A bye scores **nothing** (no P, no log points).
- **Both sides**: read `sa`, `sb` = the two managers' scores for that round
  (`scoresByMgr[x][round-1]`). **If either is `undefined`, skip** — a round only
  counts once *both* managers have a score for it.
  - `P++` for both; `PF += own score`, `PA += opponent score`.
  - `W/D/L` from comparing `sa` vs `sb`.
  - `bonus += ` the bonuses from `h2hResult` (see §3).
  - `logPts += ` result points (`win`/`draw`/`loss`) **plus** those bonuses.

### 2.3 Ordering (the actual "log" order)

Sort descending by, in order:

1. **`logPts`** (log points).
2. **Head-to-head result between the tied pair** — sum each manager's scores across
   the round(s) they actually played each other; the one with more ranks higher.
   Returns 0 (→ no effect) if they **never met** or their meetings were **level**.
3. **`PF`** (points for) — used when the pair never met or drew head-to-head.

```
sort(x, y):
    if x.logPts != y.logPts:  return y.logPts - x.logPts       // more log points first
    h = sum of x's scores − sum of y's scores in rounds they met (0 if none/level)
    if h != 0:                return -h                          // head-to-head winner first
    return y.PF - x.PF                                           // else points-for
```

(Head-to-head is a pairwise tiebreak, so with three+ managers mutually tied on log
points and beating each other cyclically the order among them can depend on
comparison order — inherent to head-to-head, not a bug. Two-way ties always resolve
cleanly.)

`h2hStandings()` wraps `h2hTable` with active managers + display names.
`standingsOrder()` returns this order when H2H is enabled (else total-points desc),
and it is what seeds the reverse waiver order in §1.4. Movement arrows compare the
current `h2hTable` order against the order computed without the latest round.

---

## 3. Bonus points

These are the **H2H log bonuses** (rugby-style), computed per matchup in
`h2hResult(a, b, cfg)` where `a`, `b` are the two managers' round scores. They are
**independent of the win/draw/loss points** and are added on top of them into
`logPts`.

Two bonuses, each worth **+1**, evaluated per manager per matchup:

1. **Attacking / score bonus** — awarded if a manager's own round score
   `>= score_bonus` (default **450**). Earned **whether they win or lose**.
2. **Losing bonus** — awarded if a manager **loses by `<= losing_margin`** (default
   **50**). Only the losing side can earn it.

A single matchup can therefore bank **0, 1, or 2** bonus points for a manager. E.g.
a manager who scores 470 but loses by 30 earns both (attacking + losing = +2);
their opponent who scored 500 earns the attacking bonus (+1) plus the win points.

```
h2hResult(a, b, cfg):                       // a, b = the two round scores
    if a > b:  ptsA = win;  ptsB = loss
    elif b > a: ptsB = win; ptsA = loss
    else:      ptsA = ptsB = draw
    if a >= score_bonus:            bonusA += 1     // attacking (either result)
    if b >= score_bonus:            bonusB += 1
    if a < b and (b - a) <= losing_margin: bonusA += 1   // losing bonus
    if b < a and (a - b) <= losing_margin: bonusB += 1
    return { ptsA, ptsB, bonusA, bonusB }

// matchup log points for a manager = result points + their bonuses
logPts += ptsA + bonusA        // (and ptsB + bonusB for the other manager)
```

Defaults `win 4 / draw 2 / loss 0 / score_bonus 450 / losing_margin 50` are stored
on the `leagues` row and admin-editable, so the same code drives any point/threshold
scheme.

> Not to be confused with the **per-player scoring system** (tries, metres, tackles,
> …), which is a separate module (`SCORING` table / `calcPlayerPoints`) that produces
> the per-round *player* points that get summed into each manager's round subtotal —
> the `scoresByMgr` input to §2. The "bonus points" here are strictly the H2H log
> bonuses above.
