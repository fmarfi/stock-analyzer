"""Retention cleanup for timestamped report files.

write_reports() in html_report.py/squeeze_report.py always writes a fresh
timestamped copy alongside latest.* on every run, so the reports directory
grows by one file per run forever unless something prunes it -- call this
right after writing a new timestamped file to keep only the N most recent
per pattern and delete the rest.
"""

import glob
import logging
import os

logger = logging.getLogger(__name__)


def prune_old_reports(reports_dir: str, pattern: str, keep: int) -> None:
    """Delete all but the `keep` most recently modified files matching
    `pattern` (a glob relative to reports_dir, e.g. "scan_report_*.html").
    """
    paths = sorted(
        glob.glob(os.path.join(reports_dir, pattern)),
        key=os.path.getmtime, reverse=True,
    )
    for path in paths[keep:]:
        try:
            os.remove(path)
            logger.info("Removed old report: %s", path)
        except OSError:
            logger.exception("Could not remove old report: %s", path)
