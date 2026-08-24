# habitrack — Design Spec

Date: 2026-08-24 (Day 1 of live operation)
Status: v3 — revised after second review. Pre-implementation. The app
already runs locally in an earlier form; this spec describes the target
state to implement next.

## 1. Purpose

A single-user, personal daily-habit tracker. The owner checks off each habit
("item") once per day with one tap, from phone or laptop. The overriding goal
is **habit formation support for the owner's life** — not building a product.

**Simplicity is the top design constraint.** The app must stay small enough
that maintaining it never competes with the habits it tracks. UI polish is
explicitly deferred until real daily friction demands it.

### Non-goals (deliberately excluded)

- Charts, monthly stats, best-streak history, icons, reminders, habit types
- Multi-user support, accounts, sign-up
- PWA / native app (a home-screen shortcut to the URL is enough)
- Any JS framework; no client-side state at all
- Add/delete-item UI (deferred — see §5)
- Git-committed data, automated backups, "GitHub grass" side effects
  (dropped — see §3)

## 2. Current state

- `app.py` (~170 lines): FastHTML + pandas + htmx. Works locally; owner
  started daily use today (ledger.csv already has live data).
- Current code still reads the item list from `items.txt` — this spec
  removes that (see §3).
- Not yet a proper git repo setup; not yet deployed.

## 3. Data model — single source of truth

One CSV file, `ledger.csv`:

```
,読書,運動,執筆,瞑想,早起き
2026-08-23,True,False,True,False,False
2026-08-24,True,True,False,False,False
```

- Index: ISO date. Columns: item names (may be Japanese/UTF-8). Values: bool.
- **Empty cells are read as False.** Hand-editing the header (adding an
  item, §5) leaves past rows blank for the new column; the reader must
  `fillna(False)` before the bool cast — otherwise pandas turns NaN into
  True and a new item appears fully checked for its entire history.
- **The CSV header row IS the item list.** `items.txt` is abolished — it
  duplicated the column set and created a footgun (removing a line from
  items.txt silently dropped that column's history on the next write).
- Full history is kept on disk forever; the UI shows a rolling window.
- In memory: a pandas DataFrame loaded per request; every checkbox toggle
  does read-modify-write of the CSV. No caching, no DB. Single user, so no
  cross-process locking — but every save is an **atomic write** (write to a
  temp file in the same directory, then `os.replace`). This is not about
  backup; it prevents a mid-write crash from corrupting the live file.
- First run with no CSV: auto-create with a default item set.

### Data lifecycle policy

`ledger.csv` is **runtime state, not versioned data**:

- NOT committed to git; `.gitignore`d.
- No automated backup. "Survive box rebuilds" is explicitly not a
  requirement: before a planned rebuild the owner copies the file off
  manually and restores it after. To remove the "forgot the copy" failure
  mode, these two steps are part of the existing hetzner-rebuild procedure
  (pre-rebuild checklist: fetch `data/ledger.csv`; post-rebuild: restore
  it) — no separate machinery.
- Rationale: the goal is habit formation, not log stewardship. Managing a
  private log inside git history (and the earlier idea of harvesting a
  GitHub contribution graph from it) adds complexity that serves the
  tooling, not the habit.

### Data placement vs static serving

`fast_app()`'s default static route serves files from `static_path="."`
for a long extension whitelist that **includes `.csv` and `.txt`**, and the
route pattern (`{fname:path}.{ext:static}`) reaches into subdirectories.
Verified against the installed fasthtml source. Therefore:

- Pass an explicit `static_path` pointing at a dedicated assets directory
  (e.g. `static/`, currently empty — the app has no static assets).
- Keep `ledger.csv` in a separate data directory (e.g. `data/`) that the
  static route cannot reach.
- Auth (§6) guards routes as defense in depth, but data must not depend on
  it: the static route must simply be unable to serve the ledger.

## 4. UI

Single page, monospace, minimal:

1. **Title**
2. **The table** — one row per item, one column per day, **last 10 days
   only**, today highlighted. Cells are real `<input type="checkbox">`.
   Each row shows a current-streak badge next to the item name.

That is the entire daily screen: checkboxes only.

Interaction: checkbox click → htmx POST `/toggle/{item}/{date}` → server
flips the DataFrame cell → saves CSV (atomic) → returns the re-rendered
table fragment (outerHTML swap). No page reloads, no client state.
Checkboxes carry `hx_disabled_elt="this"` so a double-click cannot fire
two toggles that cancel each other out.

## 5. Item add / delete

**No UI. Deferred.** It contradicts the founding decision ("items come from
a file; the daily screen is checkboxes only") and is a setup-time operation,
not a daily one.

- Adding, removing, or renaming an item = edit the `ledger.csv` header row
  directly (locally, or via ssh on the box). The server re-reads the CSV
  per request, so changes appear without restart.
- **Name constraints** (a violation corrupts data or breaks routing, so
  manual edits must respect them): no `,` `"` or newlines (CSV parsing),
  no `/` (toggle URL path), no empty or duplicate names.
- Since data is no longer in git, deleting a column is genuinely
  destructive — acceptable for a rarely-performed manual edit; the manual
  pre-rebuild copy (§3) is the safety net.
- A toggle during a hand-edit silently overwrites the edit (the toggle's
  read-modify-write starts from a stale read). Edit the file only when not
  actively using the app.
- Revisit only if editing the file proves to be real recurring friction.

## 6. Auth

**FastHTML session auth** (self-contained login):

- One shared password, supplied via environment variable (never in code or
  repo).
- A login page sets a session cookie; FastHTML Beforeware guards every
  route (skip list: `/login` only).
- **Two secrets, managed separately:** the login password AND the session
  cookie signing key (`secret_key`). The signing key must be provisioned as
  a managed secret (env var), not left to FastHTML's default behavior of
  auto-generating a `.sesskey` file in the app directory.
- `sess_https_only=True` in production, gated on an env var (e.g. set by
  the systemd unit) — the cookie is only ever sent over HTTPS (Caddy
  terminates TLS). Note for local dev: Chrome/Firefox treat
  http://localhost as a trustworthy origin and accept Secure cookies, so
  the flag would mostly work there too — but a client that rejects them
  (e.g. curl, older Safari) gets a login loop, never a "re-login once";
  the env gate keeps local dev client-agnostic.
- Failed login attempts sleep ~0.5s (or Caddy rate-limits `/login`);
  enough to make brute force impractical, nothing more.
- The app process binds to **loopback only** (`127.0.0.1`); the sole
  public path is Caddy's reverse proxy. Nobody can bypass TLS/proxy by
  hitting the app port directly.
- Login happens once per browser; daily friction is zero.
- Rationale vs alternatives: OAuth is overkill for one user; Caddy basic
  auth would move the protection into deploy config — the owner prefers the
  app to protect itself so behavior is identical everywhere.

## 7. Time zone

"Today" is computed **explicitly in code** as
`datetime.now(ZoneInfo("Europe/Helsinki")).date()` — stdlib `zoneinfo`, no
new dependency. Setting `TZ=Europe/Helsinki` on the service is auxiliary
hygiene, not the mechanism: correctness must not depend on deploy-time
environment (the box is UTC; an evening check-in must not land on the
wrong day).

## 8. Deployment

- Target: the owner's Hetzner box, via the **boxrecipe** (hetznerinit)
  composition — a systemd service + Caddy reverse-proxy entry, so the app
  survives box rebuilds. (`ledger.csv` does NOT survive rebuilds by
  design; see §3 for the manual copy procedure.)
- Public URL: **https://habitrack.ninjalabo.ai** (wildcard DNS exists).
- App listens on 127.0.0.1 only; Caddy proxies and terminates TLS (§6).
- Runtime: Python venv, `pip install -r requirements.txt`
  (`python-fasthtml`, `pandas` — no other dependencies allowed without
  explicit approval).

## 9. Known issues / accepted risks

| Item | Decision |
|---|---|
| Streak currently caps at 10 (computed from the 10-day display window, not full history) | Bug — fix in this iteration: compute streak from full CSV history. Semantics: if today is unchecked, the streak starts from yesterday |
| No cross-process file locking on the CSV | Accepted: single user, single process; atomic replace prevents corruption |
| Data loss if the box dies between manual copies | Accepted explicitly: not a requirement to prevent |
| Item name appears in URL path (UTF-8, URL-encoded) | Accepted: verified working; revisit only if it breaks |
| Whole-table re-render per toggle | Accepted: table is tiny; simplicity wins |
| Item management requires editing a CSV by hand | Accepted: setup-time operation; revisit on real friction |

## 10. Implementation plan (small PRs, ≤200 lines each)

0. **Migration prerequisite:** `/minit habitrack` cannot run against the
   existing non-empty directory. Procedure: move the prototype aside
   (e.g. `mv ~/habitrack ~/habitrack.proto`), run `/minit habitrack`, then
   bring `app.py` etc. back in and put the live `ledger.csv` into `data/`
   (gitignored). Nothing from the prototype is lost.
1. Repo hygiene: `.gitignore` (`.venv/`, `__pycache__/`, `.sesskey`,
   `data/`), commit code only.
2. Rewrite to ledger.csv-only (drop `items.txt`), move data to `data/`,
   point `static_path` at a dedicated `static/` dir, atomic CSV writes,
   explicit `ZoneInfo("Europe/Helsinki")`, fix streak-window bug.
3. Session auth: login page + Beforeware, password + signing key from env,
   `sess_https_only=True`.
4. boxrecipe: systemd unit (loopback bind, env secrets,
   `TZ=Europe/Helsinki`) + Caddy entry; deploy and verify at
   habitrack.ninjalabo.ai.

## 11. Review changelog

v1 → v2, after external AI review:

- `ledger.csv` demoted from git-committed data to runtime state; manual
  copy around rebuilds replaces all backup/versioning machinery. The
  GitHub-grass side effect is dropped with it.
- Add/delete UI removed from scope (was v1 §5); item management is direct
  CSV editing.
- Static-serving hole confirmed against fasthtml source and closed by
  design (§3): dedicated `static_path`, data in a non-served directory.
- Auth hardened: separate signing-key secret, `sess_https_only=True`,
  loopback-only bind (§6).
- Timezone moved from env-only to explicit `zoneinfo` in code (§7).
- Atomic CSV writes added (§3) — corruption prevention, not backup.
- `/minit` migration prerequisite documented (§10 step 0).

v2 → v3, after second review (fasthtml-source claims re-verified against
the installed package):

- Empty-cell invariant added to §3: empty cells read as False; the reader
  must `fillna(False)` before the bool cast (blank cells otherwise become
  True — a hand-added column would appear fully checked for all history).
- Item-name constraints added to §5 (no `,` `"` newline `/`, empty, or
  duplicate names) — hand-editing is now the item-management path, and a
  stray comma silently shifts every row.
- Manual copy around rebuilds folded into the existing hetzner-rebuild
  procedure (§3), removing the "forgot the copy" failure mode.
- §4: `hx_disabled_elt="this"` prevents double-click double-toggle.
- §5: a toggle during a hand-edit silently overwrites the edit.
- §6: local-dev note for `sess_https_only`; failed-login sleep as the
  whole brute-force defense.
- §9: streak semantics clarified (today unchecked → start from yesterday).

v3 fix, after third review:

- §6 local-dev note corrected: with `sess_https_only=True`, either the
  browser accepts Secure cookies on localhost (Chrome/Firefox — works
  normally) or rejects them (login loop); "re-login per session" was not a
  real outcome. The env-var gate is now the stated mechanism, production
  sets it via the systemd unit.
