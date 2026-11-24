import os
import sys
import json
import requests

# -------------------------------------------------------------------------------------------
# GLaDOS 自动签到增强脚本
# 支持多域名自动重试、Token 适配、Cookie 智能清洗（多行/前缀/引号容错）、真实 code 强校验
# -------------------------------------------------------------------------------------------

DOMAINS = ["glados.rocks", "glados.cloud", "glados.network"]
TOKENS = ["glados.rocks", "glados.cloud", "glados.one"]
DEFAULT_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
raw_ua = os.environ.get("GLADOS_USER_AGENT", "").strip()
USER_AGENT = raw_ua.strip("'\"` ").strip() or DEFAULT_UA

def normalize_cookie(raw: str) -> str:
    """
    智能清洗并规范化 Cookie 字符串：
    1. 自动处理从 Chrome DevTools Request Headers 中直接划选复制导致的多行换行符（换行符会导致 Python http 报错）
    2. 自动剔除可能误带的 'Cookie:' / 'cookie:' 标签前缀
    3. 自动剔除可能误全选带入的 ':authority:', 'Accept:' 等其他请求头
    4. 自动剥除首尾单引号、双引号、多余空格
    5. 将分散的 cookie 键值对以标准 RFC 6265 格式（分号+空格）拼接为单行合规标头
    """
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
        # 过滤其他误复制的请求头
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
        print("❌ Cookie 解析后为空或格式无效，请检查 GitHub Secrets 中的 GLADOS_COOKIE 配置！")
        return "❌ Cookie 为空或格式无效", False

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

    # 1. 查询账号状态（验证 Cookie 基本有效性）
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
                    print(f"[{domain}] 状态校验成功，已识别登录会话")
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

                    is_repeat = (
                        res_json.get('repeated') is True or
                        (code == 1 and any(k in mess_lower for k in [
                            'repeat', 'already', 'tomorrow', 'observation logged', 'later'
                        ]))
                    )

                    # 判定规则 1：code == 0 明确签到成功（获得当日新积分）
                    if code == 0:
                        is_checkin_ok = True
                        break
                    # 判定规则 2：repeated == True 或 code == 1 重复签到（当日已签，合规放行）
                    elif is_repeat:
                        is_checkin_ok = True
                        break
                    else:
                        print(f"[{domain}][token={token}] 签到返回: code={code}, repeated={res_json.get('repeated')}, message={mess}")
            except Exception as e:
                print(f"[{domain}][token={token}] 签到请求异常: {e}")

        if is_checkin_ok:
            break

    mess = checkin_result.get('message', str(checkin_result)) if checkin_result else '无响应或网络异常'
    code = checkin_result.get('code') if checkin_result else None

    if is_checkin_ok:
        status_text = "签到成功" if code == 0 else "今日已签到 (重复合规)"
        summary = f"账号: {email} | {status_text}: {mess} (code: {code}) | 剩余天数: {left_days} 天"
        print(f"✅ {summary}")
        return summary, True
    else:
        if code == 5 or 'cloudflare' in mess.lower():
            fail_desc = "GLaDOS 启用了 Cloudflare 人机验证 (Turnstile)，云端脚本被拦截，需网页端点击签到"
        else:
            fail_desc = mess
        summary = f"账号: {email} | 签到受阻: {fail_desc} (code: {code}) | 剩余天数: {left_days} 天"
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
                "> **排查指引与平台风控现状**：",
                "> 1. **Cloudflare 人机验证拦截 (code: 5)**：GLaDOS 官方已全面升级风控，对每日首次签到强制要求 Cloudflare Turnstile 浏览器人机验证。GitHub Actions 云端环境缺少真实图形浏览器环境，无法计算验证令牌，需在网页端点击一次打卡。",
                "> 2. **会话凭据有效性**：若状态查询能正常显示邮箱与天数，说明 Cookie 本身未过期，纯粹是首次打卡受阻于 Cloudflare 验证。",
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
