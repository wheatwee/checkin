#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""签到结果邮件通知（公用）：合并 V2Free 与 WorkBuddy 的结果文件，发送一封日报邮件。"""

import argparse
import re
import smtplib
from email.mime.text import MIMEText

RESULT_FILES = [
    ("V2Free", "result_v2free.txt"),
    ("WorkBuddy", "result_workbuddy.txt"),
]

ICON = {"ok": "✅", "already": "🟢", "fail": "❌"}


def read_result(path):
    """读取结果文件；文件不存在返回 None（表示该步未运行）"""
    try:
        with open(path, encoding="utf-8") as f:
            return f.read().strip()
    except FileNotFoundError:
        return None


def collect_sections():
    """拼装邮件正文（保留完整信息，只进邮箱、不进日志）"""
    sections = []
    for label, path in RESULT_FILES:
        content = read_result(path)
        if content is None:
            content = "（未运行）"
        elif not content:
            content = "（无输出）"
        sections.append("== %s ==\n%s" % (label, content))
    return "\n\n".join(sections)


def classify_v2free(text):
    if text is None or "❌" in text:
        return "fail"
    if "✅" in text:
        return "ok"
    if "🟢" in text:
        return "already"
    return "fail"


def classify_workbuddy(text):
    # 优先解析汇总行：签到完成 | 成功 1 / 已签 0 / 失效 0 / 失败 0
    m = re.search(r"成功\s*(\d+)\s*/\s*已签\s*(\d+)\s*/\s*失效\s*(\d+)\s*/\s*失败\s*(\d+)", text or "")
    if m:
        ok, already, expired, failed = map(int, m.groups())
        if failed or expired:
            return "fail"
        if ok:
            return "ok"
        if already:
            return "already"
        return "fail"
    if text is None or "❌" in text or "⚠️" in text:
        return "fail"
    if "🟢" in text:
        return "already"
    if "✅" in text:
        return "ok"
    return "fail"


CLASSIFIERS = {"V2Free": classify_v2free, "WorkBuddy": classify_workbuddy}


def build_subject(status):
    """取最差状态：任一失败即整体「部分失败」/「签到失败」；ok 与 already 都算正常"""
    detail = " / ".join("%s %s" % (lb, ICON[status[lb]]) for lb, _ in RESULT_FILES)
    vals = [status[lb] for lb, _ in RESULT_FILES]
    if all(v == "fail" for v in vals):
        head = "❌ 签到失败"
    elif all(v in ("ok", "already") for v in vals):
        head = "✅ 签到成功" if "ok" in vals else "🟢 今日已签"
    else:
        head = "⚠️ 部分失败"
    return "%s｜%s" % (head, detail)


def main():
    parser = argparse.ArgumentParser(description="签到结果邮件通知")
    parser.add_argument("--remail", required=True, help="接收邮箱")
    parser.add_argument("--semail", required=True, help="发送邮箱（QQ）")
    parser.add_argument("--secode", required=True, help="发送邮箱 SMTP 授权码")
    args = parser.parse_args()

    status = {label: CLASSIFIERS[label](read_result(path)) for label, path in RESULT_FILES}
    subject = build_subject(status)
    body = collect_sections()

    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = args.semail
    msg["To"] = args.remail
    try:
        server = smtplib.SMTP_SSL("smtp.qq.com", 465)
        server.login(args.semail, args.secode)
        server.sendmail(args.semail, args.remail, msg.as_string())
        server.quit()
        # 只打印摘要（正文含账号名，不进公开日志；不打印收件邮箱）
        print("邮件发送成功 | %s" % subject)
    except smtplib.SMTPException as e:
        detail = str(e).replace(args.remail, "***").replace(args.semail, "***")
        print("邮件发送失败:", detail)


if __name__ == "__main__":
    main()
