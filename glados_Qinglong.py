import os
import sys
import json
import requests

# -------------------------------------------------------------------------------------------
# GLaDOS 自动签到 (青龙面板版本)
# -------------------------------------------------------------------------------------------

DOMAINS = ["glados.rocks", "glados.cloud", "glados.network"]
TOKENS = ["glados.one", "glados.cloud", "glados.rocks"]
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"

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
            'user-agent': USER_AGENT
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

    checkin_url = f"https://{active_domain}/api/user/checkin"
    checkin_headers = {
        'cookie': cookie,
        'referer': f'https://{active_domain}/console/checkin',
        'origin': f'https://{active_domain}',
        'user-agent': USER_AGENT,
        'content-type': 'application/json;charset=UTF-8'
    }

    checkin_result = None
    for token in TOKENS:
        try:
            payload = {'token': token}
            res = requests.post(checkin_url, headers=checkin_headers, data=json.dumps(payload), timeout=15)
            if res.status_code == 200:
                res_json = res.json()
                if 'message' in res_json:
                    checkin_result = res_json
                    break
        except Exception:
            pass

    if checkin_result and 'message' in checkin_result:
        mess = checkin_result['message']
        summary = f"账号: {email} | 签到结果: {mess} | 剩余天数: {left_days} 天"
        print(f"✅ {summary}")
        return summary, True
    else:
        summary = f"⚠️ 账号: {email} | 签到异常: {checkin_result} | 剩余天数: {left_days} 天"
        print(summary)
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
        title = "GLaDOS 签到完成" if not has_failure else "GLaDOS 签到异常"
        send_pushplus(sckey, title, send_content)

def main_handler(event, context):
    return start()

if __name__ == '__main__':
    start()
