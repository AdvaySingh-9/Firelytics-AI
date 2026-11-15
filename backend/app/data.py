"""Starter catalogue based strictly on the 11 inventory rows supplied by the project team."""

NASA_BASE = "https://psi.nasa.gov/physci/repo/data/investigations/"
_ROWS = [
    ("PSI-62", []),
    ("PSI-60", []),
    ("PSI-142", ["Analyzed Data", "Experimental Table"]),
    (
        "PSI-98",
        [
            "Engineering Documents",
            "Raw Data",
            "Science Documents",
            "Experimental Table",
        ],
    ),
    ("PSI-99", ["Experimental Table", "Raw Data", "Science Documents"]),
    ("PSI-106", ["Experimental Table", "Raw Data"]),
    (
        "PSI-100",
        [
            "Engineering Documents",
            "Presentations",
            "Raw Data",
            "Science Documents",
            "Experimental Table",
        ],
    ),
    ("PSI-21", ["Experimental Table", "Raw Data"]),
    (
        "PSI-68",
        [
            "Experimental Table",
            "Science Documents",
            "Calibration",
            "Engineering Documents",
            "Raw Data",
        ],
    ),
    (
        "PSI-69",
        [
            "Experimental Table",
            "Engineering Documents",
            "Presentations",
            "Raw Data",
            "Calibration",
            "Science Documents",
        ],
    ),
    (
        "PSI-26",
        [
            "Presentations",
            "Science Documents",
            "Engineering Documents",
            "Raw Data",
            "Experimental Table",
        ],
    ),
]


def availability(assets):
    if not assets:
        return "metadata_only"
    if "Analyzed Data" in assets:
        return "analyzed_data"
    if any(
        x in assets
        for x in ("Science Documents", "Engineering Documents", "Presentations")
    ):
        return "research_documents"
    return "experimental_data"


INVESTIGATIONS = []
for study_id, assets in _ROWS:
    flex = study_id == "PSI-69"
    INVESTIGATIONS.append(
        {
            "study_id": study_id,
            "title": (
                "Flame Extinguishment Experiment"
                if flex
                else f"NASA PSI Investigation {study_id.split('-')[1]}"
            ),
            "acronym": "FLEX" if flex else "—",
            "summary": (
                "Full research package"
                if len(assets) >= 5
                else "Research documents + raw data" if assets else "Metadata only"
            ),
            "assets": assets,
            "asset_count": len(assets) + 1,
            "availability": availability(assets),
            "source_url": NASA_BASE + study_id,
            "source": "NASA Physical Sciences Informatics",
            "objective": (
                "Study liquid-fuel droplet burning and flame-extinguishment behavior in microgravity."
                if flex
                else "Investigation objective not yet enriched in the local project catalogue."
            ),
            "note": (
                "Asset categories reflect the inventory supplied by the project team. Verify file-level contents and scientific findings on the official NASA PSI record."
                if assets
                else "The supplied inventory indicates metadata only. No report or measurement files are listed in this project inventory."
            ),
        }
    )
