import os
import sys
import json
import requests

# -------------------------------------------------------------------------------------------
# GLaDOS 自动签到 (青龙面板版本)
# -------------------------------------------------------------------------------------------

DOMAINS = ["glados.cloud", "glados.rocks", "glados.network"]
TOKENS = ["glados.cloud", "glados.one", "glados.rocks"]
DEFAULT_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
raw_ua = os.environ.get("GLADOS_USER_AGENT", "").strip()
USER_AGENT = raw_ua.strip("'\"` ").strip() or DEFAULT_UA

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
    cookie = cookie.strip()
    if cookie.lower().startswith("cookie:"):
        cookie = cookie[7:].strip()
    cookie = cookie.strip("'\"` ").strip()
    if not cookie:
        return "", False

    status_data = None
    active_domain = DOMAINS[0]

    for domain in DOMAINS:
        url_status = f"https://{domain}/api/user/status"
        headers = {
            'cookie': cookie,
            'referer': f'https://{domain}/console/checkin',
            'origin': f'https://{domain}',
            'user-agent': USER_AGENT,
            'accept': 'application/json, text/plain, */*'
        }
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
        fail_msg = "❌ GLaDOS Cookie 已失效，请在网页端重新登录并更新环境变量 GLADOS_COOKIE！"
        print(fail_msg)
        return fail_msg, False

    email = status_data.get('email', '未知用户')
    left_days = str(status_data.get('leftDays', '0')).split('.')[0]

    checkin_result = None
    is_checkin_ok = False

    for domain in DOMAINS:
        checkin_url = f"https://{domain}/api/user/checkin"
        checkin_headers = {
            'cookie': cookie,
            'referer': f'https://{domain}/console/checkin',
            'origin': f'https://{domain}',
            'user-agent': USER_AGENT,
            'content-type': 'application/json;charset=UTF-8',
            'accept': 'application/json, text/plain, */*'
        }

        for token in TOKENS:
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
    sckey = os.environ.get("PUSHPLUS_TOKEN", "").strip()
    raw_cookie = os.environ.get("GLADOS_COOKIE", "").strip()

    if not raw_cookie:
        print("未获取到 GLADOS_COOKIE 环境变量")
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
