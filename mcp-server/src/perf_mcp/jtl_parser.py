"""
JTL CSV parser for JMeter test results.

Parses JMeter CSV JTL output files, computes per-label statistics and
a TOTAL aggregate row. All percentiles are derived from raw ``elapsed``
values — never from JMeter's own summary rows.

Design decisions:
- Uses pandas for vectorised percentile computation on large files (FR-NFR-001-1: <30s for 500MB)
- Reads in a single pass; skips malformed rows with a logged warning (FR-005-7, FR-005-8)
- Throughput computed from actual test duration (max ts - min ts), not JMeter header
- Received/sent KB/s aggregated from ``bytes`` / ``sentBytes`` columns
"""

from __future__ import annotations

import logging
import time
from pathlib import Path

import pandas as pd

from .models import LabelStats, ParsedJtlResult

logger = logging.getLogger(__name__)

# Mandatory JTL columns required for KPI computation.
# JMeter may add extra columns — they are silently ignored.
_REQUIRED_COLUMNS = {"timeStamp", "elapsed", "label", "success", "bytes", "sentBytes"}

# Maximum JTL file size in bytes before a warning is logged (500 MB).
_MAX_JTL_BYTES = 500 * 1024 * 1024

# Timeout for parse operation in seconds (NFR-001-1).
_PARSE_TIMEOUT_SECONDS = 30.0


def parse_jtl(jtl_path: str | Path) -> ParsedJtlResult:
    """Parse a JMeter JTL CSV file and return per-label + TOTAL KPIs.

    Reads the entire file, skips malformed rows, groups by ``label``,
    computes all required KPIs from raw ``elapsed`` values, and returns
    a :class:`ParsedJtlResult` containing per-label rows and a TOTAL row.

    Args:
        jtl_path: Absolute path to the JTL file (CSV format).

    Returns:
        :class:`ParsedJtlResult` with per-label rows and TOTAL aggregate.

    Raises:
        FileNotFoundError: If the JTL file does not exist.
        ValueError: If the file is empty, missing required columns, or
            the parse timeout of 30 seconds is exceeded.

    Example:
        >>> result = parse_jtl("C:\\\\results\\\\run1\\\\GET_RO.jtl")
        >>> print(result.total.avg_ms)
        420.5
    """
    jtl_path = Path(jtl_path)
    start_time = time.monotonic()

    # --- File existence and size checks ---
    if not jtl_path.exists():
        logger.error("JTL file not found: %s", jtl_path)
        raise FileNotFoundError(f"JTL file not found: {jtl_path}")

    file_size = jtl_path.stat().st_size
    if file_size == 0:
        logger.error("JTL file is empty: %s", jtl_path)
        raise ValueError(f"JTL file is empty: {jtl_path}")

    if file_size > _MAX_JTL_BYTES:
        logger.warning(
            "JTL file is large (%.1f MB). Parse may be slow: %s",
            file_size / (1024 * 1024),
            jtl_path,
        )

    # Count raw data rows from the source file so parser-level skipped lines
    # are reflected in rows_skipped metrics as well.
    with jtl_path.open("r", encoding="utf-8", errors="replace") as fh:
        raw_total_rows = max(sum(1 for _ in fh) - 1, 0)  # subtract header

    # --- Load CSV ---
    try:
        df = pd.read_csv(
            jtl_path,
            dtype={
                "timeStamp": "Int64",
                "elapsed": "Int64",
                "bytes": "Int64",
                "sentBytes": "Int64",
                "success": str,
                "label": str,
            },
            on_bad_lines="warn",   # Skip malformed rows, emit warning
            low_memory=False,
        )
    except Exception as exc:
        logger.error("Failed to read JTL CSV '%s': %s", jtl_path, exc, exc_info=True)
        raise ValueError(f"Failed to read JTL file '{jtl_path}': {exc}") from exc

    # --- Validate required columns ---
    missing = _REQUIRED_COLUMNS - set(df.columns)
    if missing:
        logger.error("JTL file missing required columns %s: %s", missing, jtl_path)
        raise ValueError(
            f"JTL file '{jtl_path}' is missing required columns: {sorted(missing)}. "
            f"Present columns: {sorted(df.columns.tolist())}"
        )

    total_rows_before = len(df)

    # --- Drop rows where critical numeric columns are null/malformed ---
    df = df.dropna(subset=["timeStamp", "elapsed", "label"])
    df["elapsed"] = pd.to_numeric(df["elapsed"], errors="coerce")
    df["bytes"] = pd.to_numeric(df["bytes"], errors="coerce").fillna(0)
    df["sentBytes"] = pd.to_numeric(df["sentBytes"], errors="coerce").fillna(0)
    df["timeStamp"] = pd.to_numeric(df["timeStamp"], errors="coerce")
    df = df.dropna(subset=["elapsed", "timeStamp"])

    # Includes both rows dropped during cleanup and parser-level skipped lines.
    rows_skipped = max(raw_total_rows - len(df), 0)
    if rows_skipped > 0:
        logger.warning(
            "Skipped %d malformed rows in JTL file: %s", rows_skipped, jtl_path
        )

    if df.empty:
        raise ValueError(
            f"JTL file '{jtl_path}' has no valid data rows after cleaning. "
            "Check that JMeter produced output."
        )

    # --- Check parse timeout ---
    _check_timeout(start_time, jtl_path)

    # --- Normalise success column to boolean ---
    df["is_error"] = df["success"].str.strip().str.lower() != "true"

    # --- Test duration: from first to last timestamp (ms → seconds) ---
    ts_min = df["timeStamp"].min()
    ts_max = df["timeStamp"].max() + df.loc[df["timeStamp"] == df["timeStamp"].max(), "elapsed"].iloc[0]
    test_duration_seconds = max((ts_max - ts_min) / 1000.0, 1.0)  # floor at 1s to avoid division by zero

    # --- Per-label stats ---
    label_rows: list[LabelStats] = []
    for label, group in df.groupby("label", sort=True):
        label_rows.append(_compute_stats(str(label), group, test_duration_seconds))

    # --- TOTAL row across all data ---
    total_row = _compute_stats("TOTAL", df, test_duration_seconds)

    _check_timeout(start_time, jtl_path)

    elapsed_sec = time.monotonic() - start_time
    logger.info(
        "JTL parsed in %.2fs — %d rows, %d labels, %d skipped: %s",
        elapsed_sec,
        len(df),
        len(label_rows),
        rows_skipped,
        jtl_path,
    )

    return ParsedJtlResult(
        jtl_path=str(jtl_path),
        label_rows=label_rows,
        total=total_row,
        test_duration_seconds=test_duration_seconds,
        rows_parsed=len(df),
        rows_skipped=rows_skipped,
    )


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _compute_stats(label: str, group: pd.DataFrame, test_duration_seconds: float) -> LabelStats:
    """Compute all KPIs for a single label group (or the TOTAL group).

    Args:
        label: Display name for the row (transaction label or "TOTAL").
        group: DataFrame rows for this label.
        test_duration_seconds: Full test duration used to compute throughput.

    Returns:
        :class:`LabelStats` with all KPIs populated.
    """
    elapsed = group["elapsed"].astype(float)
    sample_count = len(group)
    error_count = int(group["is_error"].sum())

    # Bandwidth: bytes column is per-response size in bytes; average then normalise to KB/s
    # Throughput for this label = sample_count / test_duration (proportional share)
    throughput = sample_count / test_duration_seconds
    received_kb_sec = (group["bytes"].sum() / 1024.0) / test_duration_seconds
    sent_kb_sec = (group["sentBytes"].sum() / 1024.0) / test_duration_seconds

    return LabelStats(
        label=label,
        sample_count=sample_count,
        avg_ms=round(float(elapsed.mean()), 2),
        median_ms=round(float(elapsed.quantile(0.50)), 2),
        p90_ms=round(float(elapsed.quantile(0.90)), 2),
        p95_ms=round(float(elapsed.quantile(0.95)), 2),
        p99_ms=round(float(elapsed.quantile(0.99)), 2),
        min_ms=round(float(elapsed.min()), 2),
        max_ms=round(float(elapsed.max()), 2),
        error_count=error_count,
        error_pct=round((error_count / sample_count) * 100, 2),
        throughput_req_sec=round(throughput, 2),
        received_kb_sec=round(received_kb_sec, 2),
        sent_kb_sec=round(sent_kb_sec, 2),
    )


def _check_timeout(start_time: float, jtl_path: Path) -> None:
    """Raise ValueError if parse wall-clock time has exceeded 30 seconds.

    Args:
        start_time: ``time.monotonic()`` value recorded at parse start.
        jtl_path: Path to the JTL file (for error message context).

    Raises:
        ValueError: If elapsed time exceeds ``_PARSE_TIMEOUT_SECONDS``.
    """
    elapsed = time.monotonic() - start_time
    if elapsed > _PARSE_TIMEOUT_SECONDS:
        raise ValueError(
            f"JTL parse timeout exceeded ({elapsed:.1f}s > {_PARSE_TIMEOUT_SECONDS}s) "
            f"for file: {jtl_path}. File may be too large or disk is slow."
        )


def find_jtl_file(result_folder: str | Path) -> Path:
    """Discover the JTL file in a result folder using glob pattern ``*.jtl``.

    JMeter output filenames vary per test script — this function discovers
    the file by extension rather than requiring a fixed name.

    Args:
        result_folder: Path to a round result folder containing the JTL file.

    Returns:
        :class:`pathlib.Path` to the discovered JTL file.

    Raises:
        FileNotFoundError: If no ``*.jtl`` file is found in the folder.
        ValueError: If multiple ``*.jtl`` files are found (ambiguous).

    Example:
        >>> jtl = find_jtl_file("\\\\\\\\vm-host\\\\PerfTest\\\\results\\\\2026-04-29_Round1_14-30-22")
        >>> print(jtl.name)
        GET_RO_Number_Round1.jtl
    """
    result_folder = Path(result_folder)
    matches = list(result_folder.glob("*.jtl"))

    if not matches:
        raise FileNotFoundError(
            f"No *.jtl file found in result folder: {result_folder}. "
            "Verify that JMeter completed and VM runner wrote the output."
        )

    if len(matches) > 1:
        newest = max(matches, key=lambda p: p.stat().st_mtime)
        logger.warning(
            "Multiple *.jtl files found in '%s': %s. Using newest: %s",
            result_folder,
            [m.name for m in matches],
            newest.name,
        )
        return newest

    return matches[0]
