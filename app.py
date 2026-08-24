"""習慣ログ — thin launcher; the app lives in nbs/01_app.ipynb → habitrack.app.

Run:
    HABITRACK_PASSWORD=... HABITRACK_SECRET_KEY=... python app.py
    # production additionally sets HABITRACK_HTTPS_ONLY=1 (systemd unit)
"""

from pathlib import Path

from habitrack.app import main

from habitrack.core import current_streak, load_full, save_full, window

HERE = Path(__file__).parent
main(HERE / "data" / "ledger.csv", static_path=str(HERE / "static"))
