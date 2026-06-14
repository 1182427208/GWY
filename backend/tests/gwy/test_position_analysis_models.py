from sqlalchemy import inspect
from sqlmodel import SQLModel

from app.gwy.models import (
    GwyPositionAnalysisSnapshot,
    GwyPositionAnalysisStep,
    GwyPositionAnalysisTask,
)


def test_position_analysis_models_are_registered_in_metadata_and_test_schema(db) -> None:
    assert GwyPositionAnalysisSnapshot.__tablename__ == "gwy_position_analysis_snapshot"
    assert GwyPositionAnalysisTask.__tablename__ == "gwy_position_analysis_task"
    assert GwyPositionAnalysisStep.__tablename__ == "gwy_position_analysis_step"

    assert "gwy_position_analysis_snapshot" in SQLModel.metadata.tables
    assert "gwy_position_analysis_task" in SQLModel.metadata.tables
    assert "gwy_position_analysis_step" in SQLModel.metadata.tables

    table_names = set(inspect(db.get_bind()).get_table_names())
    assert "gwy_position_analysis_snapshot" in table_names
    assert "gwy_position_analysis_task" in table_names
    assert "gwy_position_analysis_step" in table_names
