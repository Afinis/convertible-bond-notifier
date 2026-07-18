from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .models import Bond


class DataSourceError(RuntimeError):
    """Raised when Eastmoney cannot provide a trustworthy bond dataset."""


_SIX_DIGIT_CODE = re.compile(r"[0-9]{6}")


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
            status_forcelist=(429, *range(500, 600)),
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


def _subscription_date(record: Mapping[str, Any]) -> date:
    raw = record.get("PUBLIC_START_DATE")
    if not isinstance(raw, str) or not raw.strip():
        raise DataSourceError("字段 PUBLIC_START_DATE 缺失或格式错误")
    try:
        return datetime.fromisoformat(raw.strip()).date()
    except ValueError as exc:
        raise DataSourceError("字段 PUBLIC_START_DATE 无法解析") from exc


def _required_text(record: Mapping[str, Any], field: str) -> str:
    value = record.get(field)
    if not isinstance(value, str) or not value.strip():
        raise DataSourceError(f"当日转债缺少关键字段 {field}")
    return value.strip()


def _optional_text(record: Mapping[str, Any], field: str) -> str | None:
    value = record.get(field)
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    if not isinstance(value, str):
        raise DataSourceError(f"字段 {field} 格式错误")
    return value.strip()


def _required_code(record: Mapping[str, Any], field: str) -> str:
    value = _required_text(record, field)
    if _SIX_DIGIT_CODE.fullmatch(value) is None:
        raise DataSourceError(f"字段 {field} 必须是六位数字代码")
    return value


def _optional_code(record: Mapping[str, Any], field: str) -> str | None:
    value = _optional_text(record, field)
    if value is not None and _SIX_DIGIT_CODE.fullmatch(value) is None:
        raise DataSourceError(f"字段 {field} 必须是六位数字代码")
    return value


def _plain_decimal(value: Any, field: str) -> str | None:
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    if isinstance(value, bool) or not isinstance(
        value,
        (str, int, float, Decimal),
    ):
        raise DataSourceError(f"字段 {field} 格式错误")
    try:
        decimal_value = Decimal(str(value))
    except InvalidOperation as exc:
        raise DataSourceError(f"字段 {field} 不是有效数值") from exc
    if not decimal_value.is_finite():
        raise DataSourceError(f"字段 {field} 必须是有限数值")
    return format(decimal_value.normalize(), "f")


def _issue_price(value: Any) -> str | None:
    plain = _plain_decimal(value, "ISSUE_PRICE")
    return f"{plain} 元" if plain is not None else None


def _max_subscription(value: Any) -> str | None:
    plain = _plain_decimal(value, "ONLINE_GENERAL_AAU")
    if plain is None:
        return None
    hands = Decimal(plain)
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
                code=_required_code(record, "SECURITY_CODE"),
                subscribe_code=_optional_code(record, "CORRECODE"),
                subscribe_date=subscribe_date,
                stock_name=_optional_text(record, "SECURITY_SHORT_NAME"),
                stock_code=_optional_code(record, "CONVERT_STOCK_CODE"),
                issue_price=_issue_price(record.get("ISSUE_PRICE")),
                max_subscription=_max_subscription(
                    record.get("ONLINE_GENERAL_AAU")
                ),
                rating=_optional_text(record, "RATING"),
            )
        )
    return bonds
