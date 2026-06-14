import logging
from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, delete

from app.api.deps import get_db
from app.core.config import settings
from app.core.db import init_db
from app.gwy.models import (
    GwyAgentRun,
    GwyAgentStep,
    GwyChatAttachment,
    GwyChatMessage,
    GwyChatSession,
    GwyConversationMemory,
    GwyDecisionMemory,
    GwyExperienceMemory,
    GwyHumanReview,
    GwyPdfAsset,
    GwyPdfTable,
    GwyPdfTableRow,
    GwyPolicyDocument,
    GwyPosition,
    GwyPositionAnalysisSnapshot,
    GwyPositionAnalysisStep,
    GwyPositionAnalysisTask,
    GwyRagCacheEntry,
    GwyRecommendationItem,
    GwyRecommendationTask,
    GwyRiskItem,
    GwyToolCall,
    GwyUserProfile,
)
from app.main import app
from app.models import Item
from tests.utils.user import authentication_token_from_email
from tests.utils.utils import get_superuser_token_headers

logger = logging.getLogger(__name__)

_TEST_ENGINE = create_engine(
    "sqlite://",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)


def _reset_test_schema() -> None:
    SQLModel.metadata.drop_all(_TEST_ENGINE)
    SQLModel.metadata.create_all(_TEST_ENGINE)


@pytest.fixture(scope="session", autouse=True)
def db() -> Generator[Session, None, None]:
    _reset_test_schema()
    with Session(_TEST_ENGINE) as session:
        init_db(session)
        yield session
        session.execute(delete(Item))
        for model in (
            GwyToolCall,
            GwyAgentStep,
            GwyAgentRun,
            GwyHumanReview,
            GwyPdfTableRow,
            GwyPdfTable,
            GwyPdfAsset,
            GwyPositionAnalysisStep,
            GwyPositionAnalysisTask,
            GwyPositionAnalysisSnapshot,
            GwyRecommendationItem,
            GwyRiskItem,
            GwyChatMessage,
            GwyChatAttachment,
            GwyRagCacheEntry,
            GwyConversationMemory,
            GwyChatSession,
            GwyPolicyDocument,
            GwyDecisionMemory,
            GwyExperienceMemory,
            GwyRecommendationTask,
            GwyUserProfile,
            GwyPosition,
        ):
            session.execute(delete(model))
        session.commit()


@pytest.fixture(scope="module")
def client() -> Generator[TestClient, None, None]:
    def _override_get_db() -> Generator[Session, None, None]:
        with Session(_TEST_ENGINE) as session:
            yield session

    app.dependency_overrides[get_db] = _override_get_db
    try:
        with TestClient(app) as c:
            yield c
    finally:
        app.dependency_overrides.pop(get_db, None)


@pytest.fixture(scope="module")
def superuser_token_headers(client: TestClient) -> dict[str, str]:
    return get_superuser_token_headers(client)


@pytest.fixture(scope="module")
def normal_user_token_headers(client: TestClient, db: Session) -> dict[str, str]:
    return authentication_token_from_email(
        client=client, email=settings.EMAIL_TEST_USER, db=db
    )
