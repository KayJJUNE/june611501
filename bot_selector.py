from calendar import day_name
import os
import discord
from discord.ext import commands
from discord import app_commands
import asyncio
import time

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
    SELECTOR_TOKEN as TOKEN,
    STORY_CHAPTERS,
    STORY_CARD_REWARD,
    get_card_info_by_id,
    KAGARI_TOKEN, EROS_TOKEN, ELYSIA_TOKEN,
    DATABASE_URL, CHARACTER_PROMPTS,
    CLOUDFLARE_IMAGE_BASE_URL,
)
from database_manager import get_db_manager, DatabaseManager
from typing import Dict, TYPE_CHECKING, Any, Self
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
import re
import langdetect
from deep_translator import GoogleTranslator
import random
from math import ceil
import urllib.parse
from character_bot import CharacterBot
import character_bot
from story_mode import story_sessions, get_chapter_info
from story_mode import start_story_stage, process_story_message, handle_chapter3_gift_usage, handle_serve_command
import openai
import traceback
import importlib

# --- 상단 임포트/유틸 추가 ---
from character_bot import CardClaimView
from character_bot import get_affinity_grade

# 강제로 gift_manager 모듈을 다시 로드하여 캐시 문제를 해결합니다.
import gift_manager
importlib.reload(gift_manager)

from gift_manager import (
    get_gift_details, 
    ALL_GIFTS, 
    get_gift_emoji, 
    check_gift_preference, 
    get_gift_reaction,
    GIFT_RARITY,
    CHARACTER_GIFT_REACTIONS,
    get_gifts_by_rarity_v2
)

# --- 캐릭터별 리액션 메시지 (Eros 챕터2, 대화체+이모티콘) ---
character_reactions = {
    "Kagari": {
        "success": "Kagari: \"Oh... Did you really make this for me? (blushes) Thank you!\" 🌸",
        "fail": "Kagari: \"Hmm... I think you missed something, but I appreciate the effort!\" 😅"
    },
    "Elysia": {
        "success": "Elysia: \"Nya~! This is purr-fect! You know me so well!\" 🐾",
        "fail": "Elysia: \"Nya? It's not quite right, but thanks for trying!\" 🐾"
    },
    "Cang": {
        "success": "Cang: \"Haha, you remembered my favorite! You're amazing.\" 🥭",
        "fail": "Cang: \"Hmm, not quite what I expected, but thanks anyway!\" 🤔"
    },
    "Ira": {
        "success": "Ira: \"Whoa, this is exactly what I needed. Thanks, partner!\" ☕️",
        "fail": "Ira: \"Close, but not quite my style. Still, thanks!\" 😅"
    },
    "Dolores": {
        "success": "Dolores: \"Oh! The aroma is wonderful... You have great taste.\" 💜",
        "fail": "Dolores: \"Hmm... It's a bit different, but I appreciate your effort!\" 💜"
    },
    "Nyxara": {
        "success": "Nyxara: \"Mmm, marshmallows! You really get me, don't you?\" 🍫",
        "fail": "Nyxara: \"Not quite what I wanted, but thanks for the treat!\" 🍫"
    },
    "Lunethis": {
        "success": "Lunethis: \"Warm and gentle, just like you. Thank you so much.\" 🍵",
        "fail": "Lunethis: \"It's a little different, but I still appreciate it.\" 🍵"
    }
}

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
                description="Top 20 users by affinity and chat count with Kagari",
                value="kagari"
            ),
            discord.SelectOption(
                label="Eros Chat Ranking 💝",
                description="Top 20 users by affinity and chat count with Eros",
                value="eros"
            ),
            discord.SelectOption(
                label="Elysia Chat Ranking 🦋",
                description="Top 20 users by affinity and chat count with Elysia",
                value="elysia"
            ),
            discord.SelectOption(
                label="Total Chat Ranking 👑",
                description="Top 20 users by total affinity and chat count across all characters",
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

            user_id = interaction.user.id
            guild = interaction.guild

            if ranking_type == "kagari":
                rankings = self.view.db.get_character_ranking("Kagari")
                embed.title = "🌸 Kagari Chat Ranking"
                user_rank = self.view.db.get_user_character_rank(user_id, "Kagari")
                user_stats = self.view.db.get_user_stats(user_id, "Kagari")
            elif ranking_type == "eros":
                rankings = self.view.db.get_character_ranking("Eros")
                embed.title = "💝 Eros Chat Ranking"
                user_rank = self.view.db.get_user_character_rank(user_id, "Eros")
                user_stats = self.view.db.get_user_stats(user_id, "Eros")
            elif ranking_type == "elysia":
                rankings = self.view.db.get_character_ranking("Elysia")
                embed.title = "🦋 Elysia Chat Ranking"
                user_rank = self.view.db.get_user_character_rank(user_id, "Elysia")
                user_stats = self.view.db.get_user_stats(user_id, "Elysia")
            else:  # total
                rankings = self.view.db.get_total_ranking()
                embed.title = "👑 Total Chat Ranking"
                user_rank = self.view.db.get_user_total_rank(user_id)
                user_stats = self.view.db.get_user_stats(user_id)

            # top20 표시
            if not rankings or len(rankings) == 0:
                embed.description = "No ranking data available yet."
            else:
                ranking_text = ""
                for i, row in enumerate(rankings[:20], 1):
                    user_id_row = row[0]
                    score = row[1]
                    count = row[2] if len(row) > 2 else 0
                    user = guild.get_member(user_id_row)
                    display_name = user.display_name if user else f"User{user_id_row}"
                    ranking_text += f"{i}. {display_name} - Score: {score} (Chats: {count})\n"
                embed.description = ranking_text or "No ranking data available yet."

            # 내 랭킹이 top20 밖이면 하단에 별도 표시
            in_top20 = False
            for i, row in enumerate(rankings[:20], 1):
                if row[0] == user_id:
                    in_top20 = True
                    break
            if not in_top20:
                # 내 점수/메시지수/랭킹 표시
                my_score = user_stats.get('affinity', user_stats.get('total_emotion', 0))
                my_count = user_stats.get('messages', user_stats.get('total_messages', 0))
                embed.add_field(
                    name="Your Ranking",
                    value=f"Rank: {user_rank if user_rank < 999999 else 'Unranked'} | Score: {my_score} | Chats: {my_count}",
                    inline=False
                )

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
        if emotion_score >= 100:
            return "Gold"
        elif emotion_score >= 50:
            return "Silver"
        elif emotion_score >= 30:
            return "Bronze"
        elif emotion_score >= 10:
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
            self.user_role = discord.ui.TextInput(label="Your Role", max_length=150, required=True)
            self.character_role = discord.ui.TextInput(label="Character Role", max_length=150, required=True)
            self.story_line = discord.ui.TextInput(label="Story Line", max_length=1500, required=True, style=discord.TextStyle.paragraph)
            self.add_item(self.user_role)
            self.add_item(self.character_role)
            self.add_item(self.story_line)

        async def on_submit(self, interaction: discord.Interaction):
            # 글자수 초과 체크 (혹시 모를 예외 상황 대비)
            if len(self.user_role.value) > 150 or len(self.character_role.value) > 150:
                await interaction.response.send_message(
                    "❌ 'Your Role and Character Role must be entered in 150 characters or less..", ephemeral=True
                )
                return
            if len(self.story_line.value) > 1500:
                await interaction.response.send_message(
                    "❌ 'The Story Line must be entered within 1,500 characters..", ephemeral=True
                )
                return
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
                    topic=f"Roleplay with {self.character_name} for {interaction.user.name}",
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

def milestone_to_card_id(milestone: int, character_name: str = "Kagari") -> str:
    character_lower = character_name.lower()
    if milestone == 10:
        return f"{character_lower}c1"
    elif milestone == 30:
        return f"{character_lower}c3"
    elif milestone == 50:
        return f"{character_lower}c5"
    elif milestone == 100:
        return f"{character_lower}c10"
    elif milestone == 230:
        return f"{character_lower}s1"
    elif milestone == 240:
        return f"{character_lower}s2"
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

                try:
                    await interaction.response.send_message(
                        success_messages.get(selected_language, success_messages["en"]),
                        ephemeral=True
                    )
                except discord.errors.NotFound:
                    print("Interaction expired during language selection")
                    await interaction.channel.send(success_messages.get(selected_language, success_messages["en"]), delete_after=5)

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
                try:
                    await interaction.response.send_message(error_msg, ephemeral=True)
                except discord.errors.NotFound:
                    await interaction.channel.send(error_msg, delete_after=5)

        except discord.errors.NotFound:
            print("Interaction expired during language selection")
            try:
                await interaction.channel.send("Interaction expired. Please try again.", delete_after=5)
            except:
                pass
        except Exception as e:
            print(f"Error in language selection callback: {e}")
            try:
                await interaction.response.send_message(
                    "An error occurred while processing your language selection.",
                    ephemeral=True
                )
            except discord.errors.NotFound:
                try:
                    await interaction.channel.send("An error occurred while processing your language selection.", delete_after=5)
                except:
                    pass

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
            print(f"[DEBUG] 선택된 캐릭터: {selected_char}")

            # 선택된 캐릭터 봇 찾기
            selected_bot = self.bot_selector.character_bots.get(selected_char)
            if not selected_bot:
                print(f"[DEBUG] 캐릭터 봇을 찾을 수 없음: {selected_char}")
                try:
                    if not interaction.response.is_done():
                        await interaction.response.send_message(
                            "The selected character was not found.",
                            ephemeral=True
                        )
                    else:
                        await interaction.followup.send(
                            "The selected character was not found.",
                            ephemeral=True
                        )
                except discord.errors.NotFound:
                    print("Interaction already expired, sending message to channel instead")
                    await interaction.channel.send("The selected character was not found.", delete_after=5)
                return

            # 사용자별 채널 생성
            channel_name = f"chat-{selected_char.lower()}-{interaction.user.name}"
            print(f"[DEBUG] 생성할 채널명: {channel_name}")

            # 기존 채널 확인 및 삭제
            existing_channel = discord.utils.get(interaction.guild.channels, name=channel_name)
            if existing_channel:
                print(f"[DEBUG] 기존 채널 삭제: {existing_channel.name}")
                await existing_channel.delete()

            # 새 채널 생성
            channel = await interaction.guild.create_text_channel(
                name=channel_name,
                topic=f"Private chat with {selected_char} for {interaction.user.name}"
            )
            print(f"[DEBUG] 새 채널 생성 완료: {channel.name}")

            # 채널 등록
            success, message = await selected_bot.add_channel(channel.id, interaction.user.id)
            print("[DEBUG] add_channel 호출 후")

            if success:
                # 채널 생성 알림 메시지
                try:
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
                except discord.errors.NotFound:
                    print("Interaction expired, sending message to channel instead")
                    await channel.send(f"Start chatting with {selected_char}!", delete_after=10)

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
                await channel.send("채널 등록 중 오류가 발생했습니다. 채널을 다시 생성해주세요.")
                await channel.delete()
        except discord.errors.NotFound:
            print("Interaction expired during character selection")
            try:
                await interaction.channel.send("Interaction expired. Please try the command again.", delete_after=5)
            except:
                pass
        except Exception as e:
            print(f"Error in channel creation: {e}")
            import traceback
            print(traceback.format_exc())
            try:
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
            except discord.errors.NotFound:
                print("Interaction expired during error handling")
                try:
                    await interaction.channel.send("An error occurred, please try again.", delete_after=5)
                except:
                    pass

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
        intents = discord.Intents.default()
        intents.messages = True
        intents.guilds = True
        intents.message_content = True
        intents.members = True
        super().__init__(command_prefix="!", intents=intents)
        self.character_bots: Dict[str, "CharacterBot"] = {}
        self.db = get_db_manager()
        self.settings_manager = SettingsManager()
        self.active_channels: Dict[int, str] = {}
        self.user_languages: Dict[int, str] = {}
        self.setup_commands()
        self.roleplay_sessions = {}
        self.story_sessions = {}

    async def check_story_quests(self, user_id: int) -> list:
        """스토리 퀘스트 상태를 확인합니다."""
        quests = []
        try:
            # Kagari (3챕터)
            kagari_completed = self.db.get_completed_chapters(user_id, 'Kagari')
            quests.append({
                'id': 'story_kagari_all_chapters',
                'name': '🌸 Kagari Story Complete',
                'description': f'Complete all 3 chapters of Kagari\'s story ({len(kagari_completed)}/3)',
                'progress': len(kagari_completed),
                'max_progress': 3,
                'completed': len(kagari_completed) >= 3,
                'reward': 'Epic Gifts x3',
                'claimed': self.db.is_story_quest_claimed(user_id, 'Kagari', 'all_chapters')
            })

            # Eros (3챕터)
            eros_completed = self.db.get_completed_chapters(user_id, 'Eros')
            quests.append({
                'id': 'story_eros_all_chapters',
                'name': '💝 Eros Story Complete',
                'description': f'Complete all 3 chapters of Eros\'s story ({len(eros_completed)}/3)',
                'progress': len(eros_completed),
                'max_progress': 3,
                'completed': len(eros_completed) >= 3,
                'reward': 'Epic Gifts x3',
                'claimed': self.db.is_story_quest_claimed(user_id, 'Eros', 'all_chapters')
            })

            # Elysia (1챕터)
            elysia_completed = self.db.get_completed_chapters(user_id, 'Elysia')
            quests.append({
                'id': 'story_elysia_all_chapters',
                'name': '🦋 Elysia Story Complete',
                'description': f'Complete chapter 1 of Elysia\'s story ({len(elysia_completed)}/1)',
                'progress': len(elysia_completed),
                'max_progress': 1,
                'completed': len(elysia_completed) >= 1,
                'reward': 'Epic Gifts x3',
                'claimed': self.db.is_story_quest_claimed(user_id, 'Elysia', 'all_chapters')
            })
        except Exception as e:
            print(f"Error in check_story_quests: {e}")
        return quests
    
    async def setup_hook(self) -> None:
        """ 봇이 시작될 때 필요한 비동기 설정을 수행합니다. """
        # Cog 로드를 제거하고, 명령어는 setup_commands에서 직접 등록
        await self.tree.sync()

    async def on_ready(self):
        print(f'{self.user} has connected to Discord!')
        # self.tree.sync()는 setup_hook으로 이동했습니다.
        self.load_active_channels()

    async def get_ai_response(self, messages: list, emotion_score: int = 0) -> str:
        if not OPENAI_API_KEY:
            return "OpenAI API key is not set."
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

        max_retries = 3
        base_delay = 1.0

        for attempt in range(max_retries):
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
                print(f"Error in get_ai_response (attempt {attempt + 1}/{max_retries}): {e}")

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

                # 기존 서버 에러 체크
                is_server_error = (
                    (hasattr(e, 'http_status') and e.http_status == 500) or
                    (hasattr(e, 'status_code') and e.status_code == 500) or
                    (hasattr(e, 'args') and 'server had an error' in str(e.args[0]))
                )

                # 마지막 시도가 아니고 (네트워크 에러 또는 서버 에러)인 경우 재시도
                if attempt < max_retries - 1 and (is_network_error or is_server_error):
                    delay = base_delay * (2 ** attempt)  # 지수 백오프
                    print(f"Network/Server error detected, retrying in {delay} seconds...")
                    await asyncio.sleep(delay)
                    continue
                else:
                    # 에러가 아니거나 마지막 시도인 경우
                    if is_network_error:
                        return "Sorry, there was a temporary network issue. Please try again in a moment."
                    else:
                        return "There was a temporary issue with the AI server. Please try again in a moment."

        return "There was a temporary issue with the AI server. Please try again in a moment."

    def setup_commands(self):
        @self.tree.command(
            name="bot",
            description="Open character selection menu"
        )
        async def bot_command(interaction: discord.Interaction):
            try:
                if not isinstance(interaction.channel, discord.TextChannel):
                    await interaction.response.send_message(
                        "This command can only be used in server channels.",
                        ephemeral=True
                    )
                    return

                embed = discord.Embed(
                    title="🌸 Select Your Character!",
                    description="Please choose your favorite character below.",
                    color=discord.Color.gold()
                )
                embed.add_field(
                    name="🌸 Kagari",
                    value="Cold-hearted Yokai Warrior",
                    inline=True
                )
                embed.add_field(
                    name="💝 Eros",
                    value="Cute Honeybee",
                    inline=True
                )
                embed.add_field(
                    name="⚔️ Elysia",
                    value="Nya Kitty Girl",
                    inline=True
                )
                banner_url = "https://imagedelivery.net/ZQ-g2Ke3i84UnMdCSDAkmw/4c2404ce-0626-436d-2f4e-fdafc3ba5400/public"
                embed.set_image(url=banner_url)

                # 하단에 Terms of Service, Privacy Policy 하이퍼링크 추가
                embed.add_field(
                    name="\u200b",
                    value="[Terms of Service](https://spotzero.tartagames.com/privacy/terms)  |  [Privacy Policy](https://spotzero.tartagames.com/privacy)",
                    inline=False
                )

                view = discord.ui.View()
                view.add_item(CharacterSelect(self))

                await interaction.response.send_message(
                    embed=embed,
                    view=view,
                    ephemeral=True
                )
            except Exception as e:
                print(f"Error in bot_command: {e}")
                import traceback
                print(traceback.format_exc())
                try:
                    if not interaction.response.is_done():
                        await interaction.response.send_message(
                            "An error occurred while loading the character selection menu. Please try again.",
                            ephemeral=True
                        )
                    else:
                        await interaction.followup.send(
                            "An error occurred while loading the character selection menu. Please try again.",
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

                # ====== 디버깅 로그 추가 시작 ======
                print(f"[DEBUG] /close 명령어 호출 - channel.id: {channel.id}, channel.name: {channel.name}, category: {getattr(channel.category, 'name', None)}")
                print(f"[DEBUG] BotSelector.active_channels: {self.active_channels}")
                for char_name, bot in self.character_bots.items():
                    print(f"[DEBUG] {char_name} active_channels: {getattr(bot, 'active_channels', None)}")
                # ====== 디버깅 로그 추가 끝 ======

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
                if hasattr(self, 'remove_channel'):
                    self.remove_channel(channel.id)

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
                value=f"{self.settings_manager.daily_limit} messages",
                inline=False
            )

            admin_roles = []
            for role_id in self.settings_manager.admin_roles:
                role = interaction.guild.get_role(role_id)
                if role:
                    admin_roles.append(role.name)

            embed.add_field(
                name="Admin Roles",
                value="\n".join(admin_roles) if admin_roles else "None",
                inline=False
            )

            if self.settings_manager.is_admin(interaction.user):
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
            if not self.settings_manager.is_admin(interaction.user):
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

            self.settings_manager.add_admin_role(role.id)
            await interaction.response.send_message(f"{role.name} role has been added to the admin role.", ephemeral=True)

        @self.tree.command(
            name="ranking",
            description="Check character affinity and chat ranking"
        )
        async def ranking_command(interaction: discord.Interaction):
            try:
                view = RankingView(self.db)

                # 초기 임베드 생성
                embed = discord.Embed(
                    title="🏆 Ranking System",
                    description="Please select the ranking you want to check from the menu below.",
                    color=discord.Color.blue()
                )

                embed.add_field(
                    name="Kagari Chat Ranking 🌸",
                    value="Top 20 users by affinity and chat count with Kagari",
                    inline=False
                )
                embed.add_field(
                    name="Eros Chat Ranking 💝",
                    value="Top 20 users by affinity and chat count with Eros",
                    inline=False
                )
                embed.add_field(
                    name="Elysia Chat Ranking 🦋",
                    value="Top 20 users by affinity and chat count with Elysia",
                    inline=False
                )
                embed.add_field(
                    name="Total Chat Ranking 👑",
                    value="Top 20 users by total affinity and chat count across all characters",
                    inline=False
                )

                # followup.send 대신 response.send_message 사용
                await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

            except Exception as e:
                print(f"Error in ranking command: {e}")
                import traceback
                print(traceback.format_exc())
                if not interaction.response.is_done():
                    await interaction.response.send_message("An error occurred while loading ranking information.", ephemeral=True)
                else:
                    await interaction.followup.send("An error occurred while loading ranking information.", ephemeral=True)

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

                if not affinity_info:
                    current_affinity = 0
                    affinity_grade = get_affinity_grade(0)
                    daily_message_count = 0
                    last_message_time = "N/A"
                else:
                    current_affinity = affinity_info['emotion_score']
                    affinity_grade = get_affinity_grade(current_affinity)
                    daily_message_count = affinity_info['daily_message_count']
                    last_message_time = affinity_info.get('last_message_time', "N/A")

                # Grade emoji mapping
                grade_emoji = {
                    "Rookie": "🌱",
                    "Iron": "⚔️",
                    "Bronze": "🥉",
                    "Silver": "🥈",
                    "Gold": "🏆"
                }

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
                    value=f"```{current_affinity} points```",
                    inline=True
                )
                embed.add_field(
                    name="Today's Conversations",
                    value=f"```{daily_message_count} times```",
                    inline=True
                )
                embed.add_field(
                    name="Affinity Grade",
                    value=f"{grade_emoji.get(affinity_grade, '❓')} **{affinity_grade}**",
                    inline=True
                )

                if last_message_time and last_message_time != "N/A":
                    try:
                        # last_message_time이 이미 datetime 객체인지 확인
                        if isinstance(last_message_time, datetime):
                            formatted_time = last_message_time.strftime('%Y-%m-%d %H:%M')
                        else:
                            # 문자열인 경우 기존 로직 사용
                            last_time_str = last_message_time.split('.')[0]
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
                            value=f"```{last_message_time}```",
                            inline=False
                        )
                else:
                    embed.add_field(
                        name="Last Conversation",
                        value=f"```N/A```",
                        inline=False
                    )

                print("Embed created")

                # Get the correct image URL from config.py
                char_image_url = CHARACTER_IMAGES.get(current_bot.character_name)
                if char_image_url:
                    embed.set_thumbnail(url=char_image_url)

                await interaction.response.send_message(embed=embed)

                print("[Affinity check complete]")

            except Exception as e:
                print(f"Error during affinity command: {e}")
                import traceback
                print(traceback.format_exc())
                try:
                    await interaction.response.send_message("An error occurred while loading affinity information.", ephemeral=True)
                except:
                    await interaction.followup.send("An error occurred while loading affinity information.", ephemeral=True)

        @self.tree.command(
            name="remove_admin_role",
            description="Remove the administrator role"
        )
        @app_commands.default_permissions(administrator=True)
        async def remove_admin_role(interaction: discord.Interaction, role: discord.Role):
            if not interaction.user.guild_permissions.administrator:
                await interaction.response.send_message("This command can only be used in server channels.", ephemeral=True)
                return

            if role.id in self.settings_manager.admin_roles:
                self.settings_manager.remove_admin_role(role.id)
                await interaction.response.send_message(f"{role.name} role has been removed from the admin role.", ephemeral=True)
            else:
                await interaction.response.send_message(f"{role.name} role is not an admin role.", ephemeral=True)

        @self.tree.command(
            name="set_daily_limit",
            description="Setting a daily message limit (admin only)"
        )
        @app_commands.default_permissions(administrator=True)
        async def set_daily_limit(interaction: discord.Interaction, limit: int):
            if not self.settings_manager.is_admin(interaction.user):
                await interaction.response.send_message("This command can only be used in server channels.", ephemeral=True)
                return

            if limit < 1:
                await interaction.response.send_message("The limit must be 1 or more.", ephemeral=True)
                return

            self.settings_manager.set_daily_limit(limit)

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
            description="Check the cards you have."
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
                    await interaction.response.send_message("This command can only be used in character chat channels.", ephemeral=True)
                    return

                character_name = current_bot.character_name
                user_id = int(interaction.user.id)  # 항상 int로 변환

                # 해당 캐릭터의 카드만 조회
                user_cards = [card for card in get_user_cards(user_id) if card['character_name'] == character_name]

                # 티어별 카드 분류
                tier_counts = {'C': 0, 'B': 0, 'A': 0, 'S': 0}
                total_cards = {'C': 10, 'B': 7, 'A': 5, 'S': 4}
                for card in user_cards:
                    card_info = get_card_info_by_id(character_name, card['card_id'])
                    if card_info and 'tier' in card_info:
                        tier = card_info['tier']
                        if tier in tier_counts:
                            tier_counts[tier] += 1

                # --- 진행 바를 각 티어별 카드 수에 맞게 동적으로 생성 ---
                collection_embed = discord.Embed(
                    title=f"🎴 {character_name} Card Collection Progress",
                    description=f"Your current collection status for {character_name} cards",
                    color=discord.Color.gold()
                )
                tier_emojis = {'C': '🥉', 'B': '🥈', 'A': '🥇', 'S': '🏆'}
                bar_emojis = {'C': '🟩', 'B': '🟦', 'A': '🟨', 'S': '🟪'}
                def get_progress_bar(count, total, color_emoji, empty_emoji='⬜'):
                    filled = count
                    empty = total - count
                    return color_emoji * filled + empty_emoji * empty
                for tier in ['C', 'B', 'A', 'S']:
                    count = tier_counts[tier]
                    total = total_cards[tier]
                    emoji = tier_emojis.get(tier, '')
                    color = bar_emojis.get(tier, '⬜')
                    progress_bar = get_progress_bar(count, total, color)
                    collection_embed.add_field(
                        name=f"{tier} Tier {emoji}",
                        value=f"{progress_bar}  ({count}/{total})",
                        inline=True
                    )
                total_collected = sum(tier_counts.values())
                total_possible = sum(total_cards.values())
                total_percent = (total_collected / total_possible) * 100 if total_possible > 0 else 0
                collection_embed.add_field(
                    name="Total Collection",
                    value=f"**{total_collected} / {total_possible}**  ({total_percent:.1f}%)",
                    inline=False
                )
                collection_embed.add_field(name="", value="━━━━━━━━━━━━━━━━━━", inline=False)

                # collection_embed를 전송
                await interaction.response.send_message(embed=collection_embed, ephemeral=True)

                if not user_cards:
                    await interaction.followup.send(f"You don't have any {character_name} cards yet.", ephemeral=True)
                    return

                # 카드 슬라이더 뷰
                card_info_dict = {
                    card['card_id']: get_card_info_by_id(character_name, card['card_id'])
                    for card in user_cards if get_card_info_by_id(character_name, card['card_id'])
                }

                def get_tier_order(card_id):
                    tier = card_info_dict.get(card_id, {}).get('tier', 'Unknown')
                    tier_order = {'C': 0, 'B': 1, 'A': 2, 'S': 3}
                    return tier_order.get(tier, 4)

                sorted_cards = sorted(list(card_info_dict.keys()), key=get_tier_order)

                if not sorted_cards:
                     await interaction.followup.send(f"You don't seem to have any valid cards for {character_name}.", ephemeral=True)
                     return

                slider_view = CardSliderView(
                    user_id=user_id,
                    cards=sorted_cards,
                    character_name=character_name,
                    card_info_dict=card_info_dict,
                    db=self.db  # db 인스턴스 전달
                )

                # Send the initial message using the new method
                await slider_view.initial_message(interaction)

            except Exception as e:
                print(f"Error in mycard command: {str(e)}")
                import traceback
                print(traceback.format_exc())
                # Ensure the interaction is responded to, even if an error occurs
                if not interaction.response.is_done():
                    await interaction.response.send_message(
                        "An error occurred while loading your cards. Please try again.",
                        ephemeral=True
                    )
                else:
                    await interaction.followup.send(
                        "An error occurred while loading your cards. Please try again.",
                        ephemeral=True
                    )

        @self.tree.command(
            name="check_language",
            description="Check the language of the current channel."
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
            """Initiates the story mode UI."""
            # 현재 채널의 캐릭터 찾기 (스토리 모드는 캐릭터별로 제한할 수도 있음)
            current_bot = None
            for char_name, bot in self.character_bots.items():
                if interaction.channel.id in bot.active_channels:
                    current_bot = bot
                    break
            # 호감도 체크 (Silver 이상만 허용)
            affinity = 0
            affinity_grade = "Rookie"
            if current_bot:
                affinity_info = current_bot.db.get_affinity(interaction.user.id, current_bot.character_name)
                affinity = affinity_info['emotion_score'] if affinity_info else 0
                affinity_grade = get_affinity_grade(affinity)
            if affinity < 50:
                embed = discord.Embed(
                    title="⚠️ Story Mode Locked",
                    description="Story mode is only available for Silver level users.",
                    color=discord.Color.red()
                )
                embed.add_field(
                    name="Current Level",
                    value=f"**{affinity_grade}**",
                    inline=True
                )
                embed.add_field(
                    name="Required Level",
                    value="**Silver**",
                    inline=True
                )
                embed.add_field(
                    name="How to Unlock",
                    value="Keep chatting with the character to increase your affinity level!",
                    inline=False
                )
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return
            view = NewStoryView(self)
            await interaction.response.send_message("Please select a character to start the story with.", view=view, ephemeral=True)

        @self.tree.command(
            name="reset_story",
            description="Admin: Reset story progress for a user."
        )
        @app_commands.default_permissions(administrator=True)
        @app_commands.describe(
            user="The user whose story progress you want to reset.",
            character="The character whose story you want to reset."
        )
        @app_commands.choices(character=[
            discord.app_commands.Choice(name=name, value=name) for name in CHARACTER_INFO.keys()
        ])
        async def reset_story_command(interaction: discord.Interaction, user: discord.Member, character: str):
            """Resets story progress for a specific user and character."""
            try:
                success = self.db.reset_story_progress(user.id, character)
                if success:
                    await interaction.response.send_message(f"Successfully reset story progress for {user.display_name} with {character}.", ephemeral=True)
                else:
                    await interaction.response.send_message(f"Failed to reset story progress for {user.display_name} with {character}.", ephemeral=True)
            except Exception as e:
                print(f"Error in reset_story_command: {e}")
                traceback.print_exc()
                await interaction.response.send_message("An error occurred while resetting story progress.", ephemeral=True)

        async def story_character_select_callback(self, interaction: discord.Interaction, selected_char: str):
            # 이 함수는 더 이상 사용되지 않지만, 다른 곳에서 호출될 경우를 대비해 유지합니다.
            await interaction.response.send_message(f"Selected: {selected_char}. This part of story is under construction.", ephemeral=True)

        @self.tree.command(
            name="message_add",
            description="Admin: Manually add a user's message count."
        )
        @app_commands.default_permissions(administrator=True)
        async def message_add_command(interaction: discord.Interaction, target: discord.Member, count: int, character: str):
            if not self.settings_manager.is_admin(interaction.user):
                await interaction.response.send_message("Available to admins only.", ephemeral=True)
                return
            # DB에 메시지 추가 (실제 메시지 insert)
            for _ in range(count):
                self.db.add_message(
                    0,              # channel_id
                    target.id,      # user_id
                    character,      # character_name
                    "user",        # role
                    "[Add an admin message]",  # content
                    "en"           # language
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
            if not self.settings_manager.is_admin(interaction.user):
                await interaction.response.send_message("Available to admins only.", ephemeral=True)
                return
            # affinity 직접 수정
            try:
                # 락이 필요 없다면 아래 한 줄만!
                from datetime import datetime
                self.db.update_affinity(target.id, character, last_message="(reset)", last_message_time=datetime.utcnow(), score_change=value, highest_milestone=0)
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
            if not self.settings_manager.is_admin(interaction.user):
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
            if not self.settings_manager.is_admin(interaction.user):
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
                    self.db.add_message(
                        0,              # channel_id
                        target.id,      # user_id
                        "system",      # character_name
                        "user",        # role
                        "[Add an admin message]",  # content
                        "en"           # language
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
            class HelpSelect(discord.ui.Select):
                def __init__(self):
                    options = [
                        discord.SelectOption(
                            label="How to Use",
                            value="how_to_use",
                            description="Basic guide for using the chatbot",
                            emoji="🤖"
                        ),
                        discord.SelectOption(
                            label="Affinity & Level",
                            value="affinity",
                            description="Learn about the affinity system",
                            emoji="❤️"
                        ),
                        discord.SelectOption(
                            label="Card System",
                            value="card",
                            description="Card collection and rewards",
                            emoji="🎴"
                        ),
                        discord.SelectOption(
                            label="Story Mode",
                            value="story",
                            description="Story mode guide",
                            emoji="📖"
                        ),
                        discord.SelectOption(
                            label="Ranking",
                            value="ranking",
                            description="Ranking system guide",
                            emoji="🏆"
                        ),
                        discord.SelectOption(
                            label="FAQ",
                            value="faq",
                            description="Frequently asked questions",
                            emoji="❓"
                        )
                    ]
                    super().__init__(placeholder="Choose a topic", options=options)

                async def callback(self, interaction2: discord.Interaction):
                    topic = self.values[0]
                    embed = discord.Embed(color=discord.Color.blurple())
                    if topic == "how_to_use":
                        embed.title = "🤖 How to Use the Chatbot"
                        embed.add_field(name="How to Talk with Characters", value="- Use /bot to create a private chat channel with a character like Kagari or Eros.\n- Supports multilingual input (EN/JP/ZH), responses are always in English.\n- Characters react to your emotions, tone, and depth of conversation.\n🧠 Pro Tip: The more emotionally engaging your dialogue, the faster you grow your bond!", inline=False)
                    elif topic == "affinity":
                        embed.title = "❤️ Affinity & Level System"
                        embed.add_field(name="Level Up with Conversations", value="- Rookie (0-9): Basic chat only.\n- ⚔️ Iron (10-29): Unlock basic emotions & C-rank cards.\n- 🥉 Bronze (30-49): B/C cards & more emotions.\n- Silver (50-99): A/B/C cards & story mood options.\n- Gold (100+): S-tier chance & story unlock.\nCommand: /affinity to check your current level, progress, and daily message stats.", inline=False)
                    elif topic == "card":
                        embed.title = "🎴 Card & Reward System"
                        embed.add_field(name="How to Earn & Collect Cards", value="You earn cards through:\n- 🗣️ Emotional chat: score-based triggers (10/20/30)\n- 🎮 Story Mode completions\n- ❤️ Affinity milestone bonuses\nCard Tier Example (Gold user):\n- A (20%) / B (30%) / C (50%)\n- Gold+ user: S (10%) / A (20%) / B (30%) / C (40%)\n📜 Use /mycard to view your collection.", inline=False)
                    elif topic == "story":
                        embed.title = "📖 Story Mode Guide"
                        embed.add_field(name="How to Play", value="1. Reach Gold level (100+ affinity)\n2. Use /story to start\n3. Choose a chapter\n4. Make choices that affect the story\n\nRewards:\n- Story completion rewards\n- Special card rewards\n- Bonus affinity points", inline=False)
                    elif topic == "ranking":
                        embed.title = "🏆 Ranking System"
                        embed.add_field(name="How Rankings Work", value="Rankings are based on:\n1. Total affinity across all characters\n2. Daily conversation count\n3. Story mode completion\n\nCheck your rank with /ranking", inline=False)
                    elif topic == "faq":
                        embed.title = "❓ FAQ"
                        embed.add_field(name="Q1: How can I get higher grade cards?", value="A: Card grades depend on your affinity level:\n- Iron: Mainly C cards (80%), small chance for B (20%)\n- Bronze: Better chance for B cards (30%)\n- Silver: Can get A cards (20%)\n- Gold: Can get S cards (10%)\nHigher affinity = better card chances!", inline=False)
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

                # 2. 호감도 체크 (Silver 이상만 허용)
                affinity_info = current_bot.db.get_affinity(interaction.user.id, current_bot.character_name)
                affinity = affinity_info['emotion_score'] if affinity_info else 0
                affinity_grade = get_affinity_grade(affinity)
                if affinity < 50:
                    embed = discord.Embed(
                        title="⚠️ Roleplay Mode Locked",
                        description="Roleplay mode is only available for Silver level users.",
                        color=discord.Color.red()
                    )
                    embed.add_field(
                        name="Current Level",
                        value=f"**{affinity_grade}**",
                        inline=True
                    )
                    embed.add_field(
                        name="Required Level",
                        value="**Silver**",
                        inline=True
                    )
                    embed.add_field(
                        name="How to Unlock",
                        value="Keep chatting with the character to increase your affinity level!",
                        inline=False
                    )
                    await interaction.response.send_message(embed=embed, ephemeral=True)
                    return

                # 3. 모달 표시
                modal = RoleplayModal(current_bot.character_name)
                await interaction.response.send_modal(modal)

            except Exception as e:
                print(f"Error in /roleplay: {e}")
                await interaction.response.send_message("An error occurred, please contact your administrator.", ephemeral=True)

        # --- 인벤토리 및 선물 명령어 통합 ---

        @self.tree.command(name="inventory", description="Check your gift inventory.")
        async def inventory(interaction: discord.Interaction):
            user_gifts = self.db.get_user_gifts(interaction.user.id)

            if not user_gifts:
                embed = discord.Embed(
                    title=f"{interaction.user.display_name}'s Inventory",
                    description="You don't have any gifts yet.\nComplete daily quests to earn gifts!",
                    color=discord.Color.blue()
                )
                embed.set_thumbnail(url=interaction.user.display_avatar.url)
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return

            paginator = InventoryPaginator(interaction, user_gifts, self.db)
            initial_embed = await paginator.get_page_embed()
            await interaction.response.send_message(embed=initial_embed, view=paginator, ephemeral=True)

        # gift_autocomplete를 원래의 데이터베이스 조회 로직으로 복원
        async def gift_autocomplete(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
            try:
                # get_db_manager()를 통해 안정적으로 DB 인스턴스 획득
                db = get_db_manager()
                user_gifts = db.get_user_gifts(interaction.user.id)

                choices = []
                if user_gifts:
                    for gift_id, quantity in user_gifts:
                        details = get_gift_details(gift_id)
                        if details:
                            choice_name = f"{details['name']} (Owned: {quantity})"
                            if current.lower() in choice_name.lower():
                                choices.append(app_commands.Choice(name=choice_name, value=gift_id))

                return choices[:25]
            except Exception as e:
                print(f"[gift_autocomplete FINAL ERROR] {e}")
                import traceback
                print(traceback.format_exc())
                return []

        @self.tree.command(name="gift", description="Give a gift to the character in the current channel.")
        @app_commands.describe(item="Select the gift to send.", quantity="Enter the quantity to send. (Default: 1)")
        @app_commands.autocomplete(item=gift_autocomplete)
        async def gift(interaction: discord.Interaction, item: str, quantity: int = 1):
            """
            현재 채널의 캐릭터에게 선물을 줍니다.
            """
            await interaction.response.defer(ephemeral=True)
            try:
                print(f"[DEBUG] /gift called: user_id={interaction.user.id}, item={item}, quantity={quantity}")
                # 스토리 모드 세션 체크 등 기존 코드...
                from story_mode import story_sessions
                print(f"[DEBUG] story_sessions keys: {list(story_sessions.keys())}")
                session = story_sessions.get(interaction.channel.id)
                print(f"[DEBUG] session: {session}")
                # ... (생략) ...
                # 현재 채널의 캐릭터 봇 찾기
                current_bot = None
                for char_name, bot in self.character_bots.items():
                    if interaction.channel.id in bot.active_channels:
                        current_bot = bot
                        break
                if not current_bot:
                    print("[DEBUG] current_bot not found for channel")
                    await interaction.followup.send("You can't give gifts in this channel. Please use this in a character's chat channel.", ephemeral=True)
                    return
                character = current_bot.character_name
                user_id = interaction.user.id
                print(f"[DEBUG] character={character}, user_id={user_id}")
                # 보유 수량 체크
                user_gifts = self.db.get_user_gifts(user_id)
                print(f"[DEBUG] user_gifts: {user_gifts}")
                gift_info = next((g for g in user_gifts if g[0] == item), None)
                if not gift_info:
                    print(f"[DEBUG] User does not own gift: {item}")
                    await interaction.followup.send("You don't own this gift. Please check your inventory.", ephemeral=True)
                    return
                owned_quantity = gift_info[1]
                print(f"[DEBUG] owned_quantity: {owned_quantity}")
                if quantity <= 0 or quantity > owned_quantity:
                    print(f"[DEBUG] Invalid quantity: {quantity}")
                    await interaction.followup.send(f"Please check the quantity. You currently have {owned_quantity}.", ephemeral=True)
                    return
                # DB 차감
                print(f"[DEBUG] Attempting to use_user_gift: {item}, quantity={quantity}")
                result = self.db.use_user_gift(user_id, item, quantity)
                print(f"[DEBUG] use_user_gift result: {result}")
                if not result:
                    await interaction.followup.send("The gift could not be used. Please check the quantity or contact the administrator..", ephemeral=True)
                    return
                # 선물 정보/리액션
                gift_details = get_gift_details(item)
                print(f"[DEBUG] gift_details: {gift_details}")
                reaction_message = get_gift_reaction(character, item)
                gift_emoji = get_gift_emoji(item)
                is_preferred = check_gift_preference(character, item)
                base_affinity = 5 if is_preferred else -1
                affinity_change = base_affinity * quantity
                print(f"[DEBUG] is_preferred: {is_preferred}, affinity_change: {affinity_change}")
                # 호감도 업데이트
                affinity_info = self.db.get_affinity(user_id, character)
                highest_milestone = 0
                if affinity_info and 'highest_milestone_achieved' in affinity_info:
                    highest_milestone = affinity_info['highest_milestone_achieved']
                self.db.update_affinity(
                    user_id=user_id,
                    character_name=character,
                    last_message=f"Gave {quantity} of '{gift_details['name']}'.",
                    last_message_time=datetime.utcnow(),
                    score_change=affinity_change,
                    highest_milestone=highest_milestone
                )
                print(f"[DEBUG] Affinity updated.")
                # 임베드 생성 및 전송
                embed = discord.Embed(
                    title=f"🎁 To {character}",
                    description=f"You gave **{gift_details['name']} x{quantity}**.",
                    color=discord.Color.gold()
                )
                embed.add_field(name="Affinity Change", value=f"`{affinity_change:+}`", inline=False)
                embed.add_field(name=f"{character}'s Reaction", value=f"💬 *{reaction_message}*", inline=False)
                embed.set_thumbnail(url=interaction.user.display_avatar.url)
                embed.set_footer(text="Your gift has been delivered!")
                await interaction.followup.send(embed=embed, ephemeral=True)
                print(f"[DEBUG] Gift embed sent.")
                # 캐릭터 봇 리액션
                if current_bot:
                    await current_bot.send_reaction_message(
                        channel_id=interaction.channel_id,
                        text=f"*{reaction_message}*",
                        emoji=gift_emoji
                    )
                print(f"[DEBUG] send_reaction_message sent.")
                # 모든 단계가 성공하면 마지막에 선물 차감
                print(f"[DEBUG] Attempting to use_user_gift: {item}, quantity={quantity}")
                result = self.db.use_user_gift(user_id, item, quantity)
                print(f"[DEBUG] use_user_gift result: {result}")
                if not result:
                    await interaction.followup.send("The gift could not be used. Please check the quantity or contact the administrator..", ephemeral=True)
                    return
            except Exception as e:
                print(f"[ERROR] /gift 명령어 처리 중 오류: {e}")
                import traceback
                print(traceback.format_exc())
                try:
                    await interaction.followup.send("에러가 발생했습니다. 관리자에게 문의하세요.", ephemeral=True)
                except Exception as e2:
                    print(f"[ERROR] followup.send 실패: {e2}")

        async def give_gift_autocomplete(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
            choices = []
            for gift_id, details in ALL_GIFTS.items():
                choice_name = f"{details['name']} ({gift_id})"
                if current.lower() in choice_name.lower():
                    choices.append(app_commands.Choice(name=choice_name, value=gift_id))
            return choices[:25]

        @self.tree.command(name="give_gift", description="[Admin] Give a gift to a specific user.")
        @app_commands.describe(user="The user to receive the gift", gift_id="The ID of the gift to give", quantity="The quantity to give")
        @app_commands.checks.has_permissions(administrator=True)
        @app_commands.autocomplete(gift_id=give_gift_autocomplete)
        async def give_gift(interaction: discord.Interaction, user: discord.User, gift_id: str, quantity: int = 1):
            if gift_id not in ALL_GIFTS:
                await interaction.response.send_message(f"Gift ID '{gift_id}' does not exist.", ephemeral=True)
                return

            if quantity < 1:
                await interaction.response.send_message("Quantity must be 1 or greater.", ephemeral=True)
                return

            self.db.add_user_gift(user.id, gift_id, quantity)

            gift_info = get_gift_details(gift_id)
            embed = discord.Embed(
                title="🎁 Gift Given",
                description=f"Successfully gave {quantity} of **{gift_info['name']}** to {user.mention}.",
                color=discord.Color.green()
            )
            await interaction.response.send_message(embed=embed)

        @self.tree.command(
            name="quest",
            description="View All Quests"
        )
        async def quest_command(interaction: discord.Interaction):
            try:
                user_id = interaction.user.id
                self.db.update_login_streak(user_id)
                # 먼저 interaction 응답을 지연시킴
                await interaction.response.defer(ephemeral=True)

                quest_status = await self.get_quest_status(user_id)
                embed = self.create_quest_embed(user_id, quest_status)
                view = QuestView(user_id, quest_status, self)

                # followup으로 메시지 전송
                await interaction.followup.send(embed=embed, view=view, ephemeral=True)

            except Exception as e:
                print(f"Error in quest command: {e}")
                import traceback
                print(traceback.format_exc())
                try:
                    await interaction.followup.send("Error fetching quest information.", ephemeral=True)
                except:
                    # followup도 실패하면 일반 메시지로 전송
                    await interaction.channel.send("Error fetching quest information.")

        # /serve 자동완성: 음료 이름이 아닌, 레시피(재료 리스트)만 노출
        async def serve_autocomplete(interaction: discord.Interaction, current: str):
            session = story_sessions.get(interaction.channel.id)
            if not session or session.get('character_name') != 'Eros' or session.get('stage_num') != 1:
                return []
            chapter_info = get_chapter_info('Eros', 1)
            menu = chapter_info.get('menu', [])
            # 각 메뉴의 재료 리스트를 쉼표+공백으로 연결해서 반환 (중복 없이)
            recipes = [', '.join(drink['recipe']) for drink in menu]
            # 현재 입력값이 포함된 레시피만 필터링 (대소문자 무관)
            filtered = [r for r in recipes if current.lower() in r.lower()]
            return [discord.app_commands.Choice(name=r, value=r) for r in (filtered if filtered else recipes)]

        # /serve 명령어 등록부에 자동완성 연결
        @self.tree.command(
            name="serve",
            description="Serve a drink to the current customer in Eros story mode (Chapter 1 or 2 only)."
        )
        @app_commands.describe(drink="Enter the drink ingredients (comma or space separated)")
        @app_commands.autocomplete(drink=serve_autocomplete)
        async def serve_command(interaction: discord.Interaction, drink: str):
            session = story_sessions.get(interaction.channel.id)
            if not session or session.get('character_name') != 'Eros' or session.get('stage_num') not in [1, 2]:
                await interaction.response.send_message(
                    "This command can only be used in Eros story Chapter 1 or 2.",
                    ephemeral=True
                )
                return
            await handle_serve_command(self, interaction, session['character_name'], drink)

        # /serve_team 자동완성 함수 (챕터2 전용)
        async def serve_team_character_autocomplete(interaction: discord.Interaction, current: str):
            session = story_sessions.get(interaction.channel.id)
            if not session or session.get('character_name') != 'Eros' or session.get('stage_num') != 2:
                return []
            chapter_info = get_chapter_info('Eros', 2)
            answer_map = chapter_info.get('answer_map', {})
            characters = list(answer_map.keys())
            served = session.get('served_characters', set())
            filtered = [c for c in characters if c not in served and current.lower() in c.lower()]
            # 옵션 순서 무작위 섞기
            random.shuffle(filtered)
            if not filtered:
                filtered = [c for c in characters if c not in served]
                random.shuffle(filtered)
            return [discord.app_commands.Choice(name=c, value=c) for c in filtered]

        async def serve_team_drink_autocomplete(interaction: discord.Interaction, current: str):
            session = story_sessions.get(interaction.channel.id)
            if not session or session.get('character_name') != 'Eros' or session.get('stage_num') != 2:
                return []
            chapter_info = get_chapter_info('Eros', 2)
            drink_list = chapter_info.get('drink_list', [])
            drinks = [d['name'] for d in drink_list]
            filtered = [d for d in drinks if current.lower() in d.lower()]
            # 옵션 순서 무작위 섞기
            random.shuffle(filtered)
            if not filtered:
                filtered = drinks[:]
                random.shuffle(filtered)
            return [discord.app_commands.Choice(name=d, value=d) for d in filtered]

        @self.tree.command(
            name="serve_team",
            description="Serve a drink to a team member in Eros story mode (Chapter 2 only)."
        )
        @app_commands.describe(character="Team member name", drink="Drink name")
        @app_commands.autocomplete(character=serve_team_character_autocomplete, drink=serve_team_drink_autocomplete)
        async def serve_team_command(interaction: discord.Interaction, character: str, drink: str):
            session = story_sessions.get(interaction.channel.id)
            if not session or session.get('character_name') != 'Eros' or session.get('stage_num') != 2:
                await interaction.response.send_message(
                    "This command can only be used in Eros story Chapter 2.", ephemeral=True
                )
                return
            chapter_info = get_chapter_info('Eros', 2)
            answer_map = chapter_info.get('answer_map', {})
            drink_list = chapter_info.get('drink_list', [])
            total_characters = len(answer_map)
            # --- 캐릭터별 리액션 메시지 ---
            # (character_reactions는 이미 전역에 선언되어 있다고 가정)
            correct_drink = answer_map.get(character)
            is_correct = (drink.strip().lower() == correct_drink.strip().lower())
            # --- 제출한 캐릭터 기록 (정답/오답 무관) ---
            if 'served_characters' not in session:
                session['served_characters'] = set()
            session['served_characters'].add(character)
            served_count = len(session['served_characters'])
            # --- 리액션 임베드 (진행상황 포함) ---
            if is_correct:
                reaction_text = character_reactions.get(character, {}).get("success", f"Great! {character} is delighted with the {drink}!")
                color = discord.Color.green()
            else:
                reaction_text = character_reactions.get(character, {}).get("fail", f"Hmm... {character} doesn't seem to like the {drink}. Try again!")
                color = discord.Color.red()
            embed = discord.Embed(
                title=f"{character}'s Reaction ({served_count}/{total_characters})",
                description=reaction_text,
                color=color
            )
            await interaction.response.send_message(embed=embed)
            # --- 모든 캐릭터에게 음료를 지급한 경우 결과/리워드 임베드 출력 ---
            if served_count == total_characters:
                # 리워드 지급 (커먼 2개)
                from gift_manager import GIFT_RARITY, get_gifts_by_rarity_v2, get_gift_details
                rarity_str = GIFT_RARITY['COMMON']
                gift_ids = get_gifts_by_rarity_v2(rarity_str, 2)
                user_id = interaction.user.id
                if gift_ids:
                    for gift_id in gift_ids:
                        self.db.add_user_gift(user_id, gift_id, 1)
                    gift_names = [get_gift_details(g)['name'] for g in gift_ids if get_gift_details(g)]
                    reward_text = f"You received: **{', '.join(gift_names)}**\nCheck your inventory with `/inventory`."
                else:
                    reward_text = "You received: **No gifts available for this rarity.**\nCheck your inventory with `/inventory`."
                complete_embed = discord.Embed(
                    title="🍯 All Drinks Delivered!",
                    description=f"You have served all {total_characters} team members!\n{reward_text}",
                    color=discord.Color.gold()
                )
                await interaction.followup.send(embed=complete_embed)
                # 챕터2 클리어 기록 및 챕터3 오픈 안내
                self.db.complete_story_stage(user_id, 'Eros', 2)
                transition_embed = discord.Embed(
                    title="🔓 Chapter 3 is now unlocked!",
                    description="Congratulations! You have unlocked Chapter 3: Find the Café Culprit!\nUse `/story` to start Chapter 3!",
                    color=discord.Color.orange()
                )
                await interaction.followup.send(embed=transition_embed)
                # 세션 종료 처리
                session["is_active"] = False
            story_sessions[interaction.channel.id] = session

        @self.tree.command(
            name="reset_quest",
            description="[Admin] Reset all quest claim records for a user."
        )
        @app_commands.default_permissions(administrator=True)
        async def reset_quest_command(interaction: discord.Interaction, target: discord.Member):
            """
            관리자용: 해당 유저의 모든 퀘스트 보상 수령 기록을 리셋합니다.
            """
            try:
                result = self.db.reset_quest_claims(target.id)
                if result:
                    await interaction.response.send_message(f"{target.display_name}님의 퀘스트 보상 수령 기록이 초기화되었습니다.", ephemeral=True)
                else:
                    await interaction.response.send_message(f"퀘스트 리셋에 실패했습니다.", ephemeral=True)
            except Exception as e:
                await interaction.response.send_message(f"에러 발생: {e}", ephemeral=True)

    def create_quest_embed(self, user_id: int, quest_status: dict) -> discord.Embed:
        """
        퀘스트 현황을 보여주는 임베드를 생성합니다.
        """
        embed = discord.Embed(
            title="📜 Quest Board",
            description=(
                "You can check the progress of all quests in real time, including the 7-day login streak and story mode milestones.\n"
                "\nCheck out daily, weekly, level-up, and story quests and earn rewards!"
            ),
            color=discord.Color.dark_gold()
        )
        embed.set_footer(text="Click the [Claim] button to claim rewards for completed quests.")

        # 일일 퀘스트
        daily_quests_str = self.format_daily_quests(quest_status['daily'])
        embed.add_field(name="📅 Daily Quests", value=daily_quests_str, inline=False)

        # 주간 퀘스트
        weekly_quests_str = self.format_weekly_quests(quest_status['weekly'])
        embed.add_field(name="🗓️ Weekly Quests", value=weekly_quests_str, inline=False)

        # 레벨업 퀘스트
        levelup_quests_str = self.format_levelup_quests(quest_status['levelup'])
        embed.add_field(name="🚀 Level-up Quests", value=levelup_quests_str, inline=False)

        # 스토리 퀘스트
        story_quests_str = self.format_story_quests(quest_status['story'])
        embed.add_field(name="📖 Story Quests", value=story_quests_str, inline=False)

        # 하단에 Terms of Service, Privacy Policy 하이퍼링크 추가
        embed.add_field(
            name="\u200b",  # 빈 이름(공백) 필드로 하단에 추가
            value="[Terms of Service](https://spotzero.tartagames.com/privacy/terms)  |  [Privacy Policy](https://spotzero.tartagames.com/privacy)",
            inline=False
        )

        return embed

    async def get_quest_status(self, user_id: int) -> dict:
        """사용자의 퀘스트 상태를 조회합니다."""
        try:
            # 일일 퀘스트 상태
            daily_quests = await self.check_daily_quests(user_id)

            # 주간 퀘스트 상태
            weekly_quests = await self.check_weekly_quests(user_id)

            # 레벨업 퀘스트 상태
            levelup_quests = await self.check_levelup_quests(user_id)

            # 스토리 퀘스트 상태
            story_quests = await self.check_story_quests(user_id)

            return {
                'daily': daily_quests,
                'weekly': weekly_quests,
                'levelup': levelup_quests,
                'story': story_quests
            }
        except Exception as e:
            print(f"Error getting quest status: {e}")
            return {'daily': [], 'weekly': [], 'levelup': [], 'story': []}

    async def check_daily_quests(self, user_id: int) -> list:
        """일일 퀘스트 상태를 affinity DB의 실시간 값으로 정확히 반영합니다."""
        quests = []

        # 1. 대화 20회 퀘스트
        total_daily_messages = 0
        for char in ['Kagari', 'Eros', 'Elysia']:
            affinity_info = self.db.get_affinity(user_id, char)
            if affinity_info:
                total_daily_messages += affinity_info.get('daily_message_count', 0)
        quest_id = 'daily_conversation'
        # --- claimed 값은 반드시 quest_claims 테이블 기준으로만 판단 ---
        claimed = self.db.is_quest_claimed(user_id, quest_id)
        reward_name = None
        if claimed:
            user_gifts = self.db.get_user_gifts(user_id)
            reward_name = user_gifts[0][0] if user_gifts else None
        quests.append({
            'id': quest_id,
            'name': '💬 Daily Conversation',
            'description': f'({total_daily_messages}/20)',
            'progress': min(total_daily_messages, 20),
            'max_progress': 20,
            'completed': total_daily_messages >= 20,
            'reward': f'Random Common Item x1' + (f'\nGifts received: {reward_name}' if reward_name else ''),
            'claimed': claimed
        })

        # 2. 호감도 +5 퀘스트
        affinity_gain = self.db.get_today_affinity_gain(user_id)
        quest_id = 'daily_affinity_gain'
        # --- claimed 값은 반드시 quest_claims 테이블 기준으로만 판단 ---
        claimed = self.db.is_quest_claimed(user_id, quest_id)
        reward_name = None
        if claimed:
            user_gifts = self.db.get_user_gifts(user_id)
            reward_name = user_gifts[0][0] if user_gifts else None
        quests.append({
            'id': quest_id,
            'name': '💖 Affinity +5',
            'description': f'({affinity_gain}/5)',
            'progress': min(affinity_gain, 5),
            'max_progress': 5,
            'completed': affinity_gain >= 5,
            'reward': f'Random Common Item x1' + (f'\nGifts received: {reward_name}' if reward_name else ''),
            'claimed': claimed
        })

        return quests

    async def check_weekly_quests(self, user_id: int) -> list:
        """주간 퀘스트 상태를 확인합니다."""
        quests = []

        # 1. 7일 연속 로그인 퀘스트
        login_streak = self.db.get_login_streak(user_id)
        quest_id = 'weekly_login'
        # --- weekly claimed는 이번주 내 수령 여부로 판단 ---
        claimed = self.db.is_weekly_quest_claimed(user_id, quest_id)
        quests.append({
            'id': quest_id,
            'name': '📅 7-Day Login Streak',
            'description': f'Login for 7 consecutive days ({login_streak}/7)',
            'progress': min(login_streak, 7),
            'max_progress': 7,
            'completed': login_streak >= 7,
            'reward': 'Random Epic Items x2',
            'claimed': claimed
        })
        # 2. 카드 공유 퀘스트
        card_shared = self.db.get_card_shared_this_week(user_id)
        quest_id = 'weekly_share'
        # --- weekly claimed는 이번주 내 수령 여부로 판단 ---
        claimed = self.db.is_weekly_quest_claimed(user_id, quest_id)
        quests.append({
            'id': quest_id,
            'name': '🔗 Share Your Cards',
            'description': f'Share a card from your collection ({card_shared}/1)',
            'progress': card_shared,
            'max_progress': 1,
            'completed': card_shared >= 1,
            'reward': 'Random Common Item x1',
            'claimed': claimed
        })
        return quests

    async def check_levelup_quests(self, user_id: int) -> list:
        """레벨업 퀘스트 상태를 확인합니다."""
        quests = []
        try:
            # 각 캐릭터별 골드 달성 퀘스트만 생성
            characters = ['Kagari', 'Eros', 'Elysia']
            for character in characters:
                affinity_info = self.db.get_affinity(user_id, character)
                if not affinity_info:
                    continue
                current_score = affinity_info['emotion_score']
                current_grade = get_affinity_grade(current_score)
                # 골드 달성 여부만 체크
                has_claimed = self.db.has_levelup_flag(user_id, character, 'Gold')
                quest = {
                    'id': f'levelup_{character}_Gold',
                    'name': f'⭐ {character} Level-up',
                    'description': f'Reach Gold level with {character}',
                    'progress': 1 if current_grade == 'Gold' else 0,
                    'max_progress': 1,
                    'completed': (current_grade == 'Gold') and not has_claimed,
                    'reward': 'Epic Items x3',
                    'claimed': has_claimed,
                    'character': character,
                    'current_grade': current_grade
                }
                quests.append(quest)
        except Exception as e:
            print(f"Error checking levelup quests: {e}")
        return quests

    async def claim_levelup_reward(self, user_id: int, quest_id: str) -> tuple[bool, str]:
        try:
            parts = quest_id.split('_')
            if len(parts) != 3:
                return False, "Invalid levelup quest ID"
            character = parts[1]
            grade = parts[2]
            if grade != 'Gold':
                return False, "Only Gold level-up quests are supported."
            self.db.add_levelup_flag(user_id, character, grade)
            from gift_manager import get_gifts_by_rarity_v2, get_gift_details, GIFT_RARITY
            # 유저가 이미 받은 아이템 목록 조회
            user_gifts = set(g[0] for g in self.db.get_user_gifts(user_id))
            reward_candidates = get_gifts_by_rarity_v2(GIFT_RARITY['EPIC'], 3)
            available_rewards = [item for item in reward_candidates if item not in user_gifts]
            if not available_rewards:
                return False, "You have already received all possible rewards for this quest!"
            import random
            selected_rewards = random.sample(available_rewards, min(3, len(available_rewards)))
            for gift_id in selected_rewards:
                self.db.add_user_gift(user_id, gift_id, 1)
            self.db.claim_quest(user_id, quest_id)
            reward_names = [get_gift_details(g)['name'] + ' x1' for g in selected_rewards]
            return True, ", ".join(reward_names)
        except Exception as e:
            print(f"Error claiming levelup reward: {e}")
            import traceback
            traceback.print_exc()
            return False, "Error claiming levelup reward"


    def format_daily_quests(self, quests: list) -> str:
        if quests is None or len(quests) == 0:
            # 기본 예시 퀘스트를 반환 (진행도 0)
            return "⏳ 💬 Daily Conversation\n`[□□□□□□□□□□]` (0/20)\n└ Reward: Random Common Item x1"
        quest_lines = []
        for q in quests:
            if q.get('claimed'):
                status_icon = "✅"
            elif q.get('completed'):
                status_icon = "🎁"
            else:
                status_icon = "⏳"
            title = f"**{status_icon} {q['name']}**"
            progress_bar = self.create_progress_bar(q['progress'], q['max_progress'])
            progress_info = f"{progress_bar} `({q['progress']}/{q['max_progress']})`"
            if q.get('claimed'):
                reward_info = f"└ `Reward: {q['reward']}`"
            elif q.get('completed'):
                reward_info = f"**└ ⬇️ Claim your reward with the button below!**"
            else:
                reward_info = f"└ `Reward: {q['reward']}`"
            quest_lines.append(f"{title}\n{progress_info}\n{reward_info}")
        return "\n\n".join(quest_lines)

    def format_weekly_quests(self, quests: list) -> str:
        if quests is None or len(quests) == 0:
            return "⏳ 📅 7-Day Login Streak\n🔥 ⬜⬜⬜⬜⬜⬜⬜ (0/7)\n└ Reward: Random Epic Items x2"
        quest_lines = []
        for q in quests:
            if q.get('claimed'):
                status_icon = "✅"
            elif q.get('completed'):
                status_icon = "🎁"
            else:
                status_icon = "⏳"
            title = f"**{status_icon} {q['name']}**"
            if q['id'] == 'weekly_login':
                progress_info = self.create_streak_progress_bar(q['progress'], q['max_progress']) + f" `({q['progress']}/{q['max_progress']})`"
            else:
                progress_bar = self.create_progress_bar(q['progress'], q['max_progress'])
                progress_info = f"{progress_bar} `({q['progress']}/{q['max_progress']})`"
            if q.get('claimed'):
                reward_info = f"└ `Reward: {q['reward']}`"
            elif q.get('completed'):
                reward_info = f"**└ ⬇️ Claim your reward with the button below!**"
            else:
                reward_info = f"└ `Reward: {q['reward']}`"
            quest_lines.append(f"{title}\n{progress_info}\n{reward_info}")
        return "\n\n".join(quest_lines)

    def format_levelup_quests(self, quests: list) -> str:
        if quests is None or len(quests) == 0:
            return "⏳ ⭐ Level-up Quest\n`[□□□□□□□□□□]` (0/1)\n└ Reward: Common Item x1"
        quest_lines = []
        for q in quests:
            if q.get('claimed'):
                status_icon = "✅"
            elif q.get('completed'):
                status_icon = "🎁"
            else:
                status_icon = "⏳"
            title = f"**{status_icon} {q['name']}** - {q['description']}"
            if q.get('claimed'):
                reward_info = f"└ `Reward: {q['reward']}`"
            elif q.get('completed'):
                reward_info = f"**└ ⬇️ Claim your reward with the button below!**"
            else:
                reward_info = f"└ `Reward: {q['reward']}`"
            quest_lines.append(f"{title}\n{reward_info}")
        return "\n\n".join(quest_lines)

    def format_story_quests(self, quests: list) -> str:
        if quests is None or len(quests) == 0:
            return "⏳ 📖 Story Quest\n`[□□□□□□□□□□]` (0/1)\n└ Reward: Epic Gifts x3"
        quest_lines = []
        for q in quests:
            if q.get('claimed'):
                status_icon = "✅"
            elif q.get('completed'):
                status_icon = "🎁"
            else:
                status_icon = "⏳"
            title = f"**{status_icon} {q['name']}**"
            if 'progress' in q and 'max_progress' in q:
                progress_bar = self.create_progress_bar(q['progress'], q['max_progress'])
                progress_info = f"{progress_bar} `({q['progress']}/{q['max_progress']})`"
            else:
                progress_info = q['description']
            if q.get('claimed'):
                reward_info = f"└ `Reward: {q['reward']}`"
            elif q.get('completed'):
                reward_info = f"**└ ⬇️ Claim your reward with the button below!**"
            else:
                reward_info = f"└ `Reward: {q['reward']}`"
            quest_lines.append(f"{title}\n{progress_info}\n{reward_info}")
        return "\n\n".join(quest_lines)

    def create_progress_bar(self, current: int, maximum: int, length: int = 10) -> str:
        if maximum == 0:
            return "`[ PROGRESS_BAR_ERROR ]`"
        progress = int((current / maximum) * length)
        return f"`[{'■' * progress}{'□' * (length - progress)}]`"

    def create_streak_progress_bar(self, current: int, maximum: int = 7) -> str:
        """
        연속 로그인 퀘스트를 위한 시각적 진행 바를 생성합니다.
        (예: 🔥✅✅✅⬜⬜⬜⬜)
        """
        if current >= maximum:
            return f"🔥 {'✅' * maximum}"

        streaks = '✅' * current
        remaining = '⬜' * (maximum - current)
        return f"🔥 {streaks}{remaining}"

    async def claim_quest_reward(self, user_id: int, quest_id: str) -> tuple[bool, str]:
        """퀘스트 보상을 지급하고, 수령 상태를 기록합니다."""
        try:
            if quest_id.startswith('daily_'):
                return await self.claim_daily_reward(user_id, quest_id)
            elif quest_id.startswith('weekly_'):
                return await self.claim_weekly_reward(user_id, quest_id)
            elif quest_id.startswith('levelup_'):
                return await self.claim_levelup_reward(user_id, quest_id)
            elif quest_id.startswith('story_'):
                return await self.claim_story_reward(user_id, quest_id)
            else:
                return False, "Invalid quest ID"

        except Exception as e:
            print(f"Error claiming quest reward: {e}")
            return False, "Error claiming reward"

    async def claim_daily_reward(self, user_id: int, quest_id: str) -> tuple[bool, str]:
        print(f"[DEBUG] claim_daily_reward called with user_id: {user_id}, quest_id: '{quest_id}'")
        
        # 이미 오늘 수령했는지 확인 (날짜 기준)
        if self.db.is_quest_claimed(user_id, quest_id):
            print(f"[DEBUG] Quest already claimed today for user_id: {user_id}, quest_id: '{quest_id}'")
            return False, "You have already claimed this reward today!"
        
        # 기존: quest_type 파싱 및 reward lookup
        # 패치: quest_id를 그대로 reward lookup에 사용
        daily_rewards = {
            'daily_conversation': {'name': 'Random Common Item', 'rarity': 'COMMON', 'quantity': 1},
            'daily_affinity_gain': {'name': 'Random Common Item', 'rarity': 'COMMON', 'quantity': 1},
        }
        reward_info = daily_rewards.get(quest_id)
        print(f"[DEBUG] Available daily rewards keys: {list(daily_rewards.keys())}")
        print(f"[DEBUG] Reward lookup result: {reward_info}")
        if not reward_info:
            print(f"[DEBUG] Reward not found for quest_id: '{quest_id}'. Returning 'This is an unknown quest.'")
            return False, "This is an unknown quest."

        try:
            # 유저가 이미 받은 아이템 목록 조회
            user_gifts = set(g[0] for g in self.db.get_user_gifts(user_id))
            # 보상 후보 아이템 리스트
            from gift_manager import get_gifts_by_rarity_v2, get_gift_details, GIFT_RARITY
            reward_candidates = get_gifts_by_rarity_v2(GIFT_RARITY[reward_info['rarity'].upper()], reward_info['quantity'])
            # 아직 받지 않은 아이템만 후보로 남김
            available_rewards = [item for item in reward_candidates if item not in user_gifts]
            if not available_rewards:
                return False, "You have already received all possible rewards for this quest!"
            # 랜덤 지급
            import random
            reward_id = random.choice(available_rewards)
            self.db.add_user_gift(user_id, reward_id, 1)
            self.db.claim_quest(user_id, quest_id)
            # --- 일일 퀘스트 진행/보상 기록 추가 ---
            self.db.record_daily_quest_progress(user_id, quest_id, completed=True, reward_claimed=True)
            reward_name = get_gift_details(reward_id)['name']
            return True, f"{reward_name} x1"
        except Exception as e:
            print(f"Error claiming daily reward: {e}")
            import traceback
            traceback.print_exc()
            return False, "An error occurred while trying to earn Daily Rewards."

    async def claim_weekly_reward(self, user_id: int, quest_id: str) -> tuple[bool, str]:
        print(f"[DEBUG] claim_weekly_reward called with user_id: {user_id}, quest_id: '{quest_id}'")
        rest = quest_id.replace('weekly_', '', 1)
        type_parts = rest.rsplit('_', 1)
        quest_type = type_parts[0]
        print(f"[DEBUG] Parsed quest_type: '{quest_type}'")

        rewards = {
            'login': ('Epic Item', 'EPIC', 2),
            'share': ('Common Item', 'COMMON', 1)
        }
        print(f"[DEBUG] Available weekly rewards keys: {list(rewards.keys())}")

        reward_name, reward_rarity, reward_quantity = rewards.get(quest_type, (None, None, 0))
        print(f"[DEBUG] Reward lookup result: name={reward_name}, rarity={reward_rarity}, quantity={reward_quantity}")

        if not reward_name:
            print(f"[DEBUG] Reward not found for quest_type: '{quest_type}'. Returning 'This is an unknown quest.'")
            return False, "This is an unknown quest."

        try:
            # 주간 퀘스트: 이번 주 내에 이미 수령했는지 체크
            if self.db.is_weekly_quest_claimed(user_id, quest_id):
                return False, "You have already claimed this weekly reward!"
            from gift_manager import get_gifts_by_rarity_v2, get_gift_details, GIFT_RARITY
            reward_candidates = get_gifts_by_rarity_v2(GIFT_RARITY[reward_rarity.upper()], reward_quantity)
            if not reward_candidates:
                return False, "No rewards available for this quest!"
            import random
            reward_id = random.choice(reward_candidates)
            self.db.add_user_gift(user_id, reward_id, 1)
            self.db.claim_quest(user_id, quest_id)
            reward_name = get_gift_details(reward_id)['name']
            return True, f"{reward_name} x1"
        except Exception as e:
            print(f"Error claiming weekly reward: {e}")
            import traceback
            traceback.print_exc()
            return False, "Error earning weekly rewards."

    async def claim_story_reward(self, user_id: int, quest_id: str) -> tuple[bool, str]:
        try:
            parts = quest_id.split('_')
            if len(parts) != 3:
                return False, "Invalid story quest ID"
            character = parts[1]
            quest_type = parts[2]
            from gift_manager import get_gifts_by_rarity_v2, get_gift_details, GIFT_RARITY
            user_gifts = set(g[0] for g in self.db.get_user_gifts(user_id))
            reward_candidates = get_gifts_by_rarity_v2(GIFT_RARITY['EPIC'], 3)
            available_rewards = [item for item in reward_candidates if item not in user_gifts]
            if not available_rewards:
                return False, "You have already received all possible rewards for this quest!"
            import random
            selected_rewards = random.sample(available_rewards, min(3, len(available_rewards)))
            # Kagari 스토리 퀘스트 (3챕터 완료)
            if character == 'kagari' and quest_type == 'all_chapters':
                completed_chapters = self.db.get_completed_chapters(user_id, 'Kagari')
                if len(completed_chapters) < 3:
                    return False, "You need to complete all 3 chapters of Kagari's story first"
                if self.db.is_story_quest_claimed(user_id, 'Kagari', 'all_chapters'):
                    return False, "You have already claimed this reward"
                for gift_id in selected_rewards:
                    self.db.add_user_gift(user_id, gift_id, 1)
                self.db.claim_story_quest(user_id, 'Kagari', 'all_chapters')
                reward_names = [get_gift_details(g_id)['name'] for g_id in selected_rewards]
                return True, f"Congratulations! You completed all Kagari story chapters! You received: **{', '.join(reward_names)}**"
            # Eros 스토리 퀘스트 (3챕터 완료)
            if character == 'eros' and quest_type == 'all_chapters':
                completed_chapters = self.db.get_completed_chapters(user_id, 'Eros')
                if len(completed_chapters) < 3:
                    return False, "You need to complete all 3 chapters of Eros's story first"
                if self.db.is_story_quest_claimed(user_id, 'Eros', 'all_chapters'):
                    return False, "You have already claimed this reward"
                for gift_id in selected_rewards:
                    self.db.add_user_gift(user_id, gift_id, 1)
                self.db.claim_story_quest(user_id, 'Eros', 'all_chapters')
                reward_names = [get_gift_details(g_id)['name'] for g_id in selected_rewards]
                return True, f"Congratulations! You completed all Eros story chapters! You received: **{', '.join(reward_names)}**"
            # Elysia 스토리 퀘스트 (1챕터 완료)
            if character == 'elysia' and quest_type == 'all_chapters':
                completed_chapters = self.db.get_completed_chapters(user_id, 'Elysia')
                if len(completed_chapters) < 1:
                    return False, "You need to complete chapter 1 of Elysia's story first"
                if self.db.is_story_quest_claimed(user_id, 'Elysia', 'all_chapters'):
                    return False, "You have already claimed this reward"
                for gift_id in selected_rewards:
                    self.db.add_user_gift(user_id, gift_id, 1)
                self.db.claim_story_quest(user_id, 'Elysia', 'all_chapters')
                reward_names = [get_gift_details(g_id)['name'] for g_id in selected_rewards]
                return True, f"Congratulations! You completed Elysia's story! You received: **{', '.join(reward_names)}**"
            return False, "Unknown story quest"
        except Exception as e:
            print(f"Error claiming story reward: {e}")
            import traceback
            traceback.print_exc()
            return False, "An error occurred while claiming story reward"

    async def on_message(self, message: discord.Message):
        user_id = message.author.id
        self.db.update_login_streak(user_id)
        if message.author.bot or not message.guild:
            return

        # --- Story Mode Message Handling ---
        if any(f'-s{i}-' in message.channel.name for i in range(1, 10)):
            await process_story_message(self, message)
            return
        # --- End of Story Mode Handling ---

        # 롤플레잉 채널 처리
        if message.channel.name.startswith("rp-"):
            session = self.roleplay_sessions.get(message.channel.id)
            if session and session.get("is_active"):
                await self.process_roleplay_message(message, session)
            return

        # 기존 1:1 채널 처리
        active_character, character_name = self.get_character_for_channel(message.channel.id)
        if not active_character:
            return

        # --- Quest System: Daily Login Streak ---
        try:
            today = datetime.now(timezone('Asia/Seoul')).date()
            last_login = self.db.get_last_login_date(message.author.id)
            if last_login is None or last_login < today:
                self.db.update_login_streak(message.author.id)
        except Exception as e:
            print(f"Error updating login streak for {message.author.id}: {e}")

        # --- Normal Message Processing ---
        if active_character:
            await active_character.process_normal_message(message)

    # 롤플레잉 모드 전용 답장 함수
    async def process_roleplay_message(self, message, session):
        import asyncio
        import discord
        import re
        from config import CHARACTER_PROMPTS
        user_role = session.get("user_role", "")
        character_role = session.get("character_role", "")
        story_line = session.get("story_line", "")
        character_name = session.get("character_name", "")

        # 턴 카운트 관리
        if "turn_count" not in session:
            session["turn_count"] = 1
        else:
            session["turn_count"] += 1

        turn_str = f"({session['turn_count']}/30)"

        # 캐릭터별 성격 프롬프트 추가
        character_prompt = CHARACTER_PROMPTS.get(character_name, "")

        # system prompt 생성
        system_prompt = (
            f"{character_prompt}\n"
            f"You are now roleplaying as {character_name}.\n"
            f"User's role: {user_role}\n"
            f"Your role: {character_role}\n"
            f"Scenario: {story_line}\n"
            "Stay in character and continue the romantic roleplay. "
            "Do NOT break character. Do NOT mention you are an AI. "
            "Respond naturally and emotionally, as if you are really in this situation. "
            f"Always start your reply with '{character_name}: ' as prefix. "
            f"At the end of your reply, add '{turn_str}'. "
            "All replies must be in English."
        )

        # 대화 기록 세션에 저장
        if "history" not in session:
            session["history"] = []
        session["history"].append({"role": "user", "content": message.content})

        # OpenAI 호출
        messages = [
            {"role": "system", "content": system_prompt}
        ] + session["history"]
        ai_response = await self.get_ai_response(messages)

        # 답장에 캐릭터 이름 prefix 보장 (혹시라도 누락될 경우)
        if not ai_response.strip().startswith(f"{character_name}:"):
            ai_response = f"{character_name}: {ai_response.strip()}"

        # (n/30) 중복 방지: 여러 번 등장하면 1개만 남기고 모두 제거
        ai_response = re.sub(r"(\(\d{1,2}/30\))(?=.*\(\d{1,2}/30\))", "", ai_response)
        if not re.search(r"\(\d{1,2}/30\)", ai_response):
            ai_response = f"{ai_response} {turn_str}"

        await message.channel.send(ai_response)
        session["history"].append({"role": "assistant", "content": ai_response})

        # 30턴 종료 처리
        if session["turn_count"] >= 30:
            embed = discord.Embed(
                title="💌 Roleplay Session Ended",
                description="All 30 turns of your special date are over!\n\nThank you for sharing this story together. See you next time!",
                color=discord.Color.pink()
            )
            await message.channel.send(embed=embed)
            await asyncio.sleep(3)
            try:
                await message.channel.delete()
            except Exception as e:
                print(f"Channel deletion failed: {e}")

    def remove_channel(self, channel_id):
        # 활성화된 채널 목록에서 제거
        for bot in self.character_bots.values():
            bot.remove_channel(channel_id)
        if hasattr(self, 'remove_channel'):
            self.remove_channel(channel_id)

    def get_random_card(self, character_name: str, user_id: int) -> tuple[str, str]:
        """랜덤 카드 획득"""
        try:
            card_info = CHARACTER_CARD_INFO.get(character_name, {})
            if not card_info:
                return None, None
            user_cards = self.db.get_user_cards(user_id, character_name)
            user_card_ids = user_cards  # user_cards는 이미 카드ID 문자열 리스트임
            available_cards = []
            for card_id in card_info:
                if card_id not in user_card_ids:
                    available_cards.append(card_id)
            if not available_cards:
                return None, None
            import random
            card_id = random.choice(available_cards)
            return None, card_id
        except Exception as e:
            print(f"Error in get_random_card: {e}")
            return None, None

# === get_story_content 함수 추가 ===
def get_story_content(character_name, chapter_number):
    """
    config.py의 STORY_CHAPTERS에서 캐릭터명과 챕터 번호로 스토리 내용을 반환합니다.
    """
    chapters = STORY_CHAPTERS.get(character_name, [])
    for chapter in chapters:
        if chapter.get('id') == chapter_number:
            return chapter
    return None

class CardSliderView(discord.ui.View):
    def __init__(self, user_id, cards, character_name, card_info_dict, db):
        super().__init__(timeout=180)
        self.user_id = user_id
        self.cards = cards
        self.character_name = character_name
        self.card_info_dict = card_info_dict
        self.db = db  # db 인스턴스 저장
        self.index = 0
        self.total = len(cards)

        self.prev_button = discord.ui.Button(label="Previous", style=discord.ButtonStyle.secondary, emoji="⬅️")
        self.prev_button.callback = self.on_previous
        self.add_item(self.prev_button)

        self.next_button = discord.ui.Button(label="Next", style=discord.ButtonStyle.secondary, emoji="➡️")
        self.next_button.callback = self.on_next
        self.add_item(self.next_button)

        self.share_button = ShareCardButton(
            user_id=self.user_id,
            character_name=self.character_name,
            card_id=self.cards[self.index],
            card_info_dict=self.card_info_dict
        )
        self.add_item(self.share_button)

    async def create_embed(self):
        card_id = self.cards[self.index]
        card_info = self.card_info_dict.get(card_id, {})

        # 게임같은 느낌의 임베드 생성
        embed = discord.Embed(
            title=f"🎴 {self.character_name} Card Collection",
            description=f"**{self.index + 1}** / **{self.total}** Cards Collected",
            color=discord.Color.purple()
        )

        # 티어 정보와 이모지
        tier = card_info.get('tier', 'Unknown')
        tier_emojis = {'C': '🥉', 'B': '🥈', 'A': '🥇', 'S': '🏆'}
        tier_emoji = tier_emojis.get(tier, '❓')

        # 티어별 색상 설정
        tier_colors = {
            'C': discord.Color.light_grey(),
            'B': discord.Color.blue(), 
            'A': discord.Color.gold(),
            'S': discord.Color.purple()
        }
        embed.color = tier_colors.get(tier, discord.Color.purple())

        # 카드 넘버링 (총 유저 카드 지급 순서)
        card_number = get_card_issued_number(self.character_name, card_id)

        # 게임 스타일 필드들
        embed.add_field(
            name="⚔️ **Tier**", 
            value=f"```{tier} {tier_emoji}```", 
            inline=True
        )
        embed.add_field(
            name="🆔 **Card ID**", 
            value=f"```{card_id.upper()}```", 
            inline=True
        )
        embed.add_field(
            name="🔢 **Card Number**", 
            value=f"```#{card_number}```", 
            inline=True
        )
        embed.add_field(
            name="✨ **Ability**", 
            value="```????```", 
            inline=False
        )

        # 구분선 추가
        embed.add_field(name="", value="━━━━━━━━━━━━━━━━━━", inline=False)

        # 카드 설명 (있는 경우에만)
        if card_info.get("description"):
            embed.add_field(
                name="📖 **Description**",
                value=f"*{card_info.get('description', 'No description available.')}*",
                inline=False
            )

        # 카드 이미지 설정
        image_url = card_info.get("image_path")
        if image_url:
            cache_bust_url = f"{image_url}?t={int(time.time())}"
            embed.set_image(url=cache_bust_url)
        else:
            embed.set_footer(text="🎴 Card image not found")

        # 게임 스타일 푸터
        embed.set_footer(text=f"🎮 {self.character_name} Card Collection • Use ⬅️ ➡️ to navigate")

        return embed

    async def initial_message(self, interaction: discord.Interaction):
        embed = await self.create_embed()
        await interaction.followup.send(embed=embed, view=self, ephemeral=True)

    async def on_previous(self, interaction: discord.Interaction):
        await interaction.response.defer()
        self.index = (self.index - 1 + self.total) % self.total
        self.share_button.update_card(self.cards[self.index])
        embed = await self.create_embed()
        await interaction.edit_original_response(embed=embed, view=self)

    async def on_next(self, interaction: discord.Interaction):
        await interaction.response.defer()
        self.index = (self.index + 1) % self.total
        self.share_button.update_card(self.cards[self.index])
        embed = await self.create_embed()
        await interaction.edit_original_response(embed=embed, view=self)

class ShareCardButton(discord.ui.Button):
    def __init__(self, user_id, character_name, card_id, card_info_dict):
        super().__init__(label="Share Card", style=discord.ButtonStyle.primary, emoji="🎴")
        self.user_id = user_id
        self.character_name = character_name
        self.card_id = card_id
        self.card_info_dict = card_info_dict

    def update_card(self, card_id):
        self.card_id = card_id

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("This action is not for you.", ephemeral=True)
            return

        # self.view를 통해 CardSliderView의 db에 접근
        if not hasattr(self.view, 'db'):
            print("Error: The parent view (CardSliderView) does not have a 'db' attribute.")
            await interaction.response.send_message("An internal error occurred while sharing the card.", ephemeral=True)
            return

        card_info = self.card_info_dict.get(self.card_id, {})

        # 게임 스타일 공유 임베드
        share_embed = discord.Embed(
            title=f"🎴 Card Share",
            description=f"{interaction.user.mention} shared a **{self.character_name}** card!",
            color=discord.Color.blue()
        )

        # 티어 정보 추가
        tier = card_info.get('tier', 'Unknown')
        tier_emojis = {'C': '🥉', 'B': '🥈', 'A': '🥇', 'S': '🏆'}
        tier_emoji = tier_emojis.get(tier, '❓')

        share_embed.add_field(
            name="⚔️ **Tier**", 
            value=f"{tier} {tier_emoji}", 
            inline=True
        )
        share_embed.add_field(
            name="🆔 **Card ID**", 
            value=self.card_id.upper(), 
            inline=True
        )

        # 카드 넘버링 추가
        card_number = get_card_issued_number(self.character_name, self.card_id)
        share_embed.add_field(
            name="🔢 **Card Number**", 
            value=f"#{card_number}", 
            inline=True
        )

        image_path = card_info.get("image_path", "")
        if image_path:
            share_embed.set_image(url=image_path)

        share_embed.set_footer(text=f"🎮 {self.character_name} Card Collection")

        await interaction.response.send_message(embed=share_embed)

        # 카드 공유 기록 (퀘스트용)
        try:
            # self.view.db를 사용하여 DB에 기록
            self.view.db.record_card_share(interaction.user.id, self.character_name, self.card_id)
        except Exception as e:
            print(f"Error recording card share: {e}")


import psycopg2
from psycopg2 import pool
from config import DATABASE_CONFIG

# PostgreSQL 연결 풀 생성
connection_pool = psycopg2.pool.SimpleConnectionPool(
    1,  # 최소 연결 수
    10, # 최대 연결 수
    host=DATABASE_CONFIG['host'],
    database=DATABASE_CONFIG['database'],
    user=DATABASE_CONFIG['user'],
    password=DATABASE_CONFIG['password'],
    port=DATABASE_CONFIG['port'],
    sslmode=DATABASE_CONFIG['sslmode']
)

def get_user_cards(user_id: str) -> list:
    """PostgreSQL에서 사용자의 모든 카드 정보를 가져오며, 각 카드의 발급 순번(issued_number)도 포함합니다."""
    try:
        conn = connection_pool.getconn()
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT character_name, card_id, obtained_at, emotion_score_at_obtain,
                (
                    SELECT COUNT(*)
                    FROM user_cards AS uc2
                    WHERE uc2.character_name = uc1.character_name
                      AND uc2.card_id = uc1.card_id
                      AND uc2.obtained_at <= uc1.obtained_at
                ) AS issued_number
            FROM user_cards AS uc1
            WHERE user_id = %s
            ORDER BY character_name, obtained_at
            """, (user_id,)
        )
        cards = []
        for row in cursor.fetchall():
            cards.append({
                'character_name': row[0],
                'card_id': row[1],
                'obtained_at': row[2],
                'emotion_score_at_obtain': row[3],
                'issued_number': row[4]
            })
        cursor.close()
        connection_pool.putconn(conn)
        return cards
    except Exception as e:
        print(f"Error getting user cards: {str(e)}")
        return []

def get_card_issued_number(character_name: str, card_id: str) -> int:
    """카드의 발급 번호를 PostgreSQL DB에서 가져옵니다."""
    try:
        conn = connection_pool.getconn()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT COUNT(*) + 1
            FROM user_cards
            WHERE character_name = %s AND card_id = %s
        """, (character_name, card_id))

        issued_number = cursor.fetchone()[0]
        cursor.close()
        connection_pool.putconn(conn)
        return issued_number
    except Exception as e:
        print(f"Error getting card issued number: {str(e)}")
        return 1

class CardNavButton(discord.ui.Button):
    def __init__(self, label, slider_view, direction):
        super().__init__(label=label, style=discord.ButtonStyle.secondary)
        self.slider_view = slider_view
        self.direction = direction

    async def callback(self, interaction: discord.Interaction):
        self.slider_view.index = (self.slider_view.index + self.direction) % self.slider_view.total
        await self.slider_view.update_message(interaction)

# --- 인벤토리 및 선물하기 기능 관련 클래스 ---

class InventoryPaginator(discord.ui.View):
    def __init__(self, interaction: discord.Interaction, user_gifts: list, db_manager: DatabaseManager):
        super().__init__(timeout=180)
        self.interaction = interaction
        self.user_gifts = user_gifts
        self.db = db_manager
        self.current_page = 0
        self.items_per_page = 9 # 3x3 grid

    async def get_page_embed(self) -> discord.Embed:
        user = self.interaction.user
        embed = discord.Embed(
            title=f"{user.display_name}'s Inventory",
            color=discord.Color.blue()
        )
        embed.set_thumbnail(url=user.display_avatar.url)

        start_index = self.current_page * self.items_per_page
        end_index = start_index + self.items_per_page
        current_gifts = self.user_gifts[start_index:end_index]

        if not current_gifts:
            embed.description = "You don't have any gifts yet.\nComplete daily quests to earn gifts!"
            return embed

        description = "Check your gifts and give them to characters to increase your affinity.\n\n"
        for gift_id, quantity in current_gifts:
            gift_info = get_gift_details(gift_id)
            emoji = get_gift_emoji(gift_id)
            description += f"{emoji} **{gift_info['name']}** (x{quantity})\n"

        embed.description = description
        total_pages = ceil(len(self.user_gifts) / self.items_per_page)
        embed.set_footer(text=f"Page {self.current_page + 1}/{total_pages}")

        self.update_buttons(total_pages)
        return embed

    def update_buttons(self, total_pages: int):
        self.children[0].disabled = self.current_page == 0 # type: ignore
        self.children[1].disabled = self.current_page >= total_pages - 1 # type: ignore

    @discord.ui.button(label="◀ Previous", style=discord.ButtonStyle.grey)
    async def previous_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.current_page -= 1
        embed = await self.get_page_embed()
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="Next ▶", style=discord.ButtonStyle.grey)
    async def next_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.current_page += 1
        embed = await self.get_page_embed()
        await interaction.response.edit_message(embed=embed, view=self)


class GiftSelect(discord.ui.Select):
    def __init__(self, user_gifts: list):
        options = []
        for gift_id, quantity in user_gifts:
            gift_info = get_gift_details(gift_id)
            emoji = get_gift_emoji(gift_id)
            options.append(
                discord.SelectOption(
                    label=f"{gift_info['name']} (x{quantity})",
                    description=gift_info['description'],
                    value=gift_id,
                    emoji=emoji
                )
            )

        super().__init__(
            placeholder="Select an item to give as a gift....",
            min_values=1,
            max_values=1,
            options=options
        )

    async def callback(self, interaction: discord.Interaction):
        self.view.selected_gift = self.values[0] # type: ignore
        self.disabled = True
        self.view.children[1].disabled = False # type: ignore
        await interaction.response.edit_message(view=self.view)


class GiftConfirmButton(discord.ui.Button['GiftView']):
    def __init__(self):
        super().__init__(label="Send Gift", style=discord.ButtonStyle.green, disabled=True)

    async def callback(self, interaction: discord.Interaction):
        view = self.view
        user_id = interaction.user.id
        gift_id = view.selected_gift
        character_name = view.character_name

        success = view.db.use_user_gift(user_id, gift_id)

        if not success:
            await interaction.response.edit_message(content="Failed to use the gift. Please try again.", view=None, embed=None)
            return

        gift_info = get_gift_details(gift_id)
        is_preferred = check_gift_preference(character_name, gift_id)

        affinity_change = 5 if is_preferred else 1

        view.db.update_affinity(
            user_id=user_id,
            character_name=character_name,
            score_change=affinity_change,
            last_message=f"Gave {gift_info['name']}",
            last_message_time=datetime.utcnow()
        )

        embed = discord.Embed(
            title=f"🎁 Gift sent to {character_name}!",
            description=f"You gave **{gift_info['name']}** and your affinity changed by **{affinity_change:+}**.",
            color=discord.Color.pink()
        )
        await interaction.response.edit_message(embed=embed, view=None)

        thank_you_message = get_gift_reaction(character_name, gift_id)
        await interaction.channel.send(f"{interaction.user.mention}, {thank_you_message}")

        # Check for level up after affinity change
        await self.check_and_give_levelup_rewards(interaction, user_id, character_name)

    async def check_and_give_levelup_rewards(self, interaction: discord.Interaction, user_id: int, character_name: str):
        """
        Checks for affinity level-ups and sends rewards accordingly.
        Prevents duplicate card rewards.
        """
        try:
            affinity_info = self.db.get_affinity(user_id, character_name)
            if not affinity_info:
                return

            current_score = affinity_info['emotion_score']

            # This assumes that the affinity score *before* the gift was lower.
            # A more robust solution would be to pass the old score as an argument.
            # For now, let's check against all thresholds lower than current score.

            for threshold in AFFINITY_THRESHOLDS:
                if current_score >= threshold and (current_score - affinity_info.get('last_change', 1)) < threshold:

                    # --- Level up detected ---
                    prev_grade = get_affinity_grade(current_score - affinity_info.get('last_change', 5))
                    new_grade = get_affinity_grade(current_score)

                    if new_grade == prev_grade: continue

                    # 1. Send Level Up Embed
                    level_up_embed = self.create_level_up_embed(character_name, prev_grade, new_grade)
                    await interaction.channel.send(embed=level_up_embed)

                    # 2. Check for and give card reward
                    card_id_to_give = milestone_to_card_id(threshold, character_name)
                    if not card_id_to_give:
                        continue

                    user_cards = self.db.get_user_cards(user_id, character_name)
                    has_card = any(card[0] == card_id_to_give for card in user_cards)

                    if not has_card:
                        card_embed = discord.Embed(
                            title="🎉 Get a new card!",
                            description=f"Congratulations! {character_name} has sent you a token of affection.\nYou got a {get_card_info_by_id(card_id_to_give)['tier']} tier card!\nClick claim to receive your card.",
                            color=discord.Color.gold()
                        )
                        card_info = get_card_info_by_id(card_id_to_give)
                        if card_info and card_info.get('image_url_small'):
                           card_embed.set_image(url=f"{CLOUDFLARE_IMAGE_BASE_URL}/{card_info['image_url_small']}")

                        view = CardClaimView(user_id, character_name, card_id_to_give, self.db)
                        await interaction.channel.send(embed=card_embed, view=view)

                    break # Process only one level up at a time
        except Exception as e:
            print(f"Error checking for level up rewards: {e}")
            traceback.print_exc()

    def create_level_up_embed(self, character_name: str, prev_grade: str, new_grade: str) -> discord.Embed:
        """레벨업 임베드 생성"""
        # ... (이 함수는 character_bot.py에서 가져오거나 여기에 정의되어 있어야 합니다)
        char_info = CHARACTER_INFO.get(character_name, {})
        char_color = char_info.get('color', discord.Color.purple())

        level_messages = {
            ("Rookie", "Iron"): f"Congratulations! {character_name} has started to take an interest in you!",
            ("Iron", "Bronze"): f"Great job! {character_name} is opening up and becoming a bit more comfortable with you.",
            ("Bronze", "Silver"): f"Nice! {character_name} is now showing real trust and warmth in your conversations!",
            ("Silver", "Gold"): f"Amazing! {character_name} really enjoys talking with you! You could become great friends!"
        }

        embed = discord.Embed(
            title="🎉 Affinity Level Up!",
            description=level_messages.get((prev_grade, new_grade), "Your relationship has grown stronger!"),
            color=char_color
        )

        level_icons = AFFINITY_LEVELS # Ensure this is defined or imported
        embed.add_field(
            name="Level Change",
            value=f"{level_icons.get(prev_grade,{}).get('emoji','')} {prev_grade} → {level_icons.get(new_grade,{}).get('emoji','')} {new_grade}",
            inline=False
        )

        char_image_url = CHARACTER_IMAGES.get(character_name)
        if char_image_url:
            embed.set_thumbnail(url=char_image_url)

        return embed

class GiftView(discord.ui.View):
    def __init__(self, bot: "BotSelector", character_name: str, user_gifts: list):
        super().__init__(timeout=180)
        self.bot = bot
        self.db = bot.db
        self.character_name = character_name
        self.selected_gift: str | None = None

        self.add_item(GiftSelect(user_gifts))
        self.add_item(GiftConfirmButton())

class QuestClaimSelect(discord.ui.Select):
    """
    Dropdown menu to select a quest to claim rewards for.
    """
    def __init__(self, claimable_quests: list, bot_instance: 'BotSelector'):
        options = []
        for quest in claimable_quests:
            clean_name = re.sub(r'^\W+\s*', '', quest['name'])
            label = f"{quest['reward']}"
            if len(label) > 100:
                label = label[:97] + "..."

            options.append(discord.SelectOption(
                label=clean_name,
                description=label,
                value=quest['id'],
                emoji=quest['name'].split(' ')[0]
            ))

        super().__init__(
            placeholder="Select a quest to claim reward...",
            min_values=1,
            max_values=1,
            options=options
        )
        self.bot = bot_instance

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer()
        user_id = interaction.user.id
        quest_id = self.values[0]

        success, message = await self.bot.claim_quest_reward(user_id, quest_id)

        if success:
            response_embed = discord.Embed(
                title="🎁 Quest Reward Claimed!",
                description=f"You received: **{message}**",
                color=discord.Color.green()
            )
            response_embed.set_footer(text="Check your inventory with /inventory")
            await interaction.followup.send(embed=response_embed, ephemeral=True)

            # Update the original quest board message
            new_quest_status = await self.bot.get_quest_status(user_id)
            new_embed = self.bot.create_quest_embed(user_id, new_quest_status)
            new_view = QuestView(user_id, new_quest_status, self.bot)
            await interaction.edit_original_response(embed=new_embed, view=new_view)
        else:
            await interaction.followup.send(f"❌ {message}", ephemeral=True)

class QuestView(discord.ui.View):
    def __init__(self, user_id: int, quest_status: dict, bot_instance: 'BotSelector'):
        super().__init__(timeout=None)
        # --- claimed 값은 반드시 quest_claims 기준으로만 판단 ---
        claimable_quests = []
        for q in (quest_status.get('daily', []) + quest_status.get('weekly', []) + quest_status.get('levelup', []) + quest_status.get('story', [])):
            # 이미 claimed==True면 claimable_quests에 포함하지 않음 (선택지에서 숨김)
            if q.get('completed') and not q.get('claimed'):
                claimable_quests.append(q)
            # 혹시 completed==True, claimed==True가 동시에 True가 되는 버그 방지
            # (즉, claimed==True면 무조건 claimable_quests에 포함하지 않음)
        if claimable_quests:
            self.add_item(QuestClaimSelect(claimable_quests, bot_instance))

    class StoryCharacterSelectView(discord.ui.View):
        def __init__(self, bot_instance: "BotSelector"):
            super().__init__(timeout=180)
            self.bot = bot_instance
            options = [
                discord.SelectOption(label=name, value=name, emoji=info.get('emoji'))
                for name, info in CHARACTER_INFO.items()
            ]
            self.add_item(self.CharacterSelect(options, self.bot))

        class CharacterSelect(discord.ui.Select):
            def __init__(self, options: list, bot_instance: "BotSelector"):
                super().__init__(placeholder="Choose a character...", options=options)
                self.bot = bot_instance

            async def callback(self, interaction: discord.Interaction):
                selected_char = self.values[0]
                # story_character_select_callback 호출
                await self.bot.story_character_select_callback(interaction, selected_char)


    class StoryStageSelectView(discord.ui.View):
        def __init__(self, user, character_name, progress, bot_instance):
            super().__init__()

            story_stages = STORY_CHAPTERS.get(character_name, [])

            # 마지막으로 완료한 스테이지 계산
            completed_stages = [p['stage_num'] for p in progress if p.get('status') == 'completed']
            last_completed_stage = max(completed_stages) if completed_stages else 0

            for stage_info in story_stages:
                stage_num = stage_info['id']
                # next() 함수에 기본값 None 추가
                stage_progress = next((p for p in progress if p.get('stage_num') == stage_num), None)

                is_completed = stage_progress and stage_progress.get('status') == 'completed'
                # is_locked 조건 수정
                is_locked = not is_completed and stage_num > last_completed_stage + 1

                button_label = f"Stage {stage_num}: {stage_info['title']}"
                if is_completed:
                    button_label = f"✅ {button_label} [Cleared]"

                self.add_item(self.StoryStageButton(
                    label=button_label, 
                    style=discord.ButtonStyle.secondary if is_locked else discord.ButtonStyle.primary,
                    disabled=is_locked or is_completed,
                    custom_id=f"story_{character_name}_{stage_num}",
                    bot_selector=bot_instance,
                    character_name=character_name,
                    stage_num=stage_num
                ))

        class StoryStageButton(discord.ui.Button):
            def __init__(self, *, label: str, style: discord.ButtonStyle, disabled: bool, custom_id: str, bot_selector, character_name: str, stage_num: int):
                super().__init__(label=label, style=style, disabled=disabled, custom_id=custom_id)
                self.bot_selector = bot_selector
                self.character_name = character_name
                self.stage_num = stage_num

            async def callback(self, interaction: discord.Interaction):
                await interaction.response.send_message(f"Starting Stage {self.stage_num}...", ephemeral=True)
                channel = await start_story_stage(self.bot_selector, interaction.user, self.character_name, self.stage_num)
                await interaction.followup.send(f"Your story begins in {channel.mention}!", ephemeral=True)

    # ... (rest of the BotSelector class)

# --- 새로운 스토리 UI ---
class NewStoryCharacterSelect(discord.ui.Select):
    def __init__(self, bot_instance: "BotSelector"):
        options = [
            discord.SelectOption(label=name, value=name, emoji=info.get('emoji'))
            for name, info in CHARACTER_INFO.items()
        ]
        super().__init__(placeholder="Choose a character...", options=options)
        self.bot = bot_instance

    async def callback(self, interaction: discord.Interaction):
        try:
            print("[DEBUG] NewStoryCharacterSelect callback initiated.")
            await interaction.response.defer()

            character_name = self.values[0]
            print(f"[DEBUG] Selected character: {character_name}")
            user_id = interaction.user.id

            # 선택된 캐릭터의 스토리 정보 가져오기
            story_info = STORY_CHAPTERS.get(character_name)
            if not story_info:
                print(f"[DEBUG] No story info found for {character_name}.")
                await interaction.followup.send("This character's story is not yet available.", ephemeral=True)
                return
            print(f"[DEBUG] Story info found for {character_name}.")

            # 스토리 진행 상황 가져오기
            print(f"[DEBUG] Getting story progress for user {user_id} and character {character_name}...")
            progress = self.bot.db.get_story_progress(user_id, character_name)
            print(f"[DEBUG] Story progress received: {progress}")

            # 새로운 임베드 생성 (요청사항 반영)
            if character_name == "Eros":
                embed = discord.Embed(
                    title=f"☕ {character_name}'s Story",
                    description="A heartwarming story at Spot Zero Cafe!",
                    color=discord.Color.purple()
                )
            else:
                embed = discord.Embed(
                    title=f"🌙 {character_name}'s Story",
                    description=f"Listen to {character_name}'s hidden story and claim incredible rewards.",
                    color=discord.Color.purple()
                )

            # 시나리오 목록 생성
            chapters = story_info.get('chapters', [])
            chapter_emojis = {1: "☕", 2: "🍵", 3: "💌"} if character_name == "Eros" else {1: "🌸", 2: "🍵", 3: "💌"}

            # 마지막으로 완료한 챕터 번호 계산
            last_completed_chapter = max([p['stage_num'] for p in progress if p.get('status') == 'completed']) if progress else 0

            chapter_list_str = ""
            if character_name == "Elysia":
                # Elysia는 챕터1만 표시
                chapter_info_config = next((c for c in chapters if c['id'] == 1), None)
                emoji = chapter_emojis.get(1, '📖')
                is_completed = any(p['stage_num'] == 1 and p.get('status') == 'completed' for p in progress)
                if chapter_info_config:
                    title = chapter_info_config['title']
                    if is_completed:
                        chapter_list_str += f"{emoji} ✅ Chapter 1: {title} [Completed]\n"
                    else:
                        chapter_list_str += f"{emoji} Chapter 1: {title}\n"
            else:
                for i in range(1, 4):
                    chapter_info_config = next((c for c in chapters if c['id'] == i), None)
                    emoji = chapter_emojis.get(i, '📖')
                    is_completed = any(p['stage_num'] == i and p.get('status') == 'completed' for p in progress)
                    is_locked = not is_completed and i > last_completed_chapter + 1
                    if character_name == "Eros" and i == 1:
                        if is_completed:
                            chapter_list_str += f"{emoji} ✅ Scenario 1: A Happy Day at Spot Zero Cafe [Completed]\n"
                        elif is_locked:
                            chapter_list_str += f"{emoji} 🔒 Scenario 1: A Happy Day at Spot Zero Cafe [Locked]\n"
                        else:
                            chapter_list_str += f"{emoji} Scenario 1: A Happy Day at Spot Zero Cafe\n"
                    elif chapter_info_config:
                        title = chapter_info_config['title']
                        if is_completed:
                            chapter_list_str += f"{emoji} ✅ Chapter {i}: {title} [Completed]\n"
                        elif is_locked:
                            chapter_list_str += f"{emoji} 🔒 Chapter {i}: {title} [Locked]\n"
                        else:
                            chapter_list_str += f"{emoji} Chapter {i}: {title}\n"
                    elif i == 3:
                        if is_completed:
                            chapter_list_str += f"{emoji} ✅ Chapter 3: 이 기억을 영원히 [Completed]\n"
                        elif is_locked:
                            chapter_list_str += f"{emoji} 🔒 Chapter 3: 이 기억을 영원히 [Locked]\n"
                        else:
                            chapter_list_str += f"{emoji} Chapter 3: 이 기억을 영원히\n"

            # 보상 목록 생성
            if character_name == "Elysia":
                # Elysia는 챕터1만 있으므로 Rare Gift만 표시
                rewards_str = "🎁 Rare Gift"
            else:
                # 다른 캐릭터들은 모든 보상 표시
                rewards_str = (
                    "🎁 Rare Gift\n"
                    "💝 Common Gift\n"
                    "🎴 Special Tier Card"
                )

            embed.set_image(url=story_info['banner_image'])
            embed.add_field(name="Scenarios", value=chapter_list_str, inline=True)
            embed.add_field(name="Rewards", value=rewards_str, inline=True)
            print("[DEBUG] Embed created.")

            # 부모 View에 접근하여 아이템 교체
            self.view.clear_items()
            self.view.add_item(NewStoryChapterSelect(self.bot, character_name, progress))
            print("[DEBUG] View items cleared and new chapter select added.")

            await interaction.edit_original_response(embed=embed, view=self.view)
            print("[DEBUG] Original response edited successfully.")

        except Exception as e:
            print(f"An error occurred in NewStoryCharacterSelect callback: {e}")
            import traceback
            traceback.print_exc()
            # 오류 발생 시 사용자에게 알림
            if not interaction.response.is_done():
                await interaction.response.send_message("An error occurred while loading the character story.", ephemeral=True)
            else:
                await interaction.followup.send("An error occurred while loading the character story.", ephemeral=True)

class NewStoryChapterSelect(discord.ui.Select):
    def __init__(self, bot_instance: "BotSelector", character_name: str, progress: list):
        self.bot = bot_instance
        self.character_name = character_name
        story_info = STORY_CHAPTERS.get(character_name)

        self.completed_stages = {p['stage_num'] for p in progress if p.get('status') == 'completed'}

        # 마지막으로 완료한 챕터 번호 계산
        last_completed_chapter = max(self.completed_stages) if self.completed_stages else 0

        options = []
        for chapter in story_info.get('chapters', []):
            chapter_id = chapter['id']
            is_completed = chapter_id in self.completed_stages

            # 순서 규칙: 이전 챕터를 클리어하지 않으면 다음 챕터는 선택 불가
            is_locked = not is_completed and chapter_id > last_completed_chapter + 1

            # 선택 가능한 챕터만 옵션에 추가 (클리어했거나 잠긴 챕터는 제외)
            if not is_completed and not is_locked:
                options.append(discord.SelectOption(
                    label=f"Chapter {chapter_id}: {chapter['title']}",
                    value=str(chapter_id)
                ))

        # 선택 가능한 옵션이 없으면 기본 메시지 추가
        if not options:
            options.append(discord.SelectOption(
                label="No chapters available",
                value="none"
            ))

        super().__init__(placeholder="Select a chapter to begin...", options=options)

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer()

        # "none" 값 처리
        if self.values[0] == "none":
            await interaction.followup.send("No chapters are currently available.", ephemeral=True)
            return

        stage_num = int(self.values[0])

        # 이미 완료된 챕터인지 확인 (이미 필터링되었지만 안전을 위해)
        if stage_num in self.completed_stages:
            await interaction.followup.send("You have already completed this chapter.", ephemeral=True)
            return

        # 순서 규칙 확인: 이전 챕터를 클리어하지 않았는지 확인
        last_completed_chapter = max(self.completed_stages) if self.completed_stages else 0
        if stage_num > last_completed_chapter + 1:
            await interaction.followup.send(
                f"You must complete Chapter {last_completed_chapter + 1} first before starting Chapter {stage_num}.", 
                ephemeral=True
            )
            return

        user = interaction.user

        # 호감도 체크
        affinity_info = self.bot.db.get_affinity(user.id, self.character_name)
        current_affinity = affinity_info.get('emotion_score', 0) if affinity_info else 0

        chapter_info = next((c for c in STORY_CHAPTERS[self.character_name]['chapters'] if c['id'] == stage_num), None)
        affinity_gate = chapter_info.get('affinity_gate', 0)

        if current_affinity < affinity_gate:
            embed = discord.Embed(
                title="🔒 Story Locked",
                description=f"You need at least **{affinity_gate}** affinity with {self.character_name} to start this chapter.\nYour current affinity: **{current_affinity}**",
                color=discord.Color.red()
            )
            await interaction.followup.send(embed=embed, ephemeral=True)
            return

        channel = await start_story_stage(self.bot, user, self.character_name, stage_num)
        await interaction.followup.send(f"Your story begins in {channel.mention}!", ephemeral=True)

class NewStoryView(discord.ui.View):
    def __init__(self, bot_instance: "BotSelector"):
        super().__init__(timeout=300)
        self.add_item(NewStoryCharacterSelect(bot_instance))

    # (여기 있던 async def check_story_quests 함수 전체 삭제)

async def main():
    intents = discord.Intents.all()
    bot = BotSelector()
    await bot.start(TOKEN)
