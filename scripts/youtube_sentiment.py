"""
TSLA YouTube 관심도 수집 스크립트 (YouTube Data API v3)
GitHub Actions에서 auto-analysis.js 실행 전에 호출됨.
결과를 data/youtube-sentiment.json 에 저장.

필요 패키지: pip install google-api-python-client
필요 환경변수: YOUTUBE_API_KEY
"""

import os
import json
import sys
from datetime import datetime, timezone, timedelta
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# ── 설정 ──────────────────────────────────────────────────────────────────────

YOUTUBE_API_KEY = os.environ.get("YOUTUBE_API_KEY", "")   # ← API Key 변수 (GitHub Secret)

SEARCH_QUERIES  = ["Tesla TSLA stock", "Tesla earnings", "Tesla Optimus robot"]
MAX_RESULTS     = 15          # 쿼리당 최대 수집 영상 수
LOOKBACK_DAYS   = 7           # 최근 7일치 영상
OUTPUT_FILE     = os.path.join(os.path.dirname(__file__), "..", "data", "youtube-sentiment.json")

# ── 유틸 ──────────────────────────────────────────────────────────────────────

def iso_now_utc():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

def days_ago_iso(n: int) -> str:
    dt = datetime.now(timezone.utc) - timedelta(days=n)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")

def parse_view_count(stats: dict) -> int:
    try:
        return int(stats.get("viewCount", 0))
    except (ValueError, TypeError):
        return 0

# ── 수집 ──────────────────────────────────────────────────────────────────────

def collect_videos(youtube) -> list[dict]:
    """여러 쿼리로 Tesla 관련 최신 영상 수집 (중복 제거)"""
    published_after = days_ago_iso(LOOKBACK_DAYS)
    seen_ids: set[str] = set()
    items: list[dict] = []

    for query in SEARCH_QUERIES:
        try:
            response = youtube.search().list(
                part="snippet",
                q=query,
                type="video",
                order="viewCount",          # 조회수 높은 순
                publishedAfter=published_after,
                maxResults=MAX_RESULTS,
                relevanceLanguage="en",
            ).execute()
        except HttpError as e:
            print(f"   ⚠ YouTube search 오류 ({query}): {e}", file=sys.stderr)
            continue

        for item in response.get("items", []):
            vid_id = item["id"].get("videoId")
            if not vid_id or vid_id in seen_ids:
                continue
            seen_ids.add(vid_id)
            snippet = item.get("snippet", {})
            items.append({
                "id":           vid_id,
                "title":        snippet.get("title", ""),
                "channel":      snippet.get("channelTitle", ""),
                "publishedAt":  snippet.get("publishedAt", ""),
            })

    return items


def fetch_statistics(youtube, video_items: list[dict]) -> list[dict]:
    """video.list로 조회수/좋아요 수 일괄 조회 (50개씩 배치)"""
    result = []
    ids = [v["id"] for v in video_items]

    for i in range(0, len(ids), 50):
        batch = ids[i:i + 50]
        try:
            resp = youtube.videos().list(
                part="statistics,snippet",
                id=",".join(batch),
            ).execute()
        except HttpError as e:
            print(f"   ⚠ YouTube videos.list 오류: {e}", file=sys.stderr)
            continue

        meta = {v["id"]: v for v in video_items}
        for item in resp.get("items", []):
            vid_id = item["id"]
            stats  = item.get("statistics", {})
            base   = meta.get(vid_id, {})
            result.append({
                "id":          vid_id,
                "title":       base.get("title", item["snippet"].get("title", "")),
                "channel":     base.get("channel", item["snippet"].get("channelTitle", "")),
                "publishedAt": base.get("publishedAt", item["snippet"].get("publishedAt", "")),
                "viewCount":   parse_view_count(stats),
                "likeCount":   int(stats.get("likeCount", 0) or 0),
            })

    return result

# ── 점수 산출 ─────────────────────────────────────────────────────────────────

def calc_interest_score(videos: list[dict]) -> dict:
    """
    매수 심리 지수 기여 점수 (-3 ~ +3)

    로직:
      1. 최근 3일(hot) vs 이전 4~7일(baseline) 조회수 속도 비교
      2. 절대 조회수 기준 보정
      최종 점수: velocity_score + volume_bonus, 클리핑 -3 ~ +3
    """
    if not videos:
        return {"score": 0, "reason": "영상 없음", "video_count": 0,
                "total_views": 0, "top_videos": []}

    now_utc = datetime.now(timezone.utc)
    hot_views      = 0   # 최근 0~3일
    baseline_views = 0   # 4~7일 전

    for v in videos:
        try:
            pub = datetime.fromisoformat(v["publishedAt"].replace("Z", "+00:00"))
            age_days = (now_utc - pub).total_seconds() / 86400
        except Exception:
            age_days = LOOKBACK_DAYS

        if age_days <= 3:
            hot_views += v["viewCount"]
        else:
            baseline_views += v["viewCount"]

    total_views = hot_views + baseline_views

    # 조회수 속도 비율
    if baseline_views > 0 and hot_views > 0:
        velocity = hot_views / baseline_views
    elif hot_views > 0:
        velocity = 2.0   # 최근 영상만 있음 → 상승
    elif baseline_views > 0:
        velocity = 0.4   # 최근 3일 영상 없음 → 약한 감소 (0.0 → -3 과도 패널티 방지)
    else:
        velocity = 0.5   # 7일간 영상 없음 → 보합 처리

    # velocity → velocity_score
    if velocity >= 2.5:
        velocity_score = 3
        velocity_label = f"급등 (×{velocity:.1f})"
    elif velocity >= 1.8:
        velocity_score = 2
        velocity_label = f"상승 (×{velocity:.1f})"
    elif velocity >= 1.2:
        velocity_score = 1
        velocity_label = f"소폭 상승 (×{velocity:.1f})"
    elif velocity >= 0.7:
        velocity_score = 0
        velocity_label = f"보합 (×{velocity:.1f})"
    elif velocity >= 0.4:
        velocity_score = -1
        velocity_label = f"소폭 감소 (×{velocity:.1f})"
    else:
        velocity_score = -2
        velocity_label = f"급감 (×{velocity:.1f})"

    # 절대 조회수 보정 (+1 / -1)
    volume_bonus = 0
    if total_views >= 5_000_000:
        volume_bonus = +1
    elif total_views <= 300_000:
        volume_bonus = -1

    raw_score = velocity_score + volume_bonus
    score     = max(-3, min(3, raw_score))

    top_videos = sorted(videos, key=lambda x: x["viewCount"], reverse=True)[:5]

    reason = (
        f"조회수 속도 {velocity_label} | "
        f"최근 3일 {hot_views:,}회 / 이전 4~7일 {baseline_views:,}회 | "
        f"총 {total_views:,}회 ({len(videos)}개 영상)"
    )

    return {
        "score":           score,
        "velocity":        round(velocity, 2),
        "velocity_label":  velocity_label,
        "reason":          reason,
        "video_count":     len(videos),
        "total_views":     total_views,
        "hot_views":       hot_views,
        "baseline_views":  baseline_views,
        "top_videos": [
            {
                "title":       v["title"],
                "channel":     v["channel"],
                "publishedAt": v["publishedAt"],
                "viewCount":   v["viewCount"],
            }
            for v in top_videos
        ],
    }

# ── 메인 ──────────────────────────────────────────────────────────────────────

def main():
    if not YOUTUBE_API_KEY:
        print("   ⚠ YOUTUBE_API_KEY 없음 — YouTube 수집 건너뜀", file=sys.stderr)
        # 빈 결과 저장 (auto-analysis.js가 읽을 수 있도록)
        result = {"score": 0, "reason": "API Key 없음", "video_count": 0,
                  "total_views": 0, "top_videos": [], "collected_at": iso_now_utc()}
        os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)
        with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        sys.exit(0)

    print("   📺 YouTube 관심도 수집 시작...")

    youtube = build("youtube", "v3", developerKey=YOUTUBE_API_KEY)

    videos = collect_videos(youtube)
    print(f"   검색 완료: {len(videos)}개 영상 발견")

    videos_with_stats = fetch_statistics(youtube, videos)
    print(f"   통계 수집 완료: {len(videos_with_stats)}개")

    result = calc_interest_score(videos_with_stats)
    result["collected_at"] = iso_now_utc()

    score = result["score"]
    label = "🔼 관심↑" if score > 0 else "🔽 관심↓" if score < 0 else "➡ 보합"
    print(f"   ✅ YouTube 관심 지수: {score:+d} ({label})")
    print(f"      {result['reason']}")
    if result["top_videos"]:
        print("   📋 인기 영상 Top 3:")
        for v in result["top_videos"][:3]:
            print(f"      [{v['viewCount']:>10,}회] {v['title'][:60]}")

    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(f"   💾 저장: {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
