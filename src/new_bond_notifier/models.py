from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date


_EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class ConfigurationError(ValueError):
    """Raised when required environment configuration is absent or invalid."""


@dataclass(frozen=True, slots=True)
class Bond:
    name: str
    code: str
    subscribe_code: str | None
    subscribe_date: date
    stock_name: str | None
    stock_code: str | None
    issue_price: str | None
    max_subscription: str | None
    rating: str | None


@dataclass(frozen=True, slots=True)
class MailConfig:
    smtp_username: str
    smtp_auth_code: str
    recipients: tuple[str, ...]

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> MailConfig:
        required = ("SMTP_USERNAME", "SMTP_AUTH_CODE", "MAIL_TO")
        missing = [name for name in required if not env.get(name, "").strip()]
        if missing:
            raise ConfigurationError(f"缺少环境变量：{', '.join(missing)}")

        username = env["SMTP_USERNAME"].strip()
        recipients = tuple(
            address.strip()
            for address in env["MAIL_TO"].split(",")
            if address.strip()
        )
        addresses = (username, *recipients)
        if not recipients or any(
            _EMAIL_PATTERN.fullmatch(address) is None for address in addresses
        ):
            raise ConfigurationError("发件或收件邮箱地址格式不正确")

        return cls(
            smtp_username=username,
            smtp_auth_code=env["SMTP_AUTH_CODE"].strip(),
            recipients=recipients,
        )
