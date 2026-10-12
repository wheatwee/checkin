#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""V2Free 每日自动签到（纯 requests 版，供 GitHub Actions 调用）。

只负责登录 + 签到 + 读取流量信息并打印结果；
邮件通知统一由 notify.py 完成。
"""

import re
import time
import argparse

import requests

BASE_URL = "https://w1.v2ai.top/"  # 新版登录/签到域名

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")


def main(usr, pw):
    client = requests.Session()
    client.headers.update({"User-Agent": UA})

    # 1. 访问登录页，获取初始 Cookie
    client.get(BASE_URL + "/auth/login")

    # 2. 登录（新版表单字段：email/passwd/code/agree/remember_me）
    login_data = {
        "email": usr,
        "passwd": pw,
        "code": "",
        "agree": "1",       # 新版登录必须携带 agree=1
        "remember_me": "",
    }
    resp = client.post(
        BASE_URL + "/auth/login",
        data=login_data,
        headers={
            "Referer": BASE_URL + "/auth/login",
            "X-Requested-With": "XMLHttpRequest",
        },
    )
    try:
        login_result = resp.json()
    except ValueError:
        return usr + " " + time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()) + " ❌ 登录失败：返回内容不是 JSON"
    if login_result.get("ret") != 1:
        return usr + " " + time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()) + " ❌ 登录失败：" + str(login_result.get("msg", resp.text))

    # 3. 签到（接口未变：POST /user/checkin）
    resp = client.post(
        BASE_URL + "/user/checkin",
        headers={
            "Referer": BASE_URL + "/user",
            "X-Requested-With": "XMLHttpRequest",
        },
    )
    try:
        checkin_result = resp.json()
    except ValueError:
        return usr + " " + time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()) + " ❌ 签到失败：返回内容不是 JSON"

    if checkin_result.get("ret") == 1:
        msg = "✅ " + str(checkin_result.get("msg", "签到成功"))
    elif "签" in str(checkin_result.get("msg", "")) and "已" in str(checkin_result.get("msg", "")):
        msg = "🟢 " + str(checkin_result.get("msg", "今日已签到"))
    else:
        msg = "❌ 签到失败：" + str(checkin_result.get("msg", resp.text))

    # 4. 从用户中心页面获取当前流量信息（签到已过/失败时也能拿到）
    info = fetch_user_info(client)
    extra = ""
    if info:
        extra = "，剩余流量：" + info.get("剩余流量", "?") + "，今日已用：" + info.get("今日已用", "?")
    return usr + " " + time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()) + " " + msg + extra


def fetch_user_info(client):
    """登录后读取用户中心页面的账号流量信息"""
    try:
        html = client.get(BASE_URL + "/user").text
        info = {}
        m = re.search(r'id="remain"[^>]*>([^<]+)<', html)
        if m:
            info["剩余流量"] = m.group(1).strip()
        m = re.search(r'今日已用:\s*<a[^>]*>([^<]+)<', html)
        if m:
            info["今日已用"] = m.group(1).strip()
        return info
    except Exception:
        return {}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='V2Free签到脚本')
    parser.add_argument('--username', type=str, help='账号')
    parser.add_argument('--password', type=str, help='密码')
    args = parser.parse_args()
    print(main(args.username, args.password))
