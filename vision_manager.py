import os
import base64
from openai import AsyncOpenAI
from typing import Optional, Dict

BOT_TOKENS = {
    "kagari": os.getenv("KAGARI_TOKEN"),
    "eros": os.getenv("EROS_TOKEN"),
    "elysia": os.getenv("ELYSIA_TOKEN"),
    "selector": os.getenv("SELECTOR_TOKEN"),
}

class VisionManager:
    def __init__(self, api_key: str):
        self.client = AsyncOpenAI(api_key=api_key)

    async def analyze_image(self, attachment, prompt: str = None, character_name: str = "selector") -> dict:
        """
        attachment: discord.Attachment 객체 (이미지 첨부파일)
        prompt: 분석 프롬프트
        character_name: 캐릭터명
        """
        try:
            print("[VisionManager] analyze_image called")
            print(f"[VisionManager] attachment type: {type(attachment)}")
            image_bytes = await attachment.read()
            print(f"[VisionManager] image_bytes length: {len(image_bytes)}")
            content_type = getattr(attachment, 'content_type', None) or "image/jpeg"
            print(f"[VisionManager] content_type: {content_type}")
            image_data = base64.b64encode(image_bytes).decode('utf-8')
            image_url_base64 = f"data:{content_type};base64,{image_data}"
            prompt_text = prompt or "Describe this image in detail."
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
            import traceback
            traceback.print_exc()
            return {"error": str(e), "success": False}

    def generate_character_response(self, image_analysis: Dict, character_name: str, emotion_score: float) -> str:
        if not image_analysis.get("success"):
            return "Sorry, I couldn't analyze the image…"
        description = image_analysis["description"]

        # Character-specific style templates (English)
        styles = {
            "kagari": {
                "high": f"(smiling shyly) This is a wonderful photo! {description} I really like this kind of atmosphere. (smile)",
                "medium": f"(looking quietly) {description} It's quite an interesting picture. What do you think?",
                "low": f"(tilting head) {description} Could you tell me more about this photo?"
            },
            "eros": {
                "high": f"(playfully) Oh~ This picture is really charming! {description} What part do you like the most?",
                "medium": f"(with interest) {description} That's an interesting choice! Why did you pick this one?",
                "low": f"(curious look) {description} What stands out to you in this image?"
            },
            "elysia": {
                "high": f"(in awe) This is such a mysterious photo… {description} What kind of feelings does it give you?",
                "medium": f"(gentle smile) {description} There's something captivating about it. What are your thoughts?",
                "low": f"(thoughtful) {description} Is there anything special you feel from this image?"
            }
        }

        # 감정 점수(친밀도)에 따라 스타일 선택
        if emotion_score >= 0.7:
            level = "high"
        elif emotion_score >= 0.3:
            level = "medium"
        else:
            level = "low"

        char = character_name.lower()
        if char in styles:
            return styles[char][level]
        else:
            return f"{description}\n(이 이미지에 대해 어떻게 생각하시나요?)" 