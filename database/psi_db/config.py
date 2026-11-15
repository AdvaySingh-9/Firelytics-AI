"""Paths and tunables in one place. Override the project folder with PSI_PROJECT_DIR."""

import os
from pathlib import Path

ROOT = Path(
    os.getenv("PSI_PROJECT_DIR", Path(__file__).resolve().parent.parent)
)  # the "database" folder
DATA = ROOT / "data"
RAW = (
    DATA / "raw"
)  # YOU put files here: data/raw/<STUDY_ID>/i_Investigation.txt + report PDF
REPORTS = DATA / "reports"  # generated: data/reports/<STUDY_ID>.txt
CATALOG = DATA / "catalog"  # generated: studies.csv, studies.json
DB_PATH = DATA / "psi.db"  # generated

METADATA_FILENAME = "i_Investigation.txt"
# If a folder has several PDFs, the report is the one whose name contains these (lower-case).
# A file named exactly report.pdf always wins.
REPORT_NAME_HINTS = ("final", "report")


# --- Wording shown to users (teammates render these; edit the text here) ---
SOURCE_URL_TEMPLATE = "https://psi.nasa.gov/physci/repo/data/investigations/{study_id}"
SOURCE_ATTRIBUTION = (
    "Information from NASA's Physical Sciences Informatics (PSI) database"
)
LIMITED_INFO_MESSAGE = (
    "Limited information was available in PSI for this experiment. "
    "Please check the official website for more information."
)


def ensure_dirs():
    for d in (RAW, REPORTS, CATALOG):
        d.mkdir(parents=True, exist_ok=True)
