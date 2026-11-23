import os
import sys
import json
import requests

# -------------------------------------------------------------------------------------------
# GLaDOS 自动签到增强脚本
# 支持多域名自动重试、Token 适配、真实 code 状态码强校验、防静默假成功与失败告警
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

    # 1. 查询账号状态（验证 Cookie 基本有效性）
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
                elif res_json.get('code') in (-1, -2):
                    print(f"[{domain}] 状态查询未授权: {res_json.get('message', '没有权限/请重新登录')} (code: {res_json.get('code')})")
            else:
                print(f"[{domain}] HTTP 异常状态码: {res.status_code}")
        except Exception as e:
            print(f"[{domain}] 状态连接异常: {e}")
            continue

    if not status_data:
        fail_msg = "❌ GLaDOS Cookie 已失效（返回没有权限/需要重新登录）。请重新在浏览器登录并更新 GitHub Secrets (GLADOS_COOKIE)！"
        print(fail_msg)
        return fail_msg, False

    email = status_data.get('email', '未知用户')
    left_days = str(status_data.get('leftDays', '0')).split('.')[0]

    # 2. 执行签到（严格校验返回值中的 code，严禁将拦截或错误消息误判为成功）
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

                    # 判定规则 1：code == 0 明确签到成功
                    if code == 0:
                        is_checkin_ok = True
                        break
                    # 判定规则 2：code == 1 且包含重复签到文本（当日已签，属于合规成功）
                    elif code == 1 and any(k in mess_lower for k in ['repeat', 'already', 'try later', 'try tomorrow']):
                        is_checkin_ok = True
                        break
                    else:
                        print(f"[{domain}][token={token}] 签到被拦截或失败: code={code}, message={mess}")
            except Exception as e:
                print(f"[{domain}][token={token}] 签到请求异常: {e}")

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

def write_github_summary(results: list, has_failure: bool):
    summary_file = os.environ.get("GITHUB_STEP_SUMMARY")
    if not summary_file:
        return
    try:
        title = "### ❌ GLaDOS 自动签到失败" if has_failure else "### 🎉 GLaDOS 自动签到成功"
        lines = [title, "", "| 账号执行详情 |", "| :--- |"]
        for r in results:
            lines.append(f"| {r} |")
        lines.append("")
        if has_failure:
            lines.extend([
                "> [!WARNING]",
                "> **排查指引**：",
                "> 1. **主要原因**：若提示「Cookie 已失效/没有权限」，说明 GitHub Secrets 中的 `GLADOS_COOKIE` 依然是旧凭据。请在浏览器登录 GLaDOS 后按 F12 刷新，复制完整 `cookie:` 请求头更新到 GitHub Secrets `GLADOS_COOKIE`。",
                "> 2. **格式提醒**：若配置了 `GLADOS_USER_AGENT`，不要带从开发者控制台复制出来的首尾单引号 `'`（最新脚本已自动容错剥除）。",
            ])
        with open(summary_file, "a", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
    except Exception as e:
        print(f"写入 GitHub Step Summary 失败: {e}")

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
        title = "GLaDOS 签到完成" if not has_failure else "GLaDOS 签到失败告警"
        send_pushplus(sckey, title, send_content)

    write_github_summary(results, has_failure)

    if has_failure:
        print("\n[注意] 检测到签到失败或风控拦截，请及时检查并更新 Cookie / User-Agent！")
        sys.exit(1)
    else:
        print("\n🎉 所有账号签到执行完毕！")
