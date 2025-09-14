import psycopg2
import os

# DATABASE_URL 환경변수가 없으면 기본값 사용
DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://user:password@localhost:5432/discord_bot")

def migrate_database():
    """기존 데이터베이스에 새로운 컬럼을 추가합니다."""
    with psycopg2.connect(DATABASE_URL) as conn:
        with conn.cursor() as cursor:
            try:
                # conversations 테이블에 is_daily_message 컬럼 추가 (이미 존재하면 무시)
                cursor.execute("""
                    ALTER TABLE conversations 
                    ADD COLUMN IF NOT EXISTS is_daily_message BOOLEAN DEFAULT TRUE
                """)
                print("✅ is_daily_message 컬럼이 성공적으로 추가되었습니다.")
            except Exception as e:
                print(f"⚠️ is_daily_message 컬럼 추가 중 오류 (이미 존재할 수 있음): {e}")
            
            try:
                # 기존 데이터의 is_daily_message를 TRUE로 설정 (기본값)
                cursor.execute("""
                    UPDATE conversations 
                    SET is_daily_message = TRUE 
                    WHERE is_daily_message IS NULL
                """)
                print("✅ 기존 데이터의 is_daily_message가 TRUE로 설정되었습니다.")
            except Exception as e:
                print(f"⚠️ 기존 데이터 업데이트 중 오류: {e}")
            
            conn.commit()
            print("✅ 데이터베이스 마이그레이션이 완료되었습니다.")

def create_all_tables():
    try:
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
                    token_count INTEGER,
                    is_daily_message BOOLEAN DEFAULT TRUE
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
            # user_message_balance - 메시지 잔액 관리
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS user_message_balance (
                    user_id BIGINT PRIMARY KEY,
                    total_messages INTEGER DEFAULT 0,
                    last_updated TIMESTAMP WITH TIME ZONE DEFAULT NOW()
                )
            ''')
            # user_subscriptions - 구독 정보 관리
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS user_subscriptions (
                    id SERIAL PRIMARY KEY,
                    user_id BIGINT NOT NULL,
                    product_id VARCHAR(100) NOT NULL,
                    start_date TIMESTAMP WITH TIME ZONE NOT NULL,
                    end_date TIMESTAMP WITH TIME ZONE NOT NULL,
                    is_active BOOLEAN DEFAULT TRUE,
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
                )
            ''')
            # payment_transactions - 결제 기록
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS payment_transactions (
                    id SERIAL PRIMARY KEY,
                    transaction_id VARCHAR(255) UNIQUE NOT NULL,
                    user_id BIGINT NOT NULL,
                    product_id VARCHAR(100) NOT NULL,
                    amount INTEGER NOT NULL,
                    currency VARCHAR(10) NOT NULL,
                    status VARCHAR(50) NOT NULL,
                    payment_method VARCHAR(100),
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                    processed_at TIMESTAMP WITH TIME ZONE,
                    webhook_data JSONB
                )
            ''')
            # product_delivery_log - 상품 지급 로그
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS product_delivery_log (
                    id SERIAL PRIMARY KEY,
                    user_id BIGINT NOT NULL,
                    product_id VARCHAR(100) NOT NULL,
                    transaction_id VARCHAR(255),
                    delivery_type VARCHAR(50) NOT NULL, -- 'messages', 'gifts', 'subscription'
                    quantity INTEGER NOT NULL,
                    delivered_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                    status VARCHAR(50) DEFAULT 'delivered'
                )
            ''')
            # admin_item_logs - 관리자 아이템 지급 로그
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS admin_item_logs (
                    id SERIAL PRIMARY KEY,
                    admin_id BIGINT NOT NULL,
                    user_id BIGINT NOT NULL,
                    item_type VARCHAR(50) NOT NULL, -- 'messages', 'card', 'gift', 'affinity'
                    item_id VARCHAR(100) NOT NULL,
                    quantity INTEGER NOT NULL,
                    reason TEXT,
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
                )
            ''')
            conn.commit()
    except Exception as e:
        print(f"⚠️ 데이터베이스 연결 실패: {e}")
        print("데이터베이스 없이 봇을 실행합니다.")

if __name__ == "__main__":
    print("🚀 데이터베이스 초기화를 시작합니다...")
    create_all_tables()
    print("✅ 모든 테이블이 생성되었습니다.")
    
    print("\n🔄 데이터베이스 마이그레이션을 시작합니다...")
    migrate_database()
    print("✅ 데이터베이스 초기화가 완료되었습니다!")