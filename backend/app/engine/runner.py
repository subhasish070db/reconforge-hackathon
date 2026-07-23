"""Reconciliation orchestrator (P3) — the single engine entry point.

``reconcile(df_a, df_b, config, aux_data, run_date, data_dir)`` runs the full
deterministic pipeline and returns a ``ReconResult``:

    aux load -> transforms (per side) -> drop zero-qty -> pre-match dedup
    -> position proof (per side) -> matching waterfall
    -> residuals become breaks (two-sided paired by ISIN, else one-sided)
    -> explained-break categorization (position_control.explained_break_categories)
    -> canonical output hash

Pure function of its inputs (aux is loaded from disk only when not supplied):
no LLM, no DB, no randomness — same input, same output hash (Law 4).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

from .auxiliary import load_aux_data
from .business_days import business_day_diff, parse_holidays
from .hashing import assign_row_ids, compute_run_hash
from .matching import MatchingWaterfall, _dec
from .position_proof import PositionProofEngine
from .transforms import TransformPipeline

logger = logging.getLogger(__name__)

SEED_DIR = Path(__file__).resolve().parent.parent.parent / "data"


@dataclass
class ReconResult:
    total_a: int
    total_b: int
    matched_count: int
    break_count: int  # open breaks only (excludes explained)
    match_rate: float
    output_hash: str
    matches: List[Dict[str, Any]] = field(default_factory=list)
    breaks: List[Dict[str, Any]] = field(default_factory=list)
    explained_breaks: List[Dict[str, Any]] = field(default_factory=list)
    pass_stats: List[Dict[str, Any]] = field(default_factory=list)
    position_proof: Dict[str, Any] = field(default_factory=dict)


_A_KEY_CANDIDATES = ("trade_id", "reference", "ref", "id")
_B_KEY_CANDIDATES = ("reference", "ref", "trade_id", "id")


def _natural_key(df: pd.DataFrame, candidates: Tuple[str, ...]) -> Optional[str]:
    for c in candidates:
        if c in df.columns:
            return c
    return None


def _jsonable_row(row: Dict[str, Any]) -> Dict[str, Any]:
    return {k: (None if (isinstance(v, float) and v != v) else v) for k, v in row.items() if k != "row_id"}


def reconcile(
    df_a: pd.DataFrame,
    df_b: pd.DataFrame,
    config: Dict[str, Any],
    aux_data: Optional[Dict[str, pd.DataFrame]] = None,
    run_date: Optional[str] = None,
    data_dir: Optional[Path] = None,
) -> ReconResult:
    total_a, total_b = len(df_a), len(df_b)

    # 1) Aux data + holidays.
    if aux_data is None:
        aux_data = load_aux_data(config, data_dir or SEED_DIR)
    holidays = (
        parse_holidays(aux_data["market_holidays"].to_dict("records"))
        if "market_holidays" in aux_data else {}
    )

    # 2) Transforms (per side).
    transforms = config.get("transforms", {}) or {}
    ta = TransformPipeline.apply(df_a, transforms.get("side_a", []), aux_data)
    tb = TransformPipeline.apply(df_b, transforms.get("side_b", []), aux_data)

    # 3) Position proof runs on the transformed frames (before pruning).
    pos = PositionProofEngine()
    pc = config.get("position_control", {}) or {}
    tol = float(pc.get("tolerance", 0.0))
    proof_a = pos.verify(ta, "A", pc.get("side_a", {}), tol)
    proof_b = pos.verify(tb, "B", pc.get("side_b", {}), tol)

    # 4) Drop zero-quantity rows pre-match (logged, not breaks).
    ta, _ = _drop_zero_qty(ta, "A")
    tb, _ = _drop_zero_qty(tb, "B")

    # 5) Row ids, then pre-match dedup (surplus -> duplicate_entry breaks).
    ta = assign_row_ids(ta)
    tb = assign_row_ids(tb)
    ta, dup_breaks_a = _dedup(ta, "A", _natural_key(ta, _A_KEY_CANDIDATES))
    tb, dup_breaks_b = _dedup(tb, "B", _natural_key(tb, _B_KEY_CANDIDATES))

    # 6) Matching waterfall.
    engine = MatchingWaterfall(config, aux_data=aux_data, holidays=holidays)
    wf = engine.execute(ta, tb)

    # 7) Residuals -> breaks; explained-break categorization.
    residual_breaks, explained = _residuals_to_breaks(
        wf["residual_a"], wf["residual_b"], config, aux_data, holidays
    )
    open_breaks = dup_breaks_a + dup_breaks_b + residual_breaks

    # 8) Hash over matches (Law 4).
    output_hash = compute_run_hash(wf["matches"])

    matched_count = wf["total_matched"]
    match_rate = round(matched_count / total_a * 100, 2) if total_a else 0.0

    return ReconResult(
        total_a=total_a,
        total_b=total_b,
        matched_count=matched_count,
        break_count=len(open_breaks),
        match_rate=match_rate,
        output_hash=output_hash,
        matches=wf["matches"],
        breaks=open_breaks,
        explained_breaks=explained,
        pass_stats=wf["pass_stats"],
        position_proof={"A": proof_a, "B": proof_b},
    )


def _drop_zero_qty(df: pd.DataFrame, side: str) -> Tuple[pd.DataFrame, int]:
    if "quantity" not in df.columns:
        return df, 0
    qty = pd.to_numeric(df["quantity"], errors="coerce").fillna(0)
    keep = df[qty != 0]
    dropped = len(df) - len(keep)
    if dropped:
        logger.info("engine: dropped %d zero-quantity row(s) from side %s pre-match", dropped, side)
    return keep, dropped


def _dedup(df: pd.DataFrame, side: str, key_col: Optional[str]) -> Tuple[pd.DataFrame, List[Dict[str, Any]]]:
    """Keep the first row per natural key; surplus -> duplicate_entry breaks."""
    if not key_col or key_col not in df.columns:
        return df, []
    breaks: List[Dict[str, Any]] = []
    seen: set = set()
    keep_idx: List[Any] = []
    for idx, row in df.iterrows():
        k = str(row[key_col])
        if k in seen:
            breaks.append(_make_duplicate_break(row.to_dict(), side, key_col))
        else:
            seen.add(k)
            keep_idx.append(idx)
    return df.loc[keep_idx], breaks


def _make_duplicate_break(row: Dict[str, Any], side: str, key_col: str) -> Dict[str, Any]:
    return {
        "break_key": f"DUP::{row.get(key_col)}::{side}",
        "side": side,
        "row_a": _jsonable_row(row) if side == "A" else None,
        "row_b": _jsonable_row(row) if side == "B" else None,
        "failed_rules": [],
        "deltas": {},
        "isin": row.get("isin"),
        "currency": row.get("currency"),
        "quantity_a": _num(row.get("quantity")) if side == "A" else None,
        "quantity_b": _num(row.get("quantity")) if side == "B" else None,
        "amount_a": None,
        "amount_b": None,
        "quantity_variance": None,
        "amount_variance": None,
        "pass_that_failed": None,
        "archetype": "duplicate_entry",
        "explained": False,
        "explained_category": None,
        "severity": "medium",
        "status": "open",
    }


def _canonical_value_rules(config: Dict[str, Any]) -> List[Dict[str, Any]]:
    """The first ONE_TO_ONE pass's value rules — used to diff residual pairs."""
    for p in config.get("matching_waterfall", []):
        if p.get("type") == "ONE_TO_ONE":
            return p.get("value_rules", [])
    return []


def _residuals_to_breaks(
    residual_a: pd.DataFrame,
    residual_b: pd.DataFrame,
    config: Dict[str, Any],
    aux_data: Dict[str, pd.DataFrame],
    holidays: Dict[str, set],
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Pair residuals by ISIN into two-sided breaks; leftovers are one-sided.

    Two-sided breaks whose delta a configured explained category accounts for
    (e.g. CORPORATE_ACTION) are returned separately and excluded from the
    open-break list.
    """
    value_rules = _canonical_value_rules(config)
    explained_cats = (config.get("position_control", {}) or {}).get("explained_break_categories", [])
    ca = aux_data.get("corporate_actions")

    open_breaks: List[Dict[str, Any]] = []
    explained: List[Dict[str, Any]] = []

    a_by_isin: Dict[Any, List[dict]] = {}
    b_by_isin: Dict[Any, List[dict]] = {}
    for r in residual_a.to_dict("records"):
        a_by_isin.setdefault(r.get("isin"), []).append(r)
    for r in residual_b.to_dict("records"):
        b_by_isin.setdefault(r.get("isin"), []).append(r)

    for isin in sorted(set(a_by_isin) | set(b_by_isin), key=lambda x: str(x)):
        alist = a_by_isin.get(isin, [])
        blist = b_by_isin.get(isin, [])
        for i in range(max(len(alist), len(blist))):
            a = alist[i] if i < len(alist) else None
            b = blist[i] if i < len(blist) else None
            brk = _make_pair_break(a, b, isin, value_rules, holidays)
            cat = _explained_category(a, b, explained_cats, ca)
            if cat:
                brk["explained"] = True
                brk["explained_category"] = cat
                brk["status"] = "explained"
                explained.append(brk)
            else:
                open_breaks.append(brk)
    return open_breaks, explained


def _make_pair_break(a, b, isin, value_rules, holidays) -> Dict[str, Any]:
    side = "AB" if (a and b) else ("A" if a else "B")
    failed: List[Dict[str, Any]] = []
    deltas: Dict[str, Any] = {}
    if a and b:
        for rule in value_rules:
            passed, delta = _diff_rule(a, b, rule, holidays)
            if not passed:
                failed.append(
                    {
                        "field_a": rule["field_a"],
                        "field_b": rule["field_b"],
                        "match_type": rule["match_type"],
                        "value_a": a.get(rule["field_a"]),
                        "value_b": b.get(rule["field_b"]),
                        "delta": delta,
                    }
                )
                deltas[f'{rule["field_a"]}:{rule["match_type"]}'] = delta

    key_src = a or b
    key_name = key_src.get("trade_id") or key_src.get("reference") or key_src.get("row_id")
    return {
        "break_key": str(key_name),
        "side": side,
        "row_a": _jsonable_row(a) if a else None,
        "row_b": _jsonable_row(b) if b else None,
        "failed_rules": failed,
        "deltas": deltas,
        "isin": isin,
        "currency": (a or b).get("currency"),
        "quantity_a": _num(a.get("quantity")) if a else None,
        "quantity_b": _num(b.get("quantity")) if b else None,
        "amount_a": _num(a.get("computed_market_value", a.get("market_value"))) if a else None,
        "amount_b": _num(b.get("computed_market_value", b.get("market_value"))) if b else None,
        "quantity_variance": round(_num(a.get("quantity")) - _num(b.get("quantity")), 6) if (a and b) else None,
        "amount_variance": round(
            _num(a.get("computed_market_value", a.get("market_value")))
            - _num(b.get("computed_market_value", b.get("market_value"))), 2,
        ) if (a and b) else None,
        "pass_that_failed": 1 if (a and b) else None,
        "archetype": None if (a and b) else "missing_counterparty_leg",
        "explained": False,
        "explained_category": None,
        "severity": "high" if not (a and b) else "medium",
        "status": "open",
    }


def _diff_rule(a, b, rule, holidays) -> Tuple[bool, Any]:
    """Evaluate a canonical rule for diagnostics; on failure return a meaningful
    delta (numeric difference, or business-day distance for dates) so the P7
    classifier and the UI can explain the break."""
    mt = rule["match_type"]
    va, vb = a.get(rule["field_a"]), b.get(rule["field_b"])
    market = rule.get("calendar_market", "TARGET2")

    if mt == "EXACT":
        passed = va is not None and vb is not None and str(va).strip() == str(vb).strip()
        if passed:
            return True, None
        return False, _best_effort_delta(va, vb, holidays.get(market, set()))
    if mt in ("NUMERIC_TOLERANCE", "ASYMMETRIC_TOLERANCE"):
        da, db = _dec(va), _dec(vb)
        if da is None or db is None:
            return False, None
        return abs(da - db) <= _dec(str(rule.get("tolerance", 0))), float(da - db)
    if mt == "DATE_TOLERANCE":
        diff = business_day_diff(va, vb, holidays.get(market, set()))
        if diff is None:
            return False, None
        return diff <= int(rule.get("tolerance_days", 0)), diff
    return False, None


def _best_effort_delta(va, vb, holidays) -> Any:
    """Numeric diff if both parse as numbers, else business-day distance if both
    parse as dates, else None (a categorical/string mismatch)."""
    da, db = _dec(va), _dec(vb)
    if da is not None and db is not None:
        return float(da - db)
    day_diff = business_day_diff(va, vb, holidays)
    if day_diff is not None:
        return day_diff
    return None


def _explained_category(a, b, categories, ca_df) -> Optional[str]:
    """Return an explained-break category if the delta is accounted for."""
    if not (a and b) or ca_df is None or "CORPORATE_ACTION" not in categories:
        return None
    isin = a.get("isin")
    events = ca_df[ca_df["isin"].astype(str) == str(isin)]
    if events.empty:
        return None
    qa, qb = _num(a.get("quantity")), _num(b.get("quantity"))
    if qa <= 0 or qb <= 0:
        return None
    actual_ratio = max(qa, qb) / min(qa, qb)
    for _, ev in events.iterrows():
        try:
            ratio = float(ev.get("ratio"))
        except (TypeError, ValueError):
            continue
        if abs(actual_ratio - ratio) < 0.01:
            return "CORPORATE_ACTION"
    return None


def _num(value: Any) -> float:
    try:
        v = float(value)
        return 0.0 if v != v else v
    except (TypeError, ValueError):
        return 0.0
