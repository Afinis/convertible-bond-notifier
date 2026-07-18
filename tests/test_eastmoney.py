from datetime import date
from decimal import Decimal
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


def test_default_session_retries_429_and_every_5xx_status() -> None:
    client = EastmoneyClient()
    retry = client.session.get_adapter("https://").max_retries

    assert retry.total == 2
    assert set(retry.status_forcelist) == {429, *range(500, 600)}


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
    [
        None,
        "",
        "not-a-date",
        "2022-13-99 00:00:00",
        "2022-01-05garbage",
        "2022-01-05 99:99:99",
    ],
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


@pytest.mark.parametrize(
    "field",
    [
        "SECURITY_NAME_ABBR",
        "SECURITY_CODE",
        "CORRECODE",
        "SECURITY_SHORT_NAME",
        "CONVERT_STOCK_CODE",
        "RATING",
    ],
)
@pytest.mark.parametrize(
    "value",
    [
        pytest.param(True, id="boolean"),
        pytest.param(123456, id="integer"),
        pytest.param(["text"], id="list"),
        pytest.param({"text": "value"}, id="mapping"),
        pytest.param(b"text", id="bytes"),
        pytest.param(object(), id="object"),
    ],
)
def test_matching_record_rejects_non_string_text_fields(
    field: str,
    value: Any,
) -> None:
    with pytest.raises(DataSourceError, match=field):
        parse_bonds_for_date(
            [sample_record(**{field: value})],
            target_date=date(2022, 1, 5),
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("SECURITY_CODE", "11305"),
        ("SECURITY_CODE", "1130530"),
        ("SECURITY_CODE", "113O53"),
        ("CORRECODE", "78301"),
        ("CORRECODE", "7830120"),
        ("CORRECODE", "783O12"),
        ("CONVERT_STOCK_CODE", "60101"),
        ("CONVERT_STOCK_CODE", "6010120"),
        ("CONVERT_STOCK_CODE", "601O12"),
    ],
)
def test_matching_record_rejects_malformed_six_digit_codes(
    field: str,
    value: str,
) -> None:
    with pytest.raises(DataSourceError, match=field):
        parse_bonds_for_date(
            [sample_record(**{field: value})],
            target_date=date(2022, 1, 5),
        )


@pytest.mark.parametrize("field", ["ISSUE_PRICE", "ONLINE_GENERAL_AAU"])
@pytest.mark.parametrize(
    "value",
    [
        pytest.param(True, id="boolean"),
        pytest.param(["100"], id="list"),
        pytest.param({"value": 100}, id="mapping"),
        pytest.param(b"100", id="bytes"),
        pytest.param(1 + 2j, id="complex"),
        pytest.param(object(), id="object"),
        pytest.param("not-a-number", id="nonnumeric-text"),
    ],
)
def test_matching_record_rejects_invalid_numeric_fields(
    field: str,
    value: Any,
) -> None:
    with pytest.raises(DataSourceError, match=field):
        parse_bonds_for_date(
            [sample_record(**{field: value})],
            target_date=date(2022, 1, 5),
        )


@pytest.mark.parametrize("field", ["ISSUE_PRICE", "ONLINE_GENERAL_AAU"])
@pytest.mark.parametrize(
    "value",
    [
        pytest.param(float("nan"), id="float-nan"),
        pytest.param(float("inf"), id="float-infinity"),
        pytest.param(float("-inf"), id="float-negative-infinity"),
        pytest.param("NaN", id="text-nan"),
        pytest.param("Infinity", id="text-infinity"),
        pytest.param("-Infinity", id="text-negative-infinity"),
        pytest.param(Decimal("NaN"), id="decimal-nan"),
        pytest.param(Decimal("Infinity"), id="decimal-infinity"),
    ],
)
def test_matching_record_rejects_non_finite_numeric_fields(
    field: str,
    value: Any,
) -> None:
    with pytest.raises(DataSourceError, match=field):
        parse_bonds_for_date(
            [sample_record(**{field: value})],
            target_date=date(2022, 1, 5),
        )
