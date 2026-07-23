from pathlib import Path

from common import LocationId
from logger import Logger


def test_ingest_and_search(tmp_path: Path) -> None:
    db = tmp_path / "logger.db"
    log = Logger(db)
    try:
        location = LocationId(path="svc/api.log", service="api")
        log.ingest_line(
            "2026-07-23 ERROR payment failed for order=42",
            location=location,
            score=True,
        )
        log.ingest_line(
            "2026-07-23 INFO payment ok for order=43",
            location=location,
        )
        log.ingest_line(
            "2026-07-23 ERROR payment failed for order=99",
            location=location,
        )

        structured = log.index.query(severity="ERROR", limit=10)
        assert len(structured) >= 2
        assert all(e.location_key == "api:svc/api.log" for e in structured)

        results = log.search("find payment errors")
        assert results
        assert any("payment" in e.raw.lower() for e in results)
    finally:
        log.close()


def test_parser_clusters_templates(tmp_path: Path) -> None:
    db = tmp_path / "logger.db"
    log = Logger(db)
    try:
        _, a, _ = log.ingest_line("ERROR user=alice timeout")
        _, b, _ = log.ingest_line("ERROR user=bob timeout")
        assert a.template_id == b.template_id
    finally:
        log.close()
