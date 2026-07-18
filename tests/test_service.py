from datetime import datetime, timezone
from email.message import EmailMessage
from typing import Any
from zoneinfo import ZoneInfo

import pytest

import new_bond_notifier.service as service_module
from new_bond_notifier.eastmoney import DataSourceError
from new_bond_notifier.models import MailConfig
from new_bond_notifier.service import CheckFailed, NotifierService


CN_TZ = ZoneInfo("Asia/Shanghai")
NOW = datetime(2022, 1, 5, 9, 30, tzinfo=CN_TZ)
CONFIG = MailConfig(
    smtp_username="sender@qq.com",
    smtp_auth_code="secret",
    recipients=("to@example.com",),
)


def record(
    name: str,
    raw_date: str = "2022-01-05 00:00:00",
) -> dict[str, Any]:
    return {
        "SECURITY_NAME_ABBR": name,
        "SECURITY_CODE": "113053",
        "CORRECODE": "783012",
        "PUBLIC_START_DATE": raw_date,
        "SECURITY_SHORT_NAME": "隆基股份",
        "CONVERT_STOCK_CODE": "601012",
        "ISSUE_PRICE": 100,
        "ONLINE_GENERAL_AAU": 1000,
        "RATING": "AAA",
    }


class StubClient:
    def __init__(
        self,
        records: list[dict[str, Any]] | None = None,
        error: Exception | None = None,
    ) -> None:
        self.records = records or []
        self.error = error
        self.fetch_count = 0

    def fetch_records(self) -> list[dict[str, Any]]:
        self.fetch_count += 1
        if self.error is not None:
            raise self.error
        return self.records


class StubMailer:
    def __init__(self, error: Exception | None = None) -> None:
        self.messages: list[EmailMessage] = []
        self.error = error

    def send(self, message: EmailMessage) -> None:
        self.messages.append(message)
        if self.error is not None:
            raise self.error


def service(
    client: StubClient,
    mailer: StubMailer,
) -> NotifierService:
    return NotifierService(
        client=client,  # type: ignore[arg-type]
        mailer=mailer,  # type: ignore[arg-type]
        config=CONFIG,
        run_url="https://github.com/example/repo/actions/runs/123",
    )


def test_no_bonds_sends_no_email_and_succeeds() -> None:
    mailer = StubMailer()

    result = service(
        StubClient([record("昨天转债", "2022-01-04 00:00:00")]),
        mailer,
    ).run(NOW)

    assert result.checked_date.isoformat() == "2022-01-05"
    assert result.bonds == ()
    assert result.email_sent is False
    assert mailer.messages == []


def test_multiple_bonds_send_one_combined_email() -> None:
    mailer = StubMailer()

    result = service(
        StubClient([record("第一转债"), record("第二转债")]),
        mailer,
    ).run(NOW)

    assert len(result.bonds) == 2
    assert result.email_sent is True
    assert len(mailer.messages) == 1
    assert "共 2 只可转债" in str(mailer.messages[0]["Subject"])


def test_data_error_sends_failure_email_then_raises_check_failed() -> None:
    original = RuntimeError("data endpoint failed")
    mailer = StubMailer()

    with pytest.raises(CheckFailed) as raised:
        service(StubClient(error=original), mailer).run(NOW)

    assert raised.value.cause is original
    assert raised.value.notification_error is None
    assert len(mailer.messages) == 1
    assert "任务异常" in str(mailer.messages[0]["Subject"])


def test_failure_email_error_preserves_original_as_primary_cause() -> None:
    original = RuntimeError("data endpoint failed")
    notification = OSError("smtp failed")

    with pytest.raises(CheckFailed) as raised:
        service(
            StubClient(error=original),
            StubMailer(error=notification),
        ).run(NOW)

    assert raised.value.cause is original
    assert raised.value.notification_error is notification
    assert "RuntimeError" in str(raised.value)
    assert "OSError" in str(raised.value)


def test_failure_message_build_error_preserves_original_as_primary_cause(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = RuntimeError("data endpoint failed")
    notification = ValueError("message build failed")
    mailer = StubMailer()

    def fail_to_build_message(
        config: MailConfig,
        error: BaseException,
        run_at: datetime,
        run_url: str | None,
    ) -> EmailMessage:
        raise notification

    monkeypatch.setattr(
        service_module,
        "build_failure_message",
        fail_to_build_message,
    )

    with pytest.raises(CheckFailed) as raised:
        service(StubClient(error=original), mailer).run(NOW)

    assert raised.value.cause is original
    assert raised.value.notification_error is notification
    assert mailer.messages == []
    assert "RuntimeError" in str(raised.value)
    assert "ValueError" in str(raised.value)


def test_subscription_email_failure_is_not_reclassified_as_data_error() -> None:
    smtp_error = OSError("smtp failed")
    mailer = StubMailer(error=smtp_error)

    with pytest.raises(OSError) as raised:
        service(StubClient([record("第一转债")]), mailer).run(NOW)

    assert raised.value is smtp_error
    assert len(mailer.messages) == 1


def test_naive_injected_datetime_is_rejected_before_data_fetch() -> None:
    client = StubClient([record("第一转债")])
    mailer = StubMailer()

    with pytest.raises(ValueError, match="timezone-aware"):
        service(client, mailer).run(datetime(2022, 1, 5, 9, 30))

    assert client.fetch_count == 0
    assert mailer.messages == []


def test_aware_utc_time_uses_the_following_beijing_date() -> None:
    mailer = StubMailer()

    result = service(
        StubClient([record("第一转债", "2022-01-06 00:00:00")]),
        mailer,
    ).run(datetime(2022, 1, 5, 16, 30, tzinfo=timezone.utc))

    assert result.checked_date.isoformat() == "2022-01-06"
    assert len(result.bonds) == 1
    assert result.email_sent is True
    assert len(mailer.messages) == 1


def test_malformed_matching_record_sends_one_failure_email() -> None:
    malformed = record("缺少代码转债")
    malformed.pop("SECURITY_CODE")
    mailer = StubMailer()

    with pytest.raises(CheckFailed) as raised:
        service(StubClient([malformed]), mailer).run(NOW)

    assert isinstance(raised.value.cause, DataSourceError)
    assert raised.value.notification_error is None
    assert len(mailer.messages) == 1
    assert "任务异常" in str(mailer.messages[0]["Subject"])
