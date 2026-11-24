import os
import json
import urllib.parse
import feedparser
import requests
from google import genai

# 환경 변수에서 비밀 금고 값 불러오기
TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]
GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]

client = genai.Client(api_key=GEMINI_API_KEY)
SENT_FILE = "sent_links.json"


def load_json(path, default):
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return default


def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def fetch_rss(query, is_korean=True):
    encoded = urllib.parse.quote(query)
    if is_korean:
        url = f"https://news.google.com/rss/search?q={encoded}+when:3h&hl=ko&gl=KR&ceid=KR:ko"
    else:
        url = f"https://news.google.com/rss/search?q={encoded}+when:3h&hl=en-US&gl=US&ceid=US:en"

    feed = feedparser.parse(url)
    articles = []
    for entry in feed.entries[:5]:  # 종목당 최신 5개만 확인
        articles.append({
            "keyword": query,
            "title": entry.title,
            "link": entry.link,
            "published": getattr(entry, "published", "")
        })
    return articles


def evaluate_article(keyword, title):
    prompt = f"""
당신은 냉철한 주식 애널리스트입니다. 다음 뉴스 제목이 투자자 입장에서 주가에 직접 영향을 줄 '민감한 핵심 이슈'인지 판별하세요.

- 관심 종목/키워드: {keyword}
- 기사 제목: {title}

[통과 기준 (IMPORTANT = YES)]
- 실적 발표(어닝 서프라이즈/쇼크), 가이던스 수정
- 유상증자, 자사주 소각, 배당 변경, 액면분할
- 대규모 수주, 계약 해지, M&A, 핵심 신제품 출시/지연
- 반독점 규제, 소송, 리콜, CEO 교체, 횡령/배임
- FOMC 금리, CPI 등 거시경제에 충격을 주는 발표

[제외 기준 (IMPORTANT = NO)]
- 단순 장중 주가 등락 중계 ("~% 상승 마감", "장초반 강세")
- 근거 없는 테마주 엮기, 단순 증권사 목표가 반복 리포트, 광고성 기사

반드시 아래 JSON 형식으로만 답하세요:
{{"important": true 또는 false, "sentiment": "호재" 또는 "악재" 또는 "중립", "summary": "한국어로 핵심 내용 1~2줄 요약"}}
"""
    try:
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
        )
        text = response.text.strip()
        if text.startswith("```"):
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
        return json.loads(text.strip())
    except Exception as e:
        print(f"AI 분석 오류: {e}")
        return {"important": False}


def send_telegram(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": False
    }
    requests.post(url, json=payload, timeout=10)


def main():
    watchlist = load_json("watchlist.json", {"kr_stocks": [], "us_stocks": []})
    sent_links = load_json(SENT_FILE, [])
    sent_set = set(sent_links)

    candidates = []
    for kw in watchlist.get("kr_stocks", []):
        candidates.extend(fetch_rss(kw, is_korean=True))
    for kw in watchlist.get("us_stocks", []):
        candidates.extend(fetch_rss(kw, is_korean=False))

    new_sent = []
    for item in candidates:
        if item["link"] in sent_set:
            continue

        result = evaluate_article(item["keyword"], item["title"])
        sent_set.add(item["link"])
        new_sent.append(item["link"])

        if result.get("important"):
            sentiment = result.get("sentiment", "중립")
            emoji = "🔴" if sentiment == "호재" else ("🔵" if sentiment == "악재" else "🟡")
            msg = (
                f"{emoji} <b>[{item['keyword']}] {sentiment} 이슈</b>\n\n"
                f"📰 <b>{item['title']}</b>\n"
                f"💡 {result.get('summary', '')}\n\n"
                f"🔗 <a href=\"{item['link']}\">기사 원문 보기</a>"
            )
            send_telegram(msg)

    # 최근 500개 기록만 유지해 파일 크기 관리
    updated_links = (sent_links + new_sent)[-500:]
    save_json(SENT_FILE, updated_links)


if __name__ == "__main__":
    main()
