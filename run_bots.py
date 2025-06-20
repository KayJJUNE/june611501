import os
from dotenv import load_dotenv
import asyncio
from bot_selector import BotSelector
from character_bot import CharacterBot
import discord
from discord.ext import commands
import openai
from discord import app_commands
from typing import Dict, Any
from datetime import datetime
import langdetect
from config import (
    CHARACTER_PROMPTS, 
    OPENAI_API_KEY, 
    CHARACTER_INFO,
    CHARACTER_IMAGES,
    CHARACTER_AFFINITY_SPEECH,
    AFFINITY_LEVELS,
    get_combined_prompt
)
import setuptools
from openai_manager import analyze_emotion_with_gpt_and_pattern
from database_manager import DatabaseManager

# Load environment variables
load_dotenv()

# Get bot tokens from environment variables
SELECTOR_TOKEN = os.getenv('SELECTOR_TOKEN')
KAGARI_TOKEN = os.getenv('KAGARI_TOKEN')
EROS_TOKEN = os.getenv('EROS_TOKEN')
ELYSIA_TOKEN = os.getenv('ELYSIA_TOKEN')

async def run_bot(bot, token):
    try:
        await bot.start(token)
    except Exception as e:
        print(f"Error starting bot: {e}")

async def run_all_bots():
    try:
        # Initialize selector bot
        selector_bot = BotSelector()

        # Create character bots
        character_bots = {
            "Kagari": CharacterBot("Kagari", selector_bot),
            "Eros": CharacterBot("Eros", selector_bot),
            "Elysia": CharacterBot("Elysia", selector_bot)
        }

        # Set character_bots in selector_bot
        selector_bot.character_bots = character_bots

        # Create tasks for all bots
        tasks = [
            run_bot(selector_bot, SELECTOR_TOKEN),
            run_bot(character_bots["Kagari"], KAGARI_TOKEN),
            run_bot(character_bots["Eros"], EROS_TOKEN),
            run_bot(character_bots["Elysia"], ELYSIA_TOKEN)
        ]

        # Run all bots concurrently
        await asyncio.gather(*tasks)

    except Exception as e:
        print(f"Error occurred: {e}")
    finally:
        # Cleanup
        await selector_bot.close()
        for bot in character_bots.values():
            await bot.close()

class CharacterBot(commands.Bot):
    def __init__(self, character_name: str, bot_selector: Any):
        intents = discord.Intents.all()
        super().__init__(
            command_prefix='/',
            intents=intents,
            status=discord.Status.online,
            activity=discord.Game(name=f"Chatting as {character_name}")
        )

        # 기본 속성 초기화
        self.character_name = character_name
        self.active_channels = {}
        self.message_history = {}
        self.db = DatabaseManager()
        self.bot_selector = bot_selector
        self.user_affinity_levels = {}
        self.last_message_time = {}
        self.chat_timers = {}

        # 프롬프트 설정
        base_prompt = CHARACTER_PROMPTS.get(character_name, "")
        self.prompt = base_prompt
        self.character_styles = CHARACTER_AFFINITY_SPEECH.get(character_name, {})

    async def setup_hook(self):
        """봇 초기화 시 호출되는 메소드"""
        print(f"{self.character_name} bot is initializing...")
        try:
            await self.tree.sync()
            print(f"{self.character_name} bot commands synced!")
            self.setup_commands()
        except Exception as e:
            print(f"Error syncing commands: {e}")

    def setup_commands(self):
        """봇 명령어 설정"""
        @self.tree.command(
            name="ranking",
            description="Check character affinity ranking"
        )
        async def ranking_command(interaction: discord.Interaction):
            try:
                rankings = self.db.get_affinity_ranking()
                if not rankings:
                    await interaction.response.send_message("No ranking information yet.")
                    return

                embed = discord.Embed(
                    title=f"💝 {self.character_name} affinity ranking",
                    color=discord.Color.purple()
                )

                for i, (user_id, score) in enumerate(rankings, 1):
                    user = self.get_user(user_id)
                    display_name = user.display_name if user else f"User{user_id}"

                    level = self.get_affinity_grade(score)

                    embed.add_field(
                        name=f"{i}: {display_name}",
                        value=f"Affinity: {score} points (Level: {level})",
                        inline=False
                    )

                await interaction.response.send_message(embed=embed)

            except Exception as e:
                print(f"Error in ranking display: {e}")
                await interaction.response.send_message("Ranking information loading error.")

        @self.tree.command(
            name="affinity",
            description="Check current affinity with the character"
        )
        async def affinity_command(interaction: discord.Interaction):
            try:
                affinity_info = self.db.get_affinity(
                    interaction.user.id, self.character_name)
                emotion_score = affinity_info['emotion_score']
                daily_count = affinity_info['daily_count']

                level = self.get_affinity_grade(emotion_score)

                embed = discord.Embed(
                    title=f"💝 {interaction.user.display_name} User affinity",
                    color=discord.Color.purple()
                )

                embed.add_field(
                    name="Current affinity",
                    value=f"```Score: {emotion_score} points\nLevel: {level}\nToday's conversation: {daily_count} times```",
                    inline=False
                )

                next_level = None
                remaining_score = 0

                if level == "Rookie":
                    next_level = "Iron"
                    remaining_score = AFFINITY_LEVELS["Iron"] - emotion_score
                elif level == "Iron":
                    next_level = "Silver"
                    remaining_score = AFFINITY_LEVELS["Silver"] - emotion_score
                elif level == "Silver":
                    next_level = "Gold"
                    remaining_score = AFFINITY_LEVELS["Gold"] - emotion_score

                if next_level:
                    embed.add_field(
                        name="Next level",
                        value=f"```{next_level} level\n{remaining_score} points left```",
                        inline=False
                    )

                await interaction.response.send_message(embed=embed)

            except Exception as e:
                print(f"Error in affinity display: {e}")
                await interaction.response.send_message("Affinity information loading error.")

    async def add_channel(self, channel_id: int, user_id: int) -> tuple[bool, str]:
        """채널 활성화"""
        try:
            if channel_id in self.active_channels:
                return False, "Already activated channel."

            self.active_channels[channel_id] = {
                "user_id": user_id,
                "history": []
            }
            self.message_history[channel_id] = []
            return True, "Channel activated successfully."

        except Exception as e:
            print(f"Error in add_channel: {e}")
            return False, "Channel activation error."

    def get_intimacy_prompt(self, intimacy_level: int) -> str:
        """친밀도 레벨에 따른 프롬프트 생성"""
        try:
            # 점수에 따라 등급 결정
            if intimacy_level >= AFFINITY_LEVELS["Gold"]:
                affinity_level = "Gold"
            elif intimacy_level >= AFFINITY_LEVELS["Silver"]:
                affinity_level = "Silver"
            elif intimacy_level >= AFFINITY_LEVELS["Iron"]:
                affinity_level = "Iron"
            else:
                affinity_level = "Rookie"

            speech_pattern = CHARACTER_AFFINITY_SPEECH[self.character_name][affinity_level]
            prompt = f"{self.prompt}\n\nCurrent affinity level: {affinity_level}\nTone: {speech_pattern['tone']}"
            return prompt
        except Exception as e:
            print(f"Error in get_intimacy_prompt: {e}")
            return self.prompt

    async def get_ai_response(self, messages: list) -> str:
        """OpenAI API를 통한 응답 생성"""
        try:
            client = openai.AsyncOpenAI()
            response = await client.chat.completions.create(
                model="gpt-4o-mini",
                messages=messages,
                temperature=0.7,
                max_tokens=2000,
                presence_penalty=0.6,
                frequency_penalty=0.3
            )
            return response.choices[0].message.content
        except Exception as e:
            print(f"Error in AI response generation: {e}")
            return "Sorry, an error occurred while generating a response."

    async def send_response_with_intimacy(self, message, response: str, intimacy_level: int):
        """친밀도 레벨에 따른 응답 전송"""
        try:
            async with message.channel.typing():
                await asyncio.sleep(len(response) * 0.05)
                await message.channel.send(response)

                self.db.add_message(
                    message.channel.id,
                    message.author.id,
                    self.character_name,
                    "assistant",
                    response
                )
            return True
        except Exception as e:
            print(f"Error in sending response: {e}")
            await message.channel.send(response)
            return False

    async def on_message(self, message):
        """메시지 수신 시 호출되는 이벤트 핸들러"""
        try:
            if message.author.bot:
                return

            # 이 캐릭터 봇이 관리하는 채널이 아니면 무시
            if message.channel.id not in self.active_channels:
                return

            # 메시지 처리
            channel_id = message.channel.id
            user_id = message.author.id

            # 대화 기록 저장
            self.db.add_message(
                channel_id=channel_id,
                user_id=user_id,
                character_name=self.character_name,
                role="user",
                content=message.content
            )

            # 감정 점수 분석
            score_change = await analyze_emotion_with_gpt_and_pattern(message.content)
            if score_change is None:
                score_change = 0
            self.db.update_affinity(
                user_id,
                self.character_name,
                message.content,
                str(datetime.now()),
                score_change
            )

            # AI 응답 생성
            messages = []

            # emotion_score로 레벨 판별
            affinity_info = self.db.get_affinity(user_id, self.character_name)
            emotion_score = affinity_info['emotion_score']
            level = self.get_affinity_grade(emotion_score)
            tone = self.character_styles[level]["tone"]

            if level in ["Gold", "Silver", "Iron"]:
                recent_messages = self.db.get_recent_messages(
                    channel_id=message.channel.id,
                    limit=30,
                    user_id=message.author.id
                )

                user_name = message.author.display_name
                character_name = self.character_name

                combined_prompt = get_combined_prompt(character_name)

                context_message = {
                    "role": "system",
                    "content": (
                        f"{combined_prompt}\n"
                        f"IMPORTANT: When you talk, use the user's name ({user_name}) naturally and refer to the previous conversation.\n"
                        f"IMPORTANT: Your tone must be as follows: {tone}"
                    )
                }
                messages.append(context_message)
                messages.extend(recent_messages)
            else:
                user_name = message.author.display_name
                character_name = self.character_name

                combined_prompt = get_combined_prompt(character_name)

                context_message = {
                    "role": "system",
                    "content": (
                        f"{combined_prompt}\n"
                        f"IMPORTANT: When you talk, use the user's name ({user_name}) naturally and refer to the previous conversation.\n"
                        f"IMPORTANT: Your tone must be as follows: {tone}"
                    )
                }
                messages.append(context_message)

            # 현재 메시지 추가
            current_message = {"role": "user", "content": message.content}
            messages.append(current_message)

            # 응답 생성 및 전송
            response = await self.get_ai_response(messages)
            await self.send_response_with_intimacy(message, response, emotion_score)

        except Exception as e:
            print(f"Error in message processing: {e}")
            await message.channel.send("Sorry, an error occurred.")

    def get_affinity_grade(self, emotion_score):
        if emotion_score >= AFFINITY_LEVELS["Gold"]:
            return "Gold"
        elif emotion_score >= AFFINITY_LEVELS["Silver"]:
            return "Silver"
        elif emotion_score >= AFFINITY_LEVELS["Iron"]:
            return "Iron"
        else:
            return "Rookie"

async def call_openai(prompt):
    # 실제 OpenAI API 연동 코드로 대체 필요
    return "0"  # 임시로 항상 0 반환

if __name__ == "__main__":
    asyncio.run(run_all_bots())