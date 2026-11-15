"""Run the database commands from the Firelytics root folder.

    python run_database.py status
    python run_database.py all
    python run_database.py search "droplet extinction"
    python run_database.py serve

Same commands as `python -m psi_db ...`, just without needing to cd into database/.
"""

import os
import sys
from pathlib import Path

DB_DIR = Path(__file__).resolve().parent / "database"
sys.path.insert(0, str(DB_DIR))
os.environ["PYTHONPATH"] = (
    str(DB_DIR) + os.pathsep + os.environ.get("PYTHONPATH", "")
)  # for the server process

from psi_db.__main__ import main  # noqa: E402

if __name__ == "__main__":
    main()
