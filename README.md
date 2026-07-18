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
