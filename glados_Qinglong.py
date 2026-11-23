import os
import sys
import json
import requests

# -------------------------------------------------------------------------------------------
# GLaDOS 自动签到 (青龙面板版本)
# -------------------------------------------------------------------------------------------

DOMAINS = ["glados.rocks", "glados.cloud", "glados.network"]
TOKENS = ["glados.rocks", "glados.cloud", "glados.one"]
DEFAULT_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
raw_ua = os.environ.get("GLADOS_USER_AGENT", "").strip()
USER_AGENT = raw_ua.strip("'\"` ").strip() or DEFAULT_UA

def normalize_cookie(raw: str) -> str:
    if not raw:
        return ""
    raw = raw.strip().strip("'\"` ").strip()
    lines = raw.splitlines()
    cookie_parts = []

    for line in lines:
        line = line.strip()
        if not line:
            continue
        lower_line = line.lower()
        if lower_line.startswith("cookie:"):
            content = line[7:].strip()
            if content:
                cookie_parts.append(content.rstrip(";"))
            continue
        if any(lower_line.startswith(h) for h in [
            ":authority", ":method", ":path", ":scheme", "accept", "user-agent",
            "sec-", "priority", "referer", "origin", "content-", "host"
        ]):
            continue
        if "=" in line:
            cookie_parts.append(line.rstrip(";"))

    if cookie_parts:
        final_tokens = []
        for part in cookie_parts:
            sub_tokens = [t.strip().rstrip(";") for t in part.split(";") if t.strip()]
            final_tokens.extend(sub_tokens)
        return "; ".join(final_tokens)

    if raw.lower().startswith("cookie:"):
        raw = raw[7:].strip()
    return raw.strip().strip("'\"` ").strip()

def send_pushplus(sckey: str, title: str, content: str):
    if not sckey:
        return
    try:
        url = "http://www.pushplus.plus/send"
        data = {
            "token": sckey,
            "title": title,
            "content": content,
            "template": "html"
        }
        requests.post(url, json=data, timeout=10)
    except Exception as e:
        print(f"Pushplus 推送失败: {e}")

def checkin_account(cookie: str, sckey: str = ""):
    cookie = normalize_cookie(cookie)
    if not cookie:
        return "", False

    base_headers = {
        'cookie': cookie,
        'user-agent': USER_AGENT,
        'accept': 'application/json, text/plain, */*',
        'accept-language': 'zh-CN,zh;q=0.9,en;q=0.8',
        'sec-ch-ua-mobile': '?0',
        'sec-ch-ua-platform': '"Windows"',
        'sec-fetch-dest': 'empty',
        'sec-fetch-mode': 'cors',
        'sec-fetch-site': 'same-origin'
    }

    status_data = None
    active_domain = DOMAINS[0]

    for domain in DOMAINS:
        url_status = f"https://{domain}/api/user/status"
        headers = dict(base_headers)
        headers['referer'] = f'https://{domain}/console/checkin'
        headers['origin'] = f'https://{domain}'
        try:
            res = requests.get(url_status, headers=headers, timeout=15)
            if res.status_code == 200:
                res_json = res.json()
                if res_json.get('code') == 0 and 'data' in res_json:
                    status_data = res_json['data']
                    active_domain = domain
                    break
        except Exception:
            continue

    if not status_data:
        return "❌ GLaDOS Cookie 已失效", False

    email = status_data.get('email', '未知用户')
    left_days = str(status_data.get('leftDays', '0')).split('.')[0]

    checkin_result = None
    is_checkin_ok = False

    domains_to_try = [active_domain] + [d for d in DOMAINS if d != active_domain]
    tokens_to_try = [active_domain] + [t for t in TOKENS if t != active_domain]

    for domain in domains_to_try:
        checkin_url = f"https://{domain}/api/user/checkin"
        checkin_headers = dict(base_headers)
        checkin_headers['referer'] = f'https://{domain}/console/checkin'
        checkin_headers['origin'] = f'https://{domain}'
        checkin_headers['content-type'] = 'application/json;charset=UTF-8'

        for token in tokens_to_try:
            try:
                payload = {'token': token}
                res = requests.post(checkin_url, headers=checkin_headers, data=json.dumps(payload), timeout=15)
                if res.status_code == 200:
                    res_json = res.json()
                    checkin_result = res_json
                    code = res_json.get('code')
                    mess = str(res_json.get('message', ''))
                    mess_lower = mess.lower()

                    if code == 0:
                        is_checkin_ok = True
                        break
                    elif code == 1 and any(k in mess_lower for k in ['repeat', 'already', 'try later', 'try tomorrow']):
                        is_checkin_ok = True
                        break
            except Exception:
                pass

        if is_checkin_ok:
            break

    mess = checkin_result.get('message', str(checkin_result)) if checkin_result else '无响应或网络异常'
    code = checkin_result.get('code') if checkin_result else None

    if is_checkin_ok:
        summary = f"账号: {email} | 签到成功: {mess} (code: {code}) | 剩余天数: {left_days} 天"
        print(f"✅ {summary}")
        return summary, True
    else:
        summary = f"账号: {email} | 签到失败: {mess} (code: {code}) | 剩余天数: {left_days} 天"
        print(f"❌ {summary}")
        return summary, False

def start():
    raw_cookie = os.environ.get("GLADOS_COOKIE", "")
    sckey = os.environ.get("PUSHPLUS_TOKEN", "")

    if not raw_cookie:
        print("未获取到 GLADOS_COOKIE")
        return

    cookies = raw_cookie.split("&")
    results = []
    has_failure = False

    for c in cookies:
        if not c.strip():
            continue
        msg, ok = checkin_account(c, sckey)
        results.append(msg)
        if not ok:
            has_failure = True

    send_content = "<br>".join(results)
    if sckey:
        title = "GLaDOS 签到完成" if not has_failure else "GLaDOS 签到异常告警"
        send_pushplus(sckey, title, send_content)

def main_handler(event, context):
    return start()

if __name__ == '__main__':
    start()
