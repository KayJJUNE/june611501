import gradio as gr
import pandas as pd
import psycopg2
import os
from datetime import datetime, timedelta

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
        SELECT keyword, context
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
        SELECT character_name, keyword, context
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
        SELECT a.user_id, a.emotion_score, COALESCE(cc.daily_message_count, 0) as daily_message_count
        FROM affinity a
        LEFT JOIN conversation_count cc ON a.user_id = cc.user_id AND a.character_name = cc.character_name
        WHERE a.character_name = %s
        ORDER BY a.emotion_score DESC, daily_message_count DESC
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

if __name__ == "__main__":
    with gr.Blocks(title="디스코드 챗봇 통합 대시보드") as demo:
        gr.Markdown("# 디스코드 챗봇 통합 대시보드")

        with gr.Tab("유저 검색"):
            gr.Markdown("## 유저 정보 검색")
            user_id = gr.Textbox(label="디스코드 유저 ID 입력", value="")
            btn = gr.Button("유저 정보 조회")
            outs = [gr.Dataframe(label=label) for label in [
                "기본 정보", "캐릭터별 친밀도", "카드 목록", "카드 등급 비율", "캐릭터별 카드 분류", "최근 획득 카드", "주간 대화 수", "주간 카드 획득", "스토리 진행 현황", "로그인 정보", "선물 정보", "키워드 정보", "닉네임 정보", "에피소드 정보"
            ]]
            btn.click(user_dashboard, inputs=user_id, outputs=outs)

        with gr.Tab("전체 통계"):
            gr.Markdown("## 전체 통계 요약")
            gr.Dataframe(get_user_info(), label="캐릭터별 친밀도/메시지수")
            gr.Dataframe(get_daily_affinity_gain(), label="일일 호감도 증가량")
            gr.Dataframe(get_login_streak_ranking(), label="연속 로그인 랭킹")
            gr.Dataframe(get_message_trend(), label="전체 메시지/대화량 추이")

        with gr.Tab("퀘스트/랭킹/진행률"):
            gr.Markdown("## 퀘스트/랭킹/진행률")
            gr.Dataframe(get_quest_completion_rate('daily_conversation'), label="일일 대화 퀘스트 달성률")
            gr.Dataframe(get_quest_completion_rate('daily_affinity_gain'), label="일일 호감도 퀘스트 달성률")
            gr.Dataframe(get_quest_completion_rate('weekly_login'), label="주간 로그인 퀘스트 달성률")
            gr.Dataframe(get_quest_completion_rate('weekly_share'), label="주간 카드 공유 퀘스트 달성률")

        with gr.Tab("카드/스토리/에피소드"):
            gr.Markdown("## 카드/스토리/에피소드 현황")
            gr.Dataframe(get_user_cards(), label="전체 카드 보유 현황")
            gr.Dataframe(get_all_story_progress(), label="전체 스토리 진행 현황")

    demo.launch(share=True)