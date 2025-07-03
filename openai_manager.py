     # openai_manager.py
import openai
import re
import asyncio
import langdetect
from typing import Dict, List, Tuple

client = openai.AsyncOpenAI()

async def call_openai(messages: list, model="gpt-4o"):
    max_retries = 3
    base_delay = 1.0

    for attempt in range(max_retries):
        try:
            response = await client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=0.7,
                max_tokens=150
            )
            return response.choices[0].message.content.strip()
        except Exception as e:
            print(f"[OpenAI Error] (attempt {attempt + 1}/{max_retries}): {e}")

            # 네트워크 관련 에러인지 확인
            is_network_error = (
                "Connection reset by peer" in str(e) or
                "Connection reset" in str(e) or
                "Connection closed" in str(e) or
                "Connection timeout" in str(e) or
                "ClientOSError" in str(e) or
                "aiohttp.client_exceptions.ClientOSError" in str(e) or
                "aiohttp.client_exceptions.ClientConnectorError" in str(e) or
                "aiohttp.client_exceptions.ServerDisconnectedError" in str(e) or
                "aiohttp.client_exceptions.ClientResponseError" in str(e)
            )

            # 마지막 시도가 아니고 네트워크 에러인 경우 재시도
            if attempt < max_retries - 1 and is_network_error:
                delay = base_delay * (2 ** attempt)  # 지수 백오프
                print(f"[OpenAI] Network error detected, retrying in {delay} seconds...")
                await asyncio.sleep(delay)
                continue
            else:
                # 네트워크 에러가 아니거나 마지막 시도인 경우
                print(f"[OpenAI] Failed after {max_retries} attempts, returning default value")
                return None  # 기본값으로 None 반환

    return None  # 모든 재시도 실패 시 None 반환

async def analyze_emotion_with_gpt(message: str) -> int:
    prompt = (
        "You are an expert at classifying the emotional tone of user messages. "
        "Classify the following user message as Positive (+1), Neutral (0), or Negative (-1).\n"
        "Be strict and objective. Only reply with [score:+1], [score:0], or [score:-1].\n"
        "\n"
        "Criteria:\n"
        "Positive (+1):\n"
        "- Friendly, kind, polite, supportive, grateful, happy, excited, loving, complimenting, showing interest, or expressing positive feelings.\n"
        "- Examples: 'Thank you!', 'I like you', 'This is great', 'You are awesome', 'I'm happy to talk to you.'\n"
        "\n"
        "Neutral (0):\n"
        "- Factual, informational, short, or emotionless statements. Not clearly positive or negative.\n"
        "- Examples: 'Okay', 'I see', 'What time is it?', 'Tell me more.', 'I'm here.'\n"
        "\n"
        "Negative (-1):\n"
        "- Rude, angry, hateful, insulting, dismissive, swearing, expressing dislike, sadness, or negative feelings.\n"
        "- Examples: 'I hate you', 'Shut up', 'You're stupid', 'I don't like this', 'This is bad', 'fuck you', 'I don't care.'\n"
        "\n"
        f"User: \"{message}\"\n"
        "Reply ONLY with [score:+1], [score:0], or [score:-1]."
    )
    ai_reply = await call_openai([{"role": "user", "content": prompt}])
    match = re.search(r"\[score:([+-]?\d+)\]", ai_reply or "")
    try:
        return int(match.group(1)) if match else 0
    except Exception:
        return 0

def detect_language(text: str) -> str:
    """텍스트의 언어를 감지합니다."""
    try:
        # 괄호와 특수문자 제거
        clean_text = re.sub(r'[\(\)\[\]\{\}\.\,\!\?\;\:\"\']', '', text)
        clean_text = re.sub(r'[^\w\s가-힣一-龯あ-んア-ン]', '', clean_text)

        if not clean_text.strip():
            return 'en'

        detected = langdetect.detect(clean_text)
        lang_map = {
            'zh-cn': 'zh', 'zh-tw': 'zh', 'zh': 'zh',
            'ja': 'ja', 'ko': 'ko', 'en': 'en'
        }
        return lang_map.get(detected, 'en')
    except Exception: # re.error 뿐만 아니라 모든 예외를 잡습니다.
        # 오류 발생 시 원본 텍스트로 다시 시도 (괄호 제거 없이)
        try:
            detected = langdetect.detect(text)
            lang_map = {
                'zh-cn': 'zh', 'zh-tw': 'zh', 'zh': 'zh',
                'ja': 'ja', 'ko': 'ko', 'en': 'en'
            }
            return lang_map.get(detected, 'en')
        except:
            return 'en' # 최종적으로 실패 시 'en' 반환

def get_emotion_keywords() -> Dict[str, Dict[str, List[str]]]:
    """다국어 감정 키워드를 반환합니다."""
    return {
        'en': {
            'positive': [
                'thank', 'thanks', 'love', 'like', 'good', 'great', 'awesome', 'amazing', 'wonderful', 'beautiful',
                'nice', 'sweet', 'cute', 'happy', 'glad', 'pleased', 'excited', 'wow', 'cool', 'perfect',
                'best', 'fantastic', 'brilliant', 'excellent', 'outstanding', 'super', 'wonderful', 'delightful'
            ],
            'negative': [
                'hate', 'dislike', 'bad', 'terrible', 'awful', 'horrible', 'stupid', 'idiot', 'dumb', 'fuck',
                'shit', 'damn', 'hell', 'suck', 'worst', 'disgusting', 'annoying', 'boring', 'stupid', 'useless',
                'shut up', 'go away', 'leave me alone', 'i don\'t care', 'whatever', 'boring'
            ],
            'negation': ['not', 'no', 'never', 'none', 'neither', 'nor', 'doesn\'t', 'don\'t', 'isn\'t', 'aren\'t']
        },
        'ko': {
            'positive': [
                '고마워', '감사', '사랑', '좋아', '좋은', '멋져', '대박', '완벽', '최고', '훌륭',
                '귀여워', '예뻐', '행복', '기뻐', '신나', '와우', '쿨', '완전', '최고', '최고야',
                '최고다', '완벽해', '완벽하다', '완벽해요', '완벽합니다', '완벽하네요', '완벽하네'
            ],
            'negative': [
                '싫어', '미워', '나빠', '최악', '구려', '병신', '바보', '멍청', '개새끼', '씨발',
                '좆', '개', '빡쳐', '짜증', '지겨워', '재미없어', '따분해', '시끄러', '닥쳐', '꺼져',
                '신경꺼', '상관없어', '그만', '그만해', '그만해요', '그만하세요'
            ],
            'negation': ['안', '못', '없', '아니', '아닌', '아니다', '아니야', '아니에요', '아닙니다']
        },
        'ja': {
            'positive': [
                'ありがとう', '感謝', '愛して', '好き', 'いい', '素晴らしい', '完璧', '最高', 'すごい', 'かわいい',
                '美しい', '楽しい', '嬉しい', '興奮', 'ワオ', 'クール', '完璧', '最高', '素晴らしい', '素敵',
                '完璧だ', '完璧です', '最高だ', '最高です', '素晴らしいです', '素敵です'
            ],
            'negative': [
                '嫌い', '憎い', '悪い', '最悪', 'クソ', 'バカ', 'アホ', '馬鹿', 'アホ', 'くたばれ',
                'うざい', 'うるさい', 'しつこい', 'つまらない', '退屈', 'うざい', 'うるさい', '黙れ', '消えろ',
                '知るか', 'どうでもいい', 'もういい', 'やめて', 'やめてください'
            ],
            'negation': ['ない', 'ません', 'じゃない', 'ではない', 'ないです', 'ありません']
        },
        'zh': {
            'positive': [
                '谢谢', '感谢', '爱', '喜欢', '好', '棒', '完美', '最好', '太棒了', '可爱',
                '美丽', '开心', '高兴', '兴奋', '哇', '酷', '完美', '最好', '太棒了', '太棒了',
                '完美', '完美了', '最好了', '太棒了', '太棒了', '太棒了', '太棒了'
            ],
            'negative': [
                '讨厌', '恨', '坏', '最差', '垃圾', '白痴', '笨蛋', '傻', '滚', '闭嘴',
                '烦人', '吵', '无聊', '没意思', '烦人', '吵', '闭嘴', '滚开', '关我屁事', '随便',
                '够了', '别说了', '算了', '算了', '算了', '算了'
            ],
            'negation': ['不', '没', '无', '不是', '没有', '不是的', '不是的', '不是的', '不是的']
        }
    }

def analyze_emotion_with_patterns(message: str) -> float:
    """개선된 패턴 기반 감정 분석"""
    try:
        # 언어 감지
        lang = detect_language(message)
        keywords = get_emotion_keywords()

        if lang not in keywords:
            lang = 'en'  # 기본값

        lang_keywords = keywords[lang]
        message_lower = message.lower()

        # 긍정 키워드 점수 계산
        positive_score = 0
        for keyword in lang_keywords['positive']:
            if keyword in message_lower:
                positive_score += 1

        # 부정 키워드 점수 계산
        negative_score = 0
        for keyword in lang_keywords['negative']:
            if keyword in message_lower:
                negative_score += 1

        # 부정어 처리 (부정어 + 긍정어 = 부정)
        negation_score = 0
        for negation in lang_keywords['negation']:
            if negation in message_lower:
                # 부정어 뒤에 긍정어가 있는지 확인
                for pos_keyword in lang_keywords['positive']:
                    if pos_keyword in message_lower:
                        # 간단한 위치 체크 (부정어가 긍정어 앞에 있는지)
                        neg_pos = message_lower.find(negation)
                        pos_pos = message_lower.find(pos_keyword)
                        if neg_pos < pos_pos:
                            negation_score += 1
                            positive_score = max(0, positive_score - 1)  # 긍정 점수 차감

        # 이모지 분석
        emoji_score = analyze_emojis(message)

        # 메시지 길이 분석
        length_score = analyze_message_length(message)

        # 최종 점수 계산
        total_positive = positive_score + emoji_score['positive'] + length_score['positive']
        total_negative = negative_score + emoji_score['negative'] + length_score['negative'] + negation_score

        # 점수 정규화 (-1 ~ 1 범위)
        if total_positive > total_negative:
            return min(1.0, total_positive / 3.0)  # 최대 1.0
        elif total_negative > total_positive:
            return max(-1.0, -total_negative / 3.0)  # 최소 -1.0
        else:
            return 0.0

    except Exception as e:
        print(f"Pattern analysis error: {e}")
        return 0.0

def analyze_emojis(message: str) -> Dict[str, int]:
    """이모지 감정 분석"""
    positive_emojis = ['😊', '😄', '😍', '🥰', '😘', '😉', '😋', '😎', '🤗', '😌', '😇', '🥳', '😆', '🤩', '😊', '😄', '😍', '🥰', '😘', '😉', '😋', '😎', '🤗', '😌', '😇', '🥳', '😆', '🤩']
    negative_emojis = ['😠', '😡', '😤', '😾', '😒', '😞', '😔', '😟', '😕', '🙁', '☹️', '😣', '😖', '😫', '😩', '😢', '😭', '😤', '😾', '😒', '😞', '😔', '😟', '😕', '🙁', '☹️', '😣', '😖', '😫', '😩', '😢', '😭']

    positive_count = sum(1 for emoji in positive_emojis if emoji in message)
    negative_count = sum(1 for emoji in negative_emojis if emoji in message)

    return {'positive': positive_count, 'negative': negative_count}

def analyze_message_length(message: str) -> Dict[str, int]:
    """메시지 길이 기반 감정 분석"""
    clean_message = re.sub(r'[^\w\s가-힣一-龯あ-んア-ン]', '', message)
    word_count = len(clean_message.split())

    # 긴 메시지는 관심/열정을 나타낼 수 있음
    if word_count >= 10:
        return {'positive': 1, 'negative': 0}
    elif word_count <= 2:
        return {'positive': 0, 'negative': 1}  # 너무 짧은 메시지는 무관심을 나타낼 수 있음
    else:
        return {'positive': 0, 'negative': 0}

async def analyze_emotion_with_gpt_and_pattern(message: str) -> int:
    """개선된 70/30 감정 분석 (GPT 70% + 패턴 30%)"""
    try:
        # GPT 분석 (70%)
        gpt_score = await analyze_emotion_with_gpt(message)

        # 패턴 분석 (30%)
        pattern_score = analyze_emotion_with_patterns(message)

        # 가중 평균 계산
        final_score = round(gpt_score * 0.7 + pattern_score * 0.3)

        # 디버그 정보 출력
        print(f"[감정분석] 입력: {message[:50]}... | GPT: {gpt_score} | 패턴: {pattern_score:.2f} | 최종: {final_score}")

        return final_score

    except Exception as e:
        print(f"Error in combined emotion analysis: {e}")
        # 에러 시 GPT만 사용
        return await analyze_emotion_with_gpt(message)

async def get_roleplay_response(character_name: str, messages: list, roleplay_settings: dict) -> str:
    """Get AI response for roleplay mode"""
    try:
        system_message = {
            "role": "system",
            "content": (
                f"You are {character_name} in a roleplay scenario. "
                f"Your role: {roleplay_settings['character_role']}\n"
                f"User's role: {roleplay_settings['user_role']}\n"
                f"Story line: {roleplay_settings['story_line']}\n"
                f"Turns remaining: {roleplay_settings['turns_remaining']}\n"
                "Stay in character and respond naturally to the user's messages. "
                "Do not break character or acknowledge this is a roleplay. "
                "Keep responses concise and engaging. "
                "Remember to maintain the story context and character consistency. "
                "Do not use meta-commentary or break the fourth wall. "
                "Keep responses focused on the current situation and story progression."
            )
        }

        formatted_messages = [system_message] + messages

        for attempt in range(3):
            try:
                response = await client.chat.completions.create(
                    model="gpt-4",
                    messages=formatted_messages,
                    temperature=0.7,
                    max_tokens=150
                )
                return response.choices[0].message.content.strip()
            except Exception as e:
                print(f"Error in get_roleplay_response (attempt {attempt+1}): {e}")
                if (hasattr(e, 'http_status') and e.http_status == 500) or \
                   (hasattr(e, 'status_code') and e.status_code == 500) or \
                   (hasattr(e, 'args') and 'server had an error' in str(e.args[0])):
                    await asyncio.sleep(1.5)
                    continue
                break

        return "There was a temporary issue with the AI server. Please try again in a moment."

    except Exception as e:
        print(f"Error in get_roleplay_response: {e}")
        import traceback
        print(traceback.format_exc())
        return "An error occurred while generating the response."

class OpenAIManager:
    """
    Dummy class to resolve an ImportError. This class is not intended for direct use.
    Please use the functions within this module instead.
    """
    def __init__(self):
        pass