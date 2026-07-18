# Convertible Bond Email Notifier Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Python program that checks Eastmoney every day at 09:30 Asia/Shanghai and sends one QQ email when A-share convertible bonds are open for subscription that day.

**Architecture:** A small `src`-layout package separates configuration, Eastmoney access, date filtering, email construction, SMTP delivery, orchestration, and the CLI. GitHub Actions runs tests on code changes and runs the notifier on a timezone-aware daily schedule. All network behavior is replaceable in tests, so the automated suite never calls Eastmoney or QQ.

**Tech Stack:** Python 3.12, `requests` 2.x, standard-library `email`/`smtplib`/`zoneinfo`, pytest 8.x, GitHub Actions.

## Global Constraints

- Run once every calendar day at `09:30` in the `Asia/Shanghai` timezone.
- Monitor only A-share convertible bonds whose `PUBLIC_START_DATE` equals the current Beijing date.
- Use the Eastmoney `RPT_BOND_CB_LIST` report directly; do not add AkShare, a database, a web UI, or a second market-data source.
- Send through QQ SMTP SSL at `smtp.qq.com:465`.
- Read `SMTP_USERNAME`, `SMTP_AUTH_CODE`, and `MAIL_TO` only from environment variables.
- Send one combined HTML-and-plain-text email when one or more bonds match; send nothing when zero bonds match.
- Treat an empty/malformed data response or a matching record with missing critical fields as failure, not as “no bonds today.”
- Attempt an exception email for data-fetching, parsing, or filtering failures, then finish with a nonzero exit status.
- Never include the SMTP authorization code, full environment configuration, or full API response in logs or emails.
- Use three total HTTP attempts for transient connection failures, timeouts, HTTP 429, and HTTP 5xx.
- Keep the runtime dependency set to `requests` only.
- Automated tests must not make real HTTP or SMTP calls.
- A manually selected test-email input must verify QQ SMTP without pretending that a real bond is open for subscription; scheduled runs must never select it.

## File Map

- `pyproject.toml`: package metadata, Python floor, dependencies, pytest settings, CLI entry point.
- `.gitignore`: Python and local-secret exclusions.
- `src/new_bond_notifier/__init__.py`: package version.
- `src/new_bond_notifier/models.py`: immutable bond model and validated mail configuration.
- `src/new_bond_notifier/eastmoney.py`: HTTP session, response validation, raw field mapping, and date filtering.
- `src/new_bond_notifier/emailer.py`: multipart message rendering and QQ SMTP SSL transport.
- `src/new_bond_notifier/service.py`: one-run orchestration and failure-notification behavior.
- `src/new_bond_notifier/cli.py`: environment loading, sanitized logging, factories, and exit status.
- `src/new_bond_notifier/__main__.py`: `python -m new_bond_notifier` entry point.
- `tests/test_models.py`: model and environment validation.
- `tests/test_eastmoney.py`: request configuration, response validation, mapping, and date filtering.
- `tests/test_emailer.py`: plain/HTML rendering, escaping, recipients, and SMTP use.
- `tests/test_service.py`: no-bond, multi-bond, and error orchestration.
- `tests/test_cli.py`: exit codes, environment wiring, run URL, and log sanitization.
- `tests/test_workflows.py`: static checks for schedule, permissions, tests, and secret wiring.
- `.github/workflows/tests.yml`: tests on pushes and pull requests.
- `.github/workflows/new-bond-notifier.yml`: scheduled/manual production run.
- `README.md`: Chinese deployment, QQ authorization, manual test, costs, and troubleshooting.

---

### Task 1: Package scaffold, bond model, and mail configuration

**Files:**
- Create: `pyproject.toml`
- Create: `.gitignore`
- Create: `src/new_bond_notifier/__init__.py`
- Create: `src/new_bond_notifier/models.py`
- Test: `tests/test_models.py`

**Interfaces:**
- Produces: `Bond`, `MailConfig`, and `ConfigurationError`.
- `Bond` fields: `name: str`, `code: str`, `subscribe_code: str | None`, `subscribe_date: date`, `stock_name: str | None`, `stock_code: str | None`, `issue_price: str | None`, `max_subscription: str | None`, `rating: str | None`.
- `MailConfig.from_env(env: Mapping[str, str]) -> MailConfig`.

- [ ] **Step 1: Write the failing configuration and model tests**

```python
# tests/test_models.py
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
```

- [ ] **Step 2: Run the model tests and verify the package is missing**

Run: `python -m pytest tests/test_models.py -v`

Expected: collection fails with `ModuleNotFoundError: No module named 'new_bond_notifier'`.

- [ ] **Step 3: Add packaging metadata and local exclusions**

```toml
# pyproject.toml
[build-system]
requires = ["setuptools>=75"]
build-backend = "setuptools.build_meta"

[project]
name = "new-bond-notifier"
version = "0.1.0"
description = "A-share convertible bond subscription email notifier"
requires-python = ">=3.12"
dependencies = [
  "requests>=2.32,<3",
]

[project.optional-dependencies]
test = [
  "pytest>=8,<9",
]

[project.scripts]
new-bond-notifier = "new_bond_notifier.cli:main"

[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "-ra"
```

```gitignore
# .gitignore
__pycache__/
*.py[cod]
.pytest_cache/
.coverage
htmlcov/
.venv/
venv/
build/
dist/
*.egg-info/
.env
.env.*
!.env.example
```

- [ ] **Step 4: Add the immutable models and exact environment validation**

```python
# src/new_bond_notifier/__init__.py
"""Daily A-share convertible bond subscription notifier."""

__version__ = "0.1.0"
```

```python
# src/new_bond_notifier/models.py
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
```

- [ ] **Step 5: Install the package and run the model tests**

Run: `python -m pip install -e ".[test]"`

Expected: installation succeeds.

Run: `python -m pytest tests/test_models.py -v`

Expected: all model tests pass.

- [ ] **Step 6: Commit the scaffold and model**

```powershell
git add pyproject.toml .gitignore src/new_bond_notifier/__init__.py src/new_bond_notifier/models.py tests/test_models.py
git commit -m "feat: add notifier models and configuration"
```

---

### Task 2: Eastmoney client, response validation, and Beijing-date filtering

**Files:**
- Create: `src/new_bond_notifier/eastmoney.py`
- Test: `tests/test_eastmoney.py`

**Interfaces:**
- Consumes: `Bond` from Task 1.
- Produces: `DataSourceError`, `EastmoneyClient.fetch_records() -> list[dict[str, Any]]`, and `parse_bonds_for_date(records: Iterable[Mapping[str, Any]], target_date: date) -> list[Bond]`.
- Uses raw Eastmoney fields `SECURITY_NAME_ABBR`, `SECURITY_CODE`, `CORRECODE`, `PUBLIC_START_DATE`, `SECURITY_SHORT_NAME`, `CONVERT_STOCK_CODE`, `ISSUE_PRICE`, `ONLINE_GENERAL_AAU`, and `RATING`.

- [ ] **Step 1: Write failing tests for request parameters and response validation**

```python
# tests/test_eastmoney.py
from datetime import date
from typing import Any

import pytest

from new_bond_notifier.eastmoney import (
    DataSourceError,
    EastmoneyClient,
    parse_bonds_for_date,
)


class StubResponse:
    def __init__(self, payload: Any) -> None:
        self.payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> Any:
        if isinstance(self.payload, Exception):
            raise self.payload
        return self.payload


class StubSession:
    def __init__(self, payload: Any) -> None:
        self.payload = payload
        self.calls: list[dict[str, Any]] = []

    def get(self, url: str, **kwargs: Any) -> StubResponse:
        self.calls.append({"url": url, **kwargs})
        return StubResponse(self.payload)


def sample_record(**overrides: Any) -> dict[str, Any]:
    record: dict[str, Any] = {
        "SECURITY_NAME_ABBR": "隆22转债",
        "SECURITY_CODE": "113053",
        "CORRECODE": "783012",
        "PUBLIC_START_DATE": "2022-01-05 00:00:00",
        "SECURITY_SHORT_NAME": "隆基股份",
        "CONVERT_STOCK_CODE": "601012",
        "ISSUE_PRICE": 100,
        "ONLINE_GENERAL_AAU": 1000,
        "RATING": "AAA",
    }
    record.update(overrides)
    return record


def test_fetch_records_uses_expected_report_and_timeouts() -> None:
    session = StubSession(
        {"result": {"data": [sample_record()], "pages": 1}}
    )
    client = EastmoneyClient(session=session)  # type: ignore[arg-type]

    records = client.fetch_records()

    assert len(records) == 1
    call = session.calls[0]
    assert call["url"] == EastmoneyClient.URL
    assert call["timeout"] == (5, 15)
    assert call["params"]["reportName"] == "RPT_BOND_CB_LIST"
    assert call["params"]["sortColumns"] == "PUBLIC_START_DATE"
    assert call["params"]["sortTypes"] == "-1"
    assert call["params"]["pageSize"] == 100


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"result": None},
        {"result": {}},
        {"result": {"data": None}},
        {"result": {"data": []}},
    ],
)
def test_fetch_records_rejects_empty_or_malformed_payload(payload: Any) -> None:
    client = EastmoneyClient(
        session=StubSession(payload)  # type: ignore[arg-type]
    )

    with pytest.raises(DataSourceError):
        client.fetch_records()


def test_fetch_records_rejects_non_json_payload() -> None:
    client = EastmoneyClient(
        session=StubSession(ValueError("invalid json"))  # type: ignore[arg-type]
    )

    with pytest.raises(DataSourceError, match="JSON"):
        client.fetch_records()


def test_default_session_has_three_total_transient_attempts() -> None:
    client = EastmoneyClient()
    retry = client.session.get_adapter("https://").max_retries

    assert retry.total == 2
    assert retry.connect == 2
    assert retry.read == 2
    assert set(retry.status_forcelist) == {429, 500, 502, 503, 504}
```

- [ ] **Step 2: Add failing field-mapping and date-filter tests**

Append to `tests/test_eastmoney.py`:

```python
def test_parse_bonds_for_date_maps_all_display_fields() -> None:
    bonds = parse_bonds_for_date(
        [sample_record()], target_date=date(2022, 1, 5)
    )

    assert len(bonds) == 1
    bond = bonds[0]
    assert bond.name == "隆22转债"
    assert bond.code == "113053"
    assert bond.subscribe_code == "783012"
    assert bond.subscribe_date == date(2022, 1, 5)
    assert bond.stock_name == "隆基股份"
    assert bond.stock_code == "601012"
    assert bond.issue_price == "100 元"
    assert bond.max_subscription == "1000 手（100 万元）"
    assert bond.rating == "AAA"


def test_parse_bonds_for_date_ignores_other_dates() -> None:
    bonds = parse_bonds_for_date(
        [
            sample_record(PUBLIC_START_DATE="2022-01-04 00:00:00"),
            sample_record(PUBLIC_START_DATE="2022-01-06 00:00:00"),
        ],
        target_date=date(2022, 1, 5),
    )

    assert bonds == []


def test_parse_bonds_for_date_uses_none_for_optional_fields() -> None:
    record = sample_record()
    for field in (
        "CORRECODE",
        "SECURITY_SHORT_NAME",
        "CONVERT_STOCK_CODE",
        "ISSUE_PRICE",
        "ONLINE_GENERAL_AAU",
        "RATING",
    ):
        record.pop(field)

    bond = parse_bonds_for_date(
        [record], target_date=date(2022, 1, 5)
    )[0]

    assert bond.subscribe_code is None
    assert bond.stock_name is None
    assert bond.stock_code is None
    assert bond.issue_price is None
    assert bond.max_subscription is None
    assert bond.rating is None


@pytest.mark.parametrize("critical_field", ["SECURITY_NAME_ABBR", "SECURITY_CODE"])
def test_matching_record_requires_critical_identity_fields(
    critical_field: str,
) -> None:
    record = sample_record()
    record.pop(critical_field)

    with pytest.raises(DataSourceError, match=critical_field):
        parse_bonds_for_date([record], target_date=date(2022, 1, 5))


@pytest.mark.parametrize(
    "raw_date",
    [None, "", "not-a-date", "2022-13-99 00:00:00"],
)
def test_every_record_requires_a_parseable_subscription_date(
    raw_date: Any,
) -> None:
    with pytest.raises(DataSourceError, match="PUBLIC_START_DATE"):
        parse_bonds_for_date(
            [sample_record(PUBLIC_START_DATE=raw_date)],
            target_date=date(2022, 1, 5),
        )


def test_html_like_text_is_preserved_for_later_escaping() -> None:
    bond = parse_bonds_for_date(
        [sample_record(SECURITY_NAME_ABBR="<测试&转债>")],
        target_date=date(2022, 1, 5),
    )[0]

    assert bond.name == "<测试&转债>"
```

- [ ] **Step 3: Run the Eastmoney tests and verify the module is missing**

Run: `python -m pytest tests/test_eastmoney.py -v`

Expected: collection fails with `ModuleNotFoundError: No module named 'new_bond_notifier.eastmoney'`.

- [ ] **Step 4: Implement the HTTP client and strict response validation**

```python
# src/new_bond_notifier/eastmoney.py
from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .models import Bond


class DataSourceError(RuntimeError):
    """Raised when Eastmoney cannot provide a trustworthy bond dataset."""


class EastmoneyClient:
    URL = "https://datacenter-web.eastmoney.com/api/data/v1/get"

    def __init__(self, session: requests.Session | None = None) -> None:
        self.session = session or self._build_session()

    @staticmethod
    def _build_session() -> requests.Session:
        retry = Retry(
            total=2,
            connect=2,
            read=2,
            status=2,
            backoff_factor=0.5,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=frozenset({"GET"}),
            raise_on_status=True,
        )
        session = requests.Session()
        session.headers.update(
            {
                "Accept": "application/json,text/plain,*/*",
                "User-Agent": "new-bond-notifier/0.1",
            }
        )
        session.mount("https://", HTTPAdapter(max_retries=retry))
        return session

    def fetch_records(self) -> list[dict[str, Any]]:
        try:
            response = self.session.get(
                self.URL,
                params={
                    "reportName": "RPT_BOND_CB_LIST",
                    "columns": "ALL",
                    "sortColumns": "PUBLIC_START_DATE",
                    "sortTypes": "-1",
                    "pageNumber": 1,
                    "pageSize": 100,
                    "source": "WEB",
                    "client": "WEB",
                },
                timeout=(5, 15),
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            raise DataSourceError("东方财富请求失败") from exc

        try:
            payload = response.json()
        except ValueError as exc:
            raise DataSourceError("东方财富返回的内容不是有效 JSON") from exc

        if not isinstance(payload, dict):
            raise DataSourceError("东方财富 JSON 顶层结构异常")
        result = payload.get("result")
        if not isinstance(result, dict):
            raise DataSourceError("东方财富响应缺少 result 对象")
        records = result.get("data")
        if not isinstance(records, list) or not records:
            raise DataSourceError("东方财富可转债数据为空或结构异常")
        if not all(isinstance(record, dict) for record in records):
            raise DataSourceError("东方财富可转债记录不是对象")
        return records
```

- [ ] **Step 5: Implement strict date filtering and raw-field formatting**

Append to `src/new_bond_notifier/eastmoney.py`:

```python
def _subscription_date(record: Mapping[str, Any]) -> date:
    raw = record.get("PUBLIC_START_DATE")
    if not isinstance(raw, str) or len(raw) < 10:
        raise DataSourceError("字段 PUBLIC_START_DATE 缺失或格式错误")
    try:
        return date.fromisoformat(raw[:10])
    except ValueError as exc:
        raise DataSourceError("字段 PUBLIC_START_DATE 无法解析") from exc


def _required_text(record: Mapping[str, Any], field: str) -> str:
    value = record.get(field)
    if value is None or not str(value).strip():
        raise DataSourceError(f"当日转债缺少关键字段 {field}")
    return str(value).strip()


def _optional_text(record: Mapping[str, Any], field: str) -> str | None:
    value = record.get(field)
    if value is None or not str(value).strip():
        return None
    return str(value).strip()


def _plain_decimal(value: Any) -> str | None:
    if value is None or not str(value).strip():
        return None
    try:
        decimal_value = Decimal(str(value))
    except InvalidOperation:
        return str(value).strip()
    return format(decimal_value.normalize(), "f")


def _issue_price(value: Any) -> str | None:
    plain = _plain_decimal(value)
    return f"{plain} 元" if plain is not None else None


def _max_subscription(value: Any) -> str | None:
    plain = _plain_decimal(value)
    if plain is None:
        return None
    try:
        hands = Decimal(plain)
    except InvalidOperation:
        return plain
    ten_thousand_yuan = hands / Decimal("10")
    return (
        f"{format(hands.normalize(), 'f')} 手"
        f"（{format(ten_thousand_yuan.normalize(), 'f')} 万元）"
    )


def parse_bonds_for_date(
    records: Iterable[Mapping[str, Any]], target_date: date
) -> list[Bond]:
    bonds: list[Bond] = []
    for record in records:
        subscribe_date = _subscription_date(record)
        if subscribe_date != target_date:
            continue
        bonds.append(
            Bond(
                name=_required_text(record, "SECURITY_NAME_ABBR"),
                code=_required_text(record, "SECURITY_CODE"),
                subscribe_code=_optional_text(record, "CORRECODE"),
                subscribe_date=subscribe_date,
                stock_name=_optional_text(record, "SECURITY_SHORT_NAME"),
                stock_code=_optional_text(record, "CONVERT_STOCK_CODE"),
                issue_price=_issue_price(record.get("ISSUE_PRICE")),
                max_subscription=_max_subscription(
                    record.get("ONLINE_GENERAL_AAU")
                ),
                rating=_optional_text(record, "RATING"),
            )
        )
    return bonds
```

- [ ] **Step 6: Run the Eastmoney tests**

Run: `python -m pytest tests/test_eastmoney.py -v`

Expected: all Eastmoney tests pass.

- [ ] **Step 7: Commit the data client**

```powershell
git add src/new_bond_notifier/eastmoney.py tests/test_eastmoney.py
git commit -m "feat: fetch and filter Eastmoney bond data"
```

---

### Task 3: Multipart email rendering and QQ SMTP SSL delivery

**Files:**
- Create: `src/new_bond_notifier/emailer.py`
- Test: `tests/test_emailer.py`

**Interfaces:**
- Consumes: `Bond` and `MailConfig` from Task 1.
- Produces: `build_subscription_message(config, bonds, run_at) -> EmailMessage`, `build_failure_message(config, error, run_at, run_url) -> EmailMessage`, `build_test_message(config, run_at) -> EmailMessage`, and `QQMailer.send(message) -> None`.
- `run_at` must be timezone-aware and already expressed in `Asia/Shanghai`.

- [ ] **Step 1: Write failing multipart rendering tests**

```python
# tests/test_emailer.py
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
```

- [ ] **Step 2: Add a failing SMTP transport test**

Append to `tests/test_emailer.py`:

```python
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
```

- [ ] **Step 3: Run the email tests and verify the module is missing**

Run: `python -m pytest tests/test_emailer.py -v`

Expected: collection fails with `ModuleNotFoundError: No module named 'new_bond_notifier.emailer'`.

- [ ] **Step 4: Implement safe multipart message construction**

```python
# src/new_bond_notifier/emailer.py
from __future__ import annotations

import html
import smtplib
from collections.abc import Callable, Sequence
from datetime import datetime
from email.message import EmailMessage
from typing import Any

from .models import Bond, MailConfig


def _display(value: str | None) -> str:
    return value if value is not None else "—"


def _base_message(config: MailConfig, subject: str) -> EmailMessage:
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = config.smtp_username
    message["To"] = ", ".join(config.recipients)
    return message


def build_subscription_message(
    config: MailConfig,
    bonds: Sequence[Bond],
    run_at: datetime,
) -> EmailMessage:
    subject = (
        f"[新债申购提醒] {run_at.date().isoformat()} "
        f"共 {len(bonds)} 只可转债"
    )
    message = _base_message(config, subject)

    lines = [
        f"{run_at.date().isoformat()} 有 {len(bonds)} 只可转债可申购：",
        "",
    ]
    for index, bond in enumerate(bonds, start=1):
        lines.extend(
            [
                f"{index}. {bond.name}",
                f"债券代码：{bond.code}",
                f"申购代码：{_display(bond.subscribe_code)}",
                f"申购日期：{bond.subscribe_date.isoformat()}",
                f"正股名称：{_display(bond.stock_name)}",
                f"正股代码：{_display(bond.stock_code)}",
                f"发行价格：{_display(bond.issue_price)}",
                f"申购上限：{_display(bond.max_subscription)}",
                f"债券评级：{_display(bond.rating)}",
                "",
            ]
        )
    lines.extend(
        [
            f"查询时间：{run_at:%Y-%m-%d %H:%M:%S}（北京时间）",
            "数据来源：东方财富。",
            "本邮件仅供信息提醒，不构成投资建议；请以交易所公告和证券账户信息为准。",
        ]
    )
    message.set_content("\n".join(lines))

    headers = (
        "转债名称",
        "债券代码",
        "申购代码",
        "申购日期",
        "正股名称",
        "正股代码",
        "发行价格",
        "申购上限",
        "债券评级",
    )
    rows = []
    for bond in bonds:
        values = (
            bond.name,
            bond.code,
            _display(bond.subscribe_code),
            bond.subscribe_date.isoformat(),
            _display(bond.stock_name),
            _display(bond.stock_code),
            _display(bond.issue_price),
            _display(bond.max_subscription),
            _display(bond.rating),
        )
        cells = "".join(
            f"<td>{html.escape(value)}</td>" for value in values
        )
        rows.append(f"<tr>{cells}</tr>")
    html_body = f"""\
<html>
  <body>
    <p>{run_at.date().isoformat()} 有 {len(bonds)} 只可转债可申购：</p>
    <table style="border-collapse:collapse" border="1" cellpadding="6">
      <thead><tr>{''.join(f"<th>{header}</th>" for header in headers)}</tr></thead>
      <tbody>{''.join(rows)}</tbody>
    </table>
    <p>查询时间：{run_at:%Y-%m-%d %H:%M:%S}（北京时间）</p>
    <p>数据来源：东方财富。</p>
    <p>本邮件仅供信息提醒，不构成投资建议；请以交易所公告和证券账户信息为准。</p>
  </body>
</html>
"""
    message.add_alternative(html_body, subtype="html")
    return message


def build_failure_message(
    config: MailConfig,
    error: BaseException,
    run_at: datetime,
    run_url: str | None,
) -> EmailMessage:
    subject = f"[新债提醒任务异常] {run_at.date().isoformat()}"
    message = _base_message(config, subject)
    error_type = type(error).__name__
    safe_url = run_url or "请在 GitHub 仓库的 Actions 页面查看本次运行。"
    plain = "\n".join(
        [
            "新债提醒任务执行失败。",
            f"失败阶段：数据获取、解析或日期筛选",
            f"错误类型：{error_type}",
            f"发生时间：{run_at:%Y-%m-%d %H:%M:%S}（北京时间）",
            f"运行详情：{safe_url}",
            "为避免泄露敏感数据，邮件未包含原始响应或环境配置。",
        ]
    )
    message.set_content(plain)
    message.add_alternative(
        f"""\
<html><body>
<p>新债提醒任务执行失败。</p>
<ul>
  <li>失败阶段：数据获取、解析或日期筛选</li>
  <li>错误类型：{html.escape(error_type)}</li>
  <li>发生时间：{run_at:%Y-%m-%d %H:%M:%S}（北京时间）</li>
  <li>运行详情：{html.escape(safe_url)}</li>
</ul>
<p>为避免泄露敏感数据，邮件未包含原始响应或环境配置。</p>
</body></html>
""",
        subtype="html",
    )
    return message


def build_test_message(
    config: MailConfig,
    run_at: datetime,
) -> EmailMessage:
    message = _base_message(config, "[新债提醒测试] 邮件配置正常")
    message.set_content(
        "\n".join(
            [
                "这是一封新债提醒程序的 SMTP 配置测试邮件。",
                "收到此邮件说明 QQ 邮箱授权码和收件地址可用。",
                "本邮件不代表当天存在可申购转债。",
                f"测试时间：{run_at:%Y-%m-%d %H:%M:%S}（北京时间）",
            ]
        )
    )
    message.add_alternative(
        f"""\
<html><body>
<p>这是一封新债提醒程序的 SMTP 配置测试邮件。</p>
<p>收到此邮件说明 QQ 邮箱授权码和收件地址可用。</p>
<p><strong>本邮件不代表当天存在可申购转债。</strong></p>
<p>测试时间：{run_at:%Y-%m-%d %H:%M:%S}（北京时间）</p>
</body></html>
""",
        subtype="html",
    )
    return message
```

- [ ] **Step 5: Implement QQ SMTP SSL delivery**

Append to `src/new_bond_notifier/emailer.py`:

```python
class QQMailer:
    def __init__(
        self,
        config: MailConfig,
        smtp_factory: Callable[..., Any] = smtplib.SMTP_SSL,
    ) -> None:
        self.config = config
        self.smtp_factory = smtp_factory

    def send(self, message: EmailMessage) -> None:
        with self.smtp_factory(
            "smtp.qq.com", 465, timeout=20
        ) as smtp:
            smtp.login(
                self.config.smtp_username,
                self.config.smtp_auth_code,
            )
            smtp.send_message(message)
```

- [ ] **Step 6: Run the email tests**

Run: `python -m pytest tests/test_emailer.py -v`

Expected: all email tests pass.

- [ ] **Step 7: Commit the mail component**

```powershell
git add src/new_bond_notifier/emailer.py tests/test_emailer.py
git commit -m "feat: render and send QQ notification emails"
```

---

### Task 4: One-run orchestration and exception notification

**Files:**
- Create: `src/new_bond_notifier/service.py`
- Test: `tests/test_service.py`

**Interfaces:**
- Consumes: `EastmoneyClient.fetch_records`, `parse_bonds_for_date`, `QQMailer.send`, and both message builders.
- Produces: `RunResult`, `CheckFailed`, and `NotifierService.run(now: datetime | None = None) -> RunResult`.
- A data/parse/filter error is wrapped in `CheckFailed`; `CheckFailed.cause` remains the primary error and `notification_error` records failure of the exception email.

- [ ] **Step 1: Write failing no-bond and combined-message service tests**

```python
# tests/test_service.py
from datetime import datetime
from email.message import EmailMessage
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from new_bond_notifier.models import MailConfig
from new_bond_notifier.service import CheckFailed, NotifierService


CN_TZ = ZoneInfo("Asia/Shanghai")
NOW = datetime(2022, 1, 5, 9, 30, tzinfo=CN_TZ)
CONFIG = MailConfig(
    smtp_username="sender@qq.com",
    smtp_auth_code="secret",
    recipients=("to@example.com",),
)


def record(name: str, raw_date: str = "2022-01-05 00:00:00") -> dict[str, Any]:
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

    def fetch_records(self) -> list[dict[str, Any]]:
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
```

- [ ] **Step 2: Add failing data-error and notification-error tests**

Append to `tests/test_service.py`:

```python
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


def test_subscription_email_failure_is_not_reclassified_as_data_error() -> None:
    smtp_error = OSError("smtp failed")
    mailer = StubMailer(error=smtp_error)

    with pytest.raises(OSError) as raised:
        service(StubClient([record("第一转债")]), mailer).run(NOW)

    assert raised.value is smtp_error
    assert len(mailer.messages) == 1
```

- [ ] **Step 3: Run the service tests and verify the module is missing**

Run: `python -m pytest tests/test_service.py -v`

Expected: collection fails with `ModuleNotFoundError: No module named 'new_bond_notifier.service'`.

- [ ] **Step 4: Implement timezone-safe orchestration**

```python
# src/new_bond_notifier/service.py
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
        run_at = now.astimezone(CN_TZ) if now else datetime.now(CN_TZ)
        checked_date = run_at.date()

        try:
            records = self.client.fetch_records()
            bonds = parse_bonds_for_date(records, checked_date)
        except Exception as cause:
            failure_message = build_failure_message(
                self.config,
                cause,
                run_at,
                self.run_url,
            )
            try:
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
```

- [ ] **Step 5: Run the service tests and the suite so far**

Run: `python -m pytest tests/test_service.py -v`

Expected: all service tests pass.

Run: `python -m pytest -v`

Expected: all tests created in Tasks 1–4 pass.

- [ ] **Step 6: Commit the orchestration**

```powershell
git add src/new_bond_notifier/service.py tests/test_service.py
git commit -m "feat: orchestrate daily bond notifications"
```

---

### Task 5: CLI, sanitized logs, and process exit behavior

**Files:**
- Create: `src/new_bond_notifier/cli.py`
- Create: `src/new_bond_notifier/__main__.py`
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: all production components from Tasks 1–4.
- Produces: `github_run_url(env) -> str | None` and `main(env=None, client_factory=..., mailer_factory=..., service_factory=...) -> int`.
- Exit `0` for valid no-bond or sent-bond runs; exit `1` for configuration, data, parsing, or SMTP failures.

- [ ] **Step 1: Write failing CLI configuration, success, and log tests**

```python
# tests/test_cli.py
import logging
from collections.abc import Mapping
from datetime import date
from typing import Any

from new_bond_notifier.cli import github_run_url, main
from new_bond_notifier.service import RunResult


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
```

- [ ] **Step 2: Run the CLI tests and verify the module is missing**

Run: `python -m pytest tests/test_cli.py -v`

Expected: collection fails with `ModuleNotFoundError: No module named 'new_bond_notifier.cli'`.

- [ ] **Step 3: Implement the CLI with injectable factories and sanitized logging**

```python
# src/new_bond_notifier/cli.py
from __future__ import annotations

import logging
import os
from collections.abc import Mapping
from datetime import datetime
from typing import Any, Callable
from zoneinfo import ZoneInfo

from .eastmoney import EastmoneyClient
from .emailer import QQMailer, build_test_message
from .models import MailConfig
from .service import NotifierService


LOGGER = logging.getLogger("new_bond_notifier")
CN_TZ = ZoneInfo("Asia/Shanghai")


def github_run_url(env: Mapping[str, str]) -> str | None:
    server = env.get("GITHUB_SERVER_URL", "").rstrip("/")
    repository = env.get("GITHUB_REPOSITORY", "").strip("/")
    run_id = env.get("GITHUB_RUN_ID", "").strip()
    if not (server and repository and run_id):
        return None
    return f"{server}/{repository}/actions/runs/{run_id}"


def _test_email_requested(env: Mapping[str, str]) -> bool:
    return env.get("SEND_TEST_EMAIL", "").strip().lower() in {
        "1",
        "true",
        "yes",
    }


def main(
    env: Mapping[str, str] | None = None,
    client_factory: Callable[[], Any] = EastmoneyClient,
    mailer_factory: Callable[[MailConfig], Any] = QQMailer,
    service_factory: Callable[..., Any] = NotifierService,
) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    actual_env = os.environ if env is None else env

    try:
        config = MailConfig.from_env(actual_env)
        mailer = mailer_factory(config)
        if _test_email_requested(actual_env):
            mailer.send(
                build_test_message(config, datetime.now(CN_TZ))
            )
            LOGGER.info("QQ SMTP 测试邮件已发送")
            return 0

        client = client_factory()
        notifier = service_factory(
            client=client,
            mailer=mailer,
            config=config,
            run_url=github_run_url(actual_env),
        )
        result = notifier.run()
    except Exception as exc:
        LOGGER.error("任务失败：%s", type(exc).__name__)
        return 1

    if result.email_sent:
        LOGGER.info(
            "%s 共发现 %d 只可申购转债，提醒邮件已发送",
            result.checked_date.isoformat(),
            len(result.bonds),
        )
    else:
        LOGGER.info(
            "%s 没有可申购转债，无需发送邮件",
            result.checked_date.isoformat(),
        )
    return 0
```

```python
# src/new_bond_notifier/__main__.py
from .cli import main


raise SystemExit(main())
```

- [ ] **Step 4: Run the CLI tests and all Python tests**

Run: `python -m pytest tests/test_cli.py -v`

Expected: all CLI tests pass.

Run: `python -m pytest -v`

Expected: all Python tests pass.

- [ ] **Step 5: Verify the installed CLI fails safely without secrets**

Run: `new-bond-notifier`

Expected: one sanitized `任务失败：ConfigurationError` log line and process exit code `1`; no traceback and no credential values.

- [ ] **Step 6: Commit the CLI**

```powershell
git add src/new_bond_notifier/cli.py src/new_bond_notifier/__main__.py tests/test_cli.py
git commit -m "feat: add safe notifier command line entry point"
```

---

### Task 6: GitHub Actions test and daily notifier workflows

**Files:**
- Create: `.github/workflows/tests.yml`
- Create: `.github/workflows/new-bond-notifier.yml`
- Test: `tests/test_workflows.py`

**Interfaces:**
- Consumes: the `python -m new_bond_notifier` CLI and `.[test]` optional dependencies.
- Produces: a test workflow for `push`/`pull_request`, plus a production workflow for `schedule`/`workflow_dispatch`.
- The production workflow maps GitHub Secrets to the exact environment names consumed by `MailConfig`.

- [ ] **Step 1: Write failing static workflow tests**

```python
# tests/test_workflows.py
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
```

- [ ] **Step 2: Run the workflow tests and verify both files are absent**

Run: `python -m pytest tests/test_workflows.py -v`

Expected: tests fail with `FileNotFoundError` for `.github/workflows/tests.yml`.

- [ ] **Step 3: Add the push and pull-request test workflow**

```yaml
# .github/workflows/tests.yml
name: Tests

on:
  push:
  pull_request:

permissions:
  contents: read

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - name: Check out repository
        uses: actions/checkout@v4
      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.12"
          cache: pip
      - name: Install package and test dependencies
        run: python -m pip install -e ".[test]"
      - name: Run tests
        run: python -m pytest -v
```

- [ ] **Step 4: Add the timezone-aware production workflow**

```yaml
# .github/workflows/new-bond-notifier.yml
name: New bond notifier

on:
  schedule:
    - cron: "30 9 * * *"
      timezone: Asia/Shanghai
  workflow_dispatch:
    inputs:
      send_test_email:
        description: Send an SMTP configuration test email
        required: true
        default: false
        type: boolean

permissions:
  contents: read

concurrency:
  group: new-bond-notifier
  cancel-in-progress: false

jobs:
  notify:
    runs-on: ubuntu-latest
    timeout-minutes: 10
    steps:
      - name: Check out repository
        uses: actions/checkout@v4
      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.12"
          cache: pip
      - name: Install package and test dependencies
        run: python -m pip install -e ".[test]"
      - name: Run tests
        run: python -m pytest -v
      - name: Check subscriptions and notify
        env:
          SMTP_USERNAME: ${{ secrets.SMTP_USERNAME }}
          SMTP_AUTH_CODE: ${{ secrets.SMTP_AUTH_CODE }}
          MAIL_TO: ${{ secrets.MAIL_TO }}
          SEND_TEST_EMAIL: ${{ inputs.send_test_email }}
        run: python -m new_bond_notifier
```

- [ ] **Step 5: Run workflow tests and the full suite**

Run: `python -m pytest tests/test_workflows.py -v`

Expected: all workflow tests pass.

Run: `python -m pytest -v`

Expected: the complete suite passes.

- [ ] **Step 6: Commit both workflows**

```powershell
git add .github/workflows/tests.yml .github/workflows/new-bond-notifier.yml tests/test_workflows.py
git commit -m "ci: schedule daily new bond notifications"
```

---

### Task 7: Chinese deployment and operations guide

**Files:**
- Create: `README.md`
- Modify: `pyproject.toml`

**Interfaces:**
- Documents the exact three Secrets consumed by the program and the two supported workflow triggers.
- Explicitly states that the first production SMTP check requires the user’s own QQ authorization code and target GitHub repository.

- [ ] **Step 1: Write the complete Chinese README**

```markdown
# 新债申购邮件提醒

每天北京时间 09:30 查询 A 股当天可申购的可转债。如果有可申购转债，
程序会通过 QQ 邮箱发送一封合并提醒；如果没有，则静默结束。数据获取或解析
失败时，程序会尝试发送异常邮件，并让 GitHub Actions 显示失败。

> 本项目仅作信息提醒，不构成投资建议。申购前请以交易所公告和证券账户信息
> 为准。

## 功能

- 东方财富 `RPT_BOND_CB_LIST` 可转债数据
- 北京时间日期判断
- 多只转债合并提醒
- HTML 与纯文本双格式邮件
- 请求超时和临时故障重试
- 数据结构异常提醒
- GitHub Actions 定时和手动运行
- 自动化测试不访问真实接口或邮箱

## 费用

东方财富公开网页接口和 QQ SMTP 不要求付费。GitHub Free 私有仓库目前每月
包含 2,000 分钟 Actions 额度，本任务每天通常只占约 1 分钟。建议在 GitHub
账单设置中启用“达到预算后停止使用”，避免其他工作流消耗额度后产生费用。

## 1. 获取 QQ 邮箱 SMTP 授权码

1. 登录 QQ 邮箱网页版。
2. 打开“设置”中的账号与安全相关设置。
3. 开启 SMTP 服务。
4. 按页面提示生成授权码。
5. 单独保存授权码。程序使用授权码，不使用 QQ 登录密码。

QQ 发信服务器已固定为 `smtp.qq.com:465`，并使用 SSL。

## 2. 创建私有 GitHub 仓库

在 GitHub 创建一个 Private 仓库，将本项目的 `main` 分支推送到该仓库。
定时工作流只在默认分支运行，因此默认分支应为 `main`。

## 3. 配置 GitHub Secrets

进入仓库的 Settings → Secrets and variables → Actions，创建三个
Repository secrets：

| Secret | 内容 |
| --- | --- |
| `SMTP_USERNAME` | 完整 QQ 邮箱地址 |
| `SMTP_AUTH_CODE` | QQ 邮箱 SMTP 授权码 |
| `MAIL_TO` | 收件地址；多个地址用英文逗号分隔 |

不要把授权码写入代码、README、Issue 或 Actions 日志。

## 4. 首次手动运行

1. 打开仓库的 Actions 页面。
2. 选择 `New bond notifier`。
3. 点击 `Run workflow`，选择 `main` 分支。
4. 首次验证时勾选 `send_test_email`，然后运行。
5. 收到主题为 `[新债提醒测试] 邮件配置正常` 的邮件后，说明 QQ SMTP 配置
   可用。该邮件会明确注明它不代表当天存在可申购转债。
6. 日常手动检查不要勾选 `send_test_email`。
7. 查看 `Check subscriptions and notify` 步骤。

如果当天没有可申购转债，日志会显示“无需发送邮件”，不会收到申购提醒。

## 5. 定时运行

`.github/workflows/new-bond-notifier.yml` 使用 `Asia/Shanghai` 时区，
目标时间为每天 09:30。GitHub 官方说明计划任务在平台繁忙时可能延迟，因此
该时间不是秒级保证。

## 本地开发

要求 Python 3.12：

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[test]"
python -m pytest -v
```

本地执行真实检查前，在当前终端设置环境变量：

```powershell
$env:SMTP_USERNAME = "你的完整QQ邮箱"
$env:SMTP_AUTH_CODE = "你的QQ邮箱SMTP授权码"
$env:MAIL_TO = "你的收件地址"
python -m new_bond_notifier
```

不要把上述值保存到受 Git 跟踪的文件中。

## 运行结果

- 有当日申购：发送一封 `[新债申购提醒]` 邮件，任务成功。
- 无当日申购：不发送邮件，任务成功。
- 数据请求或解析失败：尝试发送 `[新债提醒任务异常]` 邮件，任务失败。
- QQ SMTP 失败：无法通过同一邮箱发送异常邮件，任务失败；请查看 Actions
  状态或启用 GitHub 自身的工作流失败通知。

## 常见问题

### SMTP 登录失败

确认使用的是 SMTP 授权码而不是 QQ 密码，并确认 QQ 邮箱已经开启 SMTP 服务。

### 没有收到邮件

检查垃圾邮件、`MAIL_TO`、Actions 日志和 QQ 邮箱发信限制。多个收件地址必须
使用英文逗号分隔。

### Actions 没有准时运行

GitHub 计划任务可能延迟。确认工作流文件位于默认分支，并在 Actions 页面确认
工作流处于启用状态。

### 东方财富接口报错

程序会对临时错误进行三次总尝试。如果接口字段已改变，自动重试不会解决问题，
需要根据 Actions 中的错误类型更新 `eastmoney.py` 的字段适配。

## 数据与安全限制

- 东方财富网页接口没有服务等级承诺，未来可能调整。
- 程序没有第二数据源，无法自动核验格式正确但业务内容错误的数据。
- 手动重复运行会重复发送提醒，首版不使用数据库去重。
- 程序不会登录券商账户，也不会自动申购。

## 参考资料

- [GitHub Actions 计划任务](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows)
- [GitHub Actions 免费额度](https://docs.github.com/en/billing/reference/product-usage-included)
- [东方财富可转债数据](https://data.eastmoney.com/kzz/)
```

- [ ] **Step 2: Register the completed README in package metadata**

Add this line immediately after `description` in the `[project]` table:

```toml
readme = "README.md"
```

- [ ] **Step 3: Verify README commands and references**

Run: `python -m pip install -e ".[test]"`

Expected: editable installation succeeds without a missing-readme warning.

Run: `python -m pytest -v`

Expected: all tests pass.

Run: `rg -n "SMTP_AUTH_CODE|09:30|Asia/Shanghai|不构成投资建议" README.md`

Expected: all four required operational topics appear in the README.

- [ ] **Step 4: Commit the operations guide**

```powershell
git add README.md pyproject.toml
git commit -m "docs: add notifier deployment guide"
```

---

### Task 8: Final verification and deployment handoff

**Files:**
- Modify only files implicated by verification failures.

**Interfaces:**
- Produces a clean local `main` branch ready to push to a user-approved private GitHub repository.
- Does not create or push to an external repository until the user approves the target repository name/account.

- [ ] **Step 1: Run the complete automated suite from a clean install**

Run: `python -m pip install -e ".[test]"`

Expected: installation succeeds.

Run: `python -m pytest -v`

Expected: all tests pass with zero failures, errors, or real-network calls.

- [ ] **Step 2: Run packaging and whitespace checks**

Run: `python -m compileall -q src tests`

Expected: exit code `0`.

Run: `git diff --check`

Expected: no output and exit code `0`.

- [ ] **Step 3: Confirm the CLI’s safe missing-secret behavior**

Run: `Remove-Item Env:SMTP_USERNAME -ErrorAction SilentlyContinue`

Run: `Remove-Item Env:SMTP_AUTH_CODE -ErrorAction SilentlyContinue`

Run: `Remove-Item Env:MAIL_TO -ErrorAction SilentlyContinue`

Run: `python -m new_bond_notifier`

Expected: sanitized `任务失败：ConfigurationError` log and process exit code `1`; no secret values or traceback.

- [ ] **Step 4: Inspect final repository state**

Run: `git status --short --branch`

Expected: `## main` with no uncommitted files.

Run: `git log --oneline --decorate -8`

Expected: design, plan, and implementation commits are visible in chronological order.

- [ ] **Step 5: Request the deployment target**

Ask the user for the GitHub account/organization and private repository name, unless an existing repository remote has already been approved. Do not guess an external repository owner.

- [ ] **Step 6: Push and perform the credentialed manual run after approval**

After the user approves the target, push `main`. Ask the user to configure the three Repository Secrets in the GitHub UI so the authorization code is never placed in chat. After the user confirms that setup, manually trigger `New bond notifier` with `send_test_email` selected.

Expected outcomes:

- The `Run tests` step passes.
- One clearly labeled `[新债提醒测试]` email arrives without calling Eastmoney.
- A second manual run with `send_test_email` cleared checks live Eastmoney data.
- If the live Eastmoney request is healthy and there is no current subscription, the second run succeeds and logs “无需发送邮件.”
- If current subscriptions exist, the second run sends one combined QQ email.
- If SMTP credentials are invalid, the notify step fails without printing the authorization code.

Record the Actions run URL for the handoff. Never copy secret values into the task response.
