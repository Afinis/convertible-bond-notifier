from datetime import date

import pytest

from new_bond_notifier.models import Bond, ConfigurationError, MailConfig


def test_bond_is_immutable() -> None:
    bond = Bond(
        name="隆22转债",
        code="113053",
        subscribe_code="783012",
        subscribe_date=date(2022, 1, 5),
        stock_name="隆基股份",
        stock_code="601012",
        issue_price="100 元",
        max_subscription="1000 手（100 万元）",
        rating="AAA",
    )

    with pytest.raises(AttributeError):
        bond.name = "被修改"  # type: ignore[misc]


def test_mail_config_parses_multiple_recipients() -> None:
    config = MailConfig.from_env(
        {
            "SMTP_USERNAME": "sender@qq.com",
            "SMTP_AUTH_CODE": "sixteen-character-code",
            "MAIL_TO": "first@example.com, second@example.com",
        }
    )

    assert config.smtp_username == "sender@qq.com"
    assert config.smtp_auth_code == "sixteen-character-code"
    assert config.recipients == ("first@example.com", "second@example.com")


@pytest.mark.parametrize(
    ("env", "missing_name"),
    [
        (
            {
                "SMTP_AUTH_CODE": "code",
                "MAIL_TO": "to@example.com",
            },
            "SMTP_USERNAME",
        ),
        (
            {
                "SMTP_USERNAME": "sender@qq.com",
                "MAIL_TO": "to@example.com",
            },
            "SMTP_AUTH_CODE",
        ),
        (
            {
                "SMTP_USERNAME": "sender@qq.com",
                "SMTP_AUTH_CODE": "code",
            },
            "MAIL_TO",
        ),
    ],
)
def test_mail_config_rejects_missing_values(
    env: dict[str, str], missing_name: str
) -> None:
    with pytest.raises(ConfigurationError, match=missing_name):
        MailConfig.from_env(env)


def test_mail_config_rejects_invalid_addresses() -> None:
    with pytest.raises(ConfigurationError, match="邮箱地址"):
        MailConfig.from_env(
            {
                "SMTP_USERNAME": "not-an-address",
                "SMTP_AUTH_CODE": "code",
                "MAIL_TO": "to@example.com",
            }
        )
