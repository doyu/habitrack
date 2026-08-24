"""
習慣ログ — FastHTML + pandas. See DESIGN.md for the full spec.

Data: data/ledger.csv (runtime state, gitignored) — index=date, columns=item,
values=bool. The CSV header row IS the item list; edit it directly to manage
items. Every save is an atomic replace.

Run:
    HABITRACK_PASSWORD=... HABITRACK_SECRET_KEY=... python app.py
    # production additionally sets HABITRACK_HTTPS_ONLY=1 (systemd unit)
"""

import os
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
from fasthtml.common import *

HERE = Path(__file__).parent
DATA_DIR = HERE / "data"
DATA_PATH = DATA_DIR / "ledger.csv"
DAYS_SHOWN = 10
TZ = ZoneInfo("Europe/Helsinki")  # "today" never depends on server-local time
DOW_JA = ["月", "火", "水", "木", "金", "土", "日"]
DEFAULT_ITEMS = ["読書", "運動", "執筆", "瞑想", "早起き"]

# Fail fast: without both secrets the app must not start (DESIGN.md §6) —
# FastHTML would otherwise auto-generate a .sesskey file silently.
PASSWORD = os.environ["HABITRACK_PASSWORD"]
SECRET_KEY = os.environ["HABITRACK_SECRET_KEY"]


# ---------------------------------------------------------------- backend --
def today() -> date:
    return datetime.now(TZ).date()


def load_full() -> pd.DataFrame:
    """Full history from ledger.csv; blank cells (hand-added columns) read as False."""
    if not DATA_PATH.exists():
        df = pd.DataFrame(False, index=pd.Index([today()], name="date"),
                          columns=DEFAULT_ITEMS)
        save_full(df)
        return df
    df = pd.read_csv(DATA_PATH, index_col=0)
    df = df.fillna(False).astype(bool)
    df.index = pd.Index([date.fromisoformat(d) for d in df.index], name="date")
    return df


def save_full(df: pd.DataFrame) -> None:
    """Atomic write: a mid-write crash must never corrupt the live file."""
    DATA_DIR.mkdir(exist_ok=True)
    tmp = DATA_PATH.with_suffix(".tmp")
    df.to_csv(tmp)
    os.replace(tmp, DATA_PATH)


def window(full: pd.DataFrame) -> pd.DataFrame:
    days = [today() - timedelta(days=i) for i in range(DAYS_SHOWN - 1, -1, -1)]
    return full.reindex(days, fill_value=False)


def current_streak(full: pd.DataFrame, item: str) -> int:
    col = full[item]
    d = today()
    if not col.get(d, False):  # today unchecked → streak starts from yesterday
        d -= timedelta(days=1)
    streak = 0
    while col.get(d, False):
        streak += 1
        d -= timedelta(days=1)
    return streak


# ---------------------------------------------------------------- auth -----
def auth_before(req, sess):
    if not sess.get("auth"):
        return Redirect("/login")


# ---------------------------------------------------------------- frontend --
app, rt = fast_app(
    before=Beforeware(auth_before, skip=[r"/login"]),
    secret_key=SECRET_KEY,
    sess_https_only=os.environ.get("HABITRACK_HTTPS_ONLY") == "1",
    static_path=str(HERE / "static"),  # data/ must stay unreachable (DESIGN.md §3)
    hdrs=(
        Link(rel="preconnect", href="https://fonts.googleapis.com"),
        Link(
            href="https://fonts.googleapis.com/css2?family=Shippori+Mincho:wght@500;700&family=Space+Mono:wght@400;700&display=swap",
            rel="stylesheet",
        ),
        Style("""
            :root{--paper:#EFECE3;--paper-line:#CBCABB;--ink:#23272A;--ink-soft:#5B5F58;--amber:#B9822E;--amber-soft:#E9DCC0}
            *{box-sizing:border-box}
            body{background:var(--paper);color:var(--ink);font-family:'Space Mono',monospace;
                 max-width:520px;margin:0 auto;padding:32px 20px 60px}
            h1{font-family:'Shippori Mincho',serif;font-size:22px;margin:0 0 20px;
               border-bottom:2px solid var(--ink);padding-bottom:10px}
            table{border-collapse:collapse}
            td,th{padding:0;text-align:center}
            .item-cell{font-family:'Shippori Mincho',serif;font-size:15px;text-align:left;
                       padding-right:12px;white-space:nowrap}
            .dow{font-size:9px;color:var(--ink-soft)}
            .num{font-size:9px;color:#9a9a8c}
            .today .num{color:var(--amber);font-weight:700}
            input[type=checkbox]{appearance:none;width:20px;height:20px;border:1.5px solid var(--ink-soft);
              border-radius:3px;cursor:pointer;margin:2px 4px}
            input[type=checkbox]:checked{background:var(--ink);border-color:var(--ink)}
            input[type=checkbox].today-cb{border-color:var(--amber);border-width:2.5px}
            .streak{font-size:10px;font-weight:700;color:var(--amber);background:var(--amber-soft);
                    border-radius:3px;padding:1px 5px;margin-left:6px}
            .streak.zero{background:none;color:var(--ink-soft)}
            input[type=password]{font-family:inherit;font-size:15px;padding:6px 8px;
              border:1.5px solid var(--ink-soft);border-radius:3px;background:none}
            button{font-family:inherit;font-size:14px;padding:6px 14px;cursor:pointer;
              border:1.5px solid var(--ink);border-radius:3px;background:var(--ink);color:var(--paper)}
        """),
    ),
)


def render_table():
    full = load_full()
    df = window(full)
    days = list(df.index)
    t = today()

    header = Tr(
        Th("", cls="item-cell"),
        *[
            Th(Div(DOW_JA[d.weekday()], cls="dow"), Div(str(d.day), cls="num"),
               cls="today" if d == t else "")
            for d in days
        ],
    )

    rows = [header]
    for item in df.columns:
        streak = current_streak(full, item)
        cells = [
            Td(
                Span(item),
                Span(str(streak), cls=f"streak{' zero' if streak == 0 else ''}"),
                cls="item-cell",
            )
        ]
        for d in days:
            cells.append(
                Td(
                    Input(
                        type="checkbox",
                        checked=bool(df.at[d, item]),
                        cls="today-cb" if d == t else "",
                        hx_post=f"/toggle/{item}/{d.isoformat()}",
                        hx_target="#ledger",
                        hx_swap="outerHTML",
                        hx_disabled_elt="this",
                    )
                )
            )
        rows.append(Tr(*cells))

    return Table(*rows, id="ledger")


@rt("/")
def get():
    return Titled("習慣ログ", Div(H1("習慣ログ"), render_table()))


@rt("/toggle/{item}/{d}")
def post(item: str, d: str):
    day = date.fromisoformat(d)
    full = load_full()
    if item in full.columns:
        if day not in full.index:
            full.loc[day] = False
        full.at[day, item] = not full.at[day, item]
        full.sort_index(inplace=True)
        save_full(full)
    return render_table()


@rt("/login", methods=["GET"])
def login_page():
    return Titled("習慣ログ", Div(
        H1("習慣ログ"),
        Form(
            Input(type="password", name="password", autofocus=True),
            Button("ログイン"),
            method="post", action="/login",
        ),
    ))


@rt("/login", methods=["POST"])
def login_submit(sess, password: str = ""):
    if password == PASSWORD:
        sess["auth"] = True
        return Redirect("/")
    time.sleep(0.5)  # the entire brute-force defense (DESIGN.md §6)
    return Redirect("/login")


serve(host="127.0.0.1")  # public path is the reverse proxy only (DESIGN.md §6)
