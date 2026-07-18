from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_test_workflow_runs_pytest_on_push_and_pull_request() -> None:
    workflow = read(".github/workflows/tests.yml")

    assert "push:" in workflow
    assert "pull_request:" in workflow
    assert 'python-version: "3.12"' in workflow
    assert 'python -m pip install -e ".[test]"' in workflow
    assert "python -m pytest -v" in workflow
    assert "contents: read" in workflow


def test_notifier_workflow_uses_beijing_0930_and_manual_trigger() -> None:
    workflow = read(".github/workflows/new-bond-notifier.yml")

    assert 'cron: "30 9 * * *"' in workflow
    assert "timezone: Asia/Shanghai" in workflow
    assert "workflow_dispatch:" in workflow
    assert "send_test_email:" in workflow
    assert "type: boolean" in workflow
    assert "python -m pytest -v" in workflow
    assert "python -m new_bond_notifier" in workflow


def test_notifier_workflow_wires_only_named_mail_secrets() -> None:
    workflow = read(".github/workflows/new-bond-notifier.yml")

    assert "SMTP_USERNAME: ${{ secrets.SMTP_USERNAME }}" in workflow
    assert "SMTP_AUTH_CODE: ${{ secrets.SMTP_AUTH_CODE }}" in workflow
    assert "MAIL_TO: ${{ secrets.MAIL_TO }}" in workflow
    assert "SEND_TEST_EMAIL: ${{ inputs.send_test_email }}" in workflow
    assert "contents: read" in workflow
    assert "contents: write" not in workflow
