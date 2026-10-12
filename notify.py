#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""签到结果邮件通知（公用）：合并 V2Free 与 WorkBuddy 的结果文件，发送一封日报邮件。"""

import argparse
import smtplib
from email.mime.text import MIMEText

RESULT_FILES = [
    ("V2Free", "result_v2free.txt"),
    ("WorkBuddy", "result_workbuddy.txt"),
]


def collect_sections():
    sections = []
    for label, path in RESULT_FILES:
        try:
            with open(path, encoding="utf-8") as f:
                content = f.read().strip() or "（无输出）"
        except FileNotFoundError:
            content = "（未运行）"
        sections.append("== %s ==\n%s" % (label, content))
    return "\n\n".join(sections)


def main():
    parser = argparse.ArgumentParser(description="签到结果邮件通知")
    parser.add_argument("--remail", required=True, help="接收邮箱")
    parser.add_argument("--semail", required=True, help="发送邮箱（QQ）")
    parser.add_argument("--secode", required=True, help="发送邮箱 SMTP 授权码")
    args = parser.parse_args()

    body = collect_sections()
    print(body)

    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = "V2Free+WorkBuddy 签到日报"
    msg["From"] = args.semail
    msg["To"] = args.remail
    try:
        server = smtplib.SMTP_SSL("smtp.qq.com", 465)
        server.login(args.semail, args.secode)
        server.sendmail(args.semail, args.remail, msg.as_string())
        server.quit()
        print("邮件发送成功 -> %s" % args.remail)
    except smtplib.SMTPException as e:
        print("邮件发送失败:", e)


if __name__ == "__main__":
    main()
