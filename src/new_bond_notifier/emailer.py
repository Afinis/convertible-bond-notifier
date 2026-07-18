from __future__ import annotations

import html
import smtplib
import ssl
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
            "失败阶段：数据获取、解析或日期筛选",
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


class QQMailer:
    def __init__(
        self,
        config: MailConfig,
        smtp_factory: Callable[..., Any] = smtplib.SMTP_SSL,
    ) -> None:
        self.config = config
        self.smtp_factory = smtp_factory

    def send(self, message: EmailMessage) -> None:
        context = ssl.create_default_context()
        with self.smtp_factory(
            "smtp.qq.com",
            465,
            timeout=20,
            context=context,
        ) as smtp:
            smtp.login(
                self.config.smtp_username,
                self.config.smtp_auth_code,
            )
            smtp.send_message(message)
