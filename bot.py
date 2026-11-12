import os
import re
import json
import requests
from datetime import datetime, timezone
from xml.sax.saxutils import escape

SERPER_API_KEY = (os.environ.get("SERPER_API_KEY") or "").strip()
DISCORD_WEBHOOK_URL = (os.environ.get("DISCORD_WEBHOOK_URL") or "").strip()
NTFY_TOPIC = (os.environ.get("NTFY_TOPIC") or "").strip()
SITE_URL = os.environ.get("SITE_URL", "https://아이디.github.io/저장소이름")

CONFIG_FILE = "config.json"
DATA_FILE = "events.json"
RSS_FILE = "rss.xml"


def call_serper(query, tbs=None):
    if not SERPER_API_KEY:
        print("❌ [오류] SERPER_API_KEY 환경 변수가 설정되어 있지 않습니다! GitHub Secrets를 확인해 주세요.")
        return []

    url = "https://google.serper.dev/search"
    payload = {
        "q": query,
        "gl": "kr",
        "hl": "ko",
        "num": 10
    }
    if tbs:
        payload["tbs"] = tbs

    headers = {
        "X-API-KEY": SERPER_API_KEY,
        "Content-Type": "application/json"
    }

    try:
        response = requests.post(url, headers=headers, json=payload, timeout=15)
        if response.status_code == 400 and tbs:
            # tbs 파라미터 때문에 400이 발생할 경우 tbs를 빼고 즉시 재시도
            print(f"⚠️ tbs='{tbs}' 옵션으로 400 응답 발생 ({response.text}) -> tbs 제거 후 재시도합니다.")
            payload.pop("tbs", None)
            response = requests.post(url, headers=headers, json=payload, timeout=15)

        if not response.ok:
            print(f"❌ Serper API 호출 실패 ({query}): HTTP {response.status_code} | 응답 본문: {response.text}")
            return []

        results = response.json().get("organic", [])
        print(f"🔎 쿼리 실행: '{query}' -> 검색 결과 {len(results)}건")
        return results
    except Exception as e:
        print(f"❌ Serper API 예외 발생 ({query}): {e}")
        return []


def normalize_x_link(url):
    if not url:
        return None
    # twitter.com 도메인을 x.com으로 통일
    url = url.replace("twitter.com", "x.com")
    # 1차: 일반적인 /아이디/status/숫자 형식
    match = re.search(r"https://x\.com/([^/?#]+)/status/(\d+)", url)
    if match:
        return f"https://x.com/{match.group(1)}/status/{match.group(2)}"
    # 2차: /i/web/status/숫자 또는 /i/status/숫자 형식 대응
    match_i = re.search(r"https://x\.com/i/(?:web/)?status/(\d+)", url)
    if match_i:
        return f"https://x.com/i/status/{match_i.group(1)}"
    return None


def load_json(filepath, default_val):
    if os.path.exists(filepath):
        with open(filepath, "r", encoding="utf-8") as f:
            return json.load(f)
    return default_val


def save_json(filepath, data):
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# 1. RSS 피드(rss.xml) 생성 함수
def generate_rss(events):
    now_rfc822 = datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S +0000")
    rss_items = []

    for ev in events[:30]:  # 최신 30개 항목만 RSS에 포함
        title = escape(ev.get("title", "제목 없음"))
        link = escape(ev.get("link", ""))
        desc = escape(f"[{ev.get('source_name', '')}] {ev.get('snippet', '')}")

        rss_items.append(f"""    <item>
      <title>{title}</title>
      <link>{link}</link>
      <guid isPermaLink="true">{link}</guid>
      <description>{desc}</description>
      <category>{escape(ev.get('source_name', ''))}</category>
    </item>""")

    rss_content = f"""<?xml version="1.0" encoding="UTF-8" ?>
<rss version="2.0">
  <channel>
    <title>버튜버 생일 광고 &amp; 팬 행사 아카이브</title>
    <link>{escape(SITE_URL)}</link>
    <description>정기적으로 자동 수집되는 버튜버 응원 광고 및 생일 카페 정보</description>
    <language>ko</language>
    <lastBuildDate>{now_rfc822}</lastBuildDate>
{chr(10).join(rss_items)}
  </channel>
</rss>"""

    with open(RSS_FILE, "w", encoding="utf-8") as f:
        f.write(rss_content)


# 2. 스마트폰 푸시 알림 전송 함수 (디스코드 & ntfy)
def send_notifications(new_events):
    count = len(new_events)

    # ① 디스코드 웹훅 알림 (설정되어 있을 때만 실행)
    if DISCORD_WEBHOOK_URL:
        embeds = []
        for ev in new_events[:5]:  # 한 번에 최대 5개까지 미리보기 표시
            embeds.append({
                "title": ev["title"][:250],
                "url": ev["link"],
                "description": ev["snippet"][:300],
                "color": 5814783,
                "footer": {"text": f"출처: {ev['source_name']}"}
            })

        payload = {
            "content": f"🎂 **{count}건의 새로운 버튜버 생일 광고/팬 행사**가 수집되었습니다!\n👉 아카이브 웹페이지: {SITE_URL}",
            "embeds": embeds
        }
        try:
            requests.post(DISCORD_WEBHOOK_URL, json=payload, timeout=10)
        except Exception as e:
            print(f"디스코드 알림 실패: {e}")

    # ② ntfy.sh 모바일 푸시 알림 (설정되어 있을 때만 실행)
    if NTFY_TOPIC:
        first_title = new_events[0]["title"]
        summary_msg = f"{first_title} 등 총 {count}건의 신규 행사가 업데이트되었습니다."
        try:
            requests.post(
                f"https://ntfy.sh/{NTFY_TOPIC}",
                data=summary_msg.encode("utf-8"),
                headers={
                    "Title": "새로운 버튜버 행사 알림".encode("utf-8"),
                    "Click": SITE_URL,
                    "Tags": "tada,birthday"
                },
                timeout=10
            )
        except Exception as e:
            print(f"ntfy 알림 실패: {e}")


def main():
    config = load_json(CONFIG_FILE, {"search_period": "qdr:m", "keyword_queries": [], "target_accounts": []})
    events = load_json(DATA_FILE, [])
    existing_links = {e["link"] for e in events}
    tbs_period = config.get("search_period", "qdr:m")

    new_events = []
    today_str = datetime.now().strftime("%Y-%m-%d")

    # 1) 키워드 검색
    for query in config.get("keyword_queries", []):
        for item in call_serper(query, tbs=tbs_period):
            raw_link = item.get("link", "")
            clean_link = normalize_x_link(raw_link)
            if not clean_link:
                print(f"  ⏭️ [제외 - 트윗 상태 링크 아님] {raw_link}")
                continue
            if clean_link in existing_links:
                print(f"  ⏭️ [제외 - 이미 수집됨] {clean_link}")
                continue

            new_events.append({
                "date": today_str,
                "source_type": "keyword",
                "source_name": "키워드 검색",
                "title": item.get("title", ""),
                "snippet": item.get("snippet", ""),
                "link": clean_link
            })
            existing_links.add(clean_link)
            print(f"  ✅ [신규 추가] {clean_link} | {item.get('title', '')[:40]}")

    # 2) 전문 계정 타겟 검색
    for acc in config.get("target_accounts", []):
        username = acc.get("username", "").strip()
        if not username:
            continue
        acc_query = f"site:x.com/{username}/status"
        if acc.get("filter_keywords"):
            acc_query += f" {acc['filter_keywords']}"

        for item in call_serper(acc_query, tbs=tbs_period):
            raw_link = item.get("link", "")
            clean_link = normalize_x_link(raw_link)
            if not clean_link or clean_link in existing_links:
                continue

            new_events.append({
                "date": today_str,
                "source_type": "account",
                "source_name": f"@{username} ({acc.get('name', username)})",
                "title": item.get("title", ""),
                "snippet": item.get("snippet", ""),
                "link": clean_link
            })
            existing_links.add(clean_link)
            print(f"  ✅ [신규 추가 - 계정] {clean_link} | {item.get('title', '')[:40]}")

    if new_events:
        updated_events = new_events + events
        save_json(DATA_FILE, updated_events)
        generate_rss(updated_events)
        send_notifications(new_events)
        print(f"🎉 총 {len(new_events)}개의 신규 행사를 업데이트하고 알림을 발송했습니다.")
    else:
        if not os.path.exists(RSS_FILE):
            generate_rss(events)
        print("ℹ️ 새로 추가된 행사가 없습니다.")


if __name__ == "__main__":
    main()
