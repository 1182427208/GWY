"""LangGraph agent orchestration."""

try:
    from app.gwy.agents.feishu_push_agent import FeishuPushAgent
except ModuleNotFoundError:  # pragma: no cover - optional dependency fallback
    FeishuPushAgent = None

try:
    from app.gwy.agents.policy_evidence_agent import PolicyEvidenceAgent
except ModuleNotFoundError:  # pragma: no cover - optional dependency fallback
    PolicyEvidenceAgent = None

try:
    from app.gwy.agents.position_decision_agent import PositionDecisionAgent
except ModuleNotFoundError:  # pragma: no cover - optional dependency fallback
    PositionDecisionAgent = None

try:
    from app.gwy.agents.report_generator_agent import ReportGeneratorAgent
except ModuleNotFoundError:  # pragma: no cover - optional dependency fallback
    ReportGeneratorAgent = None

try:
    from app.gwy.agents.risk_review_agent import RiskReviewAgent
except ModuleNotFoundError:  # pragma: no cover - optional dependency fallback
    RiskReviewAgent = None

try:
    from app.gwy.agents.study_plan_agent import StudyPlanAgent
except ModuleNotFoundError:  # pragma: no cover - optional dependency fallback
    StudyPlanAgent = None

try:
    from app.gwy.agents.web_verification_agent import WebVerificationAgent
except ModuleNotFoundError:  # pragma: no cover - optional dependency fallback
    WebVerificationAgent = None

__all__ = [
    "FeishuPushAgent",
    "PolicyEvidenceAgent",
    "PositionDecisionAgent",
    "ReportGeneratorAgent",
    "RiskReviewAgent",
    "StudyPlanAgent",
    "WebVerificationAgent",
]
