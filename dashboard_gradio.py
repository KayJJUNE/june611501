import gradio as gr
import pandas as pd
import psycopg2
import os
from datetime import datetime, timedelta
import matplotlib.pyplot as plt
import plotly.express as px
from wordcloud import WordCloud

DATABASE_URL = os.environ.get("DATABASE_URL")

# PostgreSQL 연결 함수
def get_conn():
    return psycopg2.connect(DATABASE_URL, sslmode='require')

def get_user_cards():
    conn = get_conn()
    df = pd.read_sql_query("""
        SELECT user_id, character_name, card_id, acquired_at
        FROM user_cards
        ORDER BY acquired_at DESC
    """, conn)
    conn.close()
    return df

def get_user_info():
    conn = get_conn()
    df = pd.read_sql_query("""
        SELECT user_id, character_name, emotion_score, daily_message_count
        FROM affinity
    """, conn)
    conn.close()
    return df

def get_user_summary(user_id):
    conn = get_conn()
    # 유저 기본 정보
    user_info = pd.read_sql_query(f"""
        SELECT
            %s as user_id,
            MIN(timestamp) as joined_at,
            SUM(CASE WHEN message_role='user' THEN 1 ELSE 0 END) as total_messages
        FROM conversations
        WHERE user_id = %s
    """, conn, params=(user_id, user_id))
    # 친밀도 등급
    affinity = pd.read_sql_query("""
        SELECT character_name, emotion_score, daily_message_count
        FROM affinity
        WHERE user_id = %s
    """, conn, params=(user_id,))
    # 카드 정보
    cards = pd.read_sql_query("""
        SELECT card_id, character_name, acquired_at
        FROM user_cards
        WHERE user_id = %s
        ORDER BY acquired_at DESC
    """, conn, params=(user_id,))
    # 카드 등급 비율
    card_tiers = pd.read_sql_query("""
        SELECT
            SUBSTRING(card_id, 1, 1) as tier,
            COUNT(*) as count
        FROM user_cards
        WHERE user_id = %s
        GROUP BY tier
    """, conn, params=(user_id,))
    # 캐릭터별 카드 분류
    char_cards = pd.read_sql_query("""
        SELECT character_name, COUNT(*) as count
        FROM user_cards
        WHERE user_id = %s
        GROUP BY character_name
    """, conn, params=(user_id,))
    # 최근 획득 카드
    recent_card = cards.head(1)
    # 주간 활동량
    week_ago = (datetime.now() - timedelta(days=7)).strftime('%Y-%m-%d')
    week_msgs = pd.read_sql_query("""
        SELECT COUNT(*) as week_messages
        FROM conversations
        WHERE user_id = %s AND timestamp >= %s AND message_role = 'user'
    """, conn, params=(user_id, week_ago))
    week_cards = pd.read_sql_query("""
        SELECT COUNT(*) as week_cards
        FROM user_cards
        WHERE user_id = %s AND acquired_at >= %s
    """, conn, params=(user_id, week_ago))
    # 스토리 진행 현황
    story_progress = get_user_story_progress(user_id)
    # 로그인 정보
    login_info = pd.read_sql_query("""
        SELECT current_streak, last_login_date
        FROM user_login_streaks
        WHERE user_id = %s
    """, conn, params=(user_id,))
    # 선물 정보
    gifts = pd.read_sql_query("""
        SELECT gift_id, quantity
        FROM user_gifts
        WHERE user_id = %s
    """, conn, params=(user_id,))
    # 키워드 정보
    keywords = pd.read_sql_query("""
        SELECT keyword_value, context
        FROM user_keywords
        WHERE user_id = %s
    """, conn, params=(user_id,))
    # 닉네임 정보
    nicknames = pd.read_sql_query("""
        SELECT character_name, nickname
        FROM user_nicknames
        WHERE user_id = %s
    """, conn, params=(user_id,))
    # 에피소드 정보
    episodes = pd.read_sql_query("""
        SELECT character, summary, timestamp
        FROM episodes
        WHERE user_id = %s
        ORDER BY timestamp DESC LIMIT 10
    """, conn, params=(user_id,))
    conn.close()
    # 결과 딕셔너리로 반환
    return {
        "기본 정보": user_info,
        "친밀도": affinity,
        "카드 목록": cards,
        "카드 등급 비율": card_tiers,
        "캐릭터별 카드 분류": char_cards,
        "최근 획득 카드": recent_card,
        "주간 대화 수": week_msgs,
        "주간 카드 획득": week_cards,
        "스토리 진행 현황": story_progress,
        "로그인 정보": login_info,
        "선물 정보": gifts,
        "키워드 정보": keywords,
        "닉네임 정보": nicknames,
        "에피소드 정보": episodes
    }

def user_dashboard(user_id):
    info = get_user_summary(user_id)
    return (
        info["기본 정보"],
        info["친밀도"],
        info["카드 목록"],
        info["카드 등급 비율"],
        info["캐릭터별 카드 분류"],
        info["최근 획득 카드"],
        info["주간 대화 수"],
        info["주간 카드 획득"],
        info["스토리 진행 현황"],
        info["로그인 정보"],
        info["선물 정보"],
        info["키워드 정보"],
        info["닉네임 정보"],
        info["에피소드 정보"]
    )

def get_daily_affinity_gain(character_name=None):
    conn = get_conn()
    today = datetime.now().strftime('%Y-%m-%d')
    if character_name:
        df = pd.read_sql_query("""
            SELECT user_id, SUM(score) as today_gain
            FROM affinity_log
            WHERE character_name = %s AND DATE(timestamp AT TIME ZONE 'Asia/Seoul') = %s
            GROUP BY user_id
            ORDER BY today_gain DESC
        """, conn, params=(character_name, today))
    else:
        df = pd.read_sql_query("""
            SELECT user_id, character_name, SUM(score) as today_gain
            FROM affinity_log
            WHERE DATE(timestamp AT TIME ZONE 'Asia/Seoul') = %s
            GROUP BY user_id, character_name
            ORDER BY today_gain DESC
        """, conn, params=(today,))
    conn.close()
    return df

def get_quest_completion_rate(quest_type):
    conn = get_conn()
    total_users = pd.read_sql_query("SELECT COUNT(DISTINCT user_id) as total FROM affinity", conn)["total"][0]
    completed = pd.read_sql_query("""
        SELECT COUNT(DISTINCT user_id) as completed
        FROM quest_claims
        WHERE quest_id = %s AND DATE(claimed_at AT TIME ZONE 'Asia/Seoul') = CURRENT_DATE
    """, conn, params=(quest_type,))["completed"][0]
    conn.close()
    percent = (completed / total_users * 100) if total_users else 0
    return pd.DataFrame({"달성 유저 수": [completed], "전체 유저 수": [total_users], "달성률(%)": [round(percent,2)]})

# --- 퀘스트 달성률 일괄 조회 함수 추가 ---
def get_quest_completion_all():
    daily_conv = get_quest_completion_rate("daily_conversation")
    daily_aff = get_quest_completion_rate("daily_affinity_gain")
    weekly_login = get_quest_completion_rate("weekly_login")
    weekly_share = get_quest_completion_rate("weekly_share")
    return daily_conv, daily_aff, weekly_login, weekly_share

def get_user_gifts(user_id):
    conn = get_conn()
    df = pd.read_sql_query("""
        SELECT gift_id, quantity
        FROM user_gifts
        WHERE user_id = %s
    """, conn, params=(user_id,))
    conn.close()
    return df

def get_login_streak_ranking():
    conn = get_conn()
    df = pd.read_sql_query("""
        SELECT user_id, current_streak
        FROM user_login_streaks
        ORDER BY current_streak DESC
    """, conn)
    conn.close()
    return df

def get_message_trend():
    conn = get_conn()
    df = pd.read_sql_query("""
        SELECT DATE(timestamp AT TIME ZONE 'Asia/Seoul') as date, COUNT(*) as messages
        FROM conversations
        WHERE message_role = 'user'
        GROUP BY DATE(timestamp AT TIME ZONE 'Asia/Seoul')
        ORDER BY date
    """, conn)
    conn.close()
    return df

def get_user_keywords(user_id):
    conn = get_conn()
    df = pd.read_sql_query("""
        SELECT character_name, keyword_value, context
        FROM user_keywords
        WHERE user_id = %s
    """, conn, params=(user_id,))
    conn.close()
    return df

def get_user_nicknames(user_id):
    conn = get_conn()
    df = pd.read_sql_query("""
        SELECT character_name, nickname
        FROM user_nicknames
        WHERE user_id = %s
    """, conn, params=(user_id,))
    conn.close()
    return df

def get_user_episodes(user_id):
    conn = get_conn()
    df = pd.read_sql_query("""
        SELECT character, summary, timestamp
        FROM episodes
        WHERE user_id = %s
        ORDER BY timestamp DESC LIMIT 10
    """, conn, params=(user_id,))
    conn.close()
    return df

def get_dashboard_stats():
    conn = get_conn()
    # 1. 총 유저 메시지 수
    total_user_messages = pd.read_sql_query(
        "SELECT COUNT(*) as total_user_messages FROM conversations WHERE LOWER(message_role)='user';", conn
    )["total_user_messages"][0]
    # 2. 챗봇 총 친밀도 점수
    total_affinity = pd.read_sql_query(
        "SELECT SUM(emotion_score) as total_affinity FROM affinity;", conn
    )["total_affinity"][0]
    # 3. OpenAI 토큰 소비량
    try:
        total_tokens = pd.read_sql_query(
            "SELECT SUM(token_count) as total_tokens FROM conversations WHERE message_role='assistant';", conn
        )["total_tokens"][0]
        if total_tokens is None:
            total_tokens = 0
    except Exception:
        total_tokens = 0
    # 4. 카드 등급별 출하량 및 백분율
    card_tiers = pd.read_sql_query(
        "SELECT SUBSTRING(card_id, 1, 1) as tier, COUNT(*) as count FROM user_cards GROUP BY tier;", conn
    )
    total_cards = card_tiers["count"].sum()
    card_tiers["percent"] = (card_tiers["count"] / total_cards * 100).round(2).astype(str) + "%"
    # 레벨 통계 추가
    level_stats = get_level_statistics()
    conn.close()
    return {
        "총 유저 메시지 수": total_user_messages,
        "총 친밀도 점수": total_affinity,
        "OpenAI 토큰 소비량": f"{total_tokens:,} 토큰",
        "카드 등급별 출하량": card_tiers,
        "레벨별 현황": level_stats
    }

def show_dashboard_stats():
    stats = get_dashboard_stats()
    # 표/카드 형태로 반환
    return (
        f"총 유저 메시지 수: {stats['총 유저 메시지 수']}",
        f"총 친밀도 점수: {stats['총 친밀도 점수']}",
        f"OpenAI 토큰 소비량: {stats['OpenAI 토큰 소비량']}",
        stats["카드 등급별 출하량"],
        stats["레벨별 현황"]
    )

def get_full_character_ranking(character_name):
    conn = get_conn()
    df = pd.read_sql_query(f'''
        SELECT a.user_id, a.emotion_score, COALESCE(cc.message_count, 0) as message_count
        FROM affinity a
        LEFT JOIN (
            SELECT user_id, character_name, COUNT(*) as message_count
            FROM conversations
            WHERE message_role = 'user'
            GROUP BY user_id, character_name
        ) cc ON a.user_id = cc.user_id AND a.character_name = cc.character_name
        WHERE a.character_name = %s
        ORDER BY a.emotion_score DESC, message_count DESC
    ''', conn, params=(character_name,))
    conn.close()
    return df

def get_full_total_ranking():
    conn = get_conn()
    df = pd.read_sql_query('''
        SELECT a.user_id, COALESCE(a.total_affinity, 0) as total_affinity, COALESCE(m.total_messages, 0) as total_messages
        FROM (
            SELECT user_id, SUM(emotion_score) as total_affinity
            FROM affinity
            GROUP BY user_id
        ) a
        LEFT JOIN (
            SELECT user_id, COUNT(*) as total_messages
            FROM conversations
            WHERE message_role = 'user'
            GROUP BY user_id
        ) m ON a.user_id = m.user_id
        UNION
        SELECT m.user_id, COALESCE(a.total_affinity, 0) as total_affinity, COALESCE(m.total_messages, 0) as total_messages
        FROM (
            SELECT user_id, COUNT(*) as total_messages
            FROM conversations
            WHERE message_role = 'user'
            GROUP BY user_id
        ) m
        LEFT JOIN (
            SELECT user_id, SUM(emotion_score) as total_affinity
            FROM affinity
            GROUP BY user_id
        ) a ON m.user_id = a.user_id
        ORDER BY total_affinity DESC, total_messages DESC
    ''', conn)
    conn.close()
    return df

def show_all_rankings():
    kagari = get_full_character_ranking("Kagari")
    eros = get_full_character_ranking("Eros")
    elysia = get_full_character_ranking("Elysia")
    total = get_full_total_ranking()
    return kagari, eros, elysia, total

def get_level_statistics():
    conn = get_conn()
    # 전체 유저 수 계산
    total_users = pd.read_sql_query("""
        SELECT COUNT(DISTINCT user_id) as total_users
        FROM affinity
    """, conn)["total_users"][0]

    # 레벨별 유저 수 계산
    level_stats = pd.read_sql_query("""
        WITH user_levels AS (
            SELECT 
                user_id,
                CASE 
                    WHEN SUM(emotion_score) < 10 THEN 'Rookie'
                    WHEN SUM(emotion_score) < 30 THEN 'Iron'
                    WHEN SUM(emotion_score) < 50 THEN 'Bronze'
                    WHEN SUM(emotion_score) < 100 THEN 'Silver'
                    ELSE 'Gold'
                END as level
            FROM affinity
            GROUP BY user_id
        )
        SELECT 
            level,
            COUNT(*) as user_count,
            ROUND(COUNT(*) * 100.0 / ?, 2) as percentage
        FROM user_levels
        GROUP BY level
        ORDER BY 
            CASE level
                WHEN 'Rookie' THEN 1
                WHEN 'Iron' THEN 2
                WHEN 'Bronze' THEN 3
                WHEN 'Silver' THEN 4
                WHEN 'Gold' THEN 5
            END
    """, conn, params=(total_users,))
    conn.close()
    return level_stats

def get_user_story_progress(user_id):
    conn = get_conn()
    # 스토리 챕터 진행 현황
    chapter_progress = pd.read_sql_query("""
        SELECT 
            character_name,
            chapter_number,
            completed_at,
            selected_choice,
            ending_type
        FROM story_progress
        WHERE user_id = %s
        ORDER BY character_name, chapter_number
    """, conn, params=(user_id,))
    conn.close()
    return chapter_progress

def get_all_story_progress():
    conn = get_conn()
    # 전체 스토리 진행 현황
    story_stats = pd.read_sql_query("""
        SELECT 
            character_name,
            chapter_number,
            COUNT(DISTINCT user_id) as completed_users,
            COUNT(DISTINCT CASE WHEN ending_type = 'Good' THEN user_id END) as good_endings,
            COUNT(DISTINCT CASE WHEN ending_type = 'Bad' THEN user_id END) as bad_endings,
            COUNT(DISTINCT CASE WHEN ending_type = 'Normal' THEN user_id END) as normal_endings
        FROM story_progress
        GROUP BY character_name, chapter_number
        ORDER BY character_name, chapter_number
    """, conn)
    conn.close()
    return story_stats

def get_basic_stats():
    conn = get_conn()
    total_turns = pd.read_sql_query("SELECT COUNT(*) FROM conversations WHERE message_role='user'", conn).iloc[0,0]
    total_cards = pd.read_sql_query("SELECT COUNT(*) FROM user_cards", conn).iloc[0,0]
    card_tiers = pd.read_sql_query("SELECT SUBSTRING(card_id,1,1) as tier, COUNT(*) as count FROM user_cards GROUP BY tier", conn)
    total_users = pd.read_sql_query("SELECT COUNT(DISTINCT user_id) FROM conversations", conn).iloc[0,0]
    rank_dist = pd.read_sql_query("""WITH user_levels AS (
        SELECT user_id,
            CASE 
                WHEN SUM(emotion_score) < 10 THEN 'Rookie'
                WHEN SUM(emotion_score) < 30 THEN 'Iron'
                WHEN SUM(emotion_score) < 50 THEN 'Bronze'
                WHEN SUM(emotion_score) < 100 THEN 'Silver'
                ELSE 'Gold'
            END as level
        FROM affinity GROUP BY user_id
    ) SELECT level, COUNT(*) as count FROM user_levels GROUP BY level ORDER BY level""", conn)
    total_gifts = pd.read_sql_query("SELECT SUM(quantity) FROM user_gifts", conn).iloc[0,0]
    conn.close()
    return total_turns, total_cards, card_tiers, total_users, rank_dist, total_gifts

def plot_card_distribution_by_character():
    conn = get_conn()
    df = pd.read_sql_query('''
        SELECT character_name, COUNT(*) as count
        FROM user_cards
        GROUP BY character_name
        ORDER BY character_name
    ''', conn)
    conn.close()
    fig = px.pie(df, names='character_name', values='count', title='캐릭터별 카드 획득 분포')
    return fig

def plot_rank_dist(rank_dist):
    fig = px.pie(rank_dist, names='level', values='count', title='랭킹 분포')
    return fig

def plot_keyword_distribution():
    conn = get_conn()
    df = pd.read_sql_query("SELECT keyword_value, COUNT(*) as count FROM user_keywords GROUP BY keyword_value ORDER BY count DESC", conn)
    conn.close()
    fig = px.bar(df, x='keyword_value', y='count', title='키워드 분포')
    return fig

def plot_gift_distribution():
    conn = get_conn()
    df = pd.read_sql_query("SELECT gift_id, SUM(quantity) as total FROM user_gifts GROUP BY gift_id ORDER BY total DESC", conn)
    conn.close()
    fig = px.bar(df, x='gift_id', y='total', title='선물 지급 분포')
    return fig

def plot_story_completion():
    conn = get_conn()
    df = pd.read_sql_query("""
        SELECT character_name, chapter_number, COUNT(DISTINCT user_id) as completed_users
        FROM story_progress
        WHERE completed_at IS NOT NULL
        GROUP BY character_name, chapter_number
        ORDER BY character_name, chapter_number
    """, conn)
    conn.close()
    fig = px.bar(df, x='character_name', y='completed_users', color='chapter_number', barmode='group', title='스토리 챕터별 완성 유저수')
    return fig

def get_card_total_by_character():
    conn = get_conn()
    df = pd.read_sql_query("""
        SELECT character_name, COUNT(*) as total_cards
        FROM user_cards
        GROUP BY character_name
        ORDER BY character_name
    """, conn)
    conn.close()
    return df

def get_card_tier_by_character():
    conn = get_conn()
    df = pd.read_sql_query("""
        SELECT character_name, UPPER(SUBSTRING(card_id, LENGTH(character_name)+1, 1)) as tier, COUNT(*) as count
        FROM user_cards
        GROUP BY character_name, tier
        ORDER BY character_name, tier
    """, conn)
    conn.close()
    return df

def get_message_trend_all():
    conn = get_conn()
    df = pd.read_sql_query("""
        SELECT DATE(timestamp) as date, COUNT(*) as total_messages
        FROM conversations
        WHERE message_role = 'user'
        GROUP BY date
        ORDER BY date
    """, conn)
    conn.close()
    return df

def get_user_card_total_by_character(user_id):
    conn = get_conn()
    df = pd.read_sql_query("""
        SELECT character_name, COUNT(*) as total_cards
        FROM user_cards
        WHERE user_id = %s
        GROUP BY character_name
        ORDER BY character_name
    """, conn, params=(user_id,))
    conn.close()
    return df

def get_user_card_tier_by_character(user_id):
    conn = get_conn()
    df = pd.read_sql_query("""
        SELECT character_name, UPPER(SUBSTRING(card_id, 1, 1)) as tier, COUNT(*) as count
        FROM user_cards
        WHERE user_id = %s
        GROUP BY character_name, tier
        ORDER BY character_name, tier
    """, conn, params=(user_id,))
    conn.close()
    return df

def get_active_user_count(days=1):
    conn = get_conn()
    df = pd.read_sql_query(f'''
        SELECT COUNT(DISTINCT user_id) as active_users
        FROM conversations
        WHERE message_role = 'user' AND timestamp >= NOW() - INTERVAL '{days} days'
    ''', conn)
    conn.close()
    return int(df['active_users'][0])

def get_total_message_user_count():
    conn = get_conn()
    df = pd.read_sql_query('''
        SELECT COUNT(DISTINCT user_id) as total_users
        FROM conversations
        WHERE message_role = 'user'
    ''', conn)
    conn.close()
    return int(df['total_users'][0])

def get_retention(days=1):
    # 1일/7일/30일 리텐션: N일 전 메시지 보낸 유저 중 오늘도 메시지 보낸 유저 비율
    conn = get_conn()
    df = pd.read_sql_query(f'''
        WITH prev AS (
            SELECT DISTINCT user_id
            FROM conversations
            WHERE message_role = 'user' AND DATE(timestamp) = CURRENT_DATE - INTERVAL '{days} days'
        ), today AS (
            SELECT DISTINCT user_id
            FROM conversations
            WHERE message_role = 'user' AND DATE(timestamp) = CURRENT_DATE
        )
        SELECT COUNT(*) as retained, (SELECT COUNT(*) FROM prev) as base
        FROM today WHERE user_id IN (SELECT user_id FROM prev)
    ''', conn)
    conn.close()
    base = df['base'][0] if df['base'][0] else 1
    return round(df['retained'][0] / base * 100, 2) if base else 0.0

def get_active_user_trend(days=30):
    conn = get_conn()
    df = pd.read_sql_query(f'''
        SELECT DATE(timestamp) as date, COUNT(DISTINCT user_id) as active_users
        FROM conversations
        WHERE message_role = 'user' AND timestamp >= NOW() - INTERVAL '{days} days'
        GROUP BY date
        ORDER BY date
    ''', conn)
    conn.close()
    return df

def get_active_user_trend_days(days=30):
    conn = get_conn()
    df = pd.read_sql_query(f'''
        SELECT DATE(timestamp) as date, COUNT(DISTINCT user_id) as active_users
        FROM conversations
        WHERE message_role = 'user' AND timestamp >= NOW() - INTERVAL '{days} days'
        GROUP BY date
        ORDER BY date
    ''', conn)
    conn.close()
    df = df.reset_index(drop=True)
    df['day'] = range(1, len(df)+1)
    return df

def get_keyword_distribution():
    conn = get_conn()
    df = pd.read_sql_query('''
        SELECT keyword_type, keyword_value, COUNT(*) as total_count
        FROM user_keywords
        GROUP BY keyword_type, keyword_value
        ORDER BY total_count DESC
    ''', conn)
    conn.close()
    return df

def get_keyword_user_count():
    conn = get_conn()
    df = pd.read_sql_query('''
        SELECT keyword_type, keyword_value, COUNT(DISTINCT user_id) as user_count
        FROM user_keywords
        GROUP BY keyword_type, keyword_value
        ORDER BY user_count DESC
    ''', conn)
    conn.close()
    return df

def get_user_summaries_table():
    conn = get_conn()
    df = pd.read_sql_query('''
        SELECT user_id, character_name, summary
        FROM memory_summaries
        ORDER BY user_id, character_name
    ''', conn)
    conn.close()
    return df

def get_user_summary_stats():
    conn = get_conn()
    df = pd.read_sql_query('''
        SELECT user_id, COUNT(*) as summary_count
        FROM memory_summaries
        GROUP BY user_id
        ORDER BY summary_count DESC
    ''', conn)
    conn.close()
    return df

def get_monthly_active_users():
    conn = get_conn()
    df = pd.read_sql_query('''
        SELECT DATE_TRUNC('month', timestamp) AS month, COUNT(DISTINCT user_id) AS active_users
        FROM conversations
        WHERE message_role = 'user'
        GROUP BY month
        ORDER BY month
    ''', conn)
    conn.close()
    return df

def get_monthly_new_users():
    conn = get_conn()
    df = pd.read_sql_query('''
        SELECT DATE_TRUNC('month', first_message) AS month, COUNT(*) AS new_users
        FROM (
            SELECT user_id, MIN(timestamp) AS first_message
            FROM conversations
            WHERE message_role = 'user'
            GROUP BY user_id
        ) t
        GROUP BY month
        ORDER BY month
    ''', conn)
    conn.close()
    return df

def get_retention_trend():
    conn = get_conn()
    # 1일, 7일, 30일 리텐션 계산
    retention = []
    for days in [1, 7, 30]:
        df = pd.read_sql_query(f'''
            WITH prev AS (
                SELECT DISTINCT user_id
                FROM conversations
                WHERE message_role = 'user' AND DATE(timestamp) = CURRENT_DATE - INTERVAL '{days} day'
            ), today AS (
                SELECT DISTINCT user_id
                FROM conversations
                WHERE message_role = 'user' AND DATE(timestamp) = CURRENT_DATE
            )
            SELECT
                (SELECT COUNT(*) FROM today WHERE user_id IN (SELECT user_id FROM prev))::float /
                GREATEST((SELECT COUNT(*) FROM prev), 1) * 100 AS retention
        ''', conn)
        retention.append({'days': days, 'retention': float(df['retention'][0])})
    conn.close()
    return pd.DataFrame(retention)

def get_story_chapter_completion():
    conn = get_conn()
    # 전체 스토리 플레이 유저 수
    total_users = pd.read_sql_query('''
        SELECT COUNT(DISTINCT user_id) as total_users
        FROM story_progress
        WHERE completed_at IS NOT NULL
    ''', conn)["total_users"][0]
    # 캐릭터별 챕터별 완료 유저수
    df = pd.read_sql_query('''
        SELECT character_name, chapter_number, COUNT(DISTINCT user_id) as completed_users
        FROM story_progress
        WHERE completed_at IS NOT NULL
        GROUP BY character_name, chapter_number
        ORDER BY character_name, chapter_number
    ''', conn)
    conn.close()
    # 퍼센트 컬럼 추가
    df["percent"] = (df["completed_users"] / total_users * 100).round(2).astype(str) + "%"
    return total_users, df

def get_roleplay_user_count():
    conn = get_conn()
    # 롤플레이 모드 플레이한 유저 총수 (story_mode_users 테이블이 있다고 가정)
    try:
        df = pd.read_sql_query('''
            SELECT COUNT(DISTINCT user_id) as roleplay_users
            FROM roleplay_sessions
        ''', conn)
        count = int(df["roleplay_users"][0])
    except Exception:
        count = 0
    conn.close()
    return count

def get_spam_messages():
    conn = get_conn()
    df = pd.read_sql_query('''
        SELECT user_id, character_name, message, reason, timestamp
        FROM spam_messages
        ORDER BY timestamp DESC
    ''', conn)
    conn.close()
    return df

if __name__ == "__main__":
    with gr.Blocks(title="디스코드 챗봇 통합 대시보드") as demo:
        gr.Markdown("# 디스코드 챗봇 통합 대시보드")

        with gr.Tab("기본 데이터/현황"):
            gr.Markdown("## 기본 데이터 및 현황")
            total_turns, total_cards, card_tiers, total_users, rank_dist, total_gifts = get_basic_stats()
            gr.Markdown(f"총 턴 수(전체 대화 수): {total_turns}")
            gr.Markdown(f"총 카드 수: {total_cards}")
            gr.Markdown(f"총 유저 수: {total_users}")
            gr.Markdown(f"총 선물 지급 수: {total_gifts}")
            gr.Plot(plot_card_distribution_by_character())
            gr.Plot(plot_rank_dist(rank_dist))
            gr.Plot(plot_gift_distribution())
            # --- 추가된 표/그래프 ---
            gr.Dataframe(get_card_total_by_character(), label="캐릭터별 총 카드 획득 현황")
            gr.Dataframe(get_card_tier_by_character(), label="캐릭터별 등급별 카드 획득 현황 (C/B/A/S)")
            gr.Plot(lambda: px.line(get_message_trend_all(), x='date', y='total_messages', title='전체 메시지/대화량 추이'))

        with gr.Tab("랭킹"):
            gr.Markdown("## 캐릭터별 호감도/대화수/로그인 랭킹")
            kagari = get_full_character_ranking("Kagari")
            eros = get_full_character_ranking("Eros")
            elysia = get_full_character_ranking("Elysia")
            gr.Dataframe(kagari, label="Kagari 호감도 랭킹")
            gr.Dataframe(eros, label="Eros 호감도 랭킹")
            gr.Dataframe(elysia, label="Elysia 호감도 랭킹")
            gr.Dataframe(get_login_streak_ranking(), label="연속 로그인 랭킹")

        with gr.Tab("AI/키워드/서머리"):
            gr.Markdown("## 키워드/AI/서머리 데이터")
            gr.Dataframe(get_user_summary_stats(), label="유저 대화 서머리 수치")
            gr.Dataframe(get_keyword_distribution(), label="키워드 분포도 (keyword_type, keyword_value)")
            gr.Dataframe(get_keyword_user_count(), label="키워드별 대화 유저수")
            gr.Dataframe(get_user_summaries_table(), label="유저별 대화 서머리 (user_id, character_name, summary)")

        with gr.Tab("퀘스트/스토리/선물"):
            gr.Markdown("## 퀘스트/스토리/선물 현황")
            daily_conv, daily_aff, weekly_login, weekly_share = get_quest_completion_all()
            gr.Dataframe(daily_conv, label="일일 대화 퀘스트 달성률")
            gr.Dataframe(daily_aff, label="일일 호감도 퀘스트 달성률")
            gr.Dataframe(weekly_login, label="주간 로그인 퀘스트 달성률")
            gr.Dataframe(weekly_share, label="주간 카드 공유 퀘스트 달성률")
            gr.Plot(plot_story_completion())
            gr.Plot(plot_gift_distribution())
            # --- 추가: 스토리 챕터별 완성 유저수 및 롤플레잉 유저수 ---
            total_story_users, story_df = get_story_chapter_completion()
            gr.Markdown(f"스토리 플레이 유저(토탈): {total_story_users}")
            gr.Dataframe(story_df, label="캐릭터별 챕터별 완료 유저수 및 퍼센트")
            gr.Markdown(f"롤플레잉 모드 플레이 유저(토탈): {get_roleplay_user_count()}")

        with gr.Tab("운영 데이터"):
            gr.Markdown("## 운영 데이터 (운영/지표)")
            gr.Markdown(f"메시지를 1번이라도 보낸 유저수 총합: {get_total_message_user_count()}")
            gr.Markdown(f"1일 리텐션: {get_retention(1)}%  |  7일 리텐션: {get_retention(7)}%  |  30일 리텐션: {get_retention(30)}%")
            gr.Markdown(f"최근 1일 엑티브 유저: {get_active_user_count(1)}  |  7일: {get_active_user_count(7)}  |  30일: {get_active_user_count(30)}")
            gr.Plot(lambda: px.line(get_active_user_trend_days(30), x='day', y='active_users', title='최근 30일(일수 기준) 엑티브 유저 추이'))
            # --- 추가: 월별 활성 유저, 신규 유저, 리텐션 ---
            gr.Dataframe(get_monthly_active_users(), label="월별 활성 유저")
            gr.Plot(lambda: px.bar(get_monthly_active_users(), x='month', y='active_users', title='월별 활성 유저'))
            gr.Dataframe(get_monthly_new_users(), label="월별 신규 유저")
            gr.Plot(lambda: px.bar(get_monthly_new_users(), x='month', y='new_users', title='월별 신규 유저'))
            gr.Dataframe(get_retention_trend(), label="1/7/30일 리텐션(%)")
            gr.Plot(lambda: px.bar(get_retention_trend(), x='days', y='retention', title='1/7/30일 리텐션(%)'))

        with gr.Tab("유저 검색"):
            gr.Markdown("## 유저 정보 검색")
            user_id = gr.Textbox(label="디스코드 유저 ID 입력", value="")
            btn = gr.Button("유저 정보 조회")
            outs = [gr.Dataframe(label=label) for label in [
                "기본 정보", "캐릭터별 친밀도", "카드 목록", "카드 등급 비율", "캐릭터별 카드 분류", "최근 획득 카드", "주간 대화 수", "주간 카드 획득", "스토리 진행 현황", "로그인 정보", "선물 정보", "키워드 정보", "닉네임 정보", "에피소드 정보"
            ]]
            # 추가: 캐릭터별 카드 현황 표
            card_total_out = gr.Dataframe(label="[유저] 캐릭터별 총 카드 획득 현황")
            card_tier_out = gr.Dataframe(label="[유저] 캐릭터별 등급별 카드 획득 현황 (C/B/A/S)")
            btn.click(user_dashboard, inputs=user_id, outputs=outs)
            btn.click(get_user_card_total_by_character, inputs=user_id, outputs=card_total_out)
            btn.click(get_user_card_tier_by_character, inputs=user_id, outputs=card_tier_out)

        with gr.Tab("스팸 메시지 관리"):
            gr.Markdown("## Spam Message Management")
            gr.Dataframe(get_spam_messages(), label="Spam Messages (user_id, character_name, message, reason, timestamp)")

    demo.launch(share=True)