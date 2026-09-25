import os
import sys
import json
import requests

# -------------------------------------------------------------------------------------------
# GLaDOS 自动签到增强脚本
# 支持多域名自动重试、Token 适配、Cookie 失效安全捕获与通知
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

    # 1. 尝试查询账号状态
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
                elif res_json.get('code') in (-1, -2):
                    print(f"[{domain}] 状态查询未授权: {res_json.get('message', '没有权限/请重新登录')} (code: {res_json.get('code')})")
        except Exception as e:
            print(f"[{domain}] 连接异常: {e}")
            continue

    if not status_data:
        fail_msg = "❌ GLaDOS Cookie 已失效（返回没有权限/需要重新登录），请重新登录网页端提取最新 Cookie 并更新 GitHub Secrets (GLADOS_COOKIE)！"
        print(fail_msg)
        return fail_msg, False

    email = status_data.get('email', '未知用户')
    left_days = str(status_data.get('leftDays', '0')).split('.')[0]

    # 2. 执行签到
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
        except Exception as e:
            print(f"签到请求异常 (token={token}): {e}")

    if checkin_result and 'message' in checkin_result:
        mess = checkin_result['message']
        summary = f"账号: {email} | 签到结果: {mess} | 剩余天数: {left_days} 天"
        print(f"✅ {summary}")
        return summary, True
    else:
        summary = f"⚠️ 账号: {email} | 签到接口响应异常: {checkin_result} | 剩余天数: {left_days} 天"
        print(summary)
        return summary, False

if __name__ == '__main__':
    sckey = os.environ.get("PUSHPLUS_TOKEN", "").strip()
    raw_cookie = os.environ.get("GLADOS_COOKIE", "").strip()

    if not raw_cookie:
        print("❌ 未获取到 GLADOS_COOKIE 环境变量，请在 GitHub 仓库 Settings -> Secrets 中配置！")
        sys.exit(1)

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
        title = "GLaDOS 签到完成" if not has_failure else "GLaDOS 签到失败-Cookie失效告警"
        send_pushplus(sckey, title, send_content)

    if has_failure:
        print("\n[注意] 检测到签到失败或 Cookie 失效，请及时更新 Cookie！")
        sys.exit(1)
    else:
        print("\n🎉 所有账号签到执行完毕！")
