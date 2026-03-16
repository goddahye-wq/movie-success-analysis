import re
from collections import Counter
from datetime import datetime, timedelta

import pandas as pd
import plotly.express as px
import requests
import streamlit as st
from googleapiclient.discovery import build

st.set_page_config(page_title="실시간 영화 분석", layout="wide")

KOBIS_API_KEY = st.secrets["KOBIS_API_KEY"]
TMDB_API_KEY = st.secrets["TMDB_API_KEY"]
YOUTUBE_API_KEY = st.secrets["YOUTUBE_API_KEY"]

MOVIE_MAP = {
    "왕과 사는 남자": {
        "display_name": "왕과 사는 남자",
        "tmdb_query": "왕과 남자",
        "kobis_name": "왕과 남자",
        "youtube_queries": [
            "왕과 사는 남자",
            "왕과 사는 남자 예고편",
            "왕과 사는 남자 리뷰",
            "왕과 사는 남자 해석",
            "왕과 사는 남자 명장면",
            "The King and the Clown trailer",
            "The King and the Clown review",
        ],
    },
    "명량": {
        "display_name": "명량",
        "tmdb_query": "명량",
        "kobis_name": "명량",
        "youtube_queries": [
            "명량",
            "명량 예고편",
            "명량 리뷰",
            "명량 해석",
            "명량 명장면",
            "Roaring Currents trailer",
            "Roaring Currents review",
        ],
    },
    "사도": {
        "display_name": "사도",
        "tmdb_query": "사도",
        "kobis_name": "사도",
        "youtube_queries": [
            "사도",
            "사도 예고편",
            "사도 리뷰",
            "사도 해석",
            "사도 명장면",
            "The Throne trailer",
            "The Throne review",
        ],
    },
    "기생충": {
        "display_name": "기생충",
        "tmdb_query": "기생충",
        "kobis_name": "기생충",
        "youtube_queries": [
            "기생충",
            "기생충 예고편",
            "기생충 리뷰",
            "기생충 해석",
            "기생충 명장면",
            "Parasite trailer",
            "Parasite review",
        ],
    },
}


@st.cache_data(ttl=3600)
def fetch_tmdb_movie(query: str):
    search_url = "https://api.themoviedb.org/3/search/movie"
    params = {
        "api_key": TMDB_API_KEY,
        "query": query,
        "language": "ko-KR",
    }
    res = requests.get(search_url, params=params, timeout=20)
    res.raise_for_status()
    results = res.json().get("results", [])

    if not results:
        return None

    movie = results[0]
    movie_id = movie["id"]

    detail_url = f"https://api.themoviedb.org/3/movie/{movie_id}"
    detail_params = {
        "api_key": TMDB_API_KEY,
        "language": "ko-KR",
    }
    detail_res = requests.get(detail_url, params=detail_params, timeout=20)
    detail_res.raise_for_status()
    detail = detail_res.json()

    genres = ", ".join([g["name"] for g in detail.get("genres", [])])

    return {
        "movie_id": movie_id,
        "title": detail.get("title", query),
        "release_date": detail.get("release_date"),
        "vote_average": float(detail.get("vote_average", 0) or 0),
        "vote_count": int(detail.get("vote_count", 0) or 0),
        "popularity": float(detail.get("popularity", 0) or 0),
        "runtime": int(detail.get("runtime", 0) or 0),
        "genres": genres,
        "overview": detail.get("overview", ""),
        "homepage": detail.get("homepage", ""),
        "tmdb_url": f"https://www.themoviedb.org/movie/{movie_id}",
    }


def make_empty_kobis_df():
    return pd.DataFrame(columns=[
        "날짜",
        "영화명",
        "일별관객수",
        "누적관객수",
        "스크린수",
        "상영횟수",
        "순위",
    ])


@st.cache_data(ttl=3600)
def fetch_kobis_boxoffice(movie_name: str, release_date: str | None, days: int = 120):
    if not release_date:
        return make_empty_kobis_df()

    try:
        start_date = datetime.strptime(release_date, "%Y-%m-%d")
    except ValueError:
        return make_empty_kobis_df()

    data = []

    for i in range(days):
        current_date = start_date + timedelta(days=i)
        target_dt = current_date.strftime("%Y%m%d")

        url = "http://www.kobis.or.kr/kobisopenapi/webservice/rest/boxoffice/searchDailyBoxOfficeList.json"
        params = {
            "key": KOBIS_API_KEY,
            "targetDt": target_dt,
        }

        try:
            res = requests.get(url, params=params, timeout=20)
            res.raise_for_status()
            json_data = res.json()
        except Exception:
            continue

        daily_list = json_data.get("boxOfficeResult", {}).get("dailyBoxOfficeList", [])

        for item in daily_list:
            if item.get("movieNm") == movie_name:
                data.append({
                    "날짜": current_date.strftime("%Y-%m-%d"),
                    "영화명": item.get("movieNm"),
                    "일별관객수": int(item.get("audiCnt", 0) or 0),
                    "누적관객수": int(item.get("audiAcc", 0) or 0),
                    "스크린수": int(item.get("scrnCnt", 0) or 0),
                    "상영횟수": int(item.get("showCnt", 0) or 0),
                    "순위": int(item.get("rank", 0) or 0),
                })

    df = pd.DataFrame(data)

    if df.empty:
        return make_empty_kobis_df()

    return df.sort_values("날짜").reset_index(drop=True)


def classify_video_type(title: str) -> str:
    t = title.lower()

    if any(k in t for k in ["예고편", "trailer", "teaser"]):
        return "예고편"
    if any(k in t for k in ["리뷰", "review", "해석", "분석", "결말", "설명"]):
        return "리뷰/해설"
    if any(k in t for k in ["명장면", "clip", "scene", "하이라이트"]):
        return "명장면/클립"
    if any(k in t for k in ["인터뷰", "interview", "gv", "제작기", "메이킹"]):
        return "인터뷰/홍보"
    return "기타"


@st.cache_data(ttl=3600)
def fetch_youtube_stats(queries: list[str], max_results_per_query: int = 8):
    youtube = build("youtube", "v3", developerKey=YOUTUBE_API_KEY)
    rows = []

    for query in queries:
        try:
            search_res = youtube.search().list(
                q=query,
                part="snippet",
                maxResults=max_results_per_query,
                type="video",
                relevanceLanguage="ko",
            ).execute()
        except Exception:
            continue

        video_ids = [item["id"]["videoId"] for item in search_res.get("items", [])]
        if not video_ids:
            continue

        try:
            stats_res = youtube.videos().list(
                id=",".join(video_ids),
                part="snippet,statistics",
            ).execute()
        except Exception:
            continue

        for item in stats_res.get("items", []):
            title = item["snippet"].get("title", "")
            rows.append({
                "video_id": item["id"],
                "title": title,
                "channel_title": item["snippet"].get("channelTitle", ""),
                "published_at": item["snippet"].get("publishedAt", ""),
                "view_count": int(item.get("statistics", {}).get("viewCount", 0) or 0),
                "like_count": int(item.get("statistics", {}).get("likeCount", 0) or 0),
                "comment_count": int(item.get("statistics", {}).get("commentCount", 0) or 0),
                "video_type": classify_video_type(title),
                "url": f"https://www.youtube.com/watch?v={item['id']}",
            })

    if not rows:
        return pd.DataFrame(columns=[
            "video_id", "title", "channel_title", "published_at",
            "view_count", "like_count", "comment_count", "video_type", "url"
        ])

    df = pd.DataFrame(rows).drop_duplicates(subset=["video_id"])
    return df.sort_values("view_count", ascending=False).reset_index(drop=True)


@st.cache_data(ttl=3600)
def fetch_youtube_comments(video_ids: list[str], max_comments_per_video: int = 30):
    youtube = build("youtube", "v3", developerKey=YOUTUBE_API_KEY)
    comments = []

    for video_id in video_ids:
        try:
            response = youtube.commentThreads().list(
                part="snippet",
                videoId=video_id,
                maxResults=min(max_comments_per_video, 100),
                textFormat="plainText",
                order="relevance",
            ).execute()
        except Exception:
            continue

        for item in response.get("items", []):
            snippet = item["snippet"]["topLevelComment"]["snippet"]
            comments.append({
                "video_id": video_id,
                "author": snippet.get("authorDisplayName", ""),
                "text": snippet.get("textDisplay", ""),
                "like_count": int(snippet.get("likeCount", 0) or 0),
                "published_at": snippet.get("publishedAt", ""),
            })

    if not comments:
        return pd.DataFrame(columns=["video_id", "author", "text", "like_count", "published_at"])

    return pd.DataFrame(comments)


def extract_top_keywords(text_series, top_n: int = 15):
    stopwords = {
        "영화", "진짜", "너무", "그냥", "정말", "이거", "이런", "저런", "그리고",
        "하는", "있는", "입니다", "에서", "으로", "하다", "같은", "대한", "the",
        "this", "that", "with", "from", "있다", "했다", "하는데", "예고편"
    }

    text = " ".join(text_series.dropna().astype(str).tolist())
    words = re.findall(r"[가-힣A-Za-z]{2,}", text)
    words = [w.lower() for w in words if w.lower() not in stopwords]

    counter = Counter(words)
    return pd.DataFrame(counter.most_common(top_n), columns=["keyword", "count"])


def build_metrics(tmdb_data, kobis_df, youtube_df):
    total_audience = 0
    if not kobis_df.empty and "누적관객수" in kobis_df.columns:
        total_audience = int(kobis_df["누적관객수"].max())

    total_views = 0
    if not youtube_df.empty and "view_count" in youtube_df.columns:
        total_views = int(youtube_df["view_count"].sum())

    return {
        "총 관객수": total_audience,
        "TMDB 인기지수": round(tmdb_data["popularity"], 1) if tmdb_data else 0,
        "유튜브 총조회수": total_views,
        "러닝타임": tmdb_data["runtime"] if tmdb_data else 0,
        "TMDB 평점": round(tmdb_data["vote_average"], 1) if tmdb_data else 0,
    }


st.sidebar.title("실시간 영화 분석")
selected_movie = st.sidebar.selectbox("영화 선택", list(MOVIE_MAP.keys()))
movie_info = MOVIE_MAP[selected_movie]

with st.spinner("API에서 데이터를 불러오는 중..."):
    tmdb_data = fetch_tmdb_movie(movie_info["tmdb_query"])
    release_date = tmdb_data["release_date"] if tmdb_data else None
    kobis_df = fetch_kobis_boxoffice(movie_info["kobis_name"], release_date, days=120)
    youtube_df = fetch_youtube_stats(movie_info["youtube_queries"])
    top_video_ids = youtube_df.head(3)["video_id"].tolist() if not youtube_df.empty else []
    comments_df = fetch_youtube_comments(top_video_ids, max_comments_per_video=30) if top_video_ids else pd.DataFrame()

metrics = build_metrics(tmdb_data, kobis_df, youtube_df)

st.title("실시간 영화 분석")
st.subheader(f"영화 '{selected_movie}' 데이터 기반 분석")

col1, col2, col3, col4, col5 = st.columns(5)
col1.metric("총 관객수", f"{metrics['총 관객수']:,}명")
col2.metric("TMDB 인기지수", metrics["TMDB 인기지수"])
col3.metric("유튜브 총조회수", f"{metrics['유튜브 총조회수']:,}회")
col4.metric("러닝타임", f"{metrics['러닝타임']}분")
col5.metric("TMDB 평점", metrics["TMDB 평점"])

st.markdown("---")

left, right = st.columns(2)

with left:
    st.subheader("1. 일별 관객수 추이")
    if not kobis_df.empty:
        fig_daily = px.bar(
            kobis_df,
            x="날짜",
            y="일별관객수",
            title="일별 관객수",
        )
        st.plotly_chart(fig_daily, use_container_width=True)
    else:
        st.info("KOBIS 관객 데이터를 찾지 못했습니다.")

with right:
    st.subheader("2. 누적 관객수 성장 추이")
    if not kobis_df.empty:
        fig_acc = px.line(
            kobis_df,
            x="날짜",
            y="누적관객수",
            title="누적 관객수 성장",
        )
        st.plotly_chart(fig_acc, use_container_width=True)
    else:
        st.info("누적 관객수 데이터를 표시할 수 없습니다.")

st.markdown("---")

left2, right2 = st.columns(2)

with left2:
    st.subheader("3. 유튜브 상위 조회수 영상")
    if not youtube_df.empty:
        show_df = youtube_df[[
            "title", "channel_title", "video_type", "view_count",
            "like_count", "comment_count", "url"
        ]].copy()
        st.dataframe(show_df, use_container_width=True)
    else:
        st.info("YouTube 데이터를 찾지 못했습니다.")

with right2:
    st.subheader("4. 콘텐츠 유형별 조회수")
    if not youtube_df.empty:
        video_type_df = (
            youtube_df.groupby("video_type", as_index=False)["view_count"]
            .sum()
            .sort_values("view_count", ascending=False)
        )
        fig_type = px.bar(
            video_type_df,
            x="video_type",
            y="view_count",
            title="콘텐츠 유형별 총 조회수",
        )
        st.plotly_chart(fig_type, use_container_width=True)
    else:
        st.info("콘텐츠 유형 데이터를 표시할 수 없습니다.")

st.markdown("---")

left3, right3 = st.columns(2)

with left3:
    st.subheader("5. 영화 기본 정보")
    if tmdb_data:
        st.write(f"**제목**: {tmdb_data['title']}")
        st.write(f"**개봉일**: {tmdb_data['release_date']}")
        st.write(f"**장르**: {tmdb_data['genres']}")
        st.write(f"**줄거리**: {tmdb_data['overview']}")
        st.markdown(f"**TMDB 페이지**: [바로가기]({tmdb_data['tmdb_url']})")
        if tmdb_data.get("homepage"):
            st.markdown(f"**공식 홈페이지**: [바로가기]({tmdb_data['homepage']})")
    else:
        st.info("TMDB 영화 정보를 불러오지 못했습니다.")

with right3:
    st.subheader("6. 댓글 키워드 분석")
    if not comments_df.empty:
        keyword_df = extract_top_keywords(comments_df["text"], top_n=15)
        fig_keywords = px.bar(
            keyword_df,
            x="keyword",
            y="count",
            title="댓글 상위 키워드",
        )
        st.plotly_chart(fig_keywords, use_container_width=True)

        st.markdown("**대표 댓글 샘플**")
        sample_comments = comments_df[["author", "text", "like_count"]].head(5)
        for _, row in sample_comments.iterrows():
            st.markdown(f"- **{row['author']}** ({row['like_count']} likes): {row['text']}")
    else:
        st.info("댓글 데이터를 가져오지 못했습니다.")
