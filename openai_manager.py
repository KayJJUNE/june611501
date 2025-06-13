     # openai_manager.py
import openai
import re
import asyncio

client = openai.AsyncOpenAI()

async def call_openai(prompt, model="gpt-4o"):
    try:
        response = await client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7,
            max_tokens=150
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        print(f"[OpenAI Error] {e}")
        return "[score:0]"  # 기본값 반환

async def analyze_emotion_with_gpt(message: str) -> int:
    prompt = (
        f"Classify the following user message as Positive (+1), Neutral (0), or Negative (-1):\n"
        f"User: \"{message}\"\n"
        "Reply ONLY with [score:+1], [score:0], or [score:-1]."
    )
    ai_reply = await call_openai(prompt)
    match = re.search(r"\[score:([+-]?\d+)\]", ai_reply)
    try:
        return int(match.group(1)) if match else 0
    except Exception:
        return 0

def analyze_emotion_with_patterns(message: str) -> int:
    positive_keywords = ["Praise", "Empathy", "Consideration", "Interest in character's story or feelings", " Sharing own thoughts or concern", "Long-form replies", "Consultation", "Sharing"]
    negative_keywords = ["Abusive", "Rude", "Unhealthy", "Inappropriate", "Dismissive", "Irritated""Too Short or Passive"]
    if any(word in message for word in positive_keywords):
        return 1
    if any(word in message for word in negative_keywords):
        return -1
    if len(message.strip()) <= 5:
        return 0
    return 0

async def analyze_emotion_with_gpt_and_pattern(message: str) -> int:
    gpt_score = await analyze_emotion_with_gpt(message)
    pattern_score = analyze_emotion_with_patterns(message)
    final_score = round(gpt_score * 0.7 + pattern_score * 0.3)
    return final_score

async def get_roleplay_response(self, character_name: str, messages: list, roleplay_settings: dict) -> str:
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
                response = await self.client.chat.completions.create(
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