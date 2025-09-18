from datetime import datetime, date, timedelta
import json
import os
import psycopg2
import gift_manager
from init_db import create_all_tables
from pytz import timezone
from psycopg2.extras import RealDictCursor
from typing import Optional, Dict, Any

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
    def add_message(self, channel_id: int, user_id: int, character_name: str, role: str, content: str, language: str = None, is_daily_message: bool = True):
        print(f"[DEBUG] add_message called: channel_id={channel_id}, user_id={user_id}, character_name={character_name}, role={role}, content={content}, language={language}, is_daily_message={is_daily_message}")
        conn = None
        try:
            conn = self.get_connection()
            with conn.cursor() as cursor:
                # CST 시간대의 현재 시간을 명시적으로 저장
                now_cst = datetime.now(CST)
                print(f"[DEBUG] add_message - now_cst: {now_cst}, type: {type(now_cst)}")
                
                cursor.execute(
                    "INSERT INTO conversations (channel_id, user_id, character_name, message_role, content, language, timestamp, is_daily_message) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                    (channel_id, user_id, character_name, role, content, language, now_cst, is_daily_message)
                )
                
                # INSERT 후 실제로 저장된 데이터 확인
                cursor.execute(
                    "SELECT timestamp, is_daily_message FROM conversations WHERE user_id = %s ORDER BY id DESC LIMIT 1",
                    (user_id,)
                )
                saved_data = cursor.fetchone()
                print(f"[DEBUG] add_message - saved timestamp: {saved_data[0]}, is_daily_message: {saved_data[1]}")
                
            conn.commit()
            print(f"[DEBUG] add_message DB INSERT SUCCESS for user_id={user_id}, character_name={character_name}, timestamp={now_cst}, is_daily_message={is_daily_message}")
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

    def add_user_affinity(self, user_id: int, character_name: str, points: int) -> bool:
        """사용자의 호감도를 직접 추가합니다."""
        conn = None
        try:
            conn = self.get_connection()
            with conn.cursor() as cursor:
                # 기존 호감도 확인
                cursor.execute("SELECT emotion_score FROM affinity WHERE user_id = %s AND character_name = %s", (user_id, character_name))
                result = cursor.fetchone()
                
                if result:
                    # 기존 호감도에 추가
                    new_score = result[0] + points
                    cursor.execute(
                        "UPDATE affinity SET emotion_score = %s WHERE user_id = %s AND character_name = %s",
                        (new_score, user_id, character_name)
                    )
                else:
                    # 새로운 호감도 레코드 생성
                    cursor.execute(
                        "INSERT INTO affinity (user_id, character_name, emotion_score, daily_message_count, last_daily_reset) VALUES (%s, %s, %s, 0, %s)",
                        (user_id, character_name, points, get_today_cst())
                    )
                
                conn.commit()
                print(f"[DEBUG] add_user_affinity - Successfully added {points} affinity points for {character_name} to user {user_id}")
                return True
        except Exception as e:
            print(f"Error adding user affinity: {e}")
            if conn: conn.rollback()
            return False
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
        """사용자가 보유한 카드 목록을 반환합니다. 중복된 카드는 제거합니다. (대소문자 구분 없음)"""
        conn = None
        try:
            conn = self.get_connection()
            with conn.cursor() as cursor:
                if character_name:
                    # 특정 캐릭터의 카드만 조회 (중복 제거, 대소문자 구분 없음)
                    cursor.execute(
                        "SELECT DISTINCT UPPER(card_id) as card_id, MIN(acquired_at) as acquired_at FROM user_cards WHERE user_id = %s AND character_name = %s GROUP BY UPPER(card_id) ORDER BY acquired_at DESC",
                        (user_id, character_name)
                    )
                else:
                    # 모든 캐릭터의 카드 조회 (중복 제거, 대소문자 구분 없음)
                    cursor.execute(
                        "SELECT character_name, UPPER(card_id) as card_id, MIN(acquired_at) as acquired_at FROM user_cards WHERE user_id = %s GROUP BY character_name, UPPER(card_id) ORDER BY acquired_at DESC",
                        (user_id,)
                    )
                return cursor.fetchall()
        except Exception as e:
            print(f"Error getting user cards: {e}")
            return []
        finally:
            self.return_connection(conn)

    def has_user_card(self, user_id: int, character_name: str, card_id: str) -> bool:
        """사용자가 특정 카드를 보유하고 있는지 확인합니다. (대소문자 구분 없음)"""
        conn = None
        try:
            conn = self.get_connection()
            with conn.cursor() as cursor:
                cursor.execute(
                    "SELECT 1 FROM user_cards WHERE user_id = %s AND character_name = %s AND UPPER(card_id) = %s",
                    (user_id, character_name, card_id.upper())
                )
                return cursor.fetchone() is not None
        except Exception as e:
            print(f"Error checking user card: {e}")
            return False
        finally:
            self.return_connection(conn)

    def get_unique_user_cards_count(self, user_id: int, character_name: str = None) -> int:
        """사용자가 보유한 고유 카드 개수를 반환합니다. (대소문자 구분 없음)"""
        conn = None
        try:
            conn = self.get_connection()
            with conn.cursor() as cursor:
                if character_name:
                    cursor.execute(
                        "SELECT COUNT(DISTINCT UPPER(card_id)) FROM user_cards WHERE user_id = %s AND character_name = %s",
                        (user_id, character_name)
                    )
                else:
                    cursor.execute(
                        "SELECT COUNT(DISTINCT CONCAT(character_name, '_', UPPER(card_id))) FROM user_cards WHERE user_id = %s",
                        (user_id,)
                    )
                result = cursor.fetchone()
                return result[0] if result else 0
        except Exception as e:
            print(f"Error getting unique user cards count: {e}")
            return 0
        finally:
            self.return_connection(conn)

    def cleanup_duplicate_cards(self, user_id: int = None) -> int:
        """중복된 카드 데이터를 정리합니다. 특정 사용자만 정리하거나 전체 정리 가능합니다. (대소문자 구분 없음)"""
        conn = None
        try:
            conn = self.get_connection()
            with conn.cursor() as cursor:
                if user_id:
                    # 특정 사용자의 중복 카드만 정리 (대소문자 구분 없음)
                    cursor.execute("""
                        DELETE FROM user_cards 
                        WHERE id NOT IN (
                            SELECT MIN(id) 
                            FROM user_cards 
                            WHERE user_id = %s 
                            GROUP BY user_id, character_name, UPPER(card_id)
                        ) AND user_id = %s
                    """, (user_id, user_id))
                else:
                    # 전체 중복 카드 정리 (대소문자 구분 없음)
                    cursor.execute("""
                        DELETE FROM user_cards 
                        WHERE id NOT IN (
                            SELECT MIN(id) 
                            FROM user_cards 
                            GROUP BY user_id, character_name, UPPER(card_id)
                        )
                    """)
                
                deleted_count = cursor.rowcount
                conn.commit()
                print(f"[DEBUG] Cleaned up {deleted_count} duplicate cards")
                return deleted_count
        except Exception as e:
            print(f"Error cleaning up duplicate cards: {e}")
            if conn: conn.rollback()
            return 0
        finally:
            self.return_connection(conn)

    def add_user_card(self, user_id: int, character_name: str, card_id: str, acquired_at: datetime = None) -> bool:
        """사용자에게 카드를 추가합니다. 이미 보유한 카드는 추가하지 않습니다."""
        conn = None
        try:
            conn = self.get_connection()
            with conn.cursor() as cursor:
                # 카드 ID를 대문자로 정규화
                normalized_card_id = card_id.upper()
                
                # 이미 해당 카드를 보유하고 있는지 확인 (대소문자 구분 없이)
                cursor.execute(
                    "SELECT 1 FROM user_cards WHERE user_id = %s AND character_name = %s AND UPPER(card_id) = %s",
                    (user_id, character_name, normalized_card_id)
                )
                if cursor.fetchone():
                    print(f"[DEBUG] User {user_id} already has card {normalized_card_id} for {character_name}")
                    return False  # 이미 보유한 카드
                
                # 호감도 점수 가져오기
                cursor.execute("SELECT emotion_score FROM affinity WHERE user_id = %s AND character_name = %s", (user_id, character_name))
                result = cursor.fetchone()
                emotion_score_at_obtain = result[0] if result else 0

                # 카드 추가 (정규화된 카드 ID 사용)
                cursor.execute(
                    "INSERT INTO user_cards (user_id, character_name, card_id, emotion_score_at_obtain, acquired_at) VALUES (%s, %s, %s, %s, %s)",
                    (user_id, character_name, normalized_card_id, emotion_score_at_obtain, acquired_at))
            conn.commit()
            print(f"[DEBUG] Successfully added card {normalized_card_id} for user {user_id} ({character_name})")
            return True
        except Exception as e:
            print(f"Error adding user card: {e}")
            if conn: conn.rollback()
            return False
        finally:
            self.return_connection(conn)

    # 선물 관련 함수
    def add_user_gift(self, user_id: int, gift_id: str, quantity: int = 1) -> bool:
        conn = None
        try:
            conn = self.get_connection()
            with conn.cursor() as cursor:
                cursor.execute("""
                    INSERT INTO user_gifts (user_id, gift_id, quantity, obtained_at) VALUES (%s, %s, %s, %s)
                    ON CONFLICT (user_id, gift_id) DO UPDATE SET 
                        quantity = user_gifts.quantity + EXCLUDED.quantity,
                        obtained_at = EXCLUDED.obtained_at;
                """, (user_id, gift_id, quantity, datetime.utcnow()))
            conn.commit()
            print(f"[DEBUG] add_user_gift - Successfully added gift {gift_id} x{quantity} for user {user_id}")
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
                cursor.execute("SELECT gift_id, quantity FROM user_gifts WHERE user_id = %s ORDER BY obtained_at DESC NULLS LAST", (user_id,))
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
        print(f"[DEBUG] add_user_keyword called: user_id={user_id}, character_name={character_name}, keyword={keyword}, context={context}")
        conn = None
        try:
            conn = self.get_connection()
            with conn.cursor() as cursor:
                cursor.execute(
                    "INSERT INTO user_keywords (user_id, character_name, keyword_type, keyword_value, context) VALUES (%s, %s, %s, %s, %s)",
                    (user_id, character_name, 'default', keyword, context)
                )
            conn.commit()
            print(f"[DEBUG] add_user_keyword DB INSERT SUCCESS for user_id={user_id}, character_name={character_name}, keyword={keyword}")
        except Exception as e:
            print(f"Error adding user keyword to DB: {e}")
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
                print(f"[DEBUG] get_total_daily_messages - user_id={user_id}, today_cst={today_cst}")
                
                # 먼저 해당 사용자의 모든 메시지를 확인
                cursor.execute(
                    "SELECT timestamp, message_role FROM conversations WHERE user_id = %s ORDER BY timestamp DESC LIMIT 5",
                    (user_id,)
                )
                recent_messages = cursor.fetchall()
                print(f"[DEBUG] get_total_daily_messages - recent messages: {recent_messages}")
                
                # 전체 메시지 수도 확인
                cursor.execute(
                    "SELECT COUNT(*) FROM conversations WHERE user_id = %s",
                    (user_id,)
                )
                total_count = cursor.fetchone()[0]
                print(f"[DEBUG] get_total_daily_messages - total messages for user: {total_count}")
                
                # 오늘 날짜의 메시지 수 확인 (단순 날짜 비교)
                cursor.execute(
                    "SELECT COUNT(*) FROM conversations WHERE user_id = %s AND DATE(timestamp) = %s AND message_role = 'user'",
                    (user_id, today_cst)
                )
                count_simple = cursor.fetchone()[0]
                print(f"[DEBUG] get_total_daily_messages - count (simple date): {count_simple}")
                
                # CST 시간대 변환을 사용한 정확한 계산
                try:
                    cursor.execute(
                        "SELECT COUNT(*) FROM conversations WHERE user_id = %s AND DATE(timestamp AT TIME ZONE 'UTC' AT TIME ZONE 'Asia/Shanghai') = %s AND message_role = 'user'",
                        (user_id, today_cst)
                    )
                    count = cursor.fetchone()[0]
                    print(f"[DEBUG] get_total_daily_messages - count (with timezone): {count}")
                    
                    # 시간대 변환이 성공하고 결과가 있으면 사용
                    if count > 0:
                        return count
                except Exception as timezone_error:
                    print(f"[DEBUG] get_total_daily_messages - timezone conversion failed: {timezone_error}")
                
                # 시간대 변환이 실패하거나 결과가 없으면 단순 날짜 비교 사용
                print(f"[DEBUG] get_total_daily_messages - using simple date count as fallback")
                return count_simple
        except Exception as e:
            print(f"Error getting total daily messages: {e}")
            return 0
        finally:
            self.return_connection(conn)

    def get_english_daily_messages(self, user_id: int) -> int:
        """CST 기준으로 오늘 하루 동안 사용자가 보낸 영어 메시지 수를 반환합니다. (데일리 퀘스트용)"""
        conn = None
        try:
            conn = self.get_connection()
            with conn.cursor() as cursor:
                today_cst = get_today_cst()
                cursor.execute(
                    "SELECT COUNT(*) FROM conversations WHERE user_id = %s AND DATE(timestamp AT TIME ZONE 'Asia/Shanghai') = %s AND message_role = 'user' AND language = 'en'",
                    (user_id, today_cst)
                )
                return cursor.fetchone()[0]
        except Exception as e:
            print(f"Error getting English daily messages: {e}")
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
                print(f"[DEBUG] is_quest_claimed - checking for user_id={user_id}, quest_id={quest_id}, today_cst={today_cst}")
                
                # 더 간단한 방식으로 오늘 날짜 체크
                cursor.execute(
                    "SELECT 1 FROM quest_claims WHERE user_id = %s AND quest_id = %s AND DATE(claimed_at) = %s",
                    (user_id, quest_id, today_cst)
                )
                result = cursor.fetchone() is not None
                print(f"[DEBUG] is_quest_claimed - result: {result}")
                return result
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
                    ON CONFLICT (user_id, quest_id, claimed_at)
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

    def record_daily_quest_progress(self, user_id: int, quest_id: str, completed: bool, reward_claimed: bool):
        """
        일일 퀘스트 진행/보상 현황을 daily_quest_progress 테이블에 기록합니다.
        quest_id는 구분용으로 context에 저장하거나, 필요시 컬럼 추가 가능.
        """
        conn = None
        try:
            today = get_today_cst()
            conn = self.get_connection()
            with conn.cursor() as cursor:
                cursor.execute("""
                    INSERT INTO daily_quest_progress (user_id, quest_date, completed, reward_claimed, completed_at)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (user_id, quest_date)
                    DO UPDATE SET completed = %s, reward_claimed = %s, completed_at = %s
                """, (user_id, today, completed, reward_claimed, datetime.now(), completed, reward_claimed, datetime.now()))
            conn.commit()
        except Exception as e:
            print(f"Error recording daily quest progress: {e}")
            if conn: conn.rollback()
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

    def add_spam_message(self, user_id: int, character_name: str, message: str, reason: str, timestamp):
        print(f"[DEBUG] add_spam_message called: user_id={user_id}, character_name={character_name}, message={message}, reason={reason}, timestamp={timestamp}")
        conn = None
        try:
            conn = self.get_connection()
            with conn.cursor() as cursor:
                cursor.execute(
                    "INSERT INTO spam_messages (user_id, character_name, message, reason, timestamp) VALUES (%s, %s, %s, %s, %s)",
                    (user_id, character_name, message, reason, timestamp)
                )
            conn.commit()
            print(f"[DEBUG] add_spam_message DB INSERT SUCCESS for user_id={user_id}, message={message}")
        except Exception as e:
            print(f"Error adding spam message to DB: {e}")
            if conn: conn.rollback()
        finally:
            self.return_connection(conn)

    # 메시지 잔액 관리 함수들
    def get_user_message_balance(self, user_id: int) -> int:
        """사용자의 메시지 잔액을 반환합니다."""
        conn = None
        try:
            conn = self.get_connection()
            with conn.cursor() as cursor:
                cursor.execute(
                    "SELECT total_messages FROM user_message_balance WHERE user_id = %s",
                    (user_id,)
                )
                result = cursor.fetchone()
                return result[0] if result else 0
        except Exception as e:
            print(f"Error getting user message balance: {e}")
            return 0
        finally:
            self.return_connection(conn)

    def add_user_messages(self, user_id: int, amount: int) -> bool:
        """사용자에게 메시지를 추가합니다."""
        conn = None
        try:
            conn = self.get_connection()
            with conn.cursor() as cursor:
                cursor.execute("""
                    INSERT INTO user_message_balance (user_id, total_messages, last_updated)
                    VALUES (%s, %s, NOW())
                    ON CONFLICT (user_id) DO UPDATE SET 
                        total_messages = user_message_balance.total_messages + EXCLUDED.total_messages,
                        last_updated = NOW()
                """, (user_id, amount))
            conn.commit()
            return True
        except Exception as e:
            print(f"Error adding user messages: {e}")
            if conn: conn.rollback()
            return False
        finally:
            self.return_connection(conn)

    def use_user_message(self, user_id: int) -> bool:
        """사용자의 메시지를 1개 차감합니다."""
        conn = None
        try:
            conn = self.get_connection()
            with conn.cursor() as cursor:
                # 먼저 잔액 확인
                cursor.execute(
                    "SELECT total_messages FROM user_message_balance WHERE user_id = %s FOR UPDATE",
                    (user_id,)
                )
                result = cursor.fetchone()
                
                if not result or result[0] <= 0:
                    return False
                
                # 메시지 차감
                cursor.execute("""
                    UPDATE user_message_balance 
                    SET total_messages = total_messages - 1, last_updated = NOW()
                    WHERE user_id = %s
                """, (user_id,))
            conn.commit()
            return True
        except Exception as e:
            print(f"Error using user message: {e}")
            if conn: conn.rollback()
            return False
        finally:
            self.return_connection(conn)

    def is_user_admin(self, user_id: int) -> bool:
        """사용자가 관리자인지 확인합니다."""
        # 하드코딩된 관리자 ID들 (실제로는 Discord 권한으로 확인해야 함)
        admin_ids = [534941503345262613]  # 관리자 ID
        return user_id in admin_ids

    def get_user_daily_message_count(self, user_id: int) -> int:
        """사용자의 오늘 일일 메시지 사용 수를 반환합니다 (UTC+0 기준)."""
        conn = None
        try:
            conn = self.get_connection()
            with conn.cursor() as cursor:
                cursor.execute("""
                    SELECT COUNT(*) FROM conversations 
                    WHERE user_id = %s 
                    AND message_role = 'user' 
                    AND DATE(timestamp AT TIME ZONE 'UTC') = CURRENT_DATE
                    AND is_daily_message = true
                """, (user_id,))
                result = cursor.fetchone()
                return result[0] if result else 0
        except Exception as e:
            print(f"Error getting daily message count: {e}")
            return 0
        finally:
            self.return_connection(conn)

    def get_user_recent_message_count(self, user_id: int, character_name: str, limit: int) -> int:
        """사용자의 최근 메시지 수를 반환합니다."""
        conn = None
        try:
            conn = self.get_connection()
            with conn.cursor() as cursor:
                cursor.execute("""
                    SELECT COUNT(*) FROM (
                        SELECT * FROM conversations 
                        WHERE user_id = %s AND character_name = %s AND message_role = 'user'
                        ORDER BY timestamp DESC
                        LIMIT %s
                    ) AS recent_messages
                """, (user_id, character_name, limit))
                result = cursor.fetchone()
                return result[0] if result else 0
        except Exception as e:
            print(f"Error getting recent message count: {e}")
            return 0
        finally:
            self.return_connection(conn)

    def get_user_recent_messages(self, user_id: int, character_name: str, limit: int) -> list:
        """사용자의 최근 메시지를 반환합니다."""
        conn = None
        try:
            conn = self.get_connection()
            with conn.cursor() as cursor:
                cursor.execute("""
                    SELECT content, timestamp FROM conversations 
                    WHERE user_id = %s AND character_name = %s AND message_role = 'user'
                    ORDER BY timestamp DESC
                    LIMIT %s
                """, (user_id, character_name, limit))
                result = cursor.fetchall()
                return result if result else []
        except Exception as e:
            print(f"Error getting recent messages: {e}")
            return []
        finally:
            self.return_connection(conn)

    def get_user_paid_message_count(self, user_id: int) -> int:
        """사용자의 오늘 유료 메시지 사용 수를 반환합니다 (UTC+0 기준)."""
        conn = None
        try:
            conn = self.get_connection()
            with conn.cursor() as cursor:
                cursor.execute("""
                    SELECT COUNT(*) FROM conversations 
                    WHERE user_id = %s 
                    AND message_role = 'user' 
                    AND DATE(timestamp AT TIME ZONE 'UTC') = CURRENT_DATE
                    AND is_daily_message = false
                """, (user_id,))
                result = cursor.fetchone()
                return result[0] if result else 0
        except Exception as e:
            print(f"Error getting paid message count: {e}")
            return 0
        finally:
            self.return_connection(conn)

    def can_user_send_message_new(self, user_id: int) -> bool:
        """새로운 메시지 사용 가능 여부 확인 로직"""
        # 관리자는 제한 없음
        if self.is_user_admin(user_id):
            return True
        
        daily_used = self.get_user_daily_message_count(user_id)
        paid_balance = self.get_user_message_balance(user_id)
        
        # 구독 사용자는 일일 20개 + 구독 추가 메시지
        if self.is_user_subscribed(user_id):
            subscription_daily_messages = self.get_subscription_daily_messages(user_id)
            max_daily_messages = 20 + subscription_daily_messages
            return daily_used < max_daily_messages
        
        # 일반 사용자: 일일 20개 + 유료 메시지
        if daily_used < 20:
            # 일일 메시지가 남아있으면 사용 가능
            return True
        elif daily_used >= 20 and paid_balance > 0:
            # 일일 메시지를 모두 사용했지만 유료 메시지가 있으면 사용 가능
            return True
        else:
            # 일일 메시지도 모두 사용하고 유료 메시지도 없으면 사용 불가
            return False

    def can_user_send_message(self, user_id: int) -> bool:
        """사용자가 메시지를 보낼 수 있는지 확인합니다."""
        # 관리자는 제한 없음
        if self.is_user_admin(user_id):
            return True
        
        daily_count = self.get_user_daily_message_count(user_id)
        
        # 구독 사용자는 일일 20개 + 구독 추가 메시지
        if self.is_user_subscribed(user_id):
            subscription_daily_messages = self.get_subscription_daily_messages(user_id)
            max_daily_messages = 20 + subscription_daily_messages
            if daily_count >= max_daily_messages:
                return False
            return True
        
        # 일반 사용자는 일일 20개 + 메시지 잔액 사용 가능
        if daily_count < 20:
            # 일일 20개 미만이면 사용 가능
            return True
        
        # 일일 20개를 모두 사용했으면 메시지 잔액 확인
        balance = self.get_user_message_balance(user_id)
        return balance > 0

    # 구독 관리 함수들
    def add_user_subscription(self, user_id: int, product_id: str, duration_days: int) -> bool:
        """사용자에게 구독을 추가합니다."""
        conn = None
        try:
            from datetime import datetime, timedelta
            conn = self.get_connection()
            with conn.cursor() as cursor:
                start_date = datetime.utcnow()
                end_date = start_date + timedelta(days=duration_days)
                
                cursor.execute("""
                    INSERT INTO user_subscriptions (user_id, product_id, start_date, end_date)
                    VALUES (%s, %s, %s, %s)
                """, (user_id, product_id, start_date, end_date))
            conn.commit()
            return True
        except Exception as e:
            print(f"Error adding user subscription: {e}")
            if conn: conn.rollback()
            return False
        finally:
            self.return_connection(conn)

    def get_active_subscriptions(self, user_id: int) -> list:
        """사용자의 활성 구독 목록을 반환합니다."""
        conn = None
        try:
            conn = self.get_connection()
            with conn.cursor() as cursor:
                cursor.execute("""
                    SELECT product_id, end_date FROM user_subscriptions 
                    WHERE user_id = %s AND is_active = TRUE AND end_date > NOW()
                """, (user_id,))
                return cursor.fetchall()
        except Exception as e:
            print(f"Error getting active subscriptions: {e}")
            return []
        finally:
            self.return_connection(conn)

    def is_user_subscribed(self, user_id: int) -> bool:
        """사용자가 활성 구독을 가지고 있는지 확인합니다."""
        subscriptions = self.get_active_subscriptions(user_id)
        return len(subscriptions) > 0

    def get_subscription_daily_messages(self, user_id: int) -> int:
        """구독 사용자의 일일 추가 메시지 수를 반환합니다."""
        try:
            conn = self.get_connection()
            with conn.cursor() as cursor:
                # 활성 구독 중에서 가장 높은 daily_messages 값을 가진 구독을 찾음
                cursor.execute("""
                    SELECT us.product_id, p.rewards
                    FROM user_subscriptions us
                    JOIN products p ON us.product_id = p.id
                    WHERE us.user_id = %s AND us.is_active = true AND us.end_date > NOW()
                    ORDER BY (p.rewards->>'daily_messages')::int DESC
                    LIMIT 1
                """, (user_id,))
                result = cursor.fetchone()
                
                if result:
                    product_id, rewards = result
                    rewards_data = json.loads(rewards) if isinstance(rewards, str) else rewards
                    return rewards_data.get('daily_messages', 0)
                return 0
        except Exception as e:
            print(f"Error getting subscription daily messages: {e}")
            return 0
        finally:
            self.return_connection(conn)

    def process_daily_subscription_rewards(self, user_id: int) -> bool:
        """구독 사용자에게 일일 보상을 지급합니다."""
        try:
            conn = self.get_connection()
            with conn.cursor() as cursor:
                # 활성 구독 조회
                cursor.execute("""
                    SELECT us.product_id, p.rewards
                    FROM user_subscriptions us
                    JOIN products p ON us.product_id = p.id
                    WHERE us.user_id = %s AND us.is_active = true AND us.end_date > NOW()
                """, (user_id,))
                subscriptions = cursor.fetchall()
                
                if not subscriptions:
                    return False
                
                # 가장 높은 daily_messages 값을 가진 구독 찾기
                max_daily_messages = 0
                max_gifts = 0
                
                for product_id, rewards in subscriptions:
                    rewards_data = json.loads(rewards) if isinstance(rewards, str) else rewards
                    daily_messages = rewards_data.get('daily_messages', 0)
                    gifts = rewards_data.get('gifts', 0)
                    
                    if daily_messages > max_daily_messages:
                        max_daily_messages = daily_messages
                    if gifts > max_gifts:
                        max_gifts = gifts
                
                # 일일 메시지 지급 (기존 메시지 잔액에 추가)
                if max_daily_messages > 0:
                    self.add_user_messages(user_id, max_daily_messages)
                    print(f"Added {max_daily_messages} daily subscription messages to user {user_id}")
                
                # 기프트 지급 (누적)
                if max_gifts > 0:
                    for _ in range(max_gifts):
                        # 랜덤 기프트 지급 (모든 캐릭터에서)
                        gift_name = self.add_random_gift_to_user(user_id, "Kagari")
                        if not gift_name:
                            gift_name = self.add_random_gift_to_user(user_id, "Eros")
                        if not gift_name:
                            gift_name = self.add_random_gift_to_user(user_id, "Elysia")
                        print(f"Added daily subscription gift to user {user_id}")
                
                return True
                
        except Exception as e:
            print(f"Error processing daily subscription rewards: {e}")
            return False
        finally:
            self.return_connection(conn)

    def add_payment_transaction(self, transaction_id: str, user_id: int, product_id: str, 
                              amount: float, currency: str, status: str, 
                              payment_method: str, timestamp: int) -> str:
        """결제 거래를 기록합니다."""
        try:
            conn = self.get_connection()
            with conn.cursor() as cursor:
                cursor.execute("""
                    INSERT INTO payment_transactions 
                    (transaction_id, user_id, product_id, amount, currency, status, payment_method, created_at, processed_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING id
                """, (
                    transaction_id, user_id, product_id, amount, currency, 
                    status, payment_method, 
                    datetime.fromtimestamp(timestamp),
                    datetime.utcnow()
                ))
                result = cursor.fetchone()
                conn.commit()
                return str(result[0])
        except Exception as e:
            print(f"Error adding payment transaction: {e}")
            conn.rollback()
            return None
        finally:
            self.return_connection(conn)

    def get_transaction_by_id(self, transaction_id: str) -> Optional[Dict]:
        """거래 ID로 거래 정보를 조회합니다."""
        try:
            conn = self.get_connection()
            with conn.cursor() as cursor:
                cursor.execute("""
                    SELECT * FROM payment_transactions 
                    WHERE transaction_id = %s
                """, (transaction_id,))
                result = cursor.fetchone()
                if result:
                    return {
                        'id': result[0],
                        'transaction_id': result[1],
                        'user_id': result[2],
                        'product_id': result[3],
                        'amount': result[4],
                        'currency': result[5],
                        'status': result[6],
                        'payment_method': result[7],
                        'created_at': result[8],
                        'processed_at': result[9]
                    }
                return None
        except Exception as e:
            print(f"Error getting transaction by ID: {e}")
            return None
        finally:
            self.return_connection(conn)

    def add_product_delivery_log(self, user_id: int, product_id: str, transaction_id: str,
                               delivery_type: str, quantity: Dict, delivered_at: datetime,
                               status: str) -> str:
        """상품 지급 로그를 기록합니다."""
        try:
            conn = self.get_connection()
            with conn.cursor() as cursor:
                cursor.execute("""
                    INSERT INTO product_delivery_log 
                    (user_id, product_id, transaction_id, delivery_type, quantity, delivered_at, status)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    RETURNING id
                """, (
                    user_id, product_id, transaction_id, delivery_type, 
                    json.dumps(quantity), delivered_at, status
                ))
                result = cursor.fetchone()
                conn.commit()
                return str(result[0])
        except Exception as e:
            print(f"Error adding product delivery log: {e}")
            conn.rollback()
            return None
        finally:
            self.return_connection(conn)

    def get_user_payment_history(self, user_id: int, limit: int = 10) -> list:
        """사용자의 결제 기록을 조회합니다."""
        conn = None
        try:
            conn = self.get_connection()
            with conn.cursor() as cursor:
                cursor.execute("""
                    SELECT transaction_id, product_id, amount, currency, 
                           payment_method, status, created_at
                    FROM payment_transactions 
                    WHERE user_id = %s 
                    ORDER BY created_at DESC 
                    LIMIT %s
                """, (user_id, limit))
                results = cursor.fetchall()
                return [
                    {
                        'transaction_id': row[0],
                        'product_id': row[1],
                        'amount': row[2],
                        'currency': row[3],
                        'payment_method': row[4],
                        'status': row[5],
                        'created_at': row[6]
                    }
                    for row in results
                ]
        except Exception as e:
            print(f"Error getting payment history: {e}")
            return []
        finally:
            self.return_connection(conn)

    def get_user_delivery_history(self, user_id: int, limit: int = 10) -> list:
        """사용자의 상품 지급 기록을 조회합니다."""
        conn = None
        try:
            conn = self.get_connection()
            with conn.cursor() as cursor:
                cursor.execute("""
                    SELECT product_id, transaction_id, delivery_type, 
                           quantity, delivered_at, status
                    FROM product_delivery_log 
                    WHERE user_id = %s 
                    ORDER BY delivered_at DESC 
                    LIMIT %s
                """, (user_id, limit))
                results = cursor.fetchall()
                return [
                    {
                        'product_id': row[0],
                        'transaction_id': row[1],
                        'delivery_type': row[2],
                        'quantity': json.loads(row[3]) if row[3] else {},
                        'delivered_at': row[4],
                        'status': row[5]
                    }
                    for row in results
                ]
        except Exception as e:
            print(f"Error getting delivery history: {e}")
            return []
        finally:
            self.return_connection(conn)

    def get_user_recent_activity(self, user_id: int, limit: int = 5) -> dict:
        """사용자의 최근 결제 및 지급 활동을 조회합니다."""
        payment_history = self.get_user_payment_history(user_id, limit)
        delivery_history = self.get_user_delivery_history(user_id, limit)
        
        return {
            'payments': payment_history,
            'deliveries': delivery_history,
            'total_payments': len(payment_history),
            'total_deliveries': len(delivery_history)
        }
    
    def get_total_message_count(self) -> int:
        """총 유저 메시지 수를 반환합니다."""
        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("SELECT COUNT(*) FROM conversations WHERE message_role = 'user'")
                return cursor.fetchone()[0]
    
    def get_daily_message_count(self) -> int:
        """오늘(UTC+8 기준) 대화한 횟수를 반환합니다."""
        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                # UTC+8 시간대 (CST) 기준으로 오늘 메시지 수 계산
                cursor.execute("""
                    SELECT COUNT(*) FROM conversations 
                    WHERE message_role = 'user' 
                    AND DATE(timestamp AT TIME ZONE 'UTC' AT TIME ZONE 'Asia/Shanghai') = CURRENT_DATE AT TIME ZONE 'Asia/Shanghai'
                """)
                return cursor.fetchone()[0]
    
    def get_total_card_count(self) -> int:
        """총 카드 지급 횟수를 반환합니다."""
        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("SELECT COUNT(*) FROM user_cards")
                return cursor.fetchone()[0]
    
    def get_daily_card_count(self) -> int:
        """오늘(UTC+8 기준) 카드 지급 횟수를 반환합니다."""
        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                # UTC+8 시간대 (CST) 기준으로 오늘 카드 지급 수 계산
                cursor.execute("""
                    SELECT COUNT(*) FROM user_cards 
                    WHERE DATE(acquired_at AT TIME ZONE 'UTC' AT TIME ZONE 'Asia/Shanghai') = CURRENT_DATE AT TIME ZONE 'Asia/Shanghai'
                """)
                return cursor.fetchone()[0]
    
    def get_user_daily_card_count(self, user_id: int) -> int:
        """특정 사용자의 오늘(CST 기준) 카드 획득 수를 반환합니다."""
        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                # CST 시간대 기준으로 오늘 카드 획득 수 계산 (다른 데일리 퀘스트와 동일한 방식)
                today_cst = get_today_cst()
                cursor.execute("""
                    SELECT COUNT(*) FROM user_cards 
                    WHERE user_id = %s 
                    AND DATE(acquired_at AT TIME ZONE 'UTC' AT TIME ZONE 'Asia/Shanghai') = %s
                """, (user_id, today_cst))
                return cursor.fetchone()[0]
    
    def get_abnormal_activity_detection(self) -> dict:
        """이상 상황을 감지합니다."""
        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                # 최근 1시간 내 메시지 수
                cursor.execute("""
                    SELECT COUNT(*) FROM conversations 
                    WHERE message_role = 'user' 
                    AND timestamp > NOW() - INTERVAL '1 hour'
                """)
                recent_messages = cursor.fetchone()[0]
                
                # 최근 1시간 내 호감도 변화가 큰 사용자들
                cursor.execute("""
                    SELECT user_id, character_name, 
                           MAX(score) - MIN(score) as score_change
                    FROM emotion_log 
                    WHERE timestamp > NOW() - INTERVAL '1 hour'
                    GROUP BY user_id, character_name
                    HAVING MAX(score) - MIN(score) > 50
                    ORDER BY score_change DESC
                    LIMIT 5
                """)
                abnormal_affinity = cursor.fetchall()
                
                return {
                    'recent_messages_1h': recent_messages,
                    'abnormal_affinity_users': abnormal_affinity,
                    'is_abnormal': recent_messages > 1000 or len(abnormal_affinity) > 0
                }
    
    def log_admin_give_item(self, admin_id: int, user_id: int, item_type: str, item_id: str, quantity: int, reason: str = ""):
        """관리자가 아이템을 지급한 기록을 로그합니다."""
        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("""
                    INSERT INTO admin_item_logs (admin_id, user_id, item_type, item_id, quantity, reason, created_at)
                    VALUES (%s, %s, %s, %s, %s, %s, NOW())
                """, (admin_id, user_id, item_type, item_id, quantity, reason))
                conn.commit()
    
    def get_admin_item_logs(self, limit: int = 50) -> list:
        """관리자 아이템 지급 로그를 조회합니다."""
        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("""
                    SELECT admin_id, user_id, item_type, item_id, quantity, reason, created_at
                    FROM admin_item_logs
                    ORDER BY created_at DESC
                    LIMIT %s
                """, (limit,))
                return cursor.fetchall()
    
    def get_user_admin_logs(self, user_id: int, limit: int = 20) -> list:
        """특정 사용자의 관리자 지급 로그를 조회합니다."""
        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("""
                    SELECT admin_id, item_type, item_id, quantity, reason, created_at
                    FROM admin_item_logs
                    WHERE user_id = %s
                    ORDER BY created_at DESC
                    LIMIT %s
                """, (user_id, limit))
                return cursor.fetchall()
    
    async def set_user_timezone(self, user_id: int, timezone: str) -> bool:
        """사용자의 시간대를 설정합니다."""
        try:
            with self.get_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute("""
                        INSERT INTO user_settings (user_id, setting_key, setting_value, updated_at)
                        VALUES (%s, 'timezone', %s, NOW())
                        ON CONFLICT (user_id, setting_key)
                        DO UPDATE SET setting_value = %s, updated_at = NOW()
                    """, (user_id, timezone, timezone))
                    conn.commit()
                    return True
        except Exception as e:
            print(f"Error setting user timezone: {e}")
            return False
    
    async def get_user_timezone(self, user_id: int) -> str:
        """사용자의 시간대를 가져옵니다."""
        try:
            with self.get_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute("""
                        SELECT setting_value FROM user_settings
                        WHERE user_id = %s AND setting_key = 'timezone'
                    """, (user_id,))
                    result = cursor.fetchone()
                    return result[0] if result else None
        except Exception as e:
            print(f"Error getting user timezone: {e}")
            return None

    # === 롤플레잉 관련 메서드들 ===
    
    def create_roleplay_session(self, session_id, user_id, character_name, mode, user_role, character_role, story_line):
        """롤플레잉 세션을 생성합니다."""
        try:
            with self.get_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute("""
                        INSERT INTO roleplay_sessions 
                        (session_id, user_id, character_name, mode, user_role, character_role, story_line)
                        VALUES (%s, %s, %s, %s, %s, %s, %s)
                    """, (session_id, user_id, character_name, mode, user_role, character_role, story_line))
                    conn.commit()
                    return True
        except Exception as e:
            print(f"Error creating roleplay session: {e}")
            return False
    
    def get_roleplay_session(self, session_id):
        """롤플레잉 세션 정보를 가져옵니다."""
        try:
            with self.get_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute("""
                        SELECT * FROM roleplay_sessions 
                        WHERE session_id = %s AND is_active = TRUE
                    """, (session_id,))
                    result = cursor.fetchone()
                    if result:
                        return {
                            'id': result[0],
                            'session_id': result[1],
                            'user_id': result[2],
                            'character_name': result[3],
                            'mode': result[4],
                            'user_role': result[5],
                            'character_role': result[6],
                            'story_line': result[7],
                            'message_count': result[8],
                            'max_messages': result[9],
                            'is_active': result[10],
                            'created_at': result[11],
                            'ended_at': result[12]
                        }
                    return None
        except Exception as e:
            print(f"Error getting roleplay session: {e}")
            return None
    
    def update_roleplay_message_count(self, session_id, message_count):
        """롤플레잉 세션의 메시지 카운트를 업데이트합니다."""
        try:
            with self.get_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute("""
                        UPDATE roleplay_sessions 
                        SET message_count = %s 
                        WHERE session_id = %s
                    """, (message_count, session_id))
                    conn.commit()
                    return True
        except Exception as e:
            print(f"Error updating roleplay message count: {e}")
            return False
    
    def end_roleplay_session(self, session_id):
        """롤플레잉 세션을 종료합니다."""
        try:
            with self.get_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute("""
                        UPDATE roleplay_sessions 
                        SET is_active = FALSE, ended_at = NOW() 
                        WHERE session_id = %s
                    """, (session_id,))
                    conn.commit()
                    return True
        except Exception as e:
            print(f"Error ending roleplay session: {e}")
            return False
    
    def save_roleplay_message(self, session_id, user_message, character_response, message_count):
        """롤플레잉 대화를 저장합니다."""
        try:
            with self.get_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute("""
                        INSERT INTO roleplay_history 
                        (session_id, user_message, character_response, message_count)
                        VALUES (%s, %s, %s, %s)
                    """, (session_id, user_message, character_response, message_count))
                    conn.commit()
                    return True
        except Exception as e:
            print(f"Error saving roleplay message: {e}")
            return False
    
    def get_roleplay_history(self, session_id, limit=50):
        """롤플레잉 대화 히스토리를 가져옵니다."""
        try:
            with self.get_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute("""
                        SELECT user_message, character_response, message_count, created_at
                        FROM roleplay_history 
                        WHERE session_id = %s 
                        ORDER BY created_at DESC 
                        LIMIT %s
                    """, (session_id, limit))
                    results = cursor.fetchall()
                    return [{
                        'user_message': row[0],
                        'character_response': row[1],
                        'message_count': row[2],
                        'created_at': row[3]
                    } for row in results]
        except Exception as e:
            print(f"Error getting roleplay history: {e}")
            return []
    