import os
import base64
from openai import AsyncOpenAI
from typing import Optional, Dict
import openai
from config import CHARACTER_PROMPTS
import aiohttp

BOT_TOKENS = {
    "kagari": os.getenv("KAGARI_TOKEN"),
    "eros": os.getenv("EROS_TOKEN"),
    "elysia": os.getenv("ELYSIA_TOKEN"),
    "selector": os.getenv("SELECTOR_TOKEN"),
}

class VisionManager:
    def __init__(self, api_key: str):
        self.client = AsyncOpenAI(api_key=api_key)

    async def analyze_image(self, attachment_or_url, prompt: str = None, character_name: str = "selector") -> dict:
        """
        attachment_or_url: discord.Attachment 객체 또는 이미지 URL(문자열)
        prompt: 분석 프롬프트
        character_name: 캐릭터명
        """
        try:
            print("[VisionManager] analyze_image called")
            # 1. 첨부파일 또는 URL을 바이트로 읽기
            if hasattr(attachment_or_url, "read"):
                # discord.Attachment 객체
                image_bytes = await attachment_or_url.read()
                content_type = getattr(attachment_or_url, "content_type", None) or "image/jpeg"
            elif isinstance(attachment_or_url, str):
                # URL인 경우
                async with aiohttp.ClientSession() as session:
                    async with session.get(attachment_or_url) as resp:
                        image_bytes = await resp.read()
                        content_type = resp.headers.get("Content-Type", "image/jpeg")
            else:
                raise ValueError("Input must be a discord.Attachment or image URL string.")

            image_data = base64.b64encode(image_bytes).decode('utf-8')
            image_url_base64 = f"data:{content_type};base64,{image_data}"

            # 프롬프트를 간결하게 변경 (2~3문장, 핵심만, 친근하게)
            prompt_text = prompt or "Please describe this image in 2-3 short, friendly sentences. Only mention the most important things you see."
            print("[VisionManager] Calling OpenAI Vision API...")
            response = await self.client.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt_text},
                            {"type": "image_url", "image_url": {"url": image_url_base64}}
                        ]
                    }
                ],
                max_tokens=300
            )
            print(f"[VisionManager] Vision API response: {response.choices[0].message.content}")
            return {
                "description": response.choices[0].message.content,
                "success": True
            }
        except Exception as e:
            print(f"[VisionManager] Error: {e}")
            return {"error": str(e), "success": False}

    async def generate_character_response(self, image_analysis: Dict, character_name: str, emotion_score: float, user_message: str = "") -> str:
        if not image_analysis.get("success"):
            return "Sorry, I couldn't analyze the image…"
        description = image_analysis["description"]

        # 캐릭터 personality 프롬프트 가져오기
        char_prompt = CHARACTER_PROMPTS.get(character_name, "")
        system_prompt = f"You are {character_name}. {char_prompt}"
        user_prompt = (
            f"User said: \"{user_message}\"\n"
            f"Here is the image description: {description}\n"
            f"Please answer as {character_name} would, using your personality, tone, and style, and refer to both the user's message and the image."
        )

        try:
            client = openai.AsyncOpenAI()
            response = await client.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                max_tokens=300
            )
            return response.choices[0].message.content.strip()
        except Exception as e:
            print(f"[VisionManager] Error in generate_character_response: {e}")
            return description + "\n(이 이미지에 대해 어떻게 생각하시나요?)" 