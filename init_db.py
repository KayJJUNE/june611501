import psycopg2
import os

DATABASE_URL = os.environ["DATABASE_URL"]

def create_all_tables():
    with psycopg2.connect(DATABASE_URL) as conn:
        with conn.cursor() as cursor:
            # conversations
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS conversations (
                    id SERIAL PRIMARY KEY,
                    channel_id BIGINT,
                    user_id BIGINT,
                    character_name TEXT,
                    message_role TEXT,
                    content TEXT,
                    language TEXT,
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    token_count INTEGER
                )
            ''')
            # affinity
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS affinity (
                    id SERIAL PRIMARY KEY,
                    user_id BIGINT,
                    character_name TEXT,
                    emotion_score INTEGER DEFAULT 0,
                    daily_message_count INTEGER DEFAULT 0,
                    last_daily_reset DATE DEFAULT CURRENT_DATE,
                    last_quest_reward_date DATE,
                    last_message_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    last_message_content TEXT,
                    UNIQUE(user_id, character_name)
                )
            ''')
            # user_language
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS user_language (
                    id SERIAL PRIMARY KEY,
                    channel_id BIGINT,
                    user_id BIGINT,
                    character_name TEXT,
                    language TEXT DEFAULT 'ko',
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(channel_id, user_id, character_name)
                )
            ''')
            # user_cards
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS user_cards (
                    user_id BIGINT,
                    character_name TEXT,
                    card_id TEXT,
                    acquired_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    emotion_score_at_obtain INTEGER,
                    PRIMARY KEY (user_id, character_name, card_id)
                )
            ''')
            # conversation_count
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS conversation_count (
                    id SERIAL PRIMARY KEY,
                    channel_id BIGINT,
                    user_id BIGINT,
                    character_name TEXT,
                    message_count INTEGER DEFAULT 0,
                    last_milestone INTEGER DEFAULT 0,
                    UNIQUE(channel_id, user_id, character_name)
                )
            ''')
            # story_progress
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS story_progress (
                    user_id BIGINT,
                    character_name TEXT,
                    chapter_number INTEGER,
                    completed_at TIMESTAMP,
                    selected_choice TEXT,
                    ending_type TEXT,
                    PRIMARY KEY (user_id, character_name, chapter_number)
                )
            ''')
            # story_unlocks
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS story_unlocks (
                    user_id BIGINT,
                    character_name TEXT,
                    chapter_id INTEGER,
                    unlocked_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (user_id, character_name, chapter_id)
                )
            ''')
            # story_choices
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS story_choices (
                    id SERIAL PRIMARY KEY,
                    user_id BIGINT,
                    character_name TEXT,
                    story_id TEXT,
                    choice_index INTEGER,
                    choice_text TEXT,
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            # scene_scores
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS scene_scores (
                    user_id BIGINT,
                    character_name TEXT,
                    chapter_id INTEGER,
                    scene_id INTEGER,
                    score INTEGER,
                    PRIMARY KEY (user_id, character_name, chapter_id, scene_id)
                )
            ''')
            # completed_chapters
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS completed_chapters (
                    id SERIAL PRIMARY KEY,
                    user_id BIGINT,
                    character_name TEXT,
                    chapter_id INTEGER,
                    completed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(user_id, character_name, chapter_id)
                )
            ''')
            # user_milestone_claims
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS user_milestone_claims (
                    user_id BIGINT,
                    character_name TEXT,
                    milestone INTEGER,
                    claimed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (user_id, character_name, milestone)
                )
            ''')
            # user_levelup_flags
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS user_levelup_flags (
                    user_id BIGINT,
                    character_name TEXT,
                    level TEXT,
                    flagged_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (user_id, character_name, level)
                )
            ''')
            # card_issued
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS card_issued (
                    character_name TEXT,
                    card_id TEXT,
                    issued_number INTEGER DEFAULT 0,
                    PRIMARY KEY (character_name, card_id)
                )
            ''')
            # emotion_log
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS emotion_log (
                    id SERIAL PRIMARY KEY,
                    user_id BIGINT,
                    character_name TEXT,
                    score INTEGER,
                    message TEXT,
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            # user_gifts
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS user_gifts (
                    id SERIAL PRIMARY KEY,
                    user_id BIGINT NOT NULL,
                    gift_id VARCHAR(50) NOT NULL,
                    quantity INTEGER NOT NULL DEFAULT 1,
                    obtained_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(user_id, gift_id)
                )
            ''')
            # --- 퀘스트 시스템을 위한 테이블 ---
            # 로그인 스트릭
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS user_login_streaks (
                    user_id BIGINT PRIMARY KEY,
                    current_streak INTEGER DEFAULT 0,
                    last_login_date DATE
                )
            ''')
            # 퀘스트 이벤트
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS user_quest_events (
                    id SERIAL PRIMARY KEY,
                    user_id BIGINT NOT NULL,
                    event_type TEXT NOT NULL, -- 'card_share' 등
                    event_date DATE DEFAULT CURRENT_DATE
                )
            ''')
            # 퀘스트 완료 기록
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS quest_claims (
                    user_id BIGINT,
                    quest_id TEXT,
                    claimed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (user_id, quest_id)
                )
            ''')
            # 스토리 퀘스트 완료 기록
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS story_quest_claims (
                    user_id BIGINT,
                    character_name TEXT,
                    quest_type TEXT, -- 'all_chapters', 'single_chapter'
                    claimed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (user_id, character_name, quest_type)
                )
            ''')
            # memory_summaries
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS memory_summaries (
                    id SERIAL PRIMARY KEY,
                    user_id BIGINT NOT NULL,
                    character_name TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    quality_score FLOAT DEFAULT 0.0,
                    token_count INTEGER DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            # user_nicknames
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS user_nicknames (
                    id SERIAL PRIMARY KEY,
                    user_id BIGINT NOT NULL,
                    character_name TEXT NOT NULL,
                    nickname TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(user_id, character_name)
                )
            ''')
            # user_keywords
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS user_keywords (
                    id SERIAL PRIMARY KEY,
                    user_id BIGINT NOT NULL,
                    character_name TEXT NOT NULL,
                    keyword TEXT NOT NULL,
                    context TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(user_id, character_name, keyword)
                )
            ''')
            # profiles
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS profiles (
                    user_id BIGINT,
                    character TEXT,
                    key TEXT,
                    value TEXT,
                    PRIMARY KEY (user_id, character, key)
                )
            ''')
            # episodes
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS episodes (
                    user_id BIGINT,
                    character TEXT,
                    episode_id SERIAL,
                    summary TEXT,
                    timestamp TIMESTAMP,
                    PRIMARY KEY (user_id, character, episode_id)
                )
            ''')
            # states
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS states (
                    user_id BIGINT,
                    character TEXT,
                    emotion_type TEXT,
                    score REAL,
                    last_updated TIMESTAMP,
                    PRIMARY KEY (user_id, character, emotion_type)
                )
            ''')
            # user_story_progress
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS user_story_progress (
                    user_id BIGINT,
                    character_name TEXT,
                    stage_num INTEGER,
                    status TEXT DEFAULT 'unlocked', -- 'unlocked', 'completed'
                    completed_at TIMESTAMP WITH TIME ZONE,
                    PRIMARY KEY (user_id, character_name, stage_num)
                )
            ''')
        conn.commit()