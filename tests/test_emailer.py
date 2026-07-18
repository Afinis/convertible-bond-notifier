from datetime import date, datetime
from email.message import EmailMessage
from zoneinfo import ZoneInfo

from new_bond_notifier.emailer import (
    QQMailer,
    build_failure_message,
    build_subscription_message,
    build_test_message,
)
from new_bond_notifier.models import Bond, MailConfig


CN_TZ = ZoneInfo("Asia/Shanghai")
RUN_AT = datetime(2022, 1, 5, 9, 30, tzinfo=CN_TZ)
CONFIG = MailConfig(
    smtp_username="sender@qq.com",
    smtp_auth_code="secret-auth-code",
    recipients=("first@example.com", "second@example.com"),
)


def bond(name: str = "隆22转债") -> Bond:
    return Bond(
        name=name,
        code="113053",
        subscribe_code="783012",
        subscribe_date=date(2022, 1, 5),
        stock_name="隆基股份",
        stock_code="601012",
        issue_price="100 元",
        max_subscription="1000 手（100 万元）",
        rating="AAA",
    )


def message_parts(message: EmailMessage) -> tuple[str, str]:
    plain = message.get_body(preferencelist=("plain",))
    html = message.get_body(preferencelist=("html",))
    assert plain is not None
    assert html is not None
    return plain.get_content(), html.get_content()


def test_subscription_message_combines_bonds_and_recipients() -> None:
    message = build_subscription_message(
        CONFIG, [bond("隆22转债"), bond("第二转债")], RUN_AT
    )
    plain, html = message_parts(message)

    assert message["Subject"] == "[新债申购提醒] 2022-01-05 共 2 只可转债"
    assert message["From"] == "sender@qq.com"
    assert message["To"] == "first@example.com, second@example.com"
    assert "隆22转债" in plain
    assert "第二转债" in plain
    assert "783012" in html
    assert "仅供信息提醒" in plain
    assert "东方财富" in html


def test_subscription_html_escapes_untrusted_text() -> None:
    message = build_subscription_message(CONFIG, [bond("<测试&转债>")], RUN_AT)
    _, html = message_parts(message)

    assert "&lt;测试&amp;转债&gt;" in html
    assert "<测试&转债>" not in html


def test_missing_optional_fields_are_rendered_as_dash() -> None:
    missing = Bond(
        name="测试转债",
        code="123456",
        subscribe_code=None,
        subscribe_date=date(2022, 1, 5),
        stock_name=None,
        stock_code=None,
        issue_price=None,
        max_subscription=None,
        rating=None,
    )

    plain, html = message_parts(
        build_subscription_message(CONFIG, [missing], RUN_AT)
    )

    assert "申购代码：—" in plain
    assert html.count(">—<") >= 5


def test_failure_message_exposes_type_but_not_error_text_or_auth_code() -> None:
    message = build_failure_message(
        CONFIG,
        RuntimeError("secret-auth-code must never appear"),
        RUN_AT,
        "https://github.com/example/repo/actions/runs/123",
    )
    plain, html = message_parts(message)

    assert message["Subject"] == "[新债提醒任务异常] 2022-01-05"
    assert "RuntimeError" in plain
    assert "https://github.com/example/repo/actions/runs/123" in html
    assert "secret-auth-code" not in plain
    assert "secret-auth-code" not in html


def test_test_message_is_unambiguously_not_a_real_subscription() -> None:
    message = build_test_message(CONFIG, RUN_AT)
    plain, html = message_parts(message)

    assert message["Subject"] == "[新债提醒测试] 邮件配置正常"
    assert "不代表当天存在可申购转债" in plain
    assert "不代表当天存在可申购转债" in html


class StubSMTP:
    instances: list["StubSMTP"] = []

    def __init__(self, host: str, port: int, timeout: int) -> None:
        self.host = host
        self.port = port
        self.timeout = timeout
        self.login_args: tuple[str, str] | None = None
        self.sent: EmailMessage | None = None
        StubSMTP.instances.append(self)

    def __enter__(self) -> "StubSMTP":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def login(self, username: str, password: str) -> None:
        self.login_args = (username, password)

    def send_message(self, message: EmailMessage) -> None:
        self.sent = message


def test_qq_mailer_uses_ssl_465_and_authorization_code() -> None:
    StubSMTP.instances.clear()
    message = build_subscription_message(CONFIG, [bond()], RUN_AT)
    mailer = QQMailer(CONFIG, smtp_factory=StubSMTP)

    mailer.send(message)

    smtp = StubSMTP.instances[0]
    assert smtp.host == "smtp.qq.com"
    assert smtp.port == 465
    assert smtp.timeout == 20
    assert smtp.login_args == ("sender@qq.com", "secret-auth-code")
    assert smtp.sent is message
