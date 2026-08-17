from fastapi.testclient import TestClient

from app.core.config import settings


def test_import_default_eval_datasets_is_available_and_idempotent(
    client: TestClient,
    normal_user_token_headers: dict[str, str],
) -> None:
    path = f"{settings.API_V1_STR}/gwy/evals/datasets/import-defaults"

    first_response = client.post(path, headers=normal_user_token_headers)
    assert first_response.status_code == 200
    first_datasets = first_response.json()
    assert {item["name"] for item in first_datasets} == {"内置评测集 dev"}
    assert {item["case_count"] for item in first_datasets} == {2}

    second_response = client.post(path, headers=normal_user_token_headers)
    assert second_response.status_code == 200
    assert len(second_response.json()) == 1

    list_response = client.get(
        f"{settings.API_V1_STR}/gwy/evals/datasets",
        headers=normal_user_token_headers,
    )
    assert list_response.status_code == 200
    assert len(list_response.json()) == 1
