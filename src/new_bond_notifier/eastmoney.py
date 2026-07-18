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
