import logging
from datetime import date
from typing import Any

import pytest

from new_bond_notifier.cli import github_run_url, main
from new_bond_notifier.models import Bond
from new_bond_notifier.service import CheckFailed, RunResult


VALID_ENV = {
    "SMTP_USERNAME": "sender@qq.com",
    "SMTP_AUTH_CODE": "super-secret-code",
    "MAIL_TO": "to@example.com",
}


class FakeClient:
    pass


class FakeMailer:
    instances: list["FakeMailer"] = []

    def __init__(self, config: object) -> None:
        self.config = config
        self.messages: list[object] = []
        FakeMailer.instances.append(self)

    def send(self, message: object) -> None:
        self.messages.append(message)


class SuccessfulService:
    def __init__(self, **kwargs: Any) -> None:
        self.kwargs = kwargs

    def run(self) -> RunResult:
        return RunResult(date(2022, 1, 5), (), False)


class FailingService:
    def __init__(self, **kwargs: Any) -> None:
        self.kwargs = kwargs

    def run(self) -> RunResult:
        raise RuntimeError("super-secret-code")


class SentBondService:
    def __init__(self, **kwargs: Any) -> None:
        self.kwargs = kwargs

    def run(self) -> RunResult:
        bond = Bond(
            name="测试转债",
            code="123456",
            subscribe_code="654321",
            subscribe_date=date(2022, 1, 5),
            stock_name="测试股份",
            stock_code="601012",
            issue_price="100 元",
            max_subscription="1000 手（100 万元）",
            rating="AAA",
        )
        return RunResult(date(2022, 1, 5), (bond,), True)


class CheckFailedService:
    def __init__(self, **kwargs: Any) -> None:
        self.kwargs = kwargs

    def run(self) -> RunResult:
        raise CheckFailed(
            RuntimeError("raw response must stay secret"),
            OSError("super-secret-code"),
        )


class FailingTestMailer(FakeMailer):
    def send(self, message: object) -> None:
        super().send(message)
        raise OSError("super-secret-code")


def test_github_run_url_is_built_only_when_all_parts_exist() -> None:
    assert (
        github_run_url(
            {
                "GITHUB_SERVER_URL": "https://github.com",
                "GITHUB_REPOSITORY": "example/repo",
                "GITHUB_RUN_ID": "123",
            }
        )
        == "https://github.com/example/repo/actions/runs/123"
    )
    assert github_run_url({}) is None


@pytest.mark.parametrize(
    "env",
    [
        {
            "GITHUB_SERVER_URL": "https://github.com",
            "GITHUB_REPOSITORY": "example/repo",
        },
        {
            "GITHUB_SERVER_URL": "https://github.com",
            "GITHUB_RUN_ID": "123",
        },
        {
            "GITHUB_REPOSITORY": "example/repo",
            "GITHUB_RUN_ID": "123",
        },
    ],
)
def test_github_run_url_rejects_every_two_of_three_partial_combination(
    env: dict[str, str],
) -> None:
    assert github_run_url(env) is None


def test_main_returns_one_for_missing_configuration(caplog: Any) -> None:
    with caplog.at_level(logging.ERROR):
        exit_code = main(env={})

    assert exit_code == 1
    assert "SMTP_AUTH_CODE" not in caplog.text


def test_main_returns_zero_for_successful_no_bond_run(caplog: Any) -> None:
    FakeMailer.instances.clear()
    with caplog.at_level(logging.INFO):
        exit_code = main(
            env=VALID_ENV,
            client_factory=FakeClient,
            mailer_factory=FakeMailer,
            service_factory=SuccessfulService,
        )

    assert exit_code == 0
    assert "2022-01-05" in caplog.text
    assert "无需发送" in caplog.text


def test_main_logs_sent_bond_count_on_success(caplog: Any) -> None:
    with caplog.at_level(logging.INFO):
        exit_code = main(
            env=VALID_ENV,
            client_factory=FakeClient,
            mailer_factory=FakeMailer,
            service_factory=SentBondService,
        )

    assert exit_code == 0
    assert "2022-01-05" in caplog.text
    assert "1 只可申购转债" in caplog.text
    assert "提醒邮件已发送" in caplog.text


def test_main_sends_explicit_test_email_without_calling_data_client(
    caplog: Any,
) -> None:
    FakeMailer.instances.clear()

    def forbidden_client() -> object:
        raise AssertionError("test-email mode must not call Eastmoney")

    with caplog.at_level(logging.INFO):
        exit_code = main(
            env={**VALID_ENV, "SEND_TEST_EMAIL": "true"},
            client_factory=forbidden_client,
            mailer_factory=FakeMailer,
            service_factory=SuccessfulService,
        )

    assert exit_code == 0
    assert "测试邮件已发送" in caplog.text
    assert len(FakeMailer.instances[0].messages) == 1
    assert (
        str(FakeMailer.instances[0].messages[0]["Subject"])
        == "[新债提醒测试] 邮件配置正常"
    )


def test_test_email_smtp_failure_is_sanitized(caplog: Any) -> None:
    with caplog.at_level(logging.ERROR):
        exit_code = main(
            env={**VALID_ENV, "SEND_TEST_EMAIL": "true"},
            client_factory=FakeClient,
            mailer_factory=FailingTestMailer,
            service_factory=SuccessfulService,
        )

    assert exit_code == 1
    assert "OSError" in caplog.text
    assert "super-secret-code" not in caplog.text


def test_check_failed_log_names_only_primary_and_notification_types(
    caplog: Any,
) -> None:
    with caplog.at_level(logging.ERROR):
        exit_code = main(
            env=VALID_ENV,
            client_factory=FakeClient,
            mailer_factory=FakeMailer,
            service_factory=CheckFailedService,
        )

    assert exit_code == 1
    assert "RuntimeError" in caplog.text
    assert "OSError" in caplog.text
    assert "raw response must stay secret" not in caplog.text
    assert "super-secret-code" not in caplog.text


def test_main_never_logs_exception_text_that_might_contain_secret(
    caplog: Any,
) -> None:
    with caplog.at_level(logging.ERROR):
        exit_code = main(
            env=VALID_ENV,
            client_factory=FakeClient,
            mailer_factory=FakeMailer,
            service_factory=FailingService,
        )

    assert exit_code == 1
    assert "RuntimeError" in caplog.text
    assert "super-secret-code" not in caplog.text
