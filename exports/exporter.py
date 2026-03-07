"""Standalone export helper – can also be run as a script for ad-hoc exports."""

from __future__ import annotations

import io
from typing import List

import pandas as pd


def leads_to_excel(rows: List[dict]) -> io.BytesIO:
    """Convert a list of lead dicts to an in-memory Excel file."""
    columns = [
        "Company Name", "Website", "Domain", "Email", "Email Valid",
        "Phone", "LinkedIn", "Address", "Industry", "City",
        "Lead Score", "Source URL",
    ]
    df = pd.DataFrame(rows, columns=columns) if rows else pd.DataFrame(columns=columns)
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Leads")
    buf.seek(0)
    return buf
