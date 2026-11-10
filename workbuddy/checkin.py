#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WorkBuddy 每日自动签到（无头版，供 GitHub Actions 调用）
=======================================================
签到流程移植自 FXmonkey/workbuddy_auto_checkin 的 wb_auto.py：
  先查状态 → 未签才领 → 已签/领取后回读连签天数、累计积分等明细。

接口契约
--------
  POST /v2/billing/meter/checkin-activity-status   查询签到状态
  POST /v2/billing/meter/daily-checkin             执行签到（幂等，已签返回 code 10001）

  请求头按 FXmonkey 原版方式：
      Authorization: Bearer <JWT>
      User-Agent: WorkBuddy
  （注意：未带 X-User-Id / X-Domain；若线上报 401/AUTH，
    回退方案是把原 build_headers() 的 X-User-Id + X-Domain 加回去）

账号来源（二选一）
------------------
  1) 环境变量 WORKBUDDY_ACCOUNTS：形如 {"accounts":[{"name":..,"token":..},...]}
  2) 本地文件 accounts.json / 签到token.json（便于本地调试）

输出格式（notify.py 依赖，勿改）
--------------------------------
  每账号一行：✅/🟢/⚠️/❌ 名称: 详情
  结尾汇总行：签到完成 | 成功 X / 已签 X / 失效 X / 失败 X

依赖：无第三方依赖（stdlib urllib），替代原 requests 版请求层。
"""

import json
import os
import ssl
import sys
import time
import urllib.error
import urllib.request

API_HOST = "https://copilot.tencent.com"
STATUS_PATH = "/v2/billing/meter/checkin-activity-status"
CHECKIN_PATH = "/v2/billing/meter/daily-checkin"

REQUEST_TIMEOUT = 20
MAX_RETRY = 3
CODE_NO_NETWORK = -1


def log(msg):
    print(msg, flush=True)


def masked(text):
    """把返回体里的 token 类字段脱敏后再落日志。"""
    if isinstance(text, dict):
        out = {}
        for k, v in text.items():
            if isinstance(v, (dict, list)):
                out[k] = masked(v)
            elif isinstance(v, str) and len(v) > 24:
                out[k] = v[:6] + "***" + v[-4:]
            else:
                out[k] = v
        return out
    if isinstance(text, list):
        return [masked(x) for x in text]
    if isinstance(text, str) and len(text) > 200:
        return text[:200] + "..."
    return text


def dig(obj, *keys):
    """逐层取值，任一层缺失返回 None。"""
    for k in keys:
        if isinstance(obj, dict) and k in obj:
            obj = obj[k]
        else:
            return None
    return obj


def unwrap(body):
    """真实返回统一是 {code,msg,data} 信封，业务字段都在 data 里。"""
    if isinstance(body, dict) and isinstance(body.get("data"), dict):
        return body["data"]
    return body if isinstance(body, dict) else {}


def request(url, headers, method="GET", payload=None, retry=True):
    body = None
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    ctx = ssl.create_default_context()
    attempt = 0
    while True:
        attempt += 1
        try:
            with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT, context=ctx) as resp:
                raw = resp.read().decode("utf-8", "replace")
                try:
                    return resp.status, json.loads(raw)
                except ValueError:
                    return resp.status, {"raw": raw[:300]}
        except urllib.error.HTTPError as e:
            raw = e.read().decode("utf-8", "replace")
            try:
                ebody = json.loads(raw)
            except ValueError:
                ebody = {"raw": raw[:300]}
            # 偶发 3xx（网关短暂跳转）不是业务结论，退避后重试
            if 300 <= e.code < 400 and attempt < MAX_RETRY:
                log("  · 收到 %d 跳转，%.1fs 后重试（%d/%d）"
                    % (e.code, 2.0 * attempt, attempt, MAX_RETRY))
                time.sleep(2.0 * attempt)
                continue
            return e.code, ebody
        except Exception as e:
            # 只对网络抖动与 5xx 重试；写操作靠接口幂等，避免重复提交
            if not retry or attempt >= MAX_RETRY:
                return CODE_NO_NETWORK, {"error": "%s: %s" % (type(e).__name__, e)}
            log("  · 请求异常，%.1fs 后重试（%d/%d）" % (2.0, attempt, MAX_RETRY))
            time.sleep(2.0)


def post(url, headers, payload=None):
    return request(url, headers, method="POST", payload=payload)


# ---------------------------------------------------------------- 签到

def run_checkin(headers, endpoint):
    """查状态 → 未签才领。返回 (ok, status, report)。

    status ∈ CLAIMED / ALREADY / INACTIVE / AUTH / NETWORK / ERROR / UNKNOWN
    """
    scode, sbody = post(endpoint + STATUS_PATH, headers)
    log("  [签到-状态] HTTP %s %s" % (scode, json.dumps(masked(sbody), ensure_ascii=False)))

    if scode == CODE_NO_NETWORK:
        return False, "NETWORK", "网络不可达，签到未完成"
    if scode in (401, 403):
        return False, "AUTH", "认证被拒（HTTP %s），请更新 token" % scode
    if not (200 <= scode < 300):
        return False, "ERROR", "状态接口异常（HTTP %s）" % scode

    status = unwrap(sbody)
    if dig(status, "active") is False:
        name = dig(status, "activity_name")
        return True, "INACTIVE", "签到活动未开启" + ("（%s）" % name if name else "")

    if dig(status, "today_checked_in") in (True, 1):
        return True, "ALREADY", _fmt_already(status)

    ccode, cbody = post(endpoint + CHECKIN_PATH, headers)
    log("  [签到-领取] HTTP %s %s" % (ccode, json.dumps(masked(cbody), ensure_ascii=False)))

    if ccode == CODE_NO_NETWORK:
        return False, "NETWORK", "领取请求未送达，签到未完成"
    if ccode in (401, 403):
        return False, "AUTH", "认证被拒（HTTP %s）" % ccode

    if _already_checked_in(ccode, cbody):
        _, fresh = post(endpoint + STATUS_PATH, headers)
        return True, "ALREADY", _fmt_already(unwrap(fresh), via="今日已签过（服务端判定已领取）")

    credit = dig(unwrap(cbody), "credit")
    if credit is not None:
        _, fresh = post(endpoint + STATUS_PATH, headers)
        s = unwrap(fresh)
        bonus = "，且为连签奖励日" if dig(s, "is_streak_day") else ""
        streak = dig(s, "streak_days")
        cum = dig(s, "total_credits")
        tail = ""
        if streak is not None:
            tail = "（连续 %s 天%s）" % (streak, "，累计 %s 积分" % cum if cum is not None else "")
        return True, "CLAIMED", "成功领取 %s 积分%s%s" % (credit, bonus, tail)

    if isinstance(cbody, dict) and ("code" in cbody or "msg" in cbody):
        return False, "ERROR", "领取失败：%s（HTTP %s）" % (cbody.get("msg") or cbody.get("code"), ccode)
    return False, "UNKNOWN", "未识别的领取返回"


def _already_checked_in(code, body):
    if isinstance(body, dict):
        msg = body.get("msg") or ""
        if body.get("code") == 10001 or "已签" in msg:
            return True
    return False


def _fmt_already(status, via="今日已签过"):
    parts = []
    if dig(status, "today_credit") is not None:
        parts.append("今日 +%s" % dig(status, "today_credit"))
    if dig(status, "streak_days") is not None:
        parts.append("连续 %s 天" % dig(status, "streak_days"))
    if dig(status, "total_credits") is not None:
        parts.append("累计 %s 积分" % dig(status, "total_credits"))
    return "%s（%s）" % (via, "，".join(parts)) if parts else via


# ---------------------------------------------------------------- 账号与输出

def load_accounts():
    """优先读环境变量 WORKBUDDY_ACCOUNTS，否则退回本地 JSON 文件。"""
    raw = os.environ.get("WORKBUDDY_ACCOUNTS", "").strip()
    if raw:
        try:
            return json.loads(raw).get("accounts", [])
        except Exception as e:  # noqa: BLE001
            print("[E] WORKBUDDY_ACCOUNTS 不是合法 JSON: %s" % e, file=sys.stderr)

    for path in ("accounts.json", "签到token.json"):
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    return json.load(f).get("accounts", [])
            except Exception as e:  # noqa: BLE001
                print("[E] 读取 %s 失败: %s" % (path, e), file=sys.stderr)
    return []


def mask(name):
    """脱敏账号名，避免在公开的 Actions 日志里暴露手机号。"""
    s = str(name)
    if len(s) == 11 and s.isdigit():
        return s[:3] + "****" + s[7:]
    if len(s) > 4:
        return s[:2] + "***" + s[-2:]
    return s


def push(title, content):
    """可选：PushPlus / Server酱 微信推送。"""
    token = os.environ.get("PUSHPLUS_TOKEN")
    if token:
        try:
            request("http://www.pushplus.plus/send", {"Content-Type": "application/json"},
                    method="POST", payload={"token": token, "title": title, "content": content},
                    retry=False)
        except Exception:  # noqa: BLE001
            pass
    key = os.environ.get("SERVERCHAN_KEY")
    if key:
        try:
            request("https://sctapi.ftqq.com/%s.send" % key, {},
                    method="POST", payload={"title": title, "desp": content}, retry=False)
        except Exception:  # noqa: BLE001
            pass


def main():
    accounts = load_accounts()
    if not accounts:
        print("[E] 没有可用账号，请配置 WORKBUDDY_ACCOUNTS 或本地 accounts.json")
        sys.exit(1)

    endpoint = API_HOST
    print("=== 开始签到，共 %d 个账号 ===" % len(accounts))
    lines = []
    summary = {"ok": 0, "already": 0, "expired": 0, "failed": 0}
    # FXmonkey 结果状态 → 本仓库四态（notify.py 依赖此映射，勿改）
    STATUS_MAP = {
        "CLAIMED": ("ok", "✅"),
        "ALREADY": ("already", "🟢"),
        "INACTIVE": ("already", "🟢"),
        "AUTH": ("expired", "⚠️"),
        "NETWORK": ("failed", "❌"),
        "ERROR": ("failed", "❌"),
        "UNKNOWN": ("failed", "❌"),
    }
    for acct in accounts:
        name = acct.get("name", "?")
        token = acct.get("token", "")
        if not token:
            ok, status, report = False, "ERROR", "缺少 token"
        else:
            headers = {
                "Accept": "application/json",
                "Authorization": "Bearer %s" % token,
                "Content-Type": "application/json",
                "User-Agent": "WorkBuddy",
            }
            try:
                ok, status, report = run_checkin(headers, endpoint)
            except Exception as e:  # noqa: BLE001
                ok, status, report = False, "ERROR", "签到模块异常（%s: %s）" % (type(e).__name__, e)
        bucket, icon = STATUS_MAP[status]
        summary[bucket] += 1
        # 控制台/Actions 日志脱敏；微信推送里保留完整账号名便于识别
        print("%s %s: %s" % (icon, mask(name), report))
        lines.append("%s %s: %s" % (icon, name, report))

    total = ("签到完成 | 成功 %d / 已签 %d / 失效 %d / 失败 %d"
             % (summary["ok"], summary["already"], summary["expired"], summary["failed"]))
    print(total)
    lines.append(total)
    push("WorkBuddy 签到", "\n".join(lines))


if __name__ == "__main__":
    main()
