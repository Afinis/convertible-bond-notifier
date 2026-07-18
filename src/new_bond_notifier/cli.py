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
from .service import CheckFailed, NotifierService


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
            mailer.send(build_test_message(config, datetime.now(CN_TZ)))
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
    except CheckFailed as exc:
        if exc.notification_error is None:
            LOGGER.error(
                "任务失败：主异常=%s",
                type(exc.cause).__name__,
            )
        else:
            LOGGER.error(
                "任务失败：主异常=%s；通知异常=%s",
                type(exc.cause).__name__,
                type(exc.notification_error).__name__,
            )
        return 1
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
