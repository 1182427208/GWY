from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

from alembic import op
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import Column, MetaData, String, Table, create_engine, inspect

_MIGRATION_PATH = (
    Path(__file__).resolve().parents[2]
    / "app"
    / "alembic"
    / "versions"
    / "a1b2c3d4e5f6_add_gwy_position_analysis_tables.py"
)
_MIGRATION_SPEC = spec_from_file_location("gwy_position_analysis_migration", _MIGRATION_PATH)
assert _MIGRATION_SPEC is not None and _MIGRATION_SPEC.loader is not None
migration = module_from_spec(_MIGRATION_SPEC)
_MIGRATION_SPEC.loader.exec_module(migration)


def test_position_analysis_migration_applies_to_sqlite(tmp_path) -> None:
    db_path = tmp_path / "position_analysis.sqlite"
    engine = create_engine(f"sqlite+pysqlite:///{db_path}")

    metadata = MetaData()
    Table("user", metadata, Column("id", String, primary_key=True))
    with engine.begin() as connection:
        metadata.create_all(connection)
        context = MigrationContext.configure(connection)
        op._proxy = Operations(context)
        try:
            migration.upgrade()
        finally:
            delattr(op, "_proxy")

    engine = create_engine(f"sqlite+pysqlite:///{db_path}")
    table_names = set(inspect(engine).get_table_names())
    assert "gwy_position_analysis_snapshot" in table_names
    assert "gwy_position_analysis_task" in table_names
    assert "gwy_position_analysis_step" in table_names
