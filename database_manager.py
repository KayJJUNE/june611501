from datetime import datetime, date, timedelta
import json
import os
import psycopg2
import gift_manager
from init_db import create_all_tables
from pytz import timezone
from psycopg2.extras import RealDictCursor

# --- CST 시간대 객체 ---
CST = timezone('Asia/Shanghai')

def get_today_cst():
    """중국 시간 기준의 오늘 날짜를 반환합니다."""
    return datetime.now(CST).date()

# --- 싱글턴 인스턴스 ---
_db_instance = None

def get_db_manager():
    """데이터베이스 관리자의 싱글턴 인스턴스를 반환합니다."""
    global _db_instance
    if _db_instance is None:
        _db_instance = DatabaseManager()
    return _db_instance

# 데이터베이스 생성 함수 호출
create_all_tables()

# 환경변수에서 DATABASE_URL 읽기
DATABASE_URL = os.environ.get("DATABASE_URL")

class DatabaseManager:
    def __init__(self):
        # 이미 인스턴스가 생성되었다면 중복 실행 방지
        global _db_instance
        if _db_instance is not None:
            # print("DatabaseManager already initialized.")
            return

        self.default_language = "en"
        print("DatabaseManager initialized.")
        self.setup_database()

    def get_connection(self):
        """데이터베이스 연결을 가져옵니다."""
        return psycopg2.connect(DATABASE_URL, sslmode='require')

    def return_connection(self, conn):
        """사용한 데이터베이스 연결을 닫습니다."""
        if conn:
            conn.close()

    def setup_database(self):
        """데이터베이스 초기화 및 필요한 컬럼 추가를 담당합니다."""
        print("Setting up database tables for PostgreSQL...")
        conn = None
        try:
            conn = self.get_connection()
            with conn.cursor() as cursor:
                self._add_column_if_not_exists(cursor, 'affinity', 'last_quest_reward_date', 'DATE')
                self._add_column_if_not_exists(cursor, 'user_cards', 'acquired_at', 'TIMESTAMP WITH TIME ZONE')
                self._add_column_if_not_exists(cursor, 'affinity', 'highest_milestone_achieved', 'INTEGER DEFAULT 0')
                self._add_column_if_not_exists(cursor, 'user_quest_events', 'character_name', 'TEXT')
                self._add_column_if_not_exists(cursor, 'user_quest_events', 'card_id', 'TEXT')
            conn.commit()
            print("Database setup completed.")
        except Exception as e:
            print(f"Error setting up database: {e}")
            if conn: conn.rollback()
        finally:
            self.return_connection(conn)

    def _add_column_if_not_exists(self, cursor, table, column, col_type):
        """테이블에 특정 컬럼이 없으면 추가합니다."""
        cursor.execute(f"""
            SELECT 1 FROM information_schema.columns 
            WHERE table_name='{table}' AND column_name='{column}'
        """)
        if not cursor.fetchone():
            cursor.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}")
            print(f"Column '{column}' added to table '{table}'.")

    # 언어 관련 함수
    def get_channel_language(self, channel_id: int, user_id: int, character_name: str) -> str:
        conn = None
        try:
            conn = self.get_connection()
            with conn.cursor() as cursor:
                cursor.execute(
                    "SELECT language FROM user_language WHERE channel_id = %s AND user_id = %s AND character_name = %s",
                    (channel_id, user_id, character_name)
                )
                result = cursor.fetchone()
                return result[0] if result else self.default_language
        except Exception as e:
            print(f"Error getting channel language: {e}")
            return self.default_language
        finally:
            self.return_connection(conn)

    def set_channel_language(self, channel_id: int, user_id: int, character_name: str, language: str) -> bool:
        conn = None
        try:
            conn = self.get_connection()
            with conn.cursor() as cursor:
                cursor.execute("""
                    INSERT INTO user_language (channel_id, user_id, character_name, language, updated_at)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (channel_id, user_id, character_name)
                    DO UPDATE SET language = EXCLUDED.language, updated_at = EXCLUDED.updated_at;
                """, (channel_id, user_id, character_name, language, datetime.now()))
            conn.commit()
            return True
        except Exception as e:
            print(f"Error in set_channel_language: {e}")
            if conn: conn.rollback()
            return False
        finally:
            self.return_connection(conn)

    # 메시지 관련 함수
    def add_message(self, channel_id: int, user_id: int, character_name: str, role: str, content: str, language: str = None):
        print(f"[DEBUG] add_message called: channel_id={channel_id}, user_id={user_id}, character_name={character_name}, role={role}, content={content}, language={language}")
        conn = None
        try:
            conn = self.get_connection()
            with conn.cursor() as cursor:
                cursor.execute(
                    "INSERT INTO conversations (channel_id, user_id, character_name, message_role, content, language) VALUES (%s, %s, %s, %s, %s, %s)",
                    (channel_id, user_id, character_name, role, content, language)
                )
            conn.commit()
            print(f"[DEBUG] add_message DB INSERT SUCCESS for user_id={user_id}, character_name={character_name}")
        except Exception as e:
            print(f"Error adding message to DB: {e}")
            if conn: conn.rollback()
        finally:
            self.return_connection(conn)

    def get_recent_messages(self, channel_id: int, limit: int = 10):
        conn = None
        try:
            conn = self.get_connection()
            with conn.cursor() as cursor:
                cursor.execute(
                    "SELECT user_id, character_name, message_role, content, language FROM conversations WHERE channel_id = %s ORDER BY timestamp DESC LIMIT %s",
                    (channel_id, limit)
                )
                return cursor.fetchall()
        except Exception as e:
            print(f"Error getting recent messages: {e}")
            return []
        finally:
            self.return_connection(conn)

    # 친밀도 및 퀘스트 관련 함수
    def get_affinity(self, user_id: int, character_name: str) -> dict | None:
        conn = None
        try:
            conn = self.get_connection()
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(
                    "SELECT emotion_score, daily_message_count, last_daily_reset, last_quest_reward_date, highest_milestone_achieved, last_message_time FROM affinity WHERE user_id = %s AND character_name = %s",
                    (user_id, character_name)
                )
                result = cursor.fetchone()
                if result:
                    # last_daily_reset 날짜를 CST 기준으로 오늘과 비교
                    today_cst = get_today_cst()
                    if result['last_daily_reset'] != today_cst:
                        result['daily_message_count'] = 0
                    return dict(result)
                return None
        except Exception as e:
            print(f"Error getting affinity: {e}")
            return None
        finally:
            self.return_connection(conn)

    def update_affinity(self, user_id: int, character_name: str, last_message: str, last_message_time: datetime, score_change: int, highest_milestone: int) -> int | None:
        conn = None
        try:
            conn = self.get_connection()
            with conn.cursor() as cursor:
                today = get_today_cst()

                cursor.execute("SELECT emotion_score, daily_message_count, last_daily_reset FROM affinity WHERE user_id = %s AND character_name = %s FOR UPDATE", (user_id, character_name))
                result = cursor.fetchone()

                if result:
                    current_score, daily_count, last_reset = result
                    daily_count = daily_count + 1 if last_reset == today else 1
                    new_score = current_score + score_change

                    cursor.execute("""
                        UPDATE affinity SET emotion_score = %s, daily_message_count = %s, last_daily_reset = %s, last_message_time = %s, last_message_content = %s, highest_milestone_achieved = %s
                        WHERE user_id = %s AND character_name = %s
                    """, (new_score, daily_count, today, last_message_time, last_message, highest_milestone, user_id, character_name))
                else:
                    new_score = score_change
                    cursor.execute("""
                        INSERT INTO affinity (user_id, character_name, emotion_score, daily_message_count, last_daily_reset, last_message_time, last_message_content, highest_milestone_achieved)
                        VALUES (%s, %s, %s, 1, %s, %s, %s, %s)
                    """, (user_id, character_name, new_score, today, last_message_time, last_message, highest_milestone))

                conn.commit()
                return new_score
        except Exception as e:
            print(f"Error updating affinity: {e}")
            if conn: conn.rollback()
            return None
        finally:
            self.return_connection(conn)

    def check_daily_quest(self, user_id: int, character_name: str) -> bool:
        conn = None
        try:
            conn = self.get_connection()
            with conn.cursor() as cursor:
                today = get_today_cst()
                cursor.execute("SELECT daily_message_count, last_quest_reward_date FROM affinity WHERE user_id = %s AND character_name = %s", (user_id, character_name))
                result = cursor.fetchone()

                if result:
                    daily_count, last_reward_date = result
                    if daily_count >= 20 and last_reward_date != today:
                        return True
                return False
        except Exception as e:
            print(f"Error checking daily quest: {e}")
            return False
        finally:
            self.return_connection(conn)

    def mark_quest_reward_claimed(self, user_id: int, character_name: str):
        conn = None
        try:
            conn = self.get_connection()
            with conn.cursor() as cursor:
                cursor.execute(
                    "UPDATE affinity SET last_quest_reward_date = %s WHERE user_id = %s AND character_name = %s",
                    (get_today_cst(), user_id, character_name)
                )
            conn.commit()
        except Exception as e:
            print(f"Error marking quest reward claimed: {e}")
            if conn: conn.rollback()
        finally:
            self.return_connection(conn)

    def get_affinity_ranking(self, character_name: str = None):
        conn = None
        try:
            conn = self.get_connection()
            with conn.cursor() as cursor:
                if character_name:
                    cursor.execute(
                        "SELECT user_id, emotion_score FROM affinity WHERE character_name = %s ORDER BY emotion_score DESC",
                        (character_name,)
                    )
                else:
                    cursor.execute(
                        "SELECT user_id, character_name, emotion_score FROM affinity ORDER BY emotion_score DESC"
                    )
                return cursor.fetchall()
        except Exception as e:
            print(f"Error getting affinity ranking: {e}")
            return []
        finally:
            self.return_connection(conn)

    def get_character_ranking(self, character_name: str):
        """특정 캐릭터의 랭킹을 반환합니다 (user_id, emotion_score, daily_message_count)"""
        EXCLUDE_BOT_IDS = [1363156675959460061]
        conn = None
        try:
            conn = self.get_connection()
            with conn.cursor() as cursor:
                cursor.execute(
                    "SELECT user_id, emotion_score, daily_message_count FROM affinity WHERE character_name = %s AND user_id NOT IN %s ORDER BY emotion_score DESC",
                    (character_name, tuple(EXCLUDE_BOT_IDS))
                )
                return cursor.fetchall()
        except Exception as e:
            print(f"Error getting character ranking: {e}")
            return []
        finally:
            self.return_connection(conn)

    def get_user_character_rank(self, user_id: int, character_name: str) -> int:
        """특정 캐릭터에서 유저의 랭킹을 반환합니다"""
        conn = None
        try:
            conn = self.get_connection()
            with conn.cursor() as cursor:
                cursor.execute(
                    "SELECT COUNT(*) + 1 FROM affinity WHERE character_name = %s AND emotion_score > (SELECT emotion_score FROM affinity WHERE user_id = %s AND character_name = %s)",
                    (character_name, user_id, character_name)
                )
                result = cursor.fetchone()
                return result[0] if result else 999999
        except Exception as e:
            print(f"Error getting user character rank: {e}")
            return 999999
        finally:
            self.return_connection(conn)

    def get_user_stats(self, user_id: int, character_name: str = None) -> dict:
        """유저의 통계 정보를 반환합니다"""
        conn = None
        try:
            conn = self.get_connection()
            with conn.cursor() as cursor:
                if character_name:
                    # 특정 캐릭터 통계
                    cursor.execute(
                        "SELECT emotion_score, daily_message_count FROM affinity WHERE user_id = %s AND character_name = %s",
                        (user_id, character_name)
                    )
                    result = cursor.fetchone()
                    if result:
                        return {
                            'affinity': result[0],
                            'messages': result[1]
                        }
                    return {'affinity': 0, 'messages': 0}
                else:
                    # 전체 통계
                    cursor.execute(
                        "SELECT SUM(emotion_score), SUM(daily_message_count) FROM affinity WHERE user_id = %s",
                        (user_id,)
                    )
                    result = cursor.fetchone()
                    if result and result[0]:
                        return {
                            'total_emotion': result[0],
                            'total_messages': result[1] or 0
                        }
                    return {'total_emotion': 0, 'total_messages': 0}
        except Exception as e:
            print(f"Error getting user stats: {e}")
            return {'affinity': 0, 'messages': 0} if character_name else {'total_emotion': 0, 'total_messages': 0}
        finally:
            self.return_connection(conn)

    def get_total_ranking(self):
        """전체 랭킹을 반환합니다 (user_id, total_emotion_score, total_messages)"""
        EXCLUDE_BOT_IDS = [1363156675959460061]
        conn = None
        try:
            conn = self.get_connection()
            with conn.cursor() as cursor:
                cursor.execute(
                    "SELECT user_id, SUM(emotion_score) as total_score, SUM(daily_message_count) as total_messages FROM affinity WHERE user_id NOT IN %s GROUP BY user_id ORDER BY total_score DESC",
                    (tuple(EXCLUDE_BOT_IDS),)
                )
                return cursor.fetchall()
        except Exception as e:
            print(f"Error getting total ranking: {e}")
            return []
        finally:
            self.return_connection(conn)

    def get_user_total_rank(self, user_id: int) -> int:
        """전체 랭킹에서 유저의 순위를 반환합니다"""
        conn = None
        try:
            conn = self.get_connection()
            with conn.cursor() as cursor:
                cursor.execute(
                    "SELECT COUNT(*) + 1 FROM (SELECT user_id, SUM(emotion_score) as total_score FROM affinity GROUP BY user_id) ranked WHERE total_score > (SELECT SUM(emotion_score) FROM affinity WHERE user_id = %s)",
                    (user_id,)
                )
                result = cursor.fetchone()
                return result[0] if result else 999999
        except Exception as e:
            print(f"Error getting user total rank: {e}")
            return 999999
        finally:
            self.return_connection(conn)

    # 카드 관련 함수
    def get_user_cards(self, user_id: int, character_name: str = None) -> list:
        """사용자가 보유한 카드 목록을 반환합니다."""
        conn = None
        try:
            conn = self.get_connection()
            with conn.cursor() as cursor:
                if character_name:
                    cursor.execute(
                        "SELECT card_id, acquired_at FROM user_cards WHERE user_id = %s AND character_name = %s",
                        (user_id, character_name)
                    )
                else:
                    cursor.execute(
                        "SELECT character_name, card_id, acquired_at FROM user_cards WHERE user_id = %s",
                        (user_id,)
                    )
                return cursor.fetchall()
        except Exception as e:
            print(f"Error getting user cards: {e}")
            return []
        finally:
            self.return_connection(conn)

    def has_user_card(self, user_id: int, character_name: str, card_id: str) -> bool:
        conn = None
        try:
            conn = self.get_connection()
            with conn.cursor() as cursor:
                cursor.execute(
                    "SELECT 1 FROM user_cards WHERE user_id = %s AND character_name = %s AND card_id = %s",
                    (user_id, character_name, card_id)
                )
                return cursor.fetchone() is not None
        except Exception as e:
            print(f"Error checking user card: {e}")
            return False
        finally:
            self.return_connection(conn)

    def add_user_card(self, user_id: int, character_name: str, card_id: str, acquired_at: datetime = None) -> bool:
        """사용자에게 카드를 추가합니다."""
        conn = None
        try:
            conn = self.get_connection()
            with conn.cursor() as cursor:
                cursor.execute("SELECT emotion_score FROM affinity WHERE user_id = %s AND character_name = %s", (user_id, character_name))
                result = cursor.fetchone()
                emotion_score_at_obtain = result[0] if result else 0

                cursor.execute(
                    "INSERT INTO user_cards (user_id, character_name, card_id, emotion_score_at_obtain, acquired_at) VALUES (%s, %s, %s, %s, %s) ON CONFLICT DO NOTHING",
                    (user_id, character_name, card_id, emotion_score_at_obtain, acquired_at))
            conn.commit()
        except Exception as e:
            print(f"Error adding user card: {e}")
            if conn: conn.rollback()
        finally:
            self.return_connection(conn)

    # 선물 관련 함수
    def add_user_gift(self, user_id: int, gift_id: str, quantity: int = 1) -> bool:
        conn = None
        try:
            conn = self.get_connection()
            with conn.cursor() as cursor:
                cursor.execute("""
                    INSERT INTO user_gifts (user_id, gift_id, quantity) VALUES (%s, %s, %s)
                    ON CONFLICT (user_id, gift_id) DO UPDATE SET quantity = user_gifts.quantity + EXCLUDED.quantity;
                """, (user_id, gift_id, quantity))
            conn.commit()
            return True
        except Exception as e:
            print(f"Error adding user gift: {e}")
            if conn: conn.rollback()
            return False
        finally:
            self.return_connection(conn)

    def use_user_gift(self, user_id: int, gift_id: str, quantity: int = 1) -> bool:
        conn = None
        try:
            conn = self.get_connection()
            with conn.cursor() as cursor:
                cursor.execute("SELECT quantity FROM user_gifts WHERE user_id = %s AND gift_id = %s FOR UPDATE", (user_id, gift_id))
                result = cursor.fetchone()
                if not result or result[0] < quantity:
                    return False

                if result[0] > quantity:
                    cursor.execute("UPDATE user_gifts SET quantity = quantity - %s WHERE user_id = %s AND gift_id = %s", (quantity, user_id, gift_id))
                else:
                    cursor.execute("DELETE FROM user_gifts WHERE user_id = %s AND gift_id = %s", (user_id, gift_id))
            conn.commit()
            return True
        except Exception as e:
            print(f"Error using user gift: {e}")
            if conn: conn.rollback()
            return False
        finally:
            self.return_connection(conn)

    def has_user_gift(self, user_id: int, gift_id: str) -> bool:
        conn = None
        try:
            conn = self.get_connection()
            with conn.cursor() as cursor:
                cursor.execute("SELECT quantity FROM user_gifts WHERE user_id = %s AND gift_id = %s", (user_id, gift_id))
                result = cursor.fetchone()
                return result is not None and result[0] > 0
        except Exception as e:
            print(f"Error checking user gift: {e}")
            return False
        finally:
            self.return_connection(conn)

    def get_user_gifts(self, user_id: int) -> list:
        conn = None
        try:
            conn = self.get_connection()
            with conn.cursor() as cursor:
                cursor.execute("SELECT gift_id, quantity FROM user_gifts WHERE user_id = %s ORDER BY obtained_at DESC", (user_id,))
                return cursor.fetchall()
        except Exception as e:
            print(f"Error getting user gifts: {e}")
            return []
        finally:
            self.return_connection(conn)

    def add_random_gift_to_user(self, user_id: int, character_name: str) -> str | None:
        try:
            gift_id, gift_name = gift_manager.get_random_gift_for_character(character_name)
            if not gift_id:
                return None

            if self.add_user_gift(user_id, gift_id, 1):
                return gift_name
            return None
        except Exception as e:
            print(f"Error adding random gift to user: {e}")
            return None

    # 레벨업 플래그 관련 함수
    def has_levelup_flag(self, user_id, character_name, level):
        conn = None
        try:
            conn = self.get_connection()
            with conn.cursor() as cursor:
                cursor.execute(
                    "SELECT 1 FROM user_levelup_flags WHERE user_id=%s AND character_name=%s AND level=%s",
                    (user_id, character_name, level)
                )
                return cursor.fetchone() is not None
        except Exception as e:
            print(f"Error checking level up flag: {e}")
            return False
        finally:
            self.return_connection(conn)

    def set_levelup_flag(self, user_id, character_name, level):
        conn = None
        try:
            conn = self.get_connection()
            with conn.cursor() as cursor:
                cursor.execute("INSERT INTO user_levelup_flags (user_id, character_name, level) VALUES (%s, %s, %s) ON CONFLICT DO NOTHING", (user_id, character_name, level))
            conn.commit()
        except Exception as e:
            print(f"Error in set_levelup_flag: {e}")
            if conn: conn.rollback()
        finally:
            self.return_connection(conn)

    # 닉네임 및 키워드 관련 함수
    def get_user_nickname(self, user_id: int, character_name: str) -> str | None:
        conn = None
        try:
            conn = self.get_connection()
            with conn.cursor() as cursor:
                cursor.execute("SELECT nickname FROM user_nicknames WHERE user_id = %s AND character_name = %s", (user_id, character_name))
                result = cursor.fetchone()
                return result[0] if result else None
        except Exception as e:
            print(f"Error getting user nickname: {e}")
            return None
        finally:
            self.return_connection(conn)

    def set_user_nickname(self, user_id: int, character_name: str, nickname: str) -> bool:
        conn = None
        try:
            print(f"[DEBUG] set_user_nickname called: user_id={user_id}, character_name={character_name}, nickname={nickname}")
            conn = self.get_connection()
            with conn.cursor() as cursor:
                cursor.execute("""
                    INSERT INTO user_nicknames (user_id, character_name, nickname, is_editable, created_at, updated_at)
                    VALUES (%s, %s, %s, %s, NOW(), NOW())
                    ON CONFLICT (user_id, character_name) DO UPDATE SET nickname = EXCLUDED.nickname, updated_at = NOW()
                """, (user_id, character_name, nickname, True))
            conn.commit()
            return True
        except Exception as e:
            print(f"[ERROR] Error setting user nickname: {e}")
            if conn: conn.rollback()
            return False
        finally:
            self.return_connection(conn)

    def get_user_keywords(self, user_id: int, character_name: str) -> list:
        conn = None
        try:
            conn = self.get_connection()
            with conn.cursor() as cursor:
                cursor.execute("SELECT keyword, context FROM user_keywords WHERE user_id = %s AND character_name = %s", (user_id, character_name))
                return cursor.fetchall()
        except Exception as e:
            print(f"Error getting user keywords: {e}")
            return []
        finally:
            self.return_connection(conn)

    def add_user_keyword(self, user_id: int, character_name: str, keyword: str, context: str):
        conn = None
        try:
            conn = self.get_connection()
            with conn.cursor() as cursor:
                cursor.execute("""
                    INSERT INTO user_keywords (user_id, character_name, keyword, context) VALUES (%s, %s, %s, %s)
                    ON CONFLICT (user_id, character_name, keyword) DO UPDATE SET context = EXCLUDED.context
                """, (user_id, character_name, keyword, context))
            conn.commit()
        except Exception as e:
            print(f"Error adding user keyword: {e}")
            if conn: conn.rollback()
        finally:
            self.return_connection(conn)

    # 메모리 관련 함수 (프로필, 에피소드, 상태)
    def set_profile(self, user_id, character, key, value):
        conn = None
        try:
            conn = self.get_connection()
            with conn.cursor() as cur:
                cur.execute('''
                    INSERT INTO profiles (user_id, character, key, value)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (user_id, character, key) DO UPDATE SET value=EXCLUDED.value
                ''', (user_id, character, key, value))
                conn.commit()
        except Exception as e:
            print(f"Error in set_profile: {e}")
            if conn: conn.rollback()
        finally:
            self.return_connection(conn)

    def get_profile(self, user_id, character):
        conn = None
        try:
            conn = self.get_connection()
            with conn.cursor() as cur:
                cur.execute('SELECT key, value FROM profiles WHERE user_id=%s AND character=%s', (user_id, character))
                return dict(cur.fetchall())
        except Exception as e:
            print(f"Error in get_profile: {e}")
            return {}
        finally:
            self.return_connection(conn)

    def add_episode(self, user_id, character, summary, timestamp):
        conn = None
        try:
            conn = self.get_connection()
            with conn.cursor() as cur:
                cur.execute('INSERT INTO episodes (user_id, character, summary, timestamp) VALUES (%s, %s, %s, %s)', (user_id, character, summary, timestamp))
                conn.commit()
        except Exception as e:
            print(f"Error in add_episode: {e}")
            if conn: conn.rollback()
        finally:
            self.return_connection(conn)

    def get_recent_episodes(self, user_id, character, days=20):
        conn = None
        try:
            conn = self.get_connection()
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT summary, timestamp FROM episodes
                    WHERE user_id=%s AND character=%s AND timestamp >= NOW() - INTERVAL '%s days'
                    ORDER BY timestamp DESC
                """, (user_id, character, days))
                return cur.fetchall()
        except Exception as e:
            print(f"Error in get_recent_episodes: {e}")
            return []
        finally:
            self.return_connection(conn)

    def set_state(self, user_id, character, emotion_type, score, last_updated):
        conn = None
        try:
            conn = self.get_connection()
            with conn.cursor() as cur:
                cur.execute('''
                    INSERT INTO states (user_id, character, emotion_type, score, last_updated)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (user_id, character, emotion_type) DO UPDATE SET score=EXCLUDED.score, last_updated=EXCLUDED.last_updated
                ''', (user_id, character, emotion_type, score, last_updated))
                conn.commit()
        except Exception as e:
            print(f"Error in set_state: {e}")
            if conn: conn.rollback()
        finally:
            self.return_connection(conn)

    def get_states(self, user_id, character):
        conn = None
        try:
            conn = self.get_connection()
            with conn.cursor() as cur:
                cur.execute('SELECT emotion_type, score FROM states WHERE user_id=%s AND character=%s', (user_id, character))
                return dict(cur.fetchall())
        except Exception as e:
            print(f"Error in get_states: {e}")
            return {}
        finally:
            self.return_connection(conn)

    def get_memory_summaries_by_affinity(self, user_id: int, character_name: str, affinity_grade: str) -> list:
        """호감도 등급에 따른 메모리 요약을 가져옵니다."""
        conn = None
        try:
            conn = self.get_connection()
            with conn.cursor() as cursor:
                # 호감도 등급에 따른 요약 개수 결정
                summary_counts = {
                    'Rookie': 1,
                    'Iron': 2,
                    'Bronze': 3,
                    'Silver': 4,
                    'Gold': 5
                }
                limit = summary_counts.get(affinity_grade, 2)

                cursor.execute('''
                    SELECT summary, created_at, quality_score
                    FROM memory_summaries
                    WHERE user_id = %s AND character_name = %s
                    ORDER BY quality_score DESC, created_at DESC
                    LIMIT %s
                ''', (user_id, character_name, limit))
                return cursor.fetchall()
        except Exception as e:
            print(f"Error getting memory summaries: {e}")
            return []
        finally:
            self.return_connection(conn)

    def add_memory_summary(self, user_id: int, character_name: str, summary: str, quality_score: float, token_count: int) -> bool:
        """메모리 요약을 추가합니다."""
        conn = None
        try:
            conn = self.get_connection()
            with conn.cursor() as cursor:
                cursor.execute('''
                    INSERT INTO memory_summaries (user_id, character_name, summary, quality_score, token_count)
                    VALUES (%s, %s, %s, %s, %s)
                ''', (user_id, character_name, summary, quality_score, token_count))
                conn.commit()
                return True
        except Exception as e:
            print(f"Error adding memory summary: {e}")
            if conn: conn.rollback()
            return False
        finally:
            self.return_connection(conn)

    def delete_old_memory_summaries(self, user_id: int, character_name: str, keep_count: int = 5) -> bool:
        """오래된 메모리 요약을 삭제합니다."""
        conn = None
        try:
            conn = self.get_connection()
            with conn.cursor() as cursor:
                cursor.execute('''
                    DELETE FROM memory_summaries
                    WHERE user_id = %s AND character_name = %s
                    AND id NOT IN (
                        SELECT id FROM memory_summaries
                        WHERE user_id = %s AND character_name = %s
                        ORDER BY quality_score DESC, created_at DESC
                        LIMIT %s
                    )
                ''', (user_id, character_name, user_id, character_name, keep_count))
                conn.commit()
                return True
        except Exception as e:
            print(f"Error deleting old memory summaries: {e}")
            if conn: conn.rollback()
            return False
        finally:
            self.return_connection(conn)

    def get_user_character_messages(self, user_id: int, character_name: str, limit: int = 20):
        """특정 캐릭터와의 메시지 기록을 가져옵니다."""
        conn = None
        try:
            conn = self.get_connection()
            with conn.cursor() as cursor:
                cursor.execute(
                    "SELECT message_role, content, language FROM conversations WHERE user_id = %s AND character_name = %s ORDER BY timestamp DESC LIMIT %s",
                    (user_id, character_name, limit)
                )
                results = cursor.fetchall()
                # 튜플을 딕셔너리로 변환
                messages = []
                for row in results:
                    messages.append({
                        "role": row[0],
                        "content": row[1],
                        "language": row[2] if row[2] else "ko"
                    })
                return messages
        except Exception as e:
            print(f"Error getting user-character messages: {e}")
            return []
        finally:
            self.return_connection(conn)

    def get_user_messages(self, user_id: int, limit: int = 20):
        """사용자의 모든 캐릭터와의 최근 대화 기록 조회"""
        conn = None
        try:
            conn = self.get_connection()
            with conn.cursor() as cursor:
                cursor.execute('''
                    SELECT character_name, message_role, content, timestamp
                    FROM conversations 
                    WHERE user_id = %s
                    ORDER BY timestamp DESC 
                    LIMIT %s
                ''', (user_id, limit))
                messages = cursor.fetchall()
                return [{
                    "character": character,
                    "role": role,
                    "content": content,
                    "timestamp": timestamp
                } for character, role, content, timestamp in reversed(messages)]
        except Exception as e:
            print(f"Error getting user messages: {e}")
            return []
        finally:
            self.return_connection(conn)

    def get_total_messages(self, user_id: int, character_name: str) -> int:
        """사용자의 특정 캐릭터와의 총 메시지 수를 반환합니다."""
        conn = None
        try:
            conn = self.get_connection()
            with conn.cursor() as cursor:
                cursor.execute('''
                    SELECT COUNT(*) 
                    FROM conversations 
                    WHERE user_id = %s 
                    AND character_name = %s 
                    AND message_role = 'user'
                ''', (user_id, character_name))
                result = cursor.fetchone()
                return result[0] if result else 0
        except Exception as e:
            print(f"Error getting total messages: {e}")
            return 0
        finally:
            self.return_connection(conn)

    def update_user_conversation_state(self, user_id: int, character_name: str, has_nickname: bool = None, language_set: bool = None, message_count: int = None) -> bool:
        """사용자 대화 상태를 업데이트합니다."""
        conn = None
        try:
            conn = self.get_connection()
            with conn.cursor() as cursor:
                # 현재 상태 조회
                cursor.execute("SELECT has_nickname, language_set, message_count FROM user_conversation_state WHERE user_id = %s AND character_name = %s", (user_id, character_name))
                result = cursor.fetchone()

                if result:
                    # 기존 상태 업데이트
                    current_has_nickname, current_language_set, current_message_count = result
                    new_has_nickname = has_nickname if has_nickname is not None else current_has_nickname
                    new_language_set = language_set if language_set is not None else current_language_set
                    new_message_count = message_count if message_count is not None else current_message_count

                    cursor.execute('''
                        UPDATE user_conversation_state
                        SET has_nickname = %s, language_set = %s, message_count = %s, last_interaction = CURRENT_TIMESTAMP
                        WHERE user_id = %s AND character_name = %s
                    ''', (new_has_nickname, new_language_set, new_message_count, user_id, character_name))
                else:
                    # 새 상태 생성
                    cursor.execute('''
                        INSERT INTO user_conversation_state (user_id, character_name, has_nickname, language_set, message_count)
                        VALUES (%s, %s, %s, %s, %s)
                    ''', (user_id, character_name, has_nickname or False, language_set or False, message_count or 0))

                conn.commit()
                return True
        except Exception as e:
            print(f"Error updating user conversation state: {e}")
            if conn: conn.rollback()
            return False
        finally:
            self.return_connection(conn)

    def add_levelup_flag(self, user_id: int, character_name: str, level: str):
        """레벨업 플래그를 추가합니다."""
        conn = None
        try:
            conn = self.get_connection()
            with conn.cursor() as cursor:
                cursor.execute(
                    "INSERT INTO user_levelup_flags (user_id, character_name, level) VALUES (%s, %s, %s) ON CONFLICT DO NOTHING",
                    (user_id, character_name, level)
                )
            conn.commit()
        except Exception as e:
            print(f"Error adding levelup flag: {e}")
            if conn: conn.rollback()
        finally:
            self.return_connection(conn)

    def get_total_daily_messages(self, user_id: int) -> int:
        """CST 기준으로 오늘 하루 동안 사용자가 보낸 총 메시지 수를 반환합니다."""
        conn = None
        try:
            conn = self.get_connection()
            with conn.cursor() as cursor:
                today_cst = get_today_cst()
                cursor.execute(
                    "SELECT COUNT(*) FROM conversations WHERE user_id = %s AND DATE(timestamp AT TIME ZONE 'Asia/Shanghai') = %s AND message_role = 'user'",
                    (user_id, today_cst)
                )
                return cursor.fetchone()[0]
        except Exception as e:
            print(f"Error getting total daily messages: {e}")
            return 0
        finally:
            self.return_connection(conn)

    def get_today_cards(self, user_id: int) -> int:
        """CST 기준으로 오늘 하루 동안 사용자가 획득한 카드 수를 반환합니다."""
        conn = None
        try:
            conn = self.get_connection()
            with conn.cursor() as cursor:
                today_cst = get_today_cst()
                cursor.execute(
                    "SELECT COUNT(*) FROM user_cards WHERE user_id = %s AND DATE(acquired_at AT TIME ZONE 'Asia/Shanghai') = %s",
                    (user_id, today_cst)
                )
                return cursor.fetchone()[0]
        except Exception as e:
            print(f"Error getting today's cards: {e}")
            return 0
        finally:
            self.return_connection(conn)

    def update_login_streak(self, user_id: int):
        """
        사용자의 연속 로그인 기록을 업데이트합니다.
        CST(중국 표준시)를 기준으로 날짜를 비교합니다.
        """
        conn = None
        try:
            conn = self.get_connection()
            with conn.cursor() as cursor:
                today_cst = get_today_cst()

                # 사용자 레코드 확인
                cursor.execute(
                    "SELECT last_login_date, current_streak FROM user_login_streaks WHERE user_id = %s",
                    (user_id,)
                )
                result = cursor.fetchone()

                if result:
                    last_login_date, current_streak = result
                    # 어제 날짜 계산
                    yesterday_cst = today_cst - timedelta(days=1)

                    if last_login_date == today_cst:
                        # 이미 오늘 로그인 기록이 있으면 아무것도 안함
                        return
                    elif last_login_date == yesterday_cst:
                        # 연속 로그인
                        new_streak = current_streak + 1
                    else:
                        # 연속 로그인 실패
                        new_streak = 1

                    cursor.execute(
                        "UPDATE user_login_streaks SET last_login_date = %s, current_streak = %s WHERE user_id = %s",
                        (today_cst, new_streak, user_id)
                    )
                else:
                    # 첫 로그인
                    cursor.execute(
                        "INSERT INTO user_login_streaks (user_id, last_login_date, current_streak) VALUES (%s, %s, 1)",
                        (user_id, today_cst)
                    )
            conn.commit()
        except Exception as e:
            print(f"Error updating login streak: {e}")
            if conn: conn.rollback()
        finally:
            self.return_connection(conn)

    def get_login_streak(self, user_id: int) -> int:
        """사용자의 현재 연속 로그인 횟수를 반환합니다."""
        conn = None
        try:
            conn = self.get_connection()
            with conn.cursor() as cursor:
                cursor.execute(
                    "SELECT current_streak FROM user_login_streaks WHERE user_id = %s",
                    (user_id,)
                )
                result = cursor.fetchone()
                return result[0] if result else 0
        except Exception as e:
            print(f"Error getting login streak: {e}")
            return 0
        finally:
            self.return_connection(conn)

    def record_card_share(self, user_id: int, character_name: str, card_id: str):
        """
        사용자가 카드를 공유했음을 기록합니다.
        (주간 퀘스트: 카드 공유)
        """
        conn = None
        try:
            conn = self.get_connection()
            with conn.cursor() as cursor:
                # 'card_share' 이벤트 기록
                cursor.execute("""
                    INSERT INTO user_quest_events (user_id, event_type, event_date, character_name, card_id)
                    VALUES (%s, 'card_share', %s, %s, %s)
                """, (user_id, get_today_cst(), character_name, card_id))
            conn.commit()
        except Exception as e:
            print(f"Error in record_card_share: {e}")
            if conn: conn.rollback()
        finally:
            self.return_connection(conn)

    def get_card_shared_this_week(self, user_id: int) -> int:
        """
        CST 기준으로 이번 주에 카드를 공유했는지 확인합니다.
        """
        conn = None
        try:
            conn = self.get_connection()
            with conn.cursor() as cursor:
                today_cst = get_today_cst()
                start_of_week = today_cst - timedelta(days=today_cst.weekday())
                end_of_week = start_of_week + timedelta(days=6)
                
                cursor.execute(
                    """
                    SELECT COUNT(*) FROM user_quest_events
                    WHERE user_id = %s AND event_type = 'card_share' AND event_date BETWEEN %s AND %s
                    """,
                    (user_id, start_of_week, end_of_week)
                )
                count = cursor.fetchone()[0]
                return 1 if count > 0 else 0
        except Exception as e:
            print(f"Error checking weekly card share: {e}")
            return 0
        finally:
            self.return_connection(conn)

    def get_story_progress(self, user_id: int, character_name: str) -> list:
        conn = None
        try:
            conn = self.get_connection()
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute("""
                    SELECT 
                        chapter_number as stage_num,
                        CASE 
                            WHEN completed_at IS NOT NULL THEN 'completed'
                            ELSE 'in_progress'
                        END as status
                    FROM story_progress
                    WHERE user_id = %s AND character_name = %s
                """, (user_id, character_name))
                return cursor.fetchall()
        except Exception as e:
            print(f"Error getting story progress: {e}")
            if conn: conn.rollback()
            return []
        finally:
            self.return_connection(conn)
            
    def complete_story_stage(self, user_id: int, character_name: str, stage_num: int):
        # 이 함수는 CST와 무관
        conn = None
        try:
            conn = self.get_connection()
            with conn.cursor() as cursor:
                cursor.execute("""
                    INSERT INTO story_progress (user_id, character_name, chapter_number, completed_at)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (user_id, character_name, chapter_number)
                    DO UPDATE SET completed_at = EXCLUDED.completed_at
                """, (user_id, character_name, stage_num, datetime.utcnow()))
            conn.commit()
        except Exception as e:
            print(f"Error completing story stage: {e}")
            if conn: conn.rollback()
        finally:
            self.return_connection(conn)
            
    def is_quest_claimed(self, user_id: int, quest_id: str) -> bool:
        """CST 기준으로 오늘 해당 퀘스트 보상을 수령했는지 확인합니다."""
        conn = None
        try:
            conn = self.get_connection()
            with conn.cursor() as cursor:
                today_cst = get_today_cst()
                cursor.execute(
                    "SELECT 1 FROM quest_claims WHERE user_id = %s AND quest_id = %s AND DATE(claimed_at AT TIME ZONE 'Asia/Shanghai') = %s",
                    (user_id, quest_id, today_cst)
                )
                return cursor.fetchone() is not None
        except Exception as e:
            print(f"Error in is_quest_claimed: {e}")
            return False
        finally:
            self.return_connection(conn)

    def claim_quest(self, user_id: int, quest_id: str):
        """퀘스트 보상 수령 상태를 CST 기준으로 기록합니다."""
        from datetime import datetime
        print(f"[DEBUG] claim_quest called: user_id={user_id}, quest_id={quest_id}")
        conn = None
        try:
            now_cst = datetime.now(CST)
            print(f"[DEBUG] claim_quest - now_cst: {now_cst}")
            conn = self.get_connection()
            with conn.cursor() as cursor:
                cursor.execute("""
                    INSERT INTO quest_claims (user_id, quest_id, claimed_at)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (user_id, quest_id)
                    DO NOTHING; 
                """, (user_id, quest_id, now_cst))
            conn.commit()
            print(f"[DEBUG] claim_quest - DB commit success for user_id={user_id}, quest_id={quest_id}")
        except Exception as e:
            print(f"[DEBUG] claim_quest - Error: {e}")
            if conn: conn.rollback()
        finally:
            self.return_connection(conn)

    def reset_story_progress(self, user_id: int, character_name: str) -> bool:
        """Deletes all story progress for a specific user and character."""
        conn = None
        try:
            conn = self.get_connection()
            with conn.cursor() as cursor:
                cursor.execute("""
                    DELETE FROM story_progress
                    WHERE user_id = %s AND character_name = %s
                """, (user_id, character_name))
            conn.commit()
            return True
        except Exception as e:
            print(f"Error resetting story progress: {e}")
            if conn: conn.rollback()
            return False
        finally:
            self.return_connection(conn)

    # --- 스토리 퀘스트 관련 함수들 ---
    
    def is_story_quest_claimed(self, user_id: int, character_name: str, quest_type: str) -> bool:
        """스토리 퀘스트 보상을 이미 수령했는지 확인합니다."""
        conn = None
        try:
            conn = self.get_connection()
            with conn.cursor() as cursor:
                cursor.execute(
                    "SELECT 1 FROM story_quest_claims WHERE user_id = %s AND character_name = %s AND quest_type = %s",
                    (user_id, character_name, quest_type)
                )
                return cursor.fetchone() is not None
        except Exception as e:
            print(f"Error checking story quest claim: {e}")
            return False
        finally:
            self.return_connection(conn)

    def claim_story_quest(self, user_id: int, character_name: str, quest_type: str):
        """스토리 퀘스트 보상 수령 상태를 기록합니다."""
        conn = None
        try:
            conn = self.get_connection()
            with conn.cursor() as cursor:
                cursor.execute("""
                    INSERT INTO story_quest_claims (user_id, character_name, quest_type, claimed_at)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (user_id, character_name, quest_type)
                    DO NOTHING
                """, (user_id, character_name, quest_type, datetime.utcnow()))
            conn.commit()
        except Exception as e:
            print(f"Error claiming story quest: {e}")
            if conn: conn.rollback()
        finally:
            self.return_connection(conn)

    def get_completed_chapters(self, user_id: int, character_name: str) -> list:
        """사용자가 완료한 챕터 목록을 반환합니다."""
        conn = None
        try:
            conn = self.get_connection()
            with conn.cursor() as cursor:
                cursor.execute("""
                    SELECT chapter_number 
                    FROM story_progress 
                    WHERE user_id = %s AND character_name = %s AND completed_at IS NOT NULL
                    ORDER BY chapter_number
                """, (user_id, character_name))
                return [row[0] for row in cursor.fetchall()]
        except Exception as e:
            print(f"Error getting completed chapters: {e}")
            return []
        finally:
            self.return_connection(conn)

    def has_all_chapters_completed(self, user_id: int, character_name: str, total_chapters: int) -> bool:
        """모든 챕터를 완료했는지 확인합니다."""
        completed = self.get_completed_chapters(user_id, character_name)
        return len(completed) >= total_chapters

    def add_emotion_log(self, user_id: int, character_name: str, score: int, message: str, timestamp: datetime = None):
        print(f"[DEBUG] add_emotion_log called: user_id={user_id}, character_name={character_name}, score={score}, message={message}, timestamp={timestamp}")
        conn = None
        try:
            if timestamp is None:
                timestamp = datetime.utcnow()
            conn = self.get_connection()
            with conn.cursor() as cursor:
                cursor.execute(
                    "INSERT INTO affinity_log (user_id, character_name, score_change, message, timestamp) VALUES (%s, %s, %s, %s, %s)",
                    (user_id, character_name, score, message, timestamp)
                )
            conn.commit()
        except Exception as e:
            print(f"Error adding emotion log: {e}")
            if conn: conn.rollback()
        finally:
            self.return_connection(conn)

    def get_card_shared_today(self, user_id: int) -> int:
        """
        CST 기준으로 오늘 카드 공유를 1회 이상 했는지 확인합니다.
        중복 공유는 불가(1회만 인정).
        """
        conn = None
        try:
            conn = self.get_connection()
            with conn.cursor() as cursor:
                today_cst = get_today_cst()
                cursor.execute(
                    """
                    SELECT COUNT(DISTINCT card_id) FROM user_quest_events
                    WHERE user_id = %s AND event_type = 'card_share' AND event_date = %s
                    """,
                    (user_id, today_cst)
                )
                count = cursor.fetchone()[0]
                return 1 if count > 0 else 0
        except Exception as e:
            print(f"Error checking daily card share: {e}")
            return 0
        finally:
            self.return_connection(conn)

    def reset_quest_claims(self, user_id: int) -> bool:
        """
        해당 유저의 모든 일일/주간/레벨업/스토리 퀘스트 보상 수령 기록을 삭제합니다.
        (quest_claims 테이블 전체 삭제)
        """
        conn = None
        try:
            conn = self.get_connection()
            with conn.cursor() as cursor:
                cursor.execute("DELETE FROM quest_claims WHERE user_id = %s", (user_id,))
            conn.commit()
            return True
        except Exception as e:
            print(f"Error resetting quest claims: {e}")
            if conn: conn.rollback()
            return False
        finally:
            self.return_connection(conn)

    def get_today_affinity_gain(self, user_id: int) -> int:
        """
        오늘 하루 동안(0시~현재) 모든 캐릭터에 대해 유저가 획득한 총 호감도 증가량을 반환합니다.
        affinity_log 테이블에 user_id, score_change, timestamp 컬럼이 있다고 가정합니다.
        """
        import datetime
        from pytz import timezone
        now = datetime.datetime.now(timezone('Asia/Seoul'))
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        conn = None
        try:
            conn = self.get_connection()
            with conn.cursor() as cursor:
                cursor.execute("""
                    SELECT COALESCE(SUM(score_change), 0)
                    FROM affinity_log
                    WHERE user_id = %s AND timestamp >= %s
                """, (user_id, today_start))
                result = cursor.fetchone()
                return result[0] if result else 0
        except Exception as e:
            print(f"Error in get_today_affinity_gain: {e}")
            return 0
        finally:
            self.return_connection(conn)

    def is_weekly_quest_claimed(self, user_id: int, quest_id: str) -> bool:
        """이번 주(월~일) 내에 해당 퀘스트 보상을 이미 수령했는지 확인합니다."""
        today = get_today_cst()
        start_of_week = today - timedelta(days=today.weekday())  # 월요일
        end_of_week = start_of_week + timedelta(days=7)
        conn = self.get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    "SELECT 1 FROM quest_claims WHERE user_id = %s AND quest_id = %s AND claimed_at >= %s AND claimed_at < %s",
                    (user_id, quest_id, start_of_week, end_of_week)
                )
                return cursor.fetchone() is not None
        finally:
            self.return_connection(conn)