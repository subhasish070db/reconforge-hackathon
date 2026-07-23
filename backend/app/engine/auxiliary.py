"""Auxiliary reference-data loader (P3).

Reads the files named in a config's ``auxiliary_files`` block from a data
directory into DataFrames keyed by alias (fx_rates, instrument_master,
account_aliases, market_holidays, corporate_actions). Pure file I/O — the
engine itself stays a pure function of (frames, config, aux_data).
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

import pandas as pd


def load_aux_data(config: Dict[str, Any], data_dir: Path) -> Dict[str, pd.DataFrame]:
    """Return {alias -> DataFrame} for every auxiliary file the config declares.

    Missing files are skipped (the engine degrades: a transform that needs an
    absent aux simply no-ops rather than crashing).
    """
    data_dir = Path(data_dir)
    out: Dict[str, pd.DataFrame] = {}
    for entry in config.get("auxiliary_files", []) or []:
        alias = entry.get("alias")
        filename = entry.get("file")
        if not alias or not filename:
            continue
        path = data_dir / filename
        if path.exists():
            out[alias] = pd.read_csv(path)
    return out
