from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from sqlmodel import Session, func, select


logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("import_positions")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Batch import Gwy position workbooks into PostgreSQL."
    )
    parser.add_argument(
        "--workbook-dir",
        type=str,
        default=None,
        help="Directory that contains the national exam position workbooks.",
    )
    parser.add_argument(
        "--years",
        type=int,
        nargs="*",
        default=None,
        help="Optional year filter, e.g. --years 2024 2025.",
    )
    parser.add_argument(
        "--no-cache-clear",
        action="store_true",
        help="Skip clearing the position catalog cache after import.",
    )
    return parser


def _default_workbook_dir(repo_root: Path) -> Path:
    return repo_root / "data" / "国考职位表"


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[2]
    backend_root = repo_root / "backend"
    if str(backend_root) not in sys.path:
        sys.path.insert(0, str(backend_root))

    from app.core.db import engine
    from app.gwy.models import GwyPosition
    from app.gwy.services.position_catalog_service import PositionCatalogService
    from app.gwy.services.position_importer import import_positions_from_directory

    workbook_dir = (
        Path(args.workbook_dir)
        if args.workbook_dir
        else _default_workbook_dir(repo_root)
    )
    if not workbook_dir.exists():
        raise FileNotFoundError(f"Workbook directory not found: {workbook_dir}")

    logger.info("Workbook directory: %s", workbook_dir)
    logger.info("Year filter: %s", args.years or "all")

    with Session(engine) as session:
        before_count = int(session.exec(select(func.count()).select_from(GwyPosition)).one())
        logger.info("Rows before import: %s", before_count)

        result = import_positions_from_directory(
            session,
            workbook_dir,
            years=list(args.years) if args.years else None,
            replace_existing=True,
        )

        cleared = 0
        if not args.no_cache_clear:
            cache_service = PositionCatalogService(session)
            cleared = cache_service.clear_cache()

        after_count = int(session.exec(select(func.count()).select_from(GwyPosition)).one())

    output = {
        "workbook_dir": str(workbook_dir),
        "imported_count": int(result.get("imported_count", 0)),
        "imported_years": list(result.get("imported_years") or []),
        "cache_cleared": int(cleared),
        "rows_before": before_count,
        "rows_after": after_count,
        "files": list(result.get("files") or []),
    }
    logger.info("Import completed: %s", output)
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
