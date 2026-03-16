import streamlit as st
import pandas as pd
import requests
import plotly.express as px
from googleapiclient.discovery import build
from datetime import datetime, timedelta

st.set_page_config(page_title="실시간 영화 분석", layout="wide")

KOBIS_API_KEY = st.secrets["KOBIS_API_KEY"]
TMDB_API_KEY = st.secrets["TMDB_API_KEY"]
YOUTUBE_API_KEY = st.secrets["YOUTUBE_API_KEY"]

# 화면 표시명과 실제 API 검색용 이름을 분리
MOVIE_MAP = {
    "왕과 사는 남자": {
        "display_name": "왕과 사는 남자",
        "tmdb_query": "왕과 남자",
        "kobis_name": "왕과 남자",
        "youtube_queries": ["왕과 남자 예고편", "The King and the Clown trailer"],
    },
    "명량": {
        "display_name": "명량",
        "tmdb_query": "명량",
        "kobis_name": "명량",
        "youtube_queries": ["명량 예고편", "Roaring Currents trailer"],
    },
    "사도": {
        "display_name": "사도",
        "tmdb_query": "사도",
        "kobis_name": "사도",
        "youtube_queries": ["사도 예고편", "The Throne trailer"],
    },
    "기생충": {
        "display_name": "기생충",
        "tmdb_query": "기생충",
        "kobis_name": "기생충",
        "youtube_queries": ["기생충 예고편", "Parasite trailer"],
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

    # 첫 결과 사용. 필요하면 release_date 기준 보정 가능
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
    """
    개봉일 기준으로 KOBIS 일별 박스오피스를 수집한다.
    release_date가 없으면 빈 DataFrame 반환.
    """
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

    if "날짜" in df.columns:
        df = df.sort_values("날짜").reset_index(drop=True)

    return df


@st.cache_data(ttl=3600)
def fetch_youtube_stats(queries: list[str]):
    youtube = build("youtube", "v3", developerKey=YOUTUBE_API_KEY)
    rows = []

    for query in queries:
        try:
            search_res = youtube.search().list(
                q=query,
                part="snippet",
                maxResults=5,
                type="video",
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
            rows.append({
                "video_id": item["id"],
                "title": item["snippet"].get("title", ""),
                "channel_title": item["snippet"].get("channelTitle", ""),
                "published_at": item["snippet"].get("publishedAt", ""),
                "view_count": int(item.get("statistics", {}).get("viewCount", 0) or 0),
                "like_count": int(item.get("statistics", {}).get("likeCount", 0) or 0),
                "comment_count": int(item.get("statistics", {}).get("commentCount", 0) or 0),
            })

    if not rows:
        return pd.DataFrame(columns=[
            "video_id", "title", "channel_title", "published_at",
            "view_count", "like_count", "comment_count"
        ])

    df = pd.DataFrame(rows).drop_duplicates(subset=["video_id"])
    return df.sort_values("view_count", ascending=False).reset_index(drop=True)


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
        "예고편 조회수": total_views,
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

metrics = build_metrics(tmdb_data, kobis_df, youtube_df)

st.title(f"실시간 영화 분석")
st.subheader(f"영화 '{selected_movie}' 데이터 기반 분석")

col1, col2, col3, col4, col5 = st.columns(5)
col1.metric("총 관객수", f"{metrics['총 관객수']:,}명")
col2.metric("TMDB 인기지수", metrics["TMDB 인기지수"])
col3.metric("예고편 조회수", f"{metrics['예고편 조회수']:,}회")
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

left2, right2 = st.columns(2)

with left2:
    st.subheader("3. YouTube 조회수 상위 영상")
    if not youtube_df.empty:
        fig_yt = px.bar(
            youtube_df.head(10),
            x="title",
            y="view_count",
            title="예고편/관련 영상 조회수",
        )
        st.plotly_chart(fig_yt, use_container_width=True)
    else:
        st.info("YouTube 데이터를 찾지 못했습니다.")

with right2:
    st.subheader("4. 영화 기본 정보")
    if tmdb_data:
        st.write(f"**제목**: {tmdb_data['title']}")
        st.write(f"**개봉일**: {tmdb_data['release_date']}")
        st.write(f"**장르**: {tmdb_data['genres']}")
        st.write(f"**줄거리**: {tmdb_data['overview']}")
    else:
        st.info("TMDB 영화 정보를 불러오지 못했습니다.")
