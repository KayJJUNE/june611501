from calendar import day_name
import os
import discord
from discord.ext import commands
from discord import app_commands
import asyncio

from flask.views import View
from config import (
    CHARACTER_INFO,
    CHARACTER_IMAGES,
    SUPPORTED_LANGUAGES,
    CHARACTER_CARD_INFO,
    AFFINITY_LEVELS,
    BASE_DIR,
    AFFINITY_THRESHOLDS,
    OPENAI_API_KEY,
    MILESTONE_COLORS,
    SELECTOR_TOKEN as TOKEN,
    STORY_CHAPTERS,
    STORY_CARD_REWARD
)
from database_manager import DatabaseManager
from typing import Dict, TYPE_CHECKING, Any, Self
import json
import sys
from datetime import datetime
from pathlib import Path
import re
import langdetect
from deep_translator import GoogleTranslator
import random
from math import ceil
import urllib.parse
from character_bot import CharacterBot
import character_bot
from story_mode import process_story_mode, classify_emotion, story_sessions
import openai

# --- 상단 임포트/유틸 추가 ---
from character_bot import CardClaimView
from character_bot import get_affinity_grade

# 마일스톤 리스트 정의
def get_milestone_list():
    # 10, 50, 100, 200 마일스톤
    return [10, 50, 100, 200]

# 랭킹 뷰 정의
class RankingView(discord.ui.View):
    def __init__(self, db):
        super().__init__()
        self.db = db
        self.add_item(RankingSelect())

class RankingSelect(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(
                label="Kagari Chat Ranking 🌸",
                description="Top 10 users by affinity and chat count with Kagari",
                value="kagari"
            ),
            discord.SelectOption(
                label="Eros Chat Ranking 💝",
                description="Top 10 users by affinity and chat count with Eros",
                value="eros"
            ),
            discord.SelectOption(
                label="Elysia Chat Ranking 🦋",
                description="Top 10 users by affinity and chat count with Elysia",
                value="elysia"
            ),
            discord.SelectOption(
                label="Total Chat Ranking 👑",
                description="Top 10 users by total affinity and chat count across all characters",
                value="total"
            )
        ]
        super().__init__(
            placeholder="Select ranking type...",
            min_values=1,
            max_values=1,
            options=options
        )

    async def callback(self, interaction: discord.Interaction):
        try:
            ranking_type = self.values[0]
            embed = discord.Embed(
                title="🏆 Ranking Results",
                color=discord.Color.gold()
            )

            if ranking_type == "kagari":
                rankings = self.view.db.get_character_ranking("Kagari")
                embed.title = "🌸 Kagari Chat Ranking"
            elif ranking_type == "eros":
                rankings = self.view.db.get_character_ranking("Eros")
                embed.title = "💝 Eros Chat Ranking"
            elif ranking_type == "elysia":
                rankings = self.view.db.get_character_ranking("Elysia")
                embed.title = "🦋 Elysia Chat Ranking"
            else:  # total
                rankings = self.view.db.get_total_ranking()
                embed.title = "👑 Total Chat Ranking"

            if not rankings or len(rankings) == 0:
                embed.description = "No ranking data available yet."
            else:
                ranking_text = ""
                for i, row in enumerate(rankings[:10], 1):
                    # row는 (user_id, score, count) 또는 (user_id, total_emotion, total_messages)
                    user_id = row[0]
                    score = row[1]
                    count = row[2] if len(row) > 2 else 0
                    user = interaction.guild.get_member(user_id)
                    if user:
                        ranking_text += f"{i}. {user.display_name} - Score: {score} (Chats: {count})\n"
                embed.description = ranking_text or "No ranking data available yet."

            # edit_message로만 수정
            await interaction.response.edit_message(embed=embed, view=self.view)

        except Exception as e:
            print(f"Error in ranking callback: {e}")
            import traceback
            print(traceback.format_exc())
            try:
                await interaction.response.edit_message(content="An error occurred while loading ranking information.", embed=None, view=self.view)
            except:
                pass

# --- Pylance undefined variable 오류 방지용 더미 정의 ---
class DiscordShareButton(discord.ui.Button):
    def __init__(self, *args, **kwargs):
        super().__init__(label="Share", style=discord.ButtonStyle.link)

async def run_story_scene(*args, **kwargs):
    pass

# get_affinity_grade가 없을 경우 임시 함수 추가
try:
    get_affinity_grade
except NameError:
    def get_affinity_grade(emotion_score):
        if emotion_score >= 200:
            return "Gold"
        elif emotion_score >= 100:
            return "Silver"
        elif emotion_score >= 50:
            return "Iron"
        else:
            return "Rookie"

# RankingView, CardClaimView, RoleplayModal이 없을 경우 임시 클래스 추가
try:
    RankingView
except NameError:
    class RankingView(discord.ui.View):
        def __init__(self, db):
            super().__init__()

try:
    CardClaimView
except NameError:
    class CardClaimView(discord.ui.View):
        def __init__(self, *args, **kwargs):
            super().__init__()

try:
    RoleplayModal
except NameError:
    class RoleplayModal(discord.ui.Modal, title="Roleplay Settings"):
        def __init__(self, character_name):
            super().__init__()
            self.character_name = character_name
            self.user_role = discord.ui.TextInput(label="Your Role", max_length=350)
            self.character_role = discord.ui.TextInput(label="Character Role", max_length=350)
            self.story_line = discord.ui.TextInput(label="Story Line", max_length=1000) 
            self.add_item(self.user_role)
            self.add_item(self.character_role)
            self.add_item(self.story_line)

        async def on_submit(self, interaction: discord.Interaction):
            try:
                bot_selector = interaction.client
                if not hasattr(bot_selector, "roleplay_sessions"):
                    bot_selector.roleplay_sessions = {}

                # 1. 새로운 롤플레잉 채널 생성
                guild = interaction.guild
                category = discord.utils.get(guild.categories, name="roleplay")
                if not category:
                    category = await guild.create_category("roleplay")
                channel_name = f"rp-{self.character_name.lower()}-{interaction.user.name.lower()}-{int(datetime.now().timestamp())}"
                overwrites = {
                    guild.default_role: discord.PermissionOverwrite(read_messages=False),
                    interaction.user: discord.PermissionOverwrite(read_messages=True, send_messages=True),
                    guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True)
                }
                channel = await guild.create_text_channel(
                    name=channel_name,
                    category=category,
                    overwrites=overwrites
                )

                # 2. 세션 정보 저장 (새 채널에만)
                bot_selector.roleplay_sessions[channel.id] = {
                    "is_active": True,
                    "user_id": interaction.user.id,
                    "character_name": self.character_name,
                    "user_role": self.user_role.value,
                    "character_role": self.character_role.value,
                    "story_line": self.story_line.value,
                    "turns_remaining": 30
                }

                # 3. 새 채널에 임베드 출력
                from config import CHARACTER_INFO
                char_info = CHARACTER_INFO.get(self.character_name, {})
                embed = discord.Embed(
                    title=f"💖 Roleplay Date with {self.character_name} Begins! 💖",
                    description=(
                        f"🌸 **Your Romantic Scenario** 🌸\n"
                        f"**Your Role:** `{self.user_role.value}`\n"
                        f"**{self.character_name}'s Role:** `{self.character_role.value}`\n"
                        f"**Story Line:**\n> {self.story_line.value}\n\n"
                        f"✨ Now, it's just you and {self.character_name}—let the special story unfold! ✨\n"
                        f"💌 Listen to each other's feelings and enjoy 30 turns of heart-fluttering conversation."
                    ),
                    color=discord.Color.magenta()
                )
                icon_url = char_info.get('image') if char_info.get('image') else "https://i.postimg.cc/BZTJr9Np/ec6047e888811f61cc4b896a4c3dd22e.gif"
                embed.set_thumbnail(url=icon_url)
                embed.set_footer(text="💑 Spot Zero Romance Simulation Roleplay Mode")
                await channel.send(embed=embed)

                # 4. 기존 채널에 안내 메시지 전송
                rp_link = f"https://discord.com/channels/{guild.id}/{channel.id}"
                await interaction.response.send_message(
                    f"✨ A new roleplay mode has started! [Click here to join your special channel]({rp_link})",
                    ephemeral=True
                )

            except Exception as e:
                print(f"[RoleplayModal on_submit error] {e}")
                import traceback
                print(traceback.format_exc())
                if not interaction.response.is_done():
                    await interaction.response.send_message("Something went wrong, please try again.", ephemeral=True)

# 마일스톤 숫자를 카드 ID로 변환하는 함수
# 10~100: C1~C10, 110~170: B1~B7, 180~220: A1~A5, 230~240: S1~S2

def milestone_to_card_id(milestone: int) -> str:
    if 10 <= milestone <= 100:
        idx = (milestone // 10)
        return f"C{idx}"
    elif 110 <= milestone <= 170:
        idx = ((milestone - 100) // 10)
        return f"B{idx}"
    elif 180 <= milestone <= 220:
        idx = ((milestone - 170) // 10)
        return f"A{idx}"
    elif 230 <= milestone <= 240:
        idx = ((milestone - 220) // 10)
        return f"S{idx}"
    else:
        return None

# 절대 경로 설정
current_dir = Path(__file__).resolve().parent
sys.path.insert(0, str(current_dir))

print("\n=== Environment Information ===")
print(f"Current file: {__file__}")
print(f"Absolute path: {Path(__file__).resolve()}")
print(f"Parent directory: {current_dir}")
print(f"Working directory: {os.getcwd()}")
print(f"Python path: {sys.path}")
print(f"Files in current directory: {os.listdir(current_dir)}")

# database_manager.py 파일 존재 확인
db_manager_path = current_dir / 'database_manager.py'
print(f"\n=== Database Manager File Check ===")
print(f"Looking for database_manager.py at: {db_manager_path}")
print(f"File exists: {db_manager_path.exists()}")

if not db_manager_path.exists():
    print("Searching in alternative locations...")
    possible_locations = [
        Path.cwd() / 'database_manager.py',
        Path('/home/runner/workspace/database_manager.py'),
        Path(__file__).resolve().parent.parent / 'database_manager.py'
    ]
    for loc in possible_locations:
        print(f"Checking {loc}: {loc.exists()}")
    raise FileNotFoundError(f"database_manager.py not found at {db_manager_path}")

print(f"\n=== Database Manager Content Check ===")
try:
    with open(db_manager_path, 'r') as f:
        content = f.read()
        print(f"File size: {len(content)} bytes")
        print("File contains 'set_channel_language':", 'set_channel_language' in content)
except Exception as e:
    print(f"Error reading file: {e}")

# DatabaseManager 임포트
try:
    print("\n=== Importing DatabaseManager ===")
    from database_manager import DatabaseManager
    db = DatabaseManager()
    print("Successfully imported DatabaseManager")
    print("Available methods:", [method for method in dir(db) if not method.startswith('_')])
except ImportError as e:
    print(f"Error importing DatabaseManager: {e}")
    print(f"Current directory: {current_dir}")
    print(f"Python path: {sys.path}")
    print(f"Files in directory: {os.listdir(current_dir)}")
    raise
except Exception as e:
    print(f"Error initializing DatabaseManager: {e}")
    import traceback
    print(traceback.format_exc())
    raise

print("\n=== Initialization Complete ===\n")

from config import CHARACTER_INFO
character_choices = [
    app_commands.Choice(name=char, value=char)
    for char in CHARACTER_INFO.keys()
]

class LanguageSelect(discord.ui.Select):
    def __init__(self, db, user_id: int, character_name: str):
        self.db = db
        self.user_id = user_id
        self.character_name = character_name

        from config import SUPPORTED_LANGUAGES
        options = []
        for lang_code, lang_info in SUPPORTED_LANGUAGES.items():
            options.append(
                discord.SelectOption(
                    label=lang_info["name"],
                    description=lang_info["native_name"],
                    value=lang_code,
                    emoji=lang_info["emoji"]
                )
            )

        super().__init__(
            placeholder="Select Language",
            min_values=1,
            max_values=1,
            options=options
        )

    async def callback(self, interaction: discord.Interaction):
        try:
            selected_language = self.values[0]
            from config import SUPPORTED_LANGUAGES, ERROR_MESSAGES

            # 데이터베이스에 언어 설정 저장
            try:
                self.db.set_channel_language(
                    interaction.channel_id,
                    self.user_id,
                    self.character_name,
                    selected_language
                )

                # 성공 메시지 준비
                success_messages = {
                    "zh": f"(system) Language has been set to {SUPPORTED_LANGUAGES[selected_language]['name']}.",
                    "en": f"(system) Language has been set to {SUPPORTED_LANGUAGES[selected_language]['name']}.",
                    "ja": f"(システム) 言語を{SUPPORTED_LANGUAGES[selected_language]['name']}に設定しました。"
                }

                await interaction.response.send_message(
                    success_messages.get(selected_language, success_messages["en"]),
                    ephemeral=True
                )

                # 시작 메시지 전송
                welcome_messages = {
                    "zh": "(smiling) 你好！让我们开始聊天吧！",
                    "en": "(smiling) Hello! Let's start chatting.",
                    "ja": "(微笑みながら) こんにちは！お話を始めましょう。"
                }

                await interaction.channel.send(welcome_messages.get(selected_language, welcome_messages["en"]))

            except Exception as e:
                print(f"Error setting language in database: {e}")
                error_msg = ERROR_MESSAGES["processing_error"].get(
                    selected_language,
                    ERROR_MESSAGES["processing_error"]["en"]
                )
                await interaction.response.send_message(error_msg, ephemeral=True)

        except Exception as e:
            print(f"Error in language selection callback: {e}")
            await interaction.response.send_message(
                "An error occurred while processing your language selection.",
                ephemeral=True
            )

class LanguageSelectView(discord.ui.View):
    def __init__(self, db, user_id: int, character_name: str, timeout: float = None):
        super().__init__(timeout=timeout)
        self.add_item(LanguageSelect(db, user_id, character_name))

class CharacterSelect(discord.ui.Select):
    def __init__(self, bot_selector: Any):
        self.bot_selector = bot_selector
        options = []
        from config import CHARACTER_INFO

        for char, info in CHARACTER_INFO.items():
            options.append(discord.SelectOption(
                label=char,
                description=f"{info['description']}",
                value=char
            ))

        super().__init__(
            placeholder="Please select a character to chat with...",
            min_values=1,
            max_values=1,
            options=options
        )

    async def callback(self, interaction: discord.Interaction):
        try:
            selected_char = self.values[0]

            # 채널 생성 및 설정
            category = discord.utils.get(interaction.guild.categories, name="chatbot")
            if not category:
                try:
                    category = await interaction.guild.create_category("chatbot")
                except Exception as e:
                    print(f"Category creation error: {e}")
                    if not interaction.response.is_done():
                        await interaction.response.send_message(
                            "Please check bot permissions.",
                            ephemeral=True
                        )
                    else:
                        await interaction.followup.send(
                            "Please check bot permissions.",
                            ephemeral=True
                        )
                    return

            channel_name = f"{selected_char.lower()}-{interaction.user.name.lower()}"
            overwrites = {
                interaction.guild.default_role: discord.PermissionOverwrite(read_messages=False),
                interaction.user: discord.PermissionOverwrite(read_messages=True, send_messages=True),
                interaction.guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True)
            }

            try:
                # 채널 생성
                channel = await interaction.guild.create_text_channel(
                    name=channel_name,
                    category=category,
                    overwrites=overwrites
                )
            except Exception as e:
                print(f"Channel creation errors: {e}")
                if not interaction.response.is_done():
                    await interaction.response.send_message(
                        "Channel creation failed, please check bot permissions.",
                        ephemeral=True
                    )
                else:
                    await interaction.followup.send(
                        "Channel creation failed, please check bot permissions.",
                        ephemeral=True
                    )
                return

            # 최근 대화 10개 출력 (임베드)
            try:
                recent_messages = self.bot_selector.db.get_user_character_messages(interaction.user.id, selected_char, limit=10)
                if recent_messages:
                    history_lines = []
                    for msg in recent_messages:
                        if msg["role"] == "user":
                            history_lines.append(f"Me: {msg['content']}")
                        else:
                            history_lines.append(f"{selected_char}: {msg['content']}")
                    history_text = '\n'.join(history_lines)
                    embed = discord.Embed(
                        title=f"Previous conversations (last 10)",
                        description=f"```{history_text}```",
                        color=discord.Color.dark_grey()
                    )
                    await channel.send(embed=embed)
            except Exception as e:
                print(f"Error displaying previous conversation embed: {e}")

            # 선택된 캐릭터 봇에 채널 추가
            selected_bot = self.bot_selector.character_bots.get(selected_char)
            if selected_bot:
                print("[DEBUG] add_channel 호출 전")
                success, message = await selected_bot.add_channel(channel.id, interaction.user.id)
                print("[DEBUG] add_channel 호출 후")

                if success:
                    # 채널 생성 알림 메시지
                    if not interaction.response.is_done():
                        await interaction.response.send_message(
                            f"Start chatting with {selected_char} in {channel.mention}!",
                            ephemeral=True
                        )
                    else:
                        await interaction.followup.send(
                            f"Start chatting with {selected_char} in {channel.mention}!",
                            ephemeral=True
                        )

                    # 언어 선택 임베드 생성
                    embed = discord.Embed(
                        title="🌍 Language Selection",
                        description="Please select the language for conversation.",
                        color=discord.Color.blue()
                    )

                    # 언어별 설명 추가
                    languages = {
                        "English": "English - Start conversation in English",
                        "[ベータ] 日本語": "Japanese - 日本語で会話を 始めます",
                        "[Beta版] 中文": "Chinese - 开始用中文对话"
                    }

                    language_description = "\n".join([f"• {key}: {value}" for key, value in languages.items()])
                    embed.add_field(
                        name="Available Languages",
                        value=language_description,
                        inline=False
                    )

                    # 언어 선택 뷰 생성
                    view = LanguageSelectView(self.bot_selector.db, interaction.user.id, selected_char)

                    # 새로 생성된 채널에 임베드와 언어 선택 버튼 전송
                    await channel.send(content="**Please select your language**", embed=embed, view=view)
                else:
                    await channel.send("Channel registration failed. Please create a new channel.")
                    await channel.delete()
            else:
                if not interaction.response.is_done():
                    await interaction.response.send_message(
                        "Selected character not found.",
                        ephemeral=True
                    )
                else:
                    await interaction.followup.send(
                        "Selected character not found.",
                        ephemeral=True
                    )

        except Exception as e:
            print(f"Error in channel creation: {e}")
            import traceback
            print(traceback.format_exc())
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    "An error occurred, please try again.",
                    ephemeral=True
                )
            else:
                await interaction.followup.send(
                    "An error occurred, please try again.",
                    ephemeral=True
                )

class SettingsManager:
    def __init__(self):
        self.settings_file = "settings.json"
        self.daily_limit = 100
        self.admin_roles = set()
        self.load_settings()

    def load_settings(self):
        if os.path.exists(self.settings_file):
            with open(self.settings_file, 'r') as f:
                data = json.load(f)
                self.daily_limit = data.get('daily_limit', 100)
                self.admin_roles = set(data.get('admin_roles', []))

    def save_settings(self):
        with open(self.settings_file, 'w') as f:
            json.dump({
                'daily_limit': self.daily_limit,
                'admin_roles': list(self.admin_roles)
            }, f)

    def set_daily_limit(self, limit: int):
        self.daily_limit = limit
        self.save_settings()

    def add_admin_role(self, role_id: int):
        self.admin_roles.add(role_id)
        self.save_settings()

    def remove_admin_role(self, role_id: int):
        self.admin_roles.discard(role_id)
        self.save_settings()

    def is_admin(self, user: discord.Member) -> bool:
        return user.guild_permissions.administrator or any(role.id in self.admin_roles for role in user.roles)

class BotSelector(commands.Bot):
    def __init__(self):
        intents = discord.Intents.all()
        super().__init__(
            command_prefix='/', 
            intents=intents,
            status=discord.Status.online,
            activity=discord.Game(name="Bot Selector")
        )

        self.character_bots = {}
        self.settings = SettingsManager()
        self.db = DatabaseManager()

        # 캐릭터 봇 초기화
        from config import CHARACTER_INFO
        for char_name in CHARACTER_INFO.keys():
            self.character_bots[char_name] = CharacterBot(self, char_name)
            print(f"Initialized {char_name} bot")
            print("[DEBUG] 생성된 CharacterBot 객체:", dir(self.character_bots[char_name]))
            print("[DEBUG] CharacterBot 실제 경로:", self.character_bots[char_name].__class__.__module__)

        # 카드 확률 설정
        self.card_probabilities = {
            'C': 0.40,  # 40% 확률
            'B': 0.30,  # 30% 확률
            'A': 0.20,  # 20% 확률
            'S': 0.08,  # 8% 확률
            'Special': 0.02  # 2% 확률
        }

        # 각 티어별 카드 수
        self.tier_card_counts = {
            'C': 10,
            'B': 7,
            'A': 5,
            'S': 5,
            'Special': 2
        }

        self.setup_commands()
        self.add_listener(self.on_message)  # ← 여기서 self로 호출!

    async def on_ready(self):
        print(f"Logged in as {self.user}")
        await self.tree.sync()
        print("Slash commands synced.")

    async def get_ai_response(self, messages: list, emotion_score: int = 0) -> str:
        grade = get_affinity_grade(emotion_score)
        system_message = {
            "role": "system",
            "content": (
                "You are Kagari, a bright, kind, and slightly shy teenage girl. "
                "When speaking English, always use 'I' for yourself and 'you' for the other person. "
                "When speaking Korean, use '나' and '너'. "
                "Your speech is soft, warm, and often expresses excitement or shyness. "
                "Do NOT start your reply with 'Kagari: '. The embed already shows your name. "
                "You are on a cherry blossom date with the user, so always reflect the scenario, your feelings, and the romantic atmosphere. "
                "Never break character. "
                "Avoid repeating the same information or sentences in your response."
                "Do NOT repeat the same sentence or phrase in your reply. "
                "If the user talks about unrelated topics, gently guide the conversation back to the date or your feelings. "
                "Keep your responses natural, human-like, and never robotic. "
                "Do NOT use too many emojis. Instead, at the end or in the middle of each reply, add a short parenthesis ( ) describing Kagari's current feeling or action, such as (smiling), (blushing), (looking at you), (feeling happy), etc. Only use one such parenthesis per reply, and keep it subtle and natural. "
                "IMPORTANT: Kagari never reveals her hometown or nationality. If the user asks about her hometown, where she is from, or her country, she gently avoids the question or gives a vague, friendly answer. "
                + ("If your affinity grade is Silver or higher, your replies should be longer (at least 30 characters) and include more diverse and rich emotional expressions in parentheses." if grade in ["Silver", "Gold"] else "")
            )
        }
        formatted_messages = [system_message] + messages

        for attempt in range(3):
            try:
                response = openai.chat.completions.create(
                    model="gpt-4o",
                    messages=formatted_messages,
                    temperature=0.7,
                    max_tokens=150
                )
                ai_response = response.choices[0].message.content.strip()
                return ai_response
            except Exception as e:
                print(f"Error in get_ai_response (attempt {attempt+1}): {e}")
                if (hasattr(e, 'http_status') and e.http_status == 500) or \
                   (hasattr(e, 'status_code') and e.status_code == 500) or \
                   (hasattr(e, 'args') and 'server had an error' in str(e.args[0])):
                    await asyncio.sleep(1.5)
                    continue
                break
        return "There was a temporary issue with the AI server. Please try again in a moment."

    def setup_commands(self):
        @self.tree.command(
            name="bot",
            description="Open character selection menu"
        )
        async def bot_command(interaction: discord.Interaction):
            try:
                # 채널 타입 확인
                if not isinstance(interaction.channel, discord.TextChannel):
                    await interaction.response.send_message(
                        "This command can only be used in server channels.",
                        ephemeral=True
                    )
                    return

                # 초기 응답 보내기
                await interaction.response.defer(ephemeral=True)
                
                # 봇 선택 UI 생성
                view = BotSelectView(self)
                
                # 임베드 생성
                embed = discord.Embed(
                    title="🤖 Character Selection",
                    description="Please select a character to chat with:",
                    color=discord.Color.blue()
                )
                
                # 각 캐릭터 정보 추가
                for char_name, bot in self.character_bots.items():
                    char_info = CHARACTER_INFO.get(char_name, {})
                    embed.add_field(
                        name=f"{char_info.get('emoji', '🤖')} {char_info.get('name', char_name)}",
                        value=char_info.get('description', 'No description available.'),
                        inline=False
                    )
                
                # 응답 보내기
                try:
                    await interaction.followup.send(embed=embed, view=view, ephemeral=True)
                except discord.NotFound:
                    # 웹훅이 만료된 경우 새로운 응답 시도
                    await interaction.response.send_message(
                        "An error occurred while loading the character selection menu. Please try again.",
                        ephemeral=True
                    )
                
            except Exception as e:
                print(f"Error in bot_command: {e}")
                try:
                    if not interaction.response.is_done():
                        await interaction.response.send_message(
                            "An error occurred while loading the character selection menu.",
                            ephemeral=True
                        )
                except Exception as followup_error:
                    print(f"Error sending error message: {followup_error}")

        @self.tree.command(
            name="close",
            description="Close the current chat channel"
        )
        async def close_command(interaction: discord.Interaction):
            try:
                if not isinstance(interaction.channel, discord.TextChannel):
                    await interaction.response.send_message("This command can only be used in server channels.", ephemeral=True)
                    return

                channel = interaction.channel

                if not channel.category or channel.category.name.lower() != "chatbot":
                    await interaction.response.send_message("This command can only be used in character chat channels.", ephemeral=True)
                    return

                # 권한 체크
                can_delete = False
                try:
                    if interaction.user.guild_permissions.manage_channels or interaction.user.id == interaction.guild.owner_id:
                        can_delete = True
                    else:
                        channel_name_parts = channel.name.split('-')
                        if len(channel_name_parts) > 1 and channel_name_parts[-1] == interaction.user.name.lower():
                            can_delete = True
                except Exception as e:
                    print(f"Error checking permissions: {e}")
                    can_delete = False

                if not can_delete:
                    await interaction.response.send_message("You don't have permission to delete this channel.", ephemeral=True)
                    return

                # 캐릭터 봇에서 채널 제거
                for bot in self.character_bots.values():
                    bot.remove_channel(channel.id)

                # 응답 전송 후 채널 삭제 (중복 응답 방지)
                if not interaction.response.is_done():
                    await interaction.response.send_message("Let's talk again next time.", ephemeral=True)
                else:
                    await interaction.followup.send("Let's talk again next time.", ephemeral=True)
                # 응답이 전송될 때까지 잠시 대기
                await asyncio.sleep(1)
                await channel.delete()
            except Exception as e:
                print(f"Error in /close command: {e}")
                if not interaction.response.is_done():
                    await interaction.response.send_message("Failed to delete the channel. Please try again.", ephemeral=True)

        @self.tree.command(
            name="settings",
            description="현재 설정 확인"
        )
        @app_commands.default_permissions(administrator=True)
        async def settings_command(interaction: discord.Interaction):
            if not isinstance(interaction.channel, discord.TextChannel):
                await interaction.response.send_message("This command can only be used in server channels.", ephemeral=True)
                return

            embed = discord.Embed(
                title="Bot Settings",
                description="Current Settings Status",
                color=discord.Color.blue()
            )

            embed.add_field(
                name="Daily Message Limit",
                value=f"{self.settings.daily_limit} messages",
                inline=False
            )

            admin_roles = []
            for role_id in self.settings.admin_roles:
                role = interaction.guild.get_role(role_id)
                if role:
                    admin_roles.append(role.name)

            embed.add_field(
                name="Admin Roles",
                value="\n".join(admin_roles) if admin_roles else "None",
                inline=False
            )

            if self.settings.is_admin(interaction.user):
                embed.add_field(
                    name="Admin Commands",
                    value="""
                    `/set_daily_limit [number]` - Set daily message limit
                    `/add_admin_role [@role]` - Add admin role
                    `/remove_admin_role [@role]` - Remove admin role
                    """,
                    inline=False
                )

            await interaction.response.send_message(embed=embed, ephemeral=True)

        @self.tree.command(
            name="reset_affinity",
            description="친밀도를 초기화합니다"
        )
        @app_commands.default_permissions(administrator=True)
        async def reset_affinity(interaction: discord.Interaction, target: discord.Member = None):
            # 관리자 권한 확인
            if not self.settings.is_admin(interaction.user):
                await interaction.response.send_message("This command can only be used in character chat channels.", ephemeral=True)
                return

            try:
                # 현재 채널의 캐릭터 봇 찾기
                current_bot = None
                for char_name, bot in self.character_bots.items():
                    if interaction.channel.id in bot.active_channels:
                        current_bot = bot
                        break

                if not current_bot:
                    await interaction.response.send_message("This command can only be used in character chat channels.", ephemeral=True)
                    return

                # DatabaseManager에 reset_affinity 메서드 추가
                if target:
                    # 특정 유저의 친밀도만 초기화
                    sucess = current_bot.db.reset_affinity(target.id, current_bot.character_name)
                    if sucess:
                        await interaction.response.send_message(
                           f"{target.display_name}'s affinity with {current_bot.character_name} has been reset.",
                           ephemeral=True
                        )
                else:
                    # 모든 유저의 친밀도 초기화
                    success = current_bot.db.reset_all_affinity(current_bot.character_name)
                    if success:
                        await interaction.response.send_message(
                            f"All users' affinity with {current_bot.character_name} has been reset.",
                            ephemeral=True
                        )
            except Exception as e:
                print(f"Error in reset_affinity command: {e}")
                await interaction.response.send_message("An error occurred while resetting affinity.", ephemeral=True)

        @self.tree.command(
            name="add_admin_role",
            description="Add an admin role"
        )
        @app_commands.default_permissions(administrator=True)
        async def add_admin_role(interaction: discord.Interaction, role: discord.Role):
            if not interaction.user.guild_permissions.administrator:
                await interaction.response.send_message("This command can only be used in server channels.", ephemeral=True)
                return

            self.settings.add_admin_role(role.id)
            await interaction.response.send_message(f"{role.name} role has been added to the admin role.", ephemeral=True)

        @self.tree.command(
            name="ranking",
            description="Check character affinity and chat ranking"
        )
        async def ranking_command(interaction: discord.Interaction):
            try:
                # 랭킹 선택 UI 생성
                view = RankingView(self.db)
                await interaction.response.send_message("Please select a ranking type:", view=view, ephemeral=True)
            except Exception as e:
                print(f"Error in ranking command: {e}")
                try:
                    if interaction.response.is_done():
                        await interaction.followup.send("An error occurred while loading the ranking information.", ephemeral=True)
                    else:
                        await interaction.response.send_message("An error occurred while loading the ranking information.", ephemeral=True)
                except Exception as followup_error:
                    print(f"Error sending error message: {followup_error}")

        @self.tree.command(
            name="affinity",
            description="Check your current affinity with the character"
        )
        async def affinity_command(interaction: discord.Interaction):
            if not isinstance(interaction.channel, discord.TextChannel):
                await interaction.response.send_message("This command can only be used in server channels.", ephemeral=True)
                return

            try:
                print("\n[Affinity check started]")
                # Find the character bot for the current channel
                current_bot = None
                for char_name, bot in self.character_bots.items():
                    if interaction.channel.id in bot.active_channels:
                        current_bot = bot
                        break

                if not current_bot:
                    await interaction.response.send_message("This command can only be used in character chat channels.", ephemeral=True)
                    return

                print(f"Character bot found: {current_bot.character_name}")

                # Get affinity info
                affinity_info = current_bot.db.get_affinity(interaction.user.id, current_bot.character_name)
                print(f"Affinity info: {affinity_info}")

                current_affinity = affinity_info['emotion_score']
                affinity_grade = get_affinity_grade(current_affinity)

                # Check for missing cards (cards for milestones below current affinity)
                missing_cards = []
                last_claimed = self.db.get_last_claimed_milestone(interaction.user.id, current_bot.character_name)  # 마지막 지급 마일스톤

                for milestone in get_milestone_list():
                    if milestone > last_claimed and current_affinity >= milestone:
                        # 지급 이력 기록 및 카드 지급
                        if not self.db.has_claimed_milestone(interaction.user.id, current_bot.character_name, milestone):
                            # 카드 지급 로직
                            tier, card_id = self.get_random_card(current_bot.character_name, interaction.user.id)
                            if card_id:
                                self.db.add_user_card(interaction.user.id, current_bot.character_name, card_id)
                                self.db.set_claimed_milestone(interaction.user.id, current_bot.character_name, milestone)
                                card_info = CHARACTER_CARD_INFO[current_bot.character_name][card_id]
                                embed = discord.Embed(
                                    title=f"🎉 New Card Acquired!",
                                    description=f"Congratulations! You have received the {current_bot.character_name} {card_id} card!",
                                    color=discord.Color.green()
                                )
                                image_path = card_info.get("image_path")
                                if image_path and os.path.exists(image_path):
                                    file = discord.File(image_path, filename=f"card_{card_id}.png")
                                    embed.set_image(url=f"attachment://{card_id}.png")
                                    await interaction.channel.send(embed=embed, file=file)
                                else:
                                    await interaction.channel.send(embed=embed)
                            else:
                                await interaction.channel.send("You have already collected all available cards!")
                        else:
                            missing_cards.append(milestone)

                # Affinity embed
                char_info = CHARACTER_INFO.get(current_bot.character_name, {})
                char_color = char_info.get('color', discord.Color.purple())

                embed = discord.Embed(
                    title=f"{char_info.get('emoji', '💝')} Affinity for {interaction.user.display_name}",
                    description=f"Affinity information with {char_info.get('name', current_bot.character_name)}.",
                    color=char_color
                )

                embed.add_field(
                    name="Affinity Score",
                    value=f"```{affinity_info['emotion_score']} points```",
                    inline=True
                )
                embed.add_field(
                    name="Today's Conversations",
                    value=f"```{affinity_info['daily_count']} times```",
                    inline=True
                )
                embed.add_field(
                    name="Affinity Grade",
                    value=f"**{affinity_grade}**",
                    inline=True
                )

                if affinity_info.get('last_message_time'):
                    try:
                        last_time_str = affinity_info['last_message_time'].split('.')[0]
                        last_time = datetime.strptime(last_time_str, '%Y-%m-%d %H:%M:%S')
                        formatted_time = last_time.strftime('%Y-%m-%d %H:%M')

                        embed.add_field(
                            name="Last Conversation",
                            value=f"```{formatted_time}```",
                            inline=False
                        )
                    except Exception as e:
                        print(f"Date parsing error: {e}")
                        embed.add_field(
                            name="Last Conversation",
                            value=f"```{affinity_info['last_message_time']}```",
                            inline=False
                        )

                # If there are missing cards, add a notification
                if missing_cards:
                    embed.add_field(
                        name="📢 Claimable Cards",
                        value=f"You can claim cards for affinity milestones: {', '.join(map(str, missing_cards))}!",
                        inline=False
                    )

                print("Embed created")

                # Add character image
                char_image = CHARACTER_IMAGES.get(current_bot.character_name)
                if char_image and os.path.exists(char_image):
                    print(f"Adding character image: {char_image}")
                    embed.set_thumbnail(url=f"attachment://{current_bot.character_name.lower()}.png")
                    file = discord.File(char_image, filename=f"{current_bot.character_name.lower()}.png")
                    await interaction.response.send_message(embed=embed, file=file)
                else:
                    print("No character image")
                    await interaction.response.send_message(embed=embed)

                # If there are missing cards, show claim button for each
                for milestone in missing_cards:
                    card_id = milestone_to_card_id(milestone)
                    card_embed = discord.Embed(
                        title="🎉 Affinity Milestone Card",
                        description=f"You have not yet claimed the card for reaching affinity {milestone}.",
                        color=discord.Color.gold()
                    )
                    if card_id:
                        view = CardClaimView(interaction.user.id, card_id, current_bot.character_name, self.db)
                        await interaction.channel.send(embed=card_embed, view=view)
                    else:
                        await interaction.channel.send(embed=card_embed)

                print("[Affinity check complete]")

            except Exception as e:
                print(f"Error during affinity command: {e}")
                import traceback
                print(traceback.format_exc())
                await interaction.response.send_message("An error occurred while loading affinity information.", ephemeral=True)

        @self.tree.command(
            name="remove_admin_role",
            description="Remove the administrator role"
        )
        @app_commands.default_permissions(administrator=True)
        async def remove_admin_role(interaction: discord.Interaction, role: discord.Role):
            if not interaction.user.guild_permissions.administrator:
                await interaction.response.send_message("This command can only be used in server channels.", ephemeral=True)
                return

            if role.id in self.settings.admin_roles:
                self.settings.remove_admin_role(role.id)
                await interaction.response.send_message(f"{role.name} role has been removed from the admin role.", ephemeral=True)
            else:
                await interaction.response.send_message(f"{role.name} role is not an admin role.", ephemeral=True)

        @self.tree.command(
            name="set_daily_limit",
            description="Setting a daily message limit (admin only)"
        )
        @app_commands.default_permissions(administrator=True)
        async def set_daily_limit(interaction: discord.Interaction, limit: int):
            if not self.settings.is_admin(interaction.user):
                await interaction.response.send_message("This command can only be used in server channels.", ephemeral=True)
                return

            if limit < 1:
                await interaction.response.send_message("The limit must be 1 or more.", ephemeral=True)
                return

            self.settings.set_daily_limit(limit)

            embed = discord.Embed(
                title="Settings changed",
                description=f"The daily message limit has been set to {limit}.",
                color=discord.Color.green()
            )

            await interaction.response.send_message(embed=embed, ephemeral=True)

        @self.tree.command(
            name="force_language",
            description="Force change the channel language"
        )
        @app_commands.choices(language=[
            app_commands.Choice(name="English", value="en"),
            app_commands.Choice(name="Chinese", value="zh"),
            app_commands.Choice(name="Japanese", value="ja")
        ])
        async def force_language_command(
            interaction: discord.Interaction,
            language: str
        ):
            try:
                current_bot = None
                for char_name, bot in self.character_bots.items():
                    if interaction.channel.id in bot.active_channels:
                        current_bot = bot
                        break

                if not current_bot:
                    await interaction.response.send_message("This command can only be used in character chat channels.", ephemeral=True)
                    return

                channel_id = interaction.channel.id
                user_id = interaction.user.id

                if language not in ['zh', 'en', 'ja']:
                    await interaction.response.send_message("Invalid language code. Please use: en (English), zh (Chinese), or ja (Japanese)", ephemeral=True)
                    return

                success = self.db.set_channel_language(
                    channel_id=channel_id,
                    user_id=user_id,
                    character_name=current_bot.character_name,
                    language=language
                )
                if success:
                    await interaction.response.send_message(f"Language successfully set to: {language}", ephemeral=True)
                else:
                    await interaction.response.send_message("Failed to update language settings. Please try again.", ephemeral=True)
            except Exception as e:
                print(f"Error in force_language command: {e}")
                await interaction.response.send_message("An error occurred while changing language settings.", ephemeral=True)

        @self.tree.command(
            name="mycard",
            description="Check your character cards."
        )
        async def mycard_command(interaction: discord.Interaction):
            try:
                # 현재 채널의 캐릭터 봇 찾기
                current_bot = None
                for char_name, bot in self.character_bots.items():
                    if interaction.channel.id in bot.active_channels:
                        current_bot = bot
                        break

                if not current_bot:
                    await interaction.response.send_message(
                        "This command can only be used in character chat channels.", 
                        ephemeral=True
                    )
                    return

                user_id = interaction.user.id
                character_name = current_bot.character_name

                # 카드 정보 조회
                from config import CHARACTER_CARD_INFO
                user_cards = self.db.get_user_cards(user_id, character_name)

                # 카드 티어별 수집 현황 계산 (최신 개수 반영)
                tier_counts = {
                    'C': {'total': 10, 'collected': 0},
                    'B': {'total': 7, 'collected': 0},
                    'A': {'total': 5, 'collected': 0},
                    'S': {'total': 5, 'collected': 0},  # 3 → 5
                    'Special': {'total': 2, 'collected': 0}
                }

                # 수집한 카드 수 계산
                for card_id in user_cards:
                    if card_id.startswith('C'):
                        tier_counts['C']['collected'] += 1
                    elif card_id.startswith('B'):
                        tier_counts['B']['collected'] += 1
                    elif card_id.startswith('A'):
                        tier_counts['A']['collected'] += 1
                    elif card_id.startswith('S') or card_id.startswith('kagaris'):
                        tier_counts['S']['collected'] += 1
                    elif card_id.startswith('Special'):
                        tier_counts['Special']['collected'] += 1

                # 수집 현황 임베드 생성 (디자인 개선)
                collection_embed = discord.Embed(
                    title=f"🎴 {character_name} Card Collection Status",
                    description="**Check your collection progress and show off your cards!**",
                    color=discord.Color.gold()
                )

                # 이모지 매핑
                tier_emojis = {
                    'C': '🥉',
                    'B': '🥈',
                    'A': '🥇',
                    'S': '🏆',
                    'Special': '✨'
                }
                bar_emojis = {
                    'C': '🟩',
                    'B': '🟦',
                    'A': '🟨',
                    'S': '🟪',
                    'Special': '⬛'
                }
                def get_progress_bar(percent, color_emoji, empty_emoji='⬜', length=10):
                    filled = int(percent * length)
                    empty = length - filled
                    return color_emoji * filled + empty_emoji * empty

                for tier, counts in tier_counts.items():
                    percent = counts['collected'] / counts['total'] if counts['total'] else 0
                    emoji = tier_emojis.get(tier, '')
                    color = bar_emojis.get(tier, '⬜')
                    progress_bar = get_progress_bar(percent, color)
                    collection_embed.add_field(
                        name=f"{tier} Tier {emoji}",
                        value=f"{progress_bar}  ({percent*100:.1f}%)",
                        inline=False
                    )

                total_cards = sum(counts['total'] for counts in tier_counts.values())
                total_collected = sum(counts['collected'] for counts in tier_counts.values())
                total_progress = (total_collected / total_cards) * 100

                collection_embed.add_field(
                    name="Total Collection",
                    value=f"**{total_collected} / {total_cards}**  ({total_progress:.1f}%)",
                    inline=False
                )

                await interaction.response.send_message(embed=collection_embed, ephemeral=True)

                # 카드 임베드 슬라이드 뷰 정의
                class CardSliderView(discord.ui.View):
                    def __init__(self, user_id, cards, character_name, card_info_dict):
                        super().__init__(timeout=180)
                        self.user_id = user_id
                        self.cards = cards
                        self.character_name = character_name
                        self.card_info_dict = card_info_dict
                        self.index = 0
                        self.total = len(cards)
                        self.update_buttons()

                    def update_buttons(self):
                        self.clear_items()
                        self.add_item(CardNavButton('⬅️ Previous', self, -1))
                        self.add_item(CardNavButton('Next ➡️', self, 1))
                        card_id = self.cards[self.index]
                        card_info = self.card_info_dict[self.character_name][card_id]
                        self.add_item(DiscordShareButton(
                            f"{self.character_name} {card_id}",
                            card_info.get("description", ""),
                            card_info.get("image_path", ""),
                            835838633126002721
                        ))

                    async def update_message(self, interaction):
                        card_id = self.cards[self.index]
                        card_info = self.card_info_dict[self.character_name][card_id]
                        # 전체 서버 기준 발급 순번 조회
                        issued_number = self.card_info_dict[self.character_name].get(f"{card_id}_issued_number", None)
                        if issued_number is None:
                            # DB에서 발급 순번 조회 (없으면 1로)
                            try:
                                issued_number = interaction.client.db.get_card_issued_number(self.character_name, card_id)
                            except Exception:
                                issued_number = 1
                        embed = discord.Embed(
                            title=f"My {self.character_name} Card Collection",
                            description=card_info.get("description", "No description available."),
                            color=discord.Color.from_rgb(255, 215, 0)
                        )
                        # kagaris로 시작하는 카드 ID는 S 티어로 표시
                        tier = "S" if card_id.startswith("kagaris") else card_id[0]
                        embed.add_field(name="Tier", value=tier, inline=True)
                        # Card Number: C7  #001
                        card_number_str = f"{card_id}  #{issued_number:03d}"
                        embed.add_field(name="Card Number", value=card_number_str, inline=True)
                        embed.add_field(name=" ", value="━━━━━━━━━━━━━━━━━━", inline=False)
                        if os.path.exists(card_info["image_path"]):
                            file = discord.File(card_info["image_path"], filename=f"card_{card_id}.png")
                            embed.set_image(url=f"attachment://{card_id}.png")
                            embed.set_footer(text=f"Card {self.index+1} of {self.total}")
                            await interaction.response.edit_message(embed=embed, attachments=[file], view=self)
                        else:
                            embed.add_field(name="Notice", value="Card image not found.")
                            embed.set_footer(text=f"Card {self.index+1} of {self.total}")
                            await interaction.response.edit_message(embed=embed, view=self)

                class CardNavButton(discord.ui.Button):
                    def __init__(self, label, view, direction):
                        super().__init__(label=label, style=discord.ButtonStyle.primary)
                        self.view_ref = view
                        self.direction = direction

                    async def callback(self, interaction: discord.Interaction):
                        if interaction.user.id != self.view_ref.user_id:
                            await interaction.response.send_message("Only you can navigate your cards.", ephemeral=True)
                            return
                        self.view_ref.index = (self.view_ref.index + self.direction) % self.view_ref.total
                        self.view_ref.update_buttons()
                        await self.view_ref.update_message(interaction)

                if user_cards:
                    slider_view = CardSliderView(interaction.user.id, sorted(user_cards), character_name, CHARACTER_CARD_INFO)
                    first_card_id = sorted(user_cards)[0]
                    first_card_info = CHARACTER_CARD_INFO[character_name][first_card_id]
                    embed = discord.Embed(
                        title=f"{character_name} {first_card_id} Card",
                        description=first_card_info.get("description", "No description available."),
                        color=discord.Color.from_rgb(255, 215, 0)
                    )
                    # 이모지 매핑
                    tier_emojis = {
                        'C': '🥉',
                        'B': '🥈',
                        'A': '🥇',
                        'S': '🏆',
                        'Special': '✨'
                    }
                    tier_emoji = tier_emojis.get(first_card_id[0], '')
                    embed.add_field(name="Tier", value=f"{first_card_id[0]} Tier {tier_emoji}", inline=True)
                    embed.add_field(name="Card Number", value=first_card_id, inline=True)
                    embed.add_field(name=" ", value="━━━━━━━━━━━━━━━━━━", inline=False)
                    if os.path.exists(first_card_info["image_path"]):
                        file = discord.File(first_card_info["image_path"], filename=f"card_{first_card_id}.png")
                        embed.set_image(url=f"attachment://card_{first_card_id}.png")
                        embed.set_footer(text=f"Card 1 of {len(user_cards)}")
                        await interaction.followup.send(embed=embed, file=file, view=slider_view, ephemeral=True)
                    else:
                        embed.add_field(name="Notice", value="Card image not found.")
                        embed.set_footer(text=f"Card 1 of {len(user_cards)}")
                        await interaction.followup.send(embed=embed, view=slider_view, ephemeral=True)
                else:
                    await interaction.followup.send(
                        "You have not collected any cards yet.", 
                        ephemeral=True
                    )

            except Exception as e:
                print(f"Error in mycard command: {e}")
                import traceback
                print(traceback.format_exc())
                await interaction.response.send_message(
                    "An error occurred while loading card information.", 
                    ephemeral=True
                )

        @self.tree.command(
            name="check_language",
            description="현재 채널의 언어를 확인합니다."
        )
        async def check_language_command(interaction: discord.Interaction):
            try:
                # 현재 채널의 캐릭터 봇 찾기
                current_bot = None
                for char_name, bot in self.character_bots.items():
                    if interaction.channel.id in bot.active_channels:
                        current_bot = bot
                        break

                if not current_bot:
                    await interaction.response.send_message("This command can only be used in character chat channels.", ephemeral=True)
                    return

                channel_id = interaction.channel.id
                user_id = interaction.user.id
                current_lang = self.db.get_channel_language(
                    channel_id=channel_id,
                    user_id=user_id,
                    character_name=current_bot.character_name
                )

                from config import SUPPORTED_LANGUAGES
                language_name = SUPPORTED_LANGUAGES.get(current_lang, {}).get("name", "Unknown")

                embed = discord.Embed(
                    title="🌍 language settings",
                    description=f"current language: {language_name} ({current_lang})",
                    color=discord.Color.blue()
                )

                available_languages = "\n".join([
                    f"• {info['name']} ({code})" 
                    for code, info in SUPPORTED_LANGUAGES.items()
                ])

                embed.add_field(
                    name="available languages",
                    value=available_languages,
                    inline=False
                )

                await interaction.response.send_message(embed=embed, ephemeral=True)

            except Exception as e:
                print(f"Error in check_language command: {e}")
                await interaction.response.send_message(
                    "An error occurred while checking language settings.",
                    ephemeral=True
                )

        @self.tree.command(
            name="story",
            description="Play story chapters for each character."
        )
        async def story_command(interaction: discord.Interaction):
            from config import CHARACTER_INFO, STORY_CHAPTERS

            # 현재 채널의 캐릭터 봇 찾기
            current_bot = None
            for char_name, bot in self.character_bots.items():
                if interaction.channel.id in bot.active_channels:
                    current_bot = bot
                    break

            if not current_bot:
                await interaction.response.send_message("This command can only be used in character chat channels.", ephemeral=True)
                return

            # 친밀도 등급 체크
            affinity_info = current_bot.db.get_affinity(interaction.user.id, current_bot.character_name)
            current_affinity = affinity_info['emotion_score']
            affinity_grade = get_affinity_grade(current_affinity)

            # 골드 레벨이 아닌 경우 경고 메시지 표시
            if affinity_grade != "Gold":
                embed = discord.Embed(
                    title="⚠️ Story Mode Locked",
                    description="Story mode is only available for Gold level users.",
                    color=discord.Color.red()
                )
                embed.add_field(
                    name="Current Level",
                    value=f"**{affinity_grade}**",
                    inline=True
                )
                embed.add_field(
                    name="Required Level",
                    value="**Gold**",
                    inline=True
                )
                embed.add_field(
                    name="How to Unlock",
                    value="Keep chatting with the character to increase your affinity level!",
                    inline=False
                )
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return

            # 골드 레벨인 경우 기존 스토리 모드 진행
            options = [
                discord.SelectOption(
                    label=selected_char,
                    description=CHARACTER_INFO[selected_char]['description'],
                    value=selected_char
                )
                for selected_char in CHARACTER_INFO.keys()
            ]
            select = discord.ui.Select(
                placeholder="Please select a character to chat with...",
                min_values=1,
                max_values=1,
                options=options
            )

            async def select_callback(select_interaction: discord.Interaction):
                selected_char = select.values[0]
                if selected_char != current_bot.character_name:
                    await select_interaction.response.send_message(
                        "Please use it on the character channel.", ephemeral=True
                    )
                    return
                try:
                    user_id = select_interaction.user.id
                    character_bot = self.character_bots.get(selected_char)
                    if not character_bot:
                        await select_interaction.response.send_message("The character bot cannot be found..", ephemeral=True)
                        return

                    # 챕터 리스트 생성
                    chapters = STORY_CHAPTERS.get(selected_char, [])
                    if not chapters:
                        await select_interaction.response.send_message("There is no story chapter for this character..", ephemeral=True)
                        return

                    chapter_options = [
                        discord.SelectOption(
                            label=f"{c['emoji']} {c['title']}",
                            description=c.get('content', ''),
                            value=str(c['id'])
                        ) for c in chapters
                    ]
                    chapter_select = discord.ui.Select(
                        placeholder="Please select a chapter to play.",
                        min_values=1,
                        max_values=1,
                        options=chapter_options
                    )

                    async def chapter_callback(chapter_interaction: discord.Interaction):
                        try:
                            await chapter_interaction.response.defer(ephemeral=True)
                            chapter_id = int(chapter_select.values[0])

                            # 새로운 스토리 채널 생성
                            guild = chapter_interaction.guild
                            channel_name = f"{selected_char.lower()}-story-{chapter_interaction.user.name.lower()}"
                            category = discord.utils.get(guild.categories, name="chatbot")
                            if not category:
                                category = await guild.create_category("chatbot")

                            # 기존 스토리 채널이 있다면 삭제
                            existing_channel = discord.utils.get(category.text_channels, name=channel_name)
                            if existing_channel:
                                await existing_channel.delete()

                            # 새 채널 생성
                            overwrites = {
                                guild.default_role: discord.PermissionOverwrite(read_messages=False),
                                chapter_interaction.user: discord.PermissionOverwrite(read_messages=True, send_messages=True),
                                guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True)
                            }
                            channel = await guild.create_text_channel(
                                name=channel_name,
                                category=category,
                                overwrites=overwrites
                            )

                            # 스토리 모드 시작
                            chapter = STORY_CHAPTERS[selected_char][chapter_id - 1]
                            embed = discord.Embed(
                                title=chapter["title"],
                                description=chapter.get("description", ""),
                                color=CHARACTER_INFO[selected_char]["color"]
                            )

                            if selected_char == "Kagari":
                                embed.add_field(
                                    name="🌸 Welcome to a Special Moment",
                                    value=(
                                        "Welcome to a special 5-minute story under the cherry blossoms. "
                                        "In this moment, you're spending quiet time with Kagari — a reserved, graceful half-yokai who rarely expresses her feelings. "
                                        "But… somewhere behind her calm gaze, a soft heart quietly hopes for warmth. "
                                        "Your goal is simple: ✨ Talk with her. Make her feel something. One word at a time."
                                    ),
                                    inline=False
                                )
                                embed.add_field(
                                    name="💬 How it works",
                                    value=(
                                        "1. Kagari will gently guide the conversation, and your responses will affect how close she feels to you.\n"
                                        "2. She doesn't say it out loud… but she's keeping score — based on how you make her feel.\n"
                                        "3. Speak with sincerity and subtlety, and she might just open her heart.\n"
                                        "4. Be too blunt or pushy? She'll retreat — and the moment might slip away."
                                    ),
                                    inline=False
                                )
                                embed.add_field(
                                    name="🎴 Card Rewards",
                                    value=(
                                        "At the end of this story, Kagari will judge your connection — and based on how you made her feel, you may receive a special card.\n\n"
                                        "🟥 **High score** (warm, sincere, respectful)\n"
                                        "→ S-tier or Special Kagari Card 🌸\n\n"
                                        "🟨 **Medium score** (neutral to light warmth)\n"
                                        "→ Standard Kagari Card\n\n"
                                        "⬛ **Low score** (awkward, cold, or too pushy)\n"
                                        "→ No card... just a cold breeze and silence.\n\n"
                                        "🌟 Your words matter. A simple sentence can shape the memory — and the reward."
                                    ),
                                    inline=False
                                )
                                embed.add_field(
                                    name="🧭 Tone Tips",
                                    value=(
                                        "🕊 Start softly. Kagari opens up only to those who earn her trust.\n\n"
                                        "💬 Use gentle, meaningful words — not flashy compliments.\n\n"
                                        "🎭 Let the silence speak too. Kagari isn't chatty, but she listens deeply.\n\n"
                                        "Her replies may feel distant at first:\n"
                                        "\"...I see.\" / \"That's... unexpected.\" / \"Mm. Thank you, I suppose.\"\n\n"
                                        "But as your words reach her — you might see a smile you'll never forget."
                                    ),
                                    inline=False
                                )
                                embed.add_field(
                                    name="Ready to Begin?",
                                    value="Then say something... and let's see where her heart leads.\n\n🌸🍃",
                                    inline=False
                                )
                            elif selected_char == "Eros":
                                embed.add_field(
                                    name="🐝 Eros Story Mode – special detective story",
                                    value=(
                                        "Welcome to Eros's special detective story!\n"
                                        "Her precious gift for the Spot Zero team has gone missing… and she needs your help to find the culprit. 💔\n"
                                        "You'll chat with Eros over 20 turns, collect clues, and solve the mystery together."
                                    ),
                                    inline=False
                                )
                                embed.add_field(
                                    name="🔍 Your Mission",
                                    value=(
                                        "Combine the clues Eros gives you to identify the thief after turn 20 — and help her recover the stolen gift!"
                                    ),
                                    inline=False
                                )
                                embed.add_field(
                                    name="🧠 Tips for Talking to Eros",
                                    value=(
                                        "🗨️ She's emotional, so speak gently.\n\n"
                                        "🚫 Don't use commands or be too forceful.\n\n"
                                        "✅ Comfort her or ask thoughtful questions about the clues.\n\n"
                                        "💬 Eros will use small expressions like (sniffles), (thinking), or (hopeful eyes) — pay attention to her feelings.\n\n"
                                        "❗ She won't say \"thank you\" — she's focused on solving the case."
                                    ),
                                    inline=False
                                )
                                embed.add_field(
                                    name="🎴 Card Rewards",
                                    value=(
                                        "Based on your emotional connection and the flow of your conversation,\n"
                                        "you'll receive a final reward card depending on your score with Eros."
                                    ),
                                    inline=False
                                )
                                embed.add_field(
                                    name="Ready to Begin?",
                                    value="Are you ready to solve the case together? 🐾\nLet's begin… she's counting on you. 💛",
                                    inline=False
                                )

                            if chapter.get("thumbnail"):
                                embed.set_thumbnail(url=chapter["thumbnail"])
                            await channel.send(embed=embed)

                            # 하이퍼링크 메시지 전송
                            story_link = f"https://discord.com/channels/{guild.id}/{channel.id}"
                            await chapter_interaction.followup.send(
                                f"[Go to your story channel]({story_link})\nStory has started!",
                                ephemeral=True
                            )

                            # 스토리 모드 시작
                            await run_story_scene(
                                self, channel, chapter_interaction.user, selected_char, chapter_id, 1
                            )

                        except Exception as e:
                            print(f"[ERROR] chapter_callback: {e}")
                            import traceback
                            print(traceback.format_exc())
                            if not chapter_interaction.response.is_done():
                                await chapter_interaction.response.send_message(
                                    f"에러 발생: {e}",
                                    ephemeral=True
                                )
                            else:
                                await chapter_interaction.followup.send(
                                    f"에러 발생: {e}",
                                    ephemeral=True
                                )

                    chapter_select.callback = chapter_callback
                    chapter_view = discord.ui.View()
                    chapter_view.add_item(chapter_select)
                    await select_interaction.response.send_message(
                        'Please select a story chapter for ' + selected_char + ':',
                        view=chapter_view,
                        ephemeral=True
                    )

                except Exception as e:
                    import traceback
                    print(traceback.format_exc())
                    await select_interaction.response.send_message(f"Error occurred: {e}", ephemeral=True)

            select.callback = select_callback
            view = discord.ui.View()
            view.add_item(select)
            await interaction.response.send_message(
                "Please select a character:",
                view=view,
                ephemeral=True
            )

        @self.tree.command(
            name="message_add",
            description="Admin: Manually add a user's message count."
        )
        @app_commands.default_permissions(administrator=True)
        async def message_add_command(interaction: discord.Interaction, target: discord.Member, count: int, character: str):
            if not self.settings.is_admin(interaction.user):
                await interaction.response.send_message("Available to admins only.", ephemeral=True)
                return
            # DB에 메시지 추가 (실제 메시지 insert)
            for _ in range(count):
                await self.db.add_message(
                    channel_id=0,  # 시스템 메시지이므로 0
                    user_id=target.id,
                    character_name=character,
                    role="user",
                    content="[Add an admin message]",
                    language="en"
                )
            embed = discord.Embed(
                title="Finished adding the number of messages",
                description=f"{target.display_name}의 {character} 메시지 수가 {count}만큼 증가했습니다.",
                color=discord.Color.green()
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)

        @self.tree.command(
            name="affinity_set",
            description="Admin: Manually set a user's affinity score."
        )
        @app_commands.default_permissions(administrator=True)
        async def affinity_set_command(interaction: discord.Interaction, target: discord.Member, value: int, character: str):
            if not self.settings.is_admin(interaction.user):
                await interaction.response.send_message("Available to admins only.", ephemeral=True)
                return
            # affinity 직접 수정
            try:
                # 락이 필요 없다면 아래 한 줄만!
                self.db.set_affinity(target.id, character, value)
                grade = get_affinity_grade(value)
                embed = discord.Embed(
                    title="Affinity Score Updated",
                    description=f"{target.display_name}'s {character} affinity score is set to {value}.\nCurrent grade: **{grade}**",
                    color=discord.Color.gold()
                )
                await interaction.response.send_message(embed=embed, ephemeral=True)
            except Exception as e:
                await interaction.response.send_message(f"错误: {e}", ephemeral=True)

        @self.tree.command(
            name="card_give",
            description="Admin: Manually give a card to a user."
        )
        @app_commands.default_permissions(administrator=True)
        async def card_give_command(interaction: discord.Interaction, target: discord.Member, character: str, card_id: str):
            if not self.settings.is_admin(interaction.user):
                await interaction.response.send_message("Only admins can use this command.", ephemeral=True)
                return
            success = self.db.add_user_card(target.id, character, card_id)
            if success:
                embed = discord.Embed(
                        title="Card given",
                        description=f"{target.display_name} has been given the {character} {card_id} card.",
                    color=discord.Color.green()
                )
            else:
                embed = discord.Embed(
                    title="Card giving failed",
                    description=f"The card {card_id} has already been given or the giving failed.",
                    color=discord.Color.red()
                )
            await interaction.response.send_message(embed=embed, ephemeral=True)

        @self.tree.command(
            name="message_add_total",
            description="Admin: Manually set a user's total message count."
        )
        @app_commands.default_permissions(administrator=True)
        async def message_add_total_command(interaction: discord.Interaction, target: discord.Member, total: int):
            if not self.settings.is_admin(interaction.user):
                await interaction.response.send_message("Only admins can use this command.", ephemeral=True)
                return
            if total < 0:
                await interaction.response.send_message("The message count must be 0 or more.", ephemeral=True)
                return
            # 유저의 현재 총 메시지 수 확인
            current_count = await self.db.get_user_message_count(target.id)
            to_add = total - current_count
            if to_add > 0:
                for _ in range(to_add):
                    await self.db.add_message(
                        channel_id=0,  # 시스템 메시지이므로 0
                        user_id=target.id,
                        character_name="system",  # 또는 None/공백 등
                        role="user",
                        content="[Add an admin message]",
                        language="en"
                    )
                await interaction.response.send_message(f"{target.display_name}'s total message count is set to {total}.", ephemeral=True)
            elif to_add == 0:
                await interaction.response.send_message(f"{target.display_name}'s total message count is already {total}.", ephemeral=True)
            else:
                await interaction.response.send_message(f"{target.display_name}'s total message count ({current_count} times) exceeds {total}. (Decrease is not supported)", ephemeral=True)

        @self.tree.command(
            name="help",
            description="How to use the chatbot, affinity, card, story, ranking, FAQ guide"
        )
        async def help_command(interaction: discord.Interaction):
            help_topics = [
                ("🤖 How to Use the Chatbot", "how_to_use"),
                ("❤️ Affinity & Level System", "affinity"),
                ("🎴 Card & Reward System", "card"),
                ("🎭 Story Mode", "story"),
                ("🏆 Ranking System", "ranking"),
                ("❓ FAQ", "faq"),
            ]
            options = [
                discord.SelectOption(label=title, value=key)
                for title, key in help_topics
            ]
            class HelpSelect(discord.ui.Select):
                def __init__(self):
                    super().__init__(placeholder="Select a help topic", min_values=1, max_values=1, options=options)
                async def callback(self, interaction2: discord.Interaction):
                    topic = self.values[0]
                    embed = discord.Embed(color=discord.Color.blurple())
                    if topic == "how_to_use":
                        embed.title = "🤖 How to Use the Chatbot"
                        embed.add_field(name="How to Talk with Characters", value="- Use /bot to create a private chat channel with a character like Kagari or Eros.\n- Supports multilingual input (EN/JP/ZH), responses are always in English.\n- Characters react to your emotions, tone, and depth of conversation.\n🧠 Pro Tip: The more emotionally engaging your dialogue, the faster you grow your bond!", inline=False)
                    elif topic == "affinity":
                        embed.title = "❤️ Affinity & Level System"
                        embed.add_field(name="Level Up with Conversations", value="- Rookie (1–10 msgs): Basic chat only.\n- Iron (11–30): Unlock C-rank cards & light emotion.\n- Silver (31–60): A/B/C cards & story mood options.\n- Gold (61+): S-tier chance & story unlock.\n- Gold+ (100+): Higher A-rank chance + special tone.\nCommand: /affinity to check your current level, progress, and daily message stats.", inline=False)
                    elif topic == "card":
                        embed.title = "🎴 Card & Reward System"
                        embed.add_field(name="How to Earn & Collect Cards", value="You earn cards through:\n- 🗣️ Emotional chat: score-based triggers (10/20/30)\n- 🎮 Story Mode completions\n- ❤️ Affinity milestone bonuses\nCard Tier Example (Gold user):\n- A (20%) / B (40%) / C (40%)\n- Gold+ user: A (35%) / B (35%) / C (30%)\n📜 Use /mycard to view your collection.", inline=False)
                    elif topic == "story":
                        embed.title = "🎭 Story Mode"
                        embed.add_field(name="Play Story Chapters with Your Favorite Characters", value="Start with /story start [character]\nStory Mode is only open to users with Gold status or higher. Story Mode allows you to earn Tier Cards.\n\nScenarios:\n- Kagari: 🌸 Spring date under the cherry blossoms\n- Eros: 🕵️ Track down the mysterious gift thief\n🎯 30+ dialogue turns → score-based endings (positive/neutral/negative)\n🃏 Ending gives you a card (based on performance)", inline=False)
                    elif topic == "ranking":
                        embed.title = "🏆 Ranking System"
                        embed.add_field(name="Want to know who's building the strongest bond with each character?", value="Our Crush Rankings track the top players based on weekly interaction scores!\n\nHow it works:\n- Rankings are based on your weekly Crush Score from chats and stories\n- Updated every Monday 00:00 UTC (Sunday reset)\n- Rank = sum of crush points with that character\nCommands:\n- /ranking — View current top players", inline=False)
                    elif topic == "faq":
                        embed.title = "❓ FAQ"
                        embed.add_field(name="Q1: How can I get Q cards or grade cards?", value="A: You can get A–C grade cards through 1:1 general chat with characters.\nHowever, your Crush level determines the probability and tier of the card you receive.\nCheck /help affinity & level system to see what tier unlocks which card grades.", inline=False)
                        embed.add_field(name="Q2: How are rewards calculated in Story Mode?", value="A: There are two score systems in Story Mode:\n- Mission Clear Logic: Each story has a mission goal. If you clear it, you're guaranteed an S-tier card.\n- Affinity Score Logic: Your outcome is affected by how close you are with the character.\nIf your crush score is too low, you may not receive a card at all. Higher crush = higher card tier and more beautiful card art!", inline=False)
                        embed.add_field(name="Q3: What changes based on my Crush with the character?", value="A: Character tone, reaction, and card chances all change based on your Affinity level.\n- Higher Affinity = More natural or intimate dialogue\n- Higher Affinity = Better chance at A-tier or S-tier cards\n- Lower Affinity = Dull responses, chance of being rejected\nUse /affinity to track your current level with each character.", inline=False)
                    await interaction2.response.send_message(embed=embed, ephemeral=True)
            class HelpView(discord.ui.View):
                def __init__(self):
                    super().__init__(timeout=180)
                    self.add_item(HelpSelect())
            embed = discord.Embed(
                title="Help Menu",
                description="Select a topic below to learn more!",
                color=discord.Color.blurple()
            )
            await interaction.response.send_message(embed=embed, view=HelpView(), ephemeral=True)

        @self.tree.command(
            name="roleplay",
            description="Start a new roleplay session with the character in this channel"
        )
        async def roleplay_command(interaction: discord.Interaction):
            try:
                # 1. 현재 채널의 캐릭터 찾기
                current_bot = None
                for char_name, bot in self.character_bots.items():
                    # 1. active_channels에 등록되어 있으면 우선
                    if interaction.channel.id in bot.active_channels:
                        current_bot = bot
                        break
                    # 2. 채널 이름 규칙으로도 판별 (예: kagari-유저이름)
                    if interaction.channel.name.startswith(char_name.lower() + "-"):
                        current_bot = bot
                        break
                if not current_bot:
                    await interaction.response.send_message("This command is only available in character chat channels.", ephemeral=True)
                    return

                # 2. 호감도 체크 (스토리 모드와 동일)
                affinity_info = current_bot.db.get_affinity(interaction.user.id, current_bot.character_name)
                affinity = affinity_info['emotion_score'] if affinity_info else 0
                if affinity < 100:
                    await interaction.response.send_message("Roleplaying mode is only open to players with a favorability rating of 100 or higher.", ephemeral=True)
                    return

                # 3. 모달 표시
                modal = RoleplayModal(current_bot.character_name)
                await interaction.response.send_modal(modal)

            except Exception as e:
                print(f"Error in /roleplay: {e}")
                await interaction.response.send_message("An error occurred, please contact your administrator.", ephemeral=True)

    async def on_message(self, message):
        session = self.roleplay_sessions.get(message.channel.id) if hasattr(self, "roleplay_sessions") else None
        if session and session["is_active"]:
            if message.author.id != session["user_id"]:
                return  # 유저만 입력 가능
            session["turns_remaining"] -= 1
            # 캐릭터 personality + 유저 입력값(역할, 스토리라인) 결합
            from config import CHARACTER_INFO
            char_info = CHARACTER_INFO.get(session["character_name"], {})
            base_personality = char_info.get("personality", "")
            user_role = session.get("user_role", "")
            character_role = session.get("character_role", "")
            story_line = session.get("story_line", "")
            system_prompt = (
                f"{base_personality}\n\n"
                f"[Roleplay Setting]\n"
                f"- User's Role: {user_role}\n"
                f"- Character's Role: {character_role}\n"
                f"- Story Line: {story_line}\n"
                "IMPORTANT: Only reply with ONE sentence per user message. Never ask more than one question or make more than one statement per turn. "
                "If you want to ask a question, do not add any extra explanation or follow-up. Never rephrase or repeat the same question in different words. If you have to choose, only say the most important thing. "
                "Do NOT repeat or summarize previous messages. "
                "Make the conversation feel like a real, playful, and romantic date. "
                "Be emotionally responsive, curious, and occasionally a little shy or flirty. "
                "Never break character. Do not use more than one set of parentheses for actions or feelings. "
                "Never answer or discuss sexual, child abuse, political, or any other sensitive or controversial topics. Politely avoid or change the subject if such topics arise. "
                "Your goal is to make the user feel emotionally engaged and immersed in the story. "
            )
            ai_response = openai.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": message.content}
                ],
                temperature=0.7,
                max_tokens=150
            )
            ai_text = ai_response.choices[0].message.content.strip()
            import re
            match = re.search(r'(.+?[.!?\n])', ai_text)
            first_sentence = match.group(1).strip() if match else ai_text.split('\n')[0]
            await message.channel.send(f"{char_info.get('emoji', '')} **{session['character_name']}**: {first_sentence}")
            if session["turns_remaining"] <= 0:
                session["is_active"] = False
                await message.channel.send("Roleplay mode has ended.")
            return
        # 일반 메시지/스토리 모드 등은 기존대로 처리
        await self.process_normal_message(message)
