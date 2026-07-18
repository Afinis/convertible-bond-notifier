from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from zoneinfo import ZoneInfo

from .eastmoney import EastmoneyClient, parse_bonds_for_date
from .emailer import (
    QQMailer,
    build_failure_message,
    build_subscription_message,
)
from .models import Bond, MailConfig


CN_TZ = ZoneInfo("Asia/Shanghai")


class CheckFailed(RuntimeError):
    def __init__(
        self,
        cause: BaseException,
        notification_error: BaseException | None = None,
    ) -> None:
        self.cause = cause
        self.notification_error = notification_error
        message = f"数据检查失败：{type(cause).__name__}"
        if notification_error is not None:
            message += (
                f"；异常邮件发送失败：{type(notification_error).__name__}"
            )
        super().__init__(message)


@dataclass(frozen=True, slots=True)
class RunResult:
    checked_date: date
    bonds: tuple[Bond, ...]
    email_sent: bool


class NotifierService:
    def __init__(
        self,
        client: EastmoneyClient,
        mailer: QQMailer,
        config: MailConfig,
        run_url: str | None = None,
    ) -> None:
        self.client = client
        self.mailer = mailer
        self.config = config
        self.run_url = run_url

    def run(self, now: datetime | None = None) -> RunResult:
        if now is not None and (
            now.tzinfo is None or now.utcoffset() is None
        ):
            raise ValueError("now must be timezone-aware")
        run_at = now.astimezone(CN_TZ) if now else datetime.now(CN_TZ)
        checked_date = run_at.date()

        try:
            records = self.client.fetch_records()
            bonds = parse_bonds_for_date(records, checked_date)
        except Exception as cause:
            try:
                failure_message = build_failure_message(
                    self.config,
                    cause,
                    run_at,
                    self.run_url,
                )
                self.mailer.send(failure_message)
            except Exception as notification_error:
                raise CheckFailed(cause, notification_error) from cause
            raise CheckFailed(cause) from cause

        if not bonds:
            return RunResult(checked_date, (), False)

        message = build_subscription_message(
            self.config,
            bonds,
            run_at,
        )
        self.mailer.send(message)
        return RunResult(checked_date, tuple(bonds), True)
