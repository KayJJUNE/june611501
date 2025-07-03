import re
import json
from typing import List, Dict, Tuple, Optional
from datetime import datetime
import psycopg2
from config import DATABASE_URL

class KeywordManager:
    def __init__(self):
        self.keyword_patterns = {
            'hobby': {
                'ko': [r'취미[는\s가]?\s*([^\.\?\!]+)', r'좋아하는\s*것[은\s가]?\s*([^\.\?\!]+)', r'즐겨하는\s*것[은\s가]?\s*([^\.\?\!]+)'],
                'en': [r'hobby[:\s]*([^\.\?\!]+)', r'like\s+to\s+([^\.\?\!]+)', r'enjoy\s+([^\.\?\!]+)', r'love\s+([^\.\?\!]+)'],
                'zh': [r'爱好[是\s]*([^\.\?\!]+)', r'喜欢[的\s]*([^\.\?\!]+)', r'享受[的\s]*([^\.\?\!]+)'],
                'ja': [r'趣味[は\s]*([^\.\?\!]+)', r'好き[な\s]*([^\.\?\!]+)', r'楽しむ[の\s]*([^\.\?\!]+)']
            },
            'food': {
                'ko': [r'좋아하는\s*음식[은\s가]?\s*([^\.\?\!]+)', r'먹고\s*싶은\s*것[은\s가]?\s*([^\.\?\!]+)', r'선호하는\s*음식[은\s가]?\s*([^\.\?\!]+)'],
                'en': [r'favorite\s+food[:\s]*([^\.\?\!]+)', r'like\s+to\s+eat\s+([^\.\?\!]+)', r'prefer\s+([^\.\?\!]+)'],
                'zh': [r'喜欢[的\s]*食物[是\s]*([^\.\?\!]+)', r'爱吃[的\s]*([^\.\?\!]+)', r'偏好[的\s]*([^\.\?\!]+)'],
                'ja': [r'好き[な\s]*食べ物[は\s]*([^\.\?\!]+)', r'食べたい[もの\s]*([^\.\?\!]+)', r'好む[の\s]*([^\.\?\!]+)']
            },
            'family': {
                'ko': [r'가족[은\s가]?\s*([^\.\?\!]+)', r'부모[는\s가]?\s*([^\.\?\!]+)', r'형제[는\s가]?\s*([^\.\?\!]+)', r'자매[는\s가]?\s*([^\.\?\!]+)'],
                'en': [r'family[:\s]*([^\.\?\!]+)', r'parents[:\s]*([^\.\?\!]+)', r'brother[:\s]*([^\.\?\!]+)', r'sister[:\s]*([^\.\?\!]+)'],
                'zh': [r'家庭[是\s]*([^\.\?\!]+)', r'父母[是\s]*([^\.\?\!]+)', r'兄弟[是\s]*([^\.\?\!]+)', r'姐妹[是\s]*([^\.\?\!]+)'],
                'ja': [r'家族[は\s]*([^\.\?\!]+)', r'両親[は\s]*([^\.\?\!]+)', r'兄弟[は\s]*([^\.\?\!]+)', r'姉妹[は\s]*([^\.\?\!]+)']
            },
            'date': {
                'ko': [r'생일[은\s가]?\s*([^\.\?\!]+)', r'기념일[은\s가]?\s*([^\.\?\!]+)', r'(\d{1,2}월\s*\d{1,2}일)', r'(\d{4}년\s*\d{1,2}월\s*\d{1,2}일)'],
                'en': [r'birthday[:\s]*([^\.\?\!]+)', r'anniversary[:\s]*([^\.\?\!]+)', r'(\w+\s+\d{1,2})', r'(\d{1,2}/\d{1,2})'],
                'zh': [r'生日[是\s]*([^\.\?\!]+)', r'纪念日[是\s]*([^\.\?\!]+)', r'(\d{1,2}月\s*\d{1,2}日)', r'(\d{4}年\s*\d{1,2}月\s*\d{1,2}日)'],
                'ja': [r'誕生日[は\s]*([^\.\?\!]+)', r'記念日[は\s]*([^\.\?\!]+)', r'(\d{1,2}月\s*\d{1,2}日)', r'(\d{4}年\s*\d{1,2}月\s*\d{1,2}日)']
            },
            'work': {
                'ko': [r'직업[은\s가]?\s*([^\.\?\!]+)', r'일[은\s가]?\s*([^\.\?\!]+)', r'학생[은\s가]?\s*([^\.\?\!]+)', r'회사[는\s가]?\s*([^\.\?\!]+)'],
                'en': [r'job[:\s]*([^\.\?\!]+)', r'work[:\s]*([^\.\?\!]+)', r'student[:\s]*([^\.\?\!]+)', r'company[:\s]*([^\.\?\!]+)'],
                'zh': [r'职业[是\s]*([^\.\?\!]+)', r'工作[是\s]*([^\.\?\!]+)', r'学生[是\s]*([^\.\?\!]+)', r'公司[是\s]*([^\.\?\!]+)'],
                'ja': [r'職業[は\s]*([^\.\?\!]+)', r'仕事[は\s]*([^\.\?\!]+)', r'学生[は\s]*([^\.\?\!]+)', r'会社[は\s]*([^\.\?\!]+)']
            },
            'location': {
                'ko': [r'사는\s*곳[은\s가]?\s*([^\.\?\!]+)', r'거주지[는\s가]?\s*([^\.\?\!]+)', r'고향[은\s가]?\s*([^\.\?\!]+)'],
                'en': [r'live[:\s]*([^\.\?\!]+)', r'from[:\s]*([^\.\?\!]+)', r'hometown[:\s]*([^\.\?\!]+)'],
                'zh': [r'住在[的\s]*地方[是\s]*([^\.\?\!]+)', r'来自[的\s]*([^\.\?\!]+)', r'家乡[是\s]*([^\.\?\!]+)'],
                'ja': [r'住んで[いる\s]*ところ[は\s]*([^\.\?\!]+)', r'出身[は\s]*([^\.\?\!]+)', r'故郷[は\s]*([^\.\?\!]+)']
            }
        }

    def detect_language(self, text: str) -> str:
        """텍스트의 언어를 감지합니다."""
        # 간단한 언어 감지 (더 정교한 감지가 필요하면 langdetect 라이브러리 사용)
        if re.search(r'[가-힣]', text):
            return 'ko'
        elif re.search(r'[一-龯]', text):
            return 'zh'
        elif re.search(r'[あ-んア-ン]', text):
            return 'ja'
        else:
            return 'en'

    def extract_keywords(self, text: str) -> List[Dict]:
        """텍스트에서 키워드를 추출합니다."""
        keywords = []
        language = self.detect_language(text)
        
        for keyword_type, patterns in self.keyword_patterns.items():
            if language in patterns:
                for pattern in patterns[language]:
                    matches = re.finditer(pattern, text, re.IGNORECASE)
                    for match in matches:
                        value = match.group(1).strip()
                        if len(value) > 1 and len(value) < 100:  # 너무 짧거나 긴 것은 제외
                            keywords.append({
                                'type': keyword_type,
                                'value': value,
                                'language': language,
                                'context': text[:200]  # 컨텍스트는 처음 200자만
                            })
        
        return keywords

    def save_keywords(self, user_id: int, character_name: str, keywords: List[Dict]) -> bool:
        """키워드를 데이터베이스에 저장합니다."""
        try:
            with psycopg2.connect(DATABASE_URL) as conn:
                with conn.cursor() as cursor:
                    for keyword in keywords:
                        # 기존 키워드가 있는지 확인
                        cursor.execute('''
                            SELECT id, confidence_score FROM user_keywords 
                            WHERE user_id = %s AND character_name = %s AND keyword_type = %s AND keyword_value = %s
                        ''', (user_id, character_name, keyword['type'], keyword['value']))
                        
                        existing = cursor.fetchone()
                        
                        if existing:
                            # 기존 키워드가 있으면 신뢰도 점수 증가
                            new_confidence = min(existing[1] + 0.5, 5.0)  # 최대 5.0
                            cursor.execute('''
                                UPDATE user_keywords 
                                SET confidence_score = %s, updated_at = CURRENT_TIMESTAMP
                                WHERE id = %s
                            ''', (new_confidence, existing[0]))
                        else:
                            # 새로운 키워드 추가
                            cursor.execute('''
                                INSERT INTO user_keywords 
                                (user_id, character_name, keyword_type, keyword_value, context, language)
                                VALUES (%s, %s, %s, %s, %s, %s)
                            ''', (user_id, character_name, keyword['type'], keyword['value'], 
                                  keyword['context'], keyword['language']))
                    
                    conn.commit()
                    return True
        except Exception as e:
            print(f"Error saving keywords: {e}")
            return False

    def get_user_keywords(self, user_id: int, character_name: str, keyword_type: str = None) -> List[Dict]:
        """사용자의 키워드를 조회합니다."""
        try:
            with psycopg2.connect(DATABASE_URL) as conn:
                with conn.cursor() as cursor:
                    if keyword_type:
                        cursor.execute('''
                            SELECT keyword_type, keyword_value, context, confidence_score, language, created_at
                            FROM user_keywords
                            WHERE user_id = %s AND character_name = %s AND keyword_type = %s
                            ORDER BY confidence_score DESC, created_at DESC
                        ''', (user_id, character_name, keyword_type))
                    else:
                        cursor.execute('''
                            SELECT keyword_type, keyword_value, context, confidence_score, language, created_at
                            FROM user_keywords
                            WHERE user_id = %s AND character_name = %s
                            ORDER BY confidence_score DESC, created_at DESC
                        ''', (user_id, character_name))
                    
                    results = cursor.fetchall()
                    return [
                        {
                            'type': row[0],
                            'value': row[1],
                            'context': row[2],
                            'confidence': row[3],
                            'language': row[4],
                            'created_at': row[5]
                        }
                        for row in results
                    ]
        except Exception as e:
            print(f"Error getting user keywords: {e}")
            return []

    def format_keywords_for_context(self, user_id: int, character_name: str) -> str:
        """키워드를 대화 컨텍스트용으로 포맷팅합니다."""
        keywords = self.get_user_keywords(user_id, character_name)
        if not keywords:
            return ""
        
        # 타입별로 그룹화
        grouped = {}
        for keyword in keywords:
            if keyword['type'] not in grouped:
                grouped[keyword['type']] = []
            grouped[keyword['type']].append(keyword)
        
        # 컨텍스트 문자열 생성
        context_parts = []
        type_names = {
            'hobby': '취미',
            'food': '음식',
            'family': '가족',
            'date': '중요한 날짜',
            'relationship': '관계',
            'preference': '선호도',
            'work': '직업/학업',
            'location': '위치'
        }
        
        for keyword_type, keyword_list in grouped.items():
            if keyword_list:
                type_name = type_names.get(keyword_type, keyword_type)
                values = [k['value'] for k in keyword_list[:3]]  # 최대 3개만
                context_parts.append(f"{type_name}: {', '.join(values)}")
        
        if context_parts:
            return "사용자 정보: " + "; ".join(context_parts)
        return ""

    def get_keyword_suggestions(self, user_id: int, character_name: str) -> List[str]:
        """캐릭터가 물어볼 수 있는 키워드 제안을 반환합니다."""
        existing_keywords = self.get_user_keywords(user_id, character_name)
        existing_types = set(k['type'] for k in existing_keywords)
        
        # 아직 수집되지 않은 키워드 타입들
        missing_types = []
        for keyword_type in ['hobby', 'food', 'family', 'work', 'location']:
            if keyword_type not in existing_types:
                missing_types.append(keyword_type)
        
        # 질문 제안
        suggestions = {
            'hobby': [
                '취미가 뭐예요?',
                'What do you like to do in your free time?',
                '你的爱好是什么？',
                '趣味は何ですか？'
            ],
            'food': [
                '좋아하는 음식이 뭐예요?',
                'What\'s your favorite food?',
                '你喜欢吃什么？',
                '好きな食べ物は何ですか？'
            ],
            'family': [
                '가족에 대해 이야기해주세요.',
                'Tell me about your family.',
                '说说你的家人吧。',
                '家族について教えてください。'
            ],
            'work': [
                '직업이 뭐예요?',
                'What do you do for work?',
                '你做什么工作？',
                'お仕事は何ですか？'
            ],
            'location': [
                '어디에 살고 계세요?',
                'Where do you live?',
                '你住在哪里？',
                'どこに住んでいますか？'
            ]
        }
        
        return [suggestions[type_name][0] for type_name in missing_types[:2]]  # 최대 2개 제안 