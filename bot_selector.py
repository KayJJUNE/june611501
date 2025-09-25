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
from products import product_manager
from payment_manager import PaymentManager, PaymentWebhookHandler

# Force reload gift_manager module to resolve cache issues.
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

# --- Dummy definitions to prevent Pylance undefined variable errors ---
class DiscordShareButton(discord.ui.Button):
    def __init__(self, *args, **kwargs):
        super().__init__(label="Share", style=discord.ButtonStyle.link)

async def run_story_scene(*args, **kwargs):
    pass

# Add temporary function if get_affinity_grade is not available
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

# Add temporary classes if RankingView, CardClaimView, RoleplayModal are not available
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

class RoleplayModal(discord.ui.Modal, title="Roleplay Settings"):
        def __init__(self, character_name):
            super().__init__()
            self.character_name = character_name
            self.user_role = discord.ui.TextInput(label="Your Role", max_length=150, required=True)
            self.character_role = discord.ui.TextInput(label="Character Role", max_length=150, required=True)
            self.story_line = discord.ui.TextInput(label="Story Line", max_length=1500, required=True, style=discord.TextStyle.paragraph)
            self.mode = discord.ui.TextInput(
                label="Roleplay Mode", 
                max_length=50, 
                required=True, 
                placeholder="romantic, friendship, healing, fantasy, custom",
                default="romantic"
            )
            self.add_item(self.user_role)
            self.add_item(self.character_role)
            self.add_item(self.story_line)
            self.add_item(self.mode)

        async def on_submit(self, interaction: discord.Interaction):
            # Check for character limit (just in case of unexpected exceptions)
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

                # 1. Create new roleplay channel
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

                # 2. Save session information (only for new channels)
                session_id = f"rp_{interaction.user.id}_{self.character_name}_{int(datetime.now().timestamp())}"
                
                # Save session to database
                bot_selector.db.create_roleplay_session(
                    session_id, interaction.user.id, self.character_name, 
                    self.mode.value.lower(), self.user_role.value, 
                    self.character_role.value, self.story_line.value
                )
                
                # Also save to memory (maintain backward compatibility)
                bot_selector.roleplay_sessions[channel.id] = {
                    "is_active": True,
                    "user_id": interaction.user.id,
                    "character_name": self.character_name,
                    "user_role": self.user_role.value,
                    "character_role": self.character_role.value,
                    "story_line": self.story_line.value,
                    "mode": self.mode.value.lower(),
                    "session_id": session_id,
                    "turns_remaining": 100
                }

                # 3. Send embed to new channel
                from config import CHARACTER_INFO
                char_info = CHARACTER_INFO.get(self.character_name, {})
                # 모드별 이모지 매핑
                mode_emojis = {
                    "romantic": "💕",
                    "friendship": "👥", 
                    "healing": "🕊️",
                    "fantasy": "⚔️",
                    "custom": "✨"
                }
                
                embed = discord.Embed(
                    title=f"🎭 Roleplay Session with {self.character_name} Begins! 🎭",
                    description=(
                        f"🎬 **Roleplay Scenario** 🎬\n"
                        f"**Mode:** {mode_emojis.get(self.mode.value.lower(), '✨')} {self.mode.value.title()}\n"
                        f"**Your Role:** `{self.user_role.value}`\n"
                        f"**{self.character_name}'s Role:** `{self.character_role.value}`\n"
                        f"**Story/Situation:**\n> {self.story_line.value}\n\n"
                        f"✨ {self.character_name} will now act according to their role and personality in this scenario! ✨\n"
                        f"💬 Enjoy 100 turns of immersive roleplay conversation."
                    ),
                    color=discord.Color.magenta()
                )
                icon_url = char_info.get('image') if char_info.get('image') else "https://i.postimg.cc/BZTJr9Np/ec6047e888811f61cc4b896a4c3dd22e.gif"
                embed.set_thumbnail(url=icon_url)
                embed.set_footer(text="🎭 Spot Zero Immersive Roleplay Mode")
                await channel.send(embed=embed)

                # 4. Send notification message to existing channel
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

            # Save language settings to database
            try:
                self.db.set_channel_language(
                    interaction.channel_id,
                    self.user_id,
                    self.character_name,
                    selected_language
                )

                # Prepare success message
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

                # Send welcome message
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

            # Create user-specific channel
            channel_name = f"chat-{selected_char.lower()}-{interaction.user.name}"
            print(f"[DEBUG] 생성할 채널명: {channel_name}")

            # Check and delete existing channel
            existing_channel = discord.utils.get(interaction.guild.channels, name=channel_name)
            if existing_channel:
                print(f"[DEBUG] 기존 채널 삭제: {existing_channel.name}")
                await existing_channel.delete()

            # Create new channel
            channel = await interaction.guild.create_text_channel(
                name=channel_name,
                topic=f"Private chat with {selected_char} for {interaction.user.name}"
            )
            print(f"[DEBUG] 새 채널 생성 완료: {channel.name}")

            # Register channel
            success, message = await selected_bot.add_channel(channel.id, interaction.user.id)
            print("[DEBUG] add_channel 호출 후")

            if success:
                # Channel creation notification message
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

                # Create language selection embed
                embed = discord.Embed(
                    title="🌍 Language Selection",
                    description="Please select the language for conversation.",
                    color=discord.Color.blue()
                )

                # Add language descriptions
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

                # Create language selection view
                view = LanguageSelectView(self.bot_selector.db, interaction.user.id, selected_char)

                # Send embed and language selection button to newly created channel
                await channel.send(content="**Please select your language**", embed=embed, view=view)
            else:
                await channel.send("An error occurred while registering the channel. Please recreate the channel.")
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
        self.roleplay_sessions = {}
        self.story_sessions = {}
        self.dm_sessions = {}  # DM 세션 관리
        
        # Admin-only channel settings
        self.admin_channels = set()  # Channel IDs allowed for admin commands
        self.admin_user_id = 534941503345262613  # Designated admin ID
        self.default_admin_channel = 1417465862910246922  # Designated admin channel ID
        
        # Set default admin channel
        self.admin_channels.add(self.default_admin_channel)
        self.load_admin_channels()  # Load admin channels from database
        
        # Initialize admin command group (will be set up later)
        self.admin_group = None
        
        # 명령어 설정 (admin_group 초기화 후)
        self.setup_commands()
        
        # 안전장치 초기화
        self.emergency_mode = False
        self.start_time = datetime.now()
        
        # 결제 매니저 초기화
        self.payment_manager = PaymentManager(self)
        self.payment_manager.set_database(self.db)
        self.payment_webhook_handler = PaymentWebhookHandler(self.payment_manager)
    
    def is_admin_channel_allowed(self, channel_id: int) -> bool:
        """Check if the channel is allowed for admin commands"""
        # Only allow designated admin channels
        return channel_id in self.admin_channels
    
    def is_admin_user(self, user_id: int) -> bool:
        """Check if the user is a designated administrator"""
        return user_id == self.admin_user_id
    
    def load_admin_channels(self):
        """Load admin channel settings from database"""
        try:
            # 기본 관리자 채널은 항상 포함
            self.admin_channels.add(self.default_admin_channel)
            
            # 파일에서 추가 채널 로드
            import json
            import os
            admin_file = "admin_channels.json"
            if os.path.exists(admin_file):
                with open(admin_file, 'r') as f:
                    data = json.load(f)
                    additional_channels = set(data.get('channels', []))
                    self.admin_channels.update(additional_channels)
                    print(f"✅ Loaded {len(self.admin_channels)} admin channels (including default)")
            else:
                print(f"✅ Using default admin channel: {self.default_admin_channel}")
        except Exception as e:
            print(f"⚠️ Failed to load admin channels: {e}")
            # 기본 채널은 유지
            self.admin_channels = {self.default_admin_channel}
    
    def save_admin_channels(self):
        """관리자 채널 설정을 저장합니다."""
        try:
            import json
            admin_file = "admin_channels.json"
            # 기본 채널을 제외하고 추가 채널만 저장
            additional_channels = self.admin_channels - {self.default_admin_channel}
            data = {'channels': list(additional_channels)}
            with open(admin_file, 'w') as f:
                json.dump(data, f)
            print(f"✅ Saved {len(additional_channels)} additional admin channels")
        except Exception as e:
            print(f"⚠️ Failed to save admin channels: {e}")
        
        # 안전장치 모듈 임포트 및 초기화
        try:
            from error_handler import ErrorHandler
            from safety_guard import safety_guard
            from monitor import BotMonitor
            
            self.error_handler = ErrorHandler(self)
            self.safety_guard = safety_guard
            self.monitor = BotMonitor(self)
            
            # 모니터링 시작
            asyncio.create_task(self.monitor.start_monitoring())
            
        except ImportError as e:
            print(f"Warning: Safety modules not available: {e}")
            self.error_handler = None
            self.safety_guard = None
            self.monitor = None

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
        # 관리자 명령어 그룹 생성 및 등록
        self.setup_admin_commands()
        
        # Cog 로드를 제거하고, 명령어는 setup_commands에서 직접 등록
        await self.tree.sync()
        
        # 자동 블랙리스트 정리 작업 시작
        asyncio.create_task(self.blacklist_cleanup_task())

    async def blacklist_cleanup_task(self):
        """자동 블랙리스트 정리 작업 (매 시간마다 실행)"""
        while True:
            try:
                # 1시간마다 실행
                await asyncio.sleep(3600)
                
                # 만료된 블랙리스트 정리
                cleaned_count = self.db.cleanup_expired_blacklist()
                if cleaned_count > 0:
                    print(f"✅ Cleaned up {cleaned_count} expired blacklist entries.")
                    
            except Exception as e:
                print(f"Error in blacklist cleanup task: {e}")

    def load_active_channels(self):
        """데이터베이스에서 활성 채널 정보를 불러옵니다."""
        try:
            # 현재는 빈 딕셔너리로 초기화
            # 나중에 데이터베이스에서 저장된 채널 정보를 불러올 수 있음
            self.active_channels = {}
            print("✅ Active channels loaded successfully")
        except Exception as e:
            print(f"⚠️ Error loading active channels: {e}")
            self.active_channels = {}
    
    def get_character_for_channel(self, channel_id: int):
        """채널 ID로 활성 캐릭터를 찾습니다."""
        try:
            # 각 캐릭터 봇의 active_channels에서 찾기
            for char_name, bot in self.character_bots.items():
                if hasattr(bot, 'active_channels') and channel_id in bot.active_channels:
                    return bot, char_name
            
            # active_channels에서 찾지 못한 경우 None 반환
            return None, None
        except Exception as e:
            print(f"Error in get_character_for_channel: {e}")
            return None, None

    async def on_ready(self):
        print(f'{self.user} has connected to Discord!')
        # self.tree.sync()는 setup_hook으로 이동했습니다.
        self.load_active_channels()

    def setup_admin_commands(self):
        """관리자 명령어들을 설정합니다."""
        # 관리자 명령어 그룹 생성
        self.admin_group = app_commands.Group(name="admin", description="Administrative commands")
        # default_permissions 제거 - 개별 명령어에서 권한 체크
        
        # 관리자 명령어들을 그룹에 추가
        self.add_admin_commands()
        
        # 그룹을 트리에 추가
        self.tree.add_command(self.admin_group)
        print("✅ Admin command group has been set up.")

    def add_admin_commands(self):
        """관리자 명령어들을 그룹에 추가합니다."""
        
        @self.admin_group.command(
            name="channel",
            description="Set admin-only channel for sensitive commands"
        )
        async def admin_channel_command(interaction: discord.Interaction, action: str = "add"):
            """관리자 전용 채널 설정"""
            if not self.is_admin_user(interaction.user.id):
                await interaction.response.send_message("❌ This command is for the designated administrator only.", ephemeral=True)
                return
            
            if not isinstance(interaction.channel, discord.TextChannel):
                await interaction.response.send_message("❌ This command can only be used in server channels.", ephemeral=True)
                return
            
            channel_id = interaction.channel.id
            
            if action.lower() == "add":
                self.admin_channels.add(channel_id)
                self.save_admin_channels()
                await interaction.response.send_message(f"✅ Channel {interaction.channel.mention} has been added to admin channels.", ephemeral=True)
            elif action.lower() == "remove":
                self.admin_channels.discard(channel_id)
                self.save_admin_channels()
                await interaction.response.send_message(f"✅ Channel {interaction.channel.mention} has been removed from admin channels.", ephemeral=True)
            elif action.lower() == "list":
                if self.admin_channels:
                    channel_mentions = [f"<#{cid}>" for cid in self.admin_channels]
                    await interaction.response.send_message(f"📋 Admin channels: {', '.join(channel_mentions)}", ephemeral=True)
                else:
                    await interaction.response.send_message("📋 No admin channels set. All channels allow admin commands.", ephemeral=True)
            else:
                await interaction.response.send_message("❌ Invalid action. Use 'add', 'remove', or 'list'.", ephemeral=True)

        @self.admin_group.command(
            name="settings",
            description="Check current settings"
        )
        async def settings_command(interaction: discord.Interaction):
            if not isinstance(interaction.channel, discord.TextChannel):
                await interaction.response.send_message("This command can only be used in server channels.", ephemeral=True)
                return
            
            # 지정된 관리자 사용자 확인
            if not self.is_admin_user(interaction.user.id):
                await interaction.response.send_message("❌ This command is for the designated administrator only.", ephemeral=True)
                return
            
            embed = discord.Embed(
                title="⚙️ Bot Settings",
                color=discord.Color.blue()
            )
            
            embed.add_field(
                name="Daily Message Limit",
                value=f"{self.settings_manager.daily_limit} messages",
                inline=False
            )
            
            if self.settings_manager.admin_roles:
                role_mentions = [f"<@&{role_id}>" for role_id in self.settings_manager.admin_roles]
                embed.add_field(
                    name="Admin Roles",
                    value=", ".join(role_mentions),
                    inline=False
                )
            else:
                embed.add_field(
                    name="Admin Roles",
                    value="No admin roles set",
                    inline=False
                )
            
            if interaction.user.guild_permissions.administrator:
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

        @self.admin_group.command(
            name="status",
            description="Check bot status and health"
        )
        async def status_command(interaction: discord.Interaction):
            """Check bot status"""
            try:
                if not self.db.is_user_admin(interaction.user.id):
                    await interaction.response.send_message("This command is for administrators only.", ephemeral=True)
                    return
                
                uptime = datetime.now() - self.start_time
                uptime_str = str(uptime).split('.')[0]  # 마이크로초 제거
                
                embed = discord.Embed(
                    title="🤖 Bot Status",
                    color=discord.Color.green()
                )
                
                embed.add_field(
                    name="🕐 Uptime",
                    value=uptime_str,
                    inline=True
                )
                
                embed.add_field(
                    name="💾 Memory Usage",
                    value=f"{self.get_memory_usage():.2f} MB",
                    inline=True
                )
                
                embed.add_field(
                    name="🔗 Database",
                    value="✅ Connected" if self.db else "❌ Disconnected",
                    inline=True
                )
                
                embed.add_field(
                    name="🚨 Emergency Mode",
                    value="🔴 Active" if self.emergency_mode else "🟢 Normal",
                    inline=True
                )
                
                embed.add_field(
                    name="📊 Active Channels",
                    value=len(self.active_channels),
                    inline=True
                )
                
                embed.add_field(
                    name="👥 Total Users",
                    value=self.get_total_users(),
                    inline=True
                )
                
                await interaction.response.send_message(embed=embed, ephemeral=True)
                
            except Exception as e:
                print(f"Error in status_command: {e}")
                await interaction.response.send_message("Error occurred while checking status.", ephemeral=True)

        # 추가 admin 명령어들
        @self.admin_group.command(
            name="reset_affinity",
            description="Reset user affinity"
        )
        async def reset_affinity(interaction: discord.Interaction, target: discord.Member = None):
            if not self.is_admin_user(interaction.user.id):
                await interaction.response.send_message("❌ This command is for the designated administrator only.", ephemeral=True)
                return
            
            if target:
                self.db.reset_user_affinity(target.id)
                await interaction.response.send_message(f"✅ {target.mention}'s affinity has been reset.", ephemeral=True)
            else:
                await interaction.response.send_message("❌ Please specify a target user.", ephemeral=True)

        @self.admin_group.command(
            name="pop",
            description="Manually distribute items to users (Messages, Cards, Gifts, Affinity)"
        )
        async def pop_command(interaction: discord.Interaction):
            if not self.is_admin_user(interaction.user.id):
                await interaction.response.send_message("❌ This command is for the designated administrator only.", ephemeral=True)
                return
            
            if not self.is_admin_channel_allowed(interaction.channel.id):
                await interaction.response.send_message("❌ This admin command can only be used in designated admin channels.", ephemeral=True)
                return
            
            # Admin Pop 인터페이스 생성
            embed = discord.Embed(
                title="🎁 Admin Item Distribution",
                description="Select the type of item you want to distribute to users.",
                color=discord.Color.gold()
            )
            
            embed.add_field(
                name="💬 Messages",
                value="Give additional message credits to users",
                inline=True
            )
            
            embed.add_field(
                name="🃏 Cards",
                value="Distribute character cards to users",
                inline=True
            )
            
            embed.add_field(
                name="🎁 Gifts",
                value="Give special gifts to users",
                inline=True
            )
            
            embed.add_field(
                name="💕 Affinity",
                value="Add affinity points for specific characters",
                inline=True
            )
            
            embed.set_footer(text="Click the buttons below to select item type")
            
            # Admin Pop 뷰 생성
            view = AdminPopView(self.db)
            
            await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

        # Admin Pop 관련 클래스들 정의
        class AdminPopView(discord.ui.View):
            def __init__(self, db):
                super().__init__(timeout=300)
                self.db = db
            
            @discord.ui.button(label="💬 Give Messages", style=discord.ButtonStyle.success, emoji="💬")
            async def give_messages(self, interaction: discord.Interaction, button: discord.ui.Button):
                modal = AdminPopMessagesModal(self.db)
                await interaction.response.send_modal(modal)
            
            @discord.ui.button(label="🃏 Give Cards", style=discord.ButtonStyle.blurple, emoji="🃏")
            async def give_cards(self, interaction: discord.Interaction, button: discord.ui.Button):
                modal = AdminPopCardsModal(self.db)
                await interaction.response.send_modal(modal)
            
            @discord.ui.button(label="🎁 Give Gifts", style=discord.ButtonStyle.secondary, emoji="🎁")
            async def give_gifts(self, interaction: discord.Interaction, button: discord.ui.Button):
                modal = AdminPopGiftsModal(self.db)
                await interaction.response.send_modal(modal)
            
            @discord.ui.button(label="💕 Give Affinity", style=discord.ButtonStyle.danger, emoji="💕")
            async def give_affinity(self, interaction: discord.Interaction, button: discord.ui.Button):
                modal = AdminPopAffinityModal(self.db)
                await interaction.response.send_modal(modal)
        
        class AdminPopMessagesModal(discord.ui.Modal):
            def __init__(self, db):
                super().__init__(title="💬 Give Messages")
                self.db = db
                self.add_item(discord.ui.TextInput(
                    label="Discord Username/ID",
                    placeholder="Enter username or user ID",
                    required=True,
                    max_length=100
                ))
                self.add_item(discord.ui.TextInput(
                    label="Message Quantity",
                    placeholder="Enter number of messages to give",
                    required=True,
                    max_length=10
                ))
            
            async def on_submit(self, interaction: discord.Interaction):
                try:
                    username = self.children[0].value.strip()
                    quantity = int(self.children[1].value.strip())
                    
                    if quantity <= 0:
                        await interaction.response.send_message("❌ Quantity must be greater than 0.", ephemeral=True)
                        return
                    
                    # 사용자 ID 파싱 (username 또는 ID)
                    user_id = None
                    try:
                        # 숫자로 시작하면 ID로 간주
                        if username.isdigit():
                            user_id = int(username)
                        else:
                            # @username 형식 처리
                            if username.startswith('<@') and username.endswith('>'):
                                user_id = int(username[2:-1])
                            else:
                                await interaction.response.send_message("❌ Please enter a valid user ID or mention.", ephemeral=True)
                                return
                    except ValueError:
                        await interaction.response.send_message("❌ Invalid user ID format.", ephemeral=True)
                        return
                    
                    # 메시지 지급
                    success = self.db.add_user_messages(user_id, quantity)
                    
                    if success:
                        await interaction.response.send_message(
                            f"✅ Successfully gave {quantity} messages to user {user_id}",
                            ephemeral=True
                        )
                    else:
                        await interaction.response.send_message(
                            f"❌ Failed to give messages to user {user_id}",
                            ephemeral=True
                        )
                        
                except ValueError:
                    await interaction.response.send_message("❌ Please enter a valid number for quantity.", ephemeral=True)
                except Exception as e:
                    print(f"Error in AdminPopMessagesModal: {e}")
                    await interaction.response.send_message("❌ An error occurred while giving messages.", ephemeral=True)
        
        class AdminPopCardsModal(discord.ui.Modal):
            def __init__(self, db):
                super().__init__(title="🃏 Give Cards")
                self.db = db
                self.add_item(discord.ui.TextInput(
                    label="Discord Username/ID",
                    placeholder="Enter username or user ID",
                    required=True,
                    max_length=100
                ))
                self.add_item(discord.ui.TextInput(
                    label="Character",
                    placeholder="Enter character name (Kagari, Eros, Elysia)",
                    required=True,
                    max_length=50
                ))
                self.add_item(discord.ui.TextInput(
                    label="Card Quantity",
                    placeholder="Enter number of cards to give",
                    required=True,
                    max_length=10
                ))
            
            async def on_submit(self, interaction: discord.Interaction):
                try:
                    username = self.children[0].value.strip()
                    character = self.children[1].value.strip().title()
                    quantity = int(self.children[2].value.strip())
                    
                    if quantity <= 0:
                        await interaction.response.send_message("❌ Quantity must be greater than 0.", ephemeral=True)
                        return
                    
                    if character not in ['Kagari', 'Eros', 'Elysia']:
                        await interaction.response.send_message("❌ Character must be Kagari, Eros, or Elysia.", ephemeral=True)
                        return
                    
                    # 사용자 ID 파싱
                    user_id = None
                    try:
                        if username.isdigit():
                            user_id = int(username)
                        elif username.startswith('<@') and username.endswith('>'):
                            user_id = int(username[2:-1])
                        else:
                            await interaction.response.send_message("❌ Please enter a valid user ID or mention.", ephemeral=True)
                            return
                    except ValueError:
                        await interaction.response.send_message("❌ Invalid user ID format.", ephemeral=True)
                        return
                    
                    # 카드 지급
                    success_count = 0
                    for _ in range(quantity):
                        success = self.db.add_user_card(user_id, f"{character.lower()}_card_1")
                        if success:
                            success_count += 1
                    
                    if success_count > 0:
                        await interaction.response.send_message(
                            f"✅ Successfully gave {success_count} {character} cards to user {user_id}",
                            ephemeral=True
                        )
                    else:
                        await interaction.response.send_message(
                            f"❌ Failed to give cards to user {user_id}",
                            ephemeral=True
                        )
                        
                except ValueError:
                    await interaction.response.send_message("❌ Please enter a valid number for quantity.", ephemeral=True)
                except Exception as e:
                    print(f"Error in AdminPopCardsModal: {e}")
                    await interaction.response.send_message("❌ An error occurred while giving cards.", ephemeral=True)
        
        class AdminPopGiftsModal(discord.ui.Modal):
            def __init__(self, db):
                super().__init__(title="🎁 Give Gifts")
                self.db = db
                self.add_item(discord.ui.TextInput(
                    label="Discord Username/ID",
                    placeholder="Enter username or user ID",
                    required=True,
                    max_length=100
                ))
                self.add_item(discord.ui.TextInput(
                    label="Gift ID",
                    placeholder="Enter gift ID (e.g., cherry_blossom, honey_cake)",
                    required=True,
                    max_length=50
                ))
                self.add_item(discord.ui.TextInput(
                    label="Gift Quantity",
                    placeholder="Enter number of gifts to give",
                    required=True,
                    max_length=10
                ))
            
            async def on_submit(self, interaction: discord.Interaction):
                try:
                    username = self.children[0].value.strip()
                    gift_id = self.children[1].value.strip()
                    quantity = int(self.children[2].value.strip())
                    
                    if quantity <= 0:
                        await interaction.response.send_message("❌ Quantity must be greater than 0.", ephemeral=True)
                        return
                    
                    # 사용자 ID 파싱
                    user_id = None
                    try:
                        if username.isdigit():
                            user_id = int(username)
                        elif username.startswith('<@') and username.endswith('>'):
                            user_id = int(username[2:-1])
                        else:
                            await interaction.response.send_message("❌ Please enter a valid user ID or mention.", ephemeral=True)
                            return
                    except ValueError:
                        await interaction.response.send_message("❌ Invalid user ID format.", ephemeral=True)
                        return
                    
                    # 선물 지급
                    success = self.db.add_user_gift(user_id, gift_id, quantity)
                    
                    if success:
                        await interaction.response.send_message(
                            f"✅ Successfully gave {quantity} {gift_id} gifts to user {user_id}",
                            ephemeral=True
                        )
                    else:
                        await interaction.response.send_message(
                            f"❌ Failed to give gifts to user {user_id}",
                            ephemeral=True
                        )
                        
                except ValueError:
                    await interaction.response.send_message("❌ Please enter a valid number for quantity.", ephemeral=True)
                except Exception as e:
                    print(f"Error in AdminPopGiftsModal: {e}")
                    await interaction.response.send_message("❌ An error occurred while giving gifts.", ephemeral=True)
        
        class AdminPopAffinityModal(discord.ui.Modal):
            def __init__(self, db):
                super().__init__(title="💕 Give Affinity")
                self.db = db
                self.add_item(discord.ui.TextInput(
                    label="Discord Username/ID",
                    placeholder="Enter username or user ID",
                    required=True,
                    max_length=100
                ))
                self.add_item(discord.ui.TextInput(
                    label="Character",
                    placeholder="Enter character name (Kagari, Eros, Elysia)",
                    required=True,
                    max_length=50
                ))
                self.add_item(discord.ui.TextInput(
                    label="Affinity Points",
                    placeholder="Enter number of affinity points to add",
                    required=True,
                    max_length=10
                ))
            
            async def on_submit(self, interaction: discord.Interaction):
                try:
                    username = self.children[0].value.strip()
                    character = self.children[1].value.strip().title()
                    points = int(self.children[2].value.strip())
                    
                    if character not in ['Kagari', 'Eros', 'Elysia']:
                        await interaction.response.send_message("❌ Character must be Kagari, Eros, or Elysia.", ephemeral=True)
                        return
                    
                    # 사용자 ID 파싱
                    user_id = None
                    try:
                        if username.isdigit():
                            user_id = int(username)
                        elif username.startswith('<@') and username.endswith('>'):
                            user_id = int(username[2:-1])
                        else:
                            await interaction.response.send_message("❌ Please enter a valid user ID or mention.", ephemeral=True)
                            return
                    except ValueError:
                        await interaction.response.send_message("❌ Invalid user ID format.", ephemeral=True)
                        return
                    
                    # 호감도 추가
                    success = self.db.update_affinity(user_id, character, points, f"Admin gave {points} affinity points")
                    
                    if success:
                        await interaction.response.send_message(
                            f"✅ Successfully added {points} affinity points for {character} to user {user_id}",
                            ephemeral=True
                        )
                    else:
                        await interaction.response.send_message(
                            f"❌ Failed to add affinity points to user {user_id}",
                            ephemeral=True
                        )
                        
                except ValueError:
                    await interaction.response.send_message("❌ Please enter a valid number for affinity points.", ephemeral=True)
                except Exception as e:
                    print(f"Error in AdminPopAffinityModal: {e}")
                    await interaction.response.send_message("❌ An error occurred while adding affinity points.", ephemeral=True)

        # Admin System 관련 클래스들 정의
        class AdminSystemView(discord.ui.View):
            def __init__(self, db, bot_selector):
                super().__init__(timeout=300)
                self.db = db
                self.bot_selector = bot_selector
            
            @discord.ui.button(label="📊 Status & Settings", style=discord.ButtonStyle.primary, emoji="📊")
            async def status_settings(self, interaction: discord.Interaction, button: discord.ui.Button):
                view = StatusSettingsView(self.db, self.bot_selector)
                embed = discord.Embed(
                    title="📊 Status & Settings",
                    description="Select the status or settings function you want to use.",
                    color=discord.Color.blue()
                )
                embed.add_field(name="🔍 Status", value="Check bot status and health", inline=True)
                embed.add_field(name="⚙️ Settings", value="View current settings", inline=True)
                await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
            
            @discord.ui.button(label="🔧 Channel & Roles", style=discord.ButtonStyle.secondary, emoji="🔧")
            async def channel_roles(self, interaction: discord.Interaction, button: discord.ui.Button):
                view = ChannelRolesView(self.db, self.bot_selector)
                embed = discord.Embed(
                    title="🔧 Channel & Roles",
                    description="Select the channel or role function you want to use.",
                    color=discord.Color.orange()
                )
                embed.add_field(name="📺 Channel", value="Manage admin channels", inline=True)
                embed.add_field(name="👥 Add Role", value="Add admin role", inline=True)
                embed.add_field(name="❌ Remove Role", value="Remove admin role", inline=True)
                await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
            
            @discord.ui.button(label="👤 User Management", style=discord.ButtonStyle.success, emoji="👤")
            async def user_management(self, interaction: discord.Interaction, button: discord.ui.Button):
                view = UserManagementView(self.db, self.bot_selector)
                embed = discord.Embed(
                    title="👤 User Management",
                    description="Select the user management function you want to use.",
                    color=discord.Color.green()
                )
                embed.add_field(name="📝 Set Daily Limit", value="Set daily message limit", inline=True)
                embed.add_field(name="📖 Reset Story", value="Reset user story progress", inline=True)
                embed.add_field(name="💬 Message Add", value="Add user message count", inline=True)
                embed.add_field(name="🎯 Reset Quest", value="Reset user quest claims", inline=True)
                await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
            
            @discord.ui.button(label="🧹 Maintenance", style=discord.ButtonStyle.danger, emoji="🧹")
            async def maintenance(self, interaction: discord.Interaction, button: discord.ui.Button):
                view = MaintenanceView(self.db, self.bot_selector)
                embed = discord.Embed(
                    title="🧹 Maintenance",
                    description="Select the maintenance function you want to use.",
                    color=discord.Color.red()
                )
                embed.add_field(name="🃏 Cleanup Cards", value="Clean up duplicate cards", inline=True)
                embed.add_field(name="🚨 Emergency Stop", value="Emergency stop mode", inline=True)
                await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
            
            @discord.ui.button(label="💳 Payment & Testing", style=discord.ButtonStyle.blurple, emoji="💳")
            async def payment_testing(self, interaction: discord.Interaction, button: discord.ui.Button):
                view = PaymentTestingView(self.db, self.bot_selector)
                embed = discord.Embed(
                    title="💳 Payment & Testing",
                    description="Select the payment or testing function you want to use.",
                    color=discord.Color.purple()
                )
                embed.add_field(name="🧪 Test Payment", value="Test payment success DM", inline=True)
                embed.add_field(name="🔗 Payment Webhook", value="Process payment webhook", inline=True)
                await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
            
            @discord.ui.button(label="🚫 Blacklist Management", style=discord.ButtonStyle.danger, emoji="🚫")
            async def blacklist_management(self, interaction: discord.Interaction, button: discord.ui.Button):
                view = BlacklistManagementView(self.db, self.bot_selector)
                embed = discord.Embed(
                    title="🚫 Blacklist Management",
                    description="Select the blacklist management function you want to use.",
                    color=discord.Color.dark_red()
                )
                embed.add_field(name="➕ Add to Blacklist", value="Add user to blacklist", inline=True)
                embed.add_field(name="➖ Remove from Blacklist", value="Remove user from blacklist", inline=True)
                embed.add_field(name="📋 View Blacklist", value="View current blacklist", inline=True)
                await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

        # Status & Settings View
        class StatusSettingsView(discord.ui.View):
            def __init__(self, db, bot_selector):
                super().__init__(timeout=300)
                self.db = db
                self.bot_selector = bot_selector
            
            @discord.ui.button(label="🔍 Status", style=discord.ButtonStyle.primary, emoji="🔍")
            async def status(self, interaction: discord.Interaction, button: discord.ui.Button):
                # 기존 status 명령어 로직 사용
                try:
                    uptime = datetime.utcnow() - self.bot_selector.start_time
                    uptime_str = str(uptime).split('.')[0]
                    
                    embed = discord.Embed(
                        title="🤖 Bot Status",
                        description="Current bot status and health information",
                        color=discord.Color.green()
                    )
                    
                    embed.add_field(
                        name="🕐 Uptime",
                        value=uptime_str,
                        inline=True
                    )
                    
                    embed.add_field(
                        name="💾 Memory Usage",
                        value=f"{self.bot_selector.get_memory_usage():.2f} MB",
                        inline=True
                    )
                    
                    embed.add_field(
                        name="🔗 Database",
                        value="✅ Connected" if self.db else "❌ Disconnected",
                        inline=True
                    )
                    
                    embed.add_field(
                        name="🚨 Emergency Mode",
                        value="🔴 Active" if self.bot_selector.emergency_mode else "🟢 Normal",
                        inline=True
                    )
                    
                    embed.add_field(
                        name="📊 Active Channels",
                        value=len(self.bot_selector.active_channels),
                        inline=True
                    )
                    
                    embed.add_field(
                        name="👥 Total Users",
                        value=self.bot_selector.get_total_users(),
                        inline=True
                    )
                    
                    await interaction.response.send_message(embed=embed, ephemeral=True)
                    
                except Exception as e:
                    print(f"Error in status: {e}")
                    await interaction.response.send_message("Error occurred while checking status.", ephemeral=True)
            
            @discord.ui.button(label="⚙️ Settings", style=discord.ButtonStyle.secondary, emoji="⚙️")
            async def settings(self, interaction: discord.Interaction, button: discord.ui.Button):
                # 기존 settings 명령어 로직 사용
                embed = discord.Embed(
                    title="⚙️ Bot Settings",
                    description="Current bot configuration and settings",
                    color=discord.Color.blue()
                )
                
                embed.add_field(
                    name="Daily Message Limit",
                    value=f"{self.bot_selector.settings_manager.daily_limit} messages",
                    inline=False
                )
                
                if self.bot_selector.settings_manager.admin_roles:
                    role_mentions = [f"<@&{role_id}>" for role_id in self.bot_selector.settings_manager.admin_roles]
                    embed.add_field(
                        name="Admin Roles",
                        value=", ".join(role_mentions),
                        inline=False
                    )
                else:
                    embed.add_field(
                        name="Admin Roles",
                        value="No admin roles set",
                        inline=False
                    )
                
                await interaction.response.send_message(embed=embed, ephemeral=True)

        # Channel & Roles View
        class ChannelRolesView(discord.ui.View):
            def __init__(self, db, bot_selector):
                super().__init__(timeout=300)
                self.db = db
                self.bot_selector = bot_selector
            
            @discord.ui.button(label="📺 Channel", style=discord.ButtonStyle.primary, emoji="📺")
            async def channel(self, interaction: discord.Interaction, button: discord.ui.Button):
                modal = ChannelModal(self.bot_selector)
                await interaction.response.send_modal(modal)
            
            @discord.ui.button(label="👥 Add Role", style=discord.ButtonStyle.success, emoji="👥")
            async def add_role(self, interaction: discord.Interaction, button: discord.ui.Button):
                modal = AddRoleModal(self.bot_selector)
                await interaction.response.send_modal(modal)
            
            @discord.ui.button(label="❌ Remove Role", style=discord.ButtonStyle.danger, emoji="❌")
            async def remove_role(self, interaction: discord.Interaction, button: discord.ui.Button):
                modal = RemoveRoleModal(self.bot_selector)
                await interaction.response.send_modal(modal)

        # User Management View
        class UserManagementView(discord.ui.View):
            def __init__(self, db, bot_selector):
                super().__init__(timeout=300)
                self.db = db
                self.bot_selector = bot_selector
            
            @discord.ui.button(label="📝 Set Daily Limit", style=discord.ButtonStyle.primary, emoji="📝")
            async def set_daily_limit(self, interaction: discord.Interaction, button: discord.ui.Button):
                modal = SetDailyLimitModal(self.bot_selector)
                await interaction.response.send_modal(modal)
            
            @discord.ui.button(label="📖 Reset Story", style=discord.ButtonStyle.secondary, emoji="📖")
            async def reset_story(self, interaction: discord.Interaction, button: discord.ui.Button):
                modal = ResetStoryModal(self.db)
                await interaction.response.send_modal(modal)
            
            @discord.ui.button(label="💬 Message Add", style=discord.ButtonStyle.success, emoji="💬")
            async def message_add(self, interaction: discord.Interaction, button: discord.ui.Button):
                modal = MessageAddModal(self.db)
                await interaction.response.send_modal(modal)
            
            @discord.ui.button(label="🎯 Reset Quest", style=discord.ButtonStyle.danger, emoji="🎯")
            async def reset_quest(self, interaction: discord.Interaction, button: discord.ui.Button):
                modal = ResetQuestModal(self.db)
                await interaction.response.send_modal(modal)

        # Maintenance View
        class MaintenanceView(discord.ui.View):
            def __init__(self, db, bot_selector):
                super().__init__(timeout=300)
                self.db = db
                self.bot_selector = bot_selector
            
            @discord.ui.button(label="🃏 Cleanup Cards", style=discord.ButtonStyle.secondary, emoji="🃏")
            async def cleanup_cards(self, interaction: discord.Interaction, button: discord.ui.Button):
                modal = CleanupCardsModal(self.db)
                await interaction.response.send_modal(modal)
            
            @discord.ui.button(label="🚨 Emergency Stop", style=discord.ButtonStyle.danger, emoji="🚨")
            async def emergency_stop(self, interaction: discord.Interaction, button: discord.ui.Button):
                self.bot_selector.emergency_mode = True
                await interaction.response.send_message("🚨 Emergency mode activated! Bot is now in emergency stop mode.", ephemeral=True)

        # Payment & Testing View
        class PaymentTestingView(discord.ui.View):
            def __init__(self, db, bot_selector):
                super().__init__(timeout=300)
                self.db = db
                self.bot_selector = bot_selector
            
            @discord.ui.button(label="🧪 Test Payment", style=discord.ButtonStyle.primary, emoji="🧪")
            async def test_payment(self, interaction: discord.Interaction, button: discord.ui.Button):
                modal = TestPaymentModal(self.db)
                await interaction.response.send_modal(modal)
            
            @discord.ui.button(label="🔗 Payment Webhook", style=discord.ButtonStyle.secondary, emoji="🔗")
            async def payment_webhook(self, interaction: discord.Interaction, button: discord.ui.Button):
                modal = PaymentWebhookModal(self.db)
                await interaction.response.send_modal(modal)

        # Modal 클래스들 정의
        class ChannelModal(discord.ui.Modal):
            def __init__(self, bot_selector):
                super().__init__(title="📺 Admin Channel Management")
                self.bot_selector = bot_selector
                self.add_item(discord.ui.TextInput(
                    label="Action (add/remove/list)",
                    placeholder="Enter 'add', 'remove', or 'list'",
                    required=True,
                    max_length=10
                ))
                self.add_item(discord.ui.TextInput(
                    label="Channel ID (for add/remove)",
                    placeholder="Enter channel ID or leave empty for list",
                    required=False,
                    max_length=20
                ))
            
            async def on_submit(self, interaction: discord.Interaction):
                action = self.children[0].value.lower()
                channel_id = self.children[1].value
                
                if action == "add" and channel_id:
                    try:
                        channel_id = int(channel_id)
                        self.bot_selector.add_admin_channel(channel_id)
                        await interaction.response.send_message(f"✅ Channel <#{channel_id}> has been added to admin channels.", ephemeral=True)
                    except ValueError:
                        await interaction.response.send_message("❌ Invalid channel ID format.", ephemeral=True)
                elif action == "remove" and channel_id:
                    try:
                        channel_id = int(channel_id)
                        self.bot_selector.remove_admin_channel(channel_id)
                        await interaction.response.send_message(f"✅ Channel <#{channel_id}> has been removed from admin channels.", ephemeral=True)
                    except ValueError:
                        await interaction.response.send_message("❌ Invalid channel ID format.", ephemeral=True)
                elif action == "list":
                    if self.bot_selector.admin_channels:
                        channel_mentions = [f"<#{cid}>" for cid in self.bot_selector.admin_channels]
                        await interaction.response.send_message(f"📋 Admin channels: {', '.join(channel_mentions)}", ephemeral=True)
                    else:
                        await interaction.response.send_message("📋 No admin channels set. All channels allow admin commands.", ephemeral=True)
                else:
                    await interaction.response.send_message("❌ Invalid action. Use 'add', 'remove', or 'list'.", ephemeral=True)

        class AddRoleModal(discord.ui.Modal):
            def __init__(self, bot_selector):
                super().__init__(title="👥 Add Admin Role")
                self.bot_selector = bot_selector
                self.add_item(discord.ui.TextInput(
                    label="Role ID",
                    placeholder="Enter the role ID to add as admin",
                    required=True,
                    max_length=20
                ))
            
            async def on_submit(self, interaction: discord.Interaction):
                try:
                    role_id = int(self.children[0].value)
                    self.bot_selector.settings_manager.add_admin_role(role_id)
                    await interaction.response.send_message(f"✅ Role <@&{role_id}> has been added as an admin role.", ephemeral=True)
                except ValueError:
                    await interaction.response.send_message("❌ Invalid role ID format.", ephemeral=True)

        class RemoveRoleModal(discord.ui.Modal):
            def __init__(self, bot_selector):
                super().__init__(title="❌ Remove Admin Role")
                self.bot_selector = bot_selector
                self.add_item(discord.ui.TextInput(
                    label="Role ID",
                    placeholder="Enter the role ID to remove from admin",
                    required=True,
                    max_length=20
                ))
            
            async def on_submit(self, interaction: discord.Interaction):
                try:
                    role_id = int(self.children[0].value)
                    self.bot_selector.settings_manager.remove_admin_role(role_id)
                    await interaction.response.send_message(f"✅ Role <@&{role_id}> has been removed from admin roles.", ephemeral=True)
                except ValueError:
                    await interaction.response.send_message("❌ Invalid role ID format.", ephemeral=True)

        class SetDailyLimitModal(discord.ui.Modal):
            def __init__(self, bot_selector):
                super().__init__(title="📝 Set Daily Limit")
                self.bot_selector = bot_selector
                self.add_item(discord.ui.TextInput(
                    label="Daily Message Limit",
                    placeholder="Enter the daily message limit",
                    required=True,
                    max_length=10
                ))
            
            async def on_submit(self, interaction: discord.Interaction):
                try:
                    limit = int(self.children[0].value)
                    if limit < 1:
                        await interaction.response.send_message("❌ Daily limit must be at least 1.", ephemeral=True)
                        return
                    self.bot_selector.settings_manager.set_daily_limit(limit)
                    await interaction.response.send_message(f"✅ Daily message limit has been set to {limit}.", ephemeral=True)
                except ValueError:
                    await interaction.response.send_message("❌ Please enter a valid number.", ephemeral=True)

        class ResetStoryModal(discord.ui.Modal):
            def __init__(self, db):
                super().__init__(title="📖 Reset Story Progress")
                self.db = db
                self.add_item(discord.ui.TextInput(
                    label="User ID",
                    placeholder="Enter the user ID to reset story progress",
                    required=True,
                    max_length=20
                ))
            
            async def on_submit(self, interaction: discord.Interaction):
                try:
                    user_id = int(self.children[0].value)
                    self.db.reset_story_progress(user_id)
                    await interaction.response.send_message(f"✅ Story progress has been reset for user {user_id}.", ephemeral=True)
                except ValueError:
                    await interaction.response.send_message("❌ Invalid user ID format.", ephemeral=True)
                except Exception as e:
                    print(f"Error in reset_story: {e}")
                    await interaction.response.send_message("❌ An error occurred while resetting story progress.", ephemeral=True)

        class MessageAddModal(discord.ui.Modal):
            def __init__(self, db):
                super().__init__(title="💬 Add User Messages")
                self.db = db
                self.add_item(discord.ui.TextInput(
                    label="User ID",
                    placeholder="Enter the user ID",
                    required=True,
                    max_length=20
                ))
                self.add_item(discord.ui.TextInput(
                    label="Message Count",
                    placeholder="Enter the number of messages to add",
                    required=True,
                    max_length=10
                ))
            
            async def on_submit(self, interaction: discord.Interaction):
                try:
                    user_id = int(self.children[0].value)
                    count = int(self.children[1].value)
                    if count < 1:
                        await interaction.response.send_message("❌ Message count must be at least 1.", ephemeral=True)
                        return
                    self.db.add_user_messages(user_id, count)
                    await interaction.response.send_message(f"✅ Added {count} messages to user {user_id}.", ephemeral=True)
                except ValueError:
                    await interaction.response.send_message("❌ Please enter valid numbers.", ephemeral=True)
                except Exception as e:
                    print(f"Error in message_add: {e}")
                    await interaction.response.send_message("❌ An error occurred while adding messages.", ephemeral=True)

        class ResetQuestModal(discord.ui.Modal):
            def __init__(self, db):
                super().__init__(title="🎯 Reset Quest Claims")
                self.db = db
                self.add_item(discord.ui.TextInput(
                    label="User ID",
                    placeholder="Enter the user ID to reset quest claims",
                    required=True,
                    max_length=20
                ))
            
            async def on_submit(self, interaction: discord.Interaction):
                try:
                    user_id = int(self.children[0].value)
                    self.db.reset_quest_claims(user_id)
                    await interaction.response.send_message(f"✅ Quest claims have been reset for user {user_id}.", ephemeral=True)
                except ValueError:
                    await interaction.response.send_message("❌ Invalid user ID format.", ephemeral=True)
                except Exception as e:
                    print(f"Error in reset_quest: {e}")
                    await interaction.response.send_message("❌ An error occurred while resetting quest claims.", ephemeral=True)

        class CleanupCardsModal(discord.ui.Modal):
            def __init__(self, db):
                super().__init__(title="🃏 Cleanup Duplicate Cards")
                self.db = db
                self.add_item(discord.ui.TextInput(
                    label="User ID (or 'all' for all users)",
                    placeholder="Enter user ID or 'all'",
                    required=True,
                    max_length=20
                ))
            
            async def on_submit(self, interaction: discord.Interaction):
                try:
                    user_input = self.children[0].value.lower()
                    if user_input == "all":
                        cleaned = self.db.cleanup_duplicate_cards()
                        await interaction.response.send_message(f"✅ Cleaned up duplicate cards for all users. Removed {cleaned} duplicates.", ephemeral=True)
                    else:
                        user_id = int(user_input)
                        cleaned = self.db.cleanup_duplicate_cards(user_id)
                        await interaction.response.send_message(f"✅ Cleaned up duplicate cards for user {user_id}. Removed {cleaned} duplicates.", ephemeral=True)
                except ValueError:
                    await interaction.response.send_message("❌ Invalid user ID format. Use a number or 'all'.", ephemeral=True)
                except Exception as e:
                    print(f"Error in cleanup_cards: {e}")
                    await interaction.response.send_message("❌ An error occurred while cleaning up duplicate cards.", ephemeral=True)

        class TestPaymentModal(discord.ui.Modal):
            def __init__(self, db):
                super().__init__(title="🧪 Test Payment")
                self.db = db
                self.add_item(discord.ui.TextInput(
                    label="User ID",
                    placeholder="Enter the user ID to send test payment DM",
                    required=True,
                    max_length=20
                ))
            
            async def on_submit(self, interaction: discord.Interaction):
                try:
                    user_id = int(self.children[0].value)
                    user = interaction.client.get_user(user_id)
                    if not user:
                        await interaction.response.send_message("❌ User not found.", ephemeral=True)
                        return
                    
                    # Test payment success DM
                    embed = discord.Embed(
                        title="🎉 Payment Successful!",
                        description="Your payment has been processed successfully.",
                        color=discord.Color.green()
                    )
                    embed.add_field(name="Transaction ID", value="TEST_123456789", inline=False)
                    embed.add_field(name="Amount", value="$9.99", inline=True)
                    embed.add_field(name="Status", value="Completed", inline=True)
                    
                    try:
                        await user.send(embed=embed)
                        await interaction.response.send_message(f"✅ Test payment DM sent to {user.mention}.", ephemeral=True)
                    except discord.Forbidden:
                        await interaction.response.send_message("❌ Cannot send DM to this user. They may have DMs disabled.", ephemeral=True)
                except ValueError:
                    await interaction.response.send_message("❌ Invalid user ID format.", ephemeral=True)
                except Exception as e:
                    print(f"Error in test_payment: {e}")
                    await interaction.response.send_message("❌ An error occurred while sending test payment DM.", ephemeral=True)

        class PaymentWebhookModal(discord.ui.Modal):
            def __init__(self, db):
                super().__init__(title="🔗 Payment Webhook")
                self.db = db
                self.add_item(discord.ui.TextInput(
                    label="Webhook Data (JSON)",
                    placeholder="Enter webhook data as JSON",
                    required=True,
                    style=discord.TextStyle.paragraph,
                    max_length=2000
                ))
            
            async def on_submit(self, interaction: discord.Interaction):
                try:
                    import json
                    webhook_data = json.loads(self.children[0].value)
                    
                    # Process webhook data (simplified)
                    await interaction.response.send_message("✅ Webhook data processed successfully.", ephemeral=True)
                except json.JSONDecodeError:
                    await interaction.response.send_message("❌ Invalid JSON format.", ephemeral=True)
                except Exception as e:
                    print(f"Error in payment_webhook: {e}")
                    await interaction.response.send_message("❌ An error occurred while processing webhook data.", ephemeral=True)

        # Blacklist Management View
        class BlacklistManagementView(discord.ui.View):
            def __init__(self, db, bot_selector):
                super().__init__(timeout=300)
                self.db = db
                self.bot_selector = bot_selector
            
            @discord.ui.button(label="➕ Add to Blacklist", style=discord.ButtonStyle.danger, emoji="➕")
            async def add_to_blacklist(self, interaction: discord.Interaction, button: discord.ui.Button):
                modal = AddBlacklistModal(self.db, self.bot_selector)
                await interaction.response.send_modal(modal)
            
            @discord.ui.button(label="➖ Remove from Blacklist", style=discord.ButtonStyle.success, emoji="➖")
            async def remove_from_blacklist(self, interaction: discord.Interaction, button: discord.ui.Button):
                modal = RemoveBlacklistModal(self.db, self.bot_selector)
                await interaction.response.send_modal(modal)
            
            @discord.ui.button(label="📋 View Blacklist", style=discord.ButtonStyle.primary, emoji="📋")
            async def view_blacklist(self, interaction: discord.Interaction, button: discord.ui.Button):
                try:
                    # 만료된 블랙리스트 정리
                    self.db.cleanup_expired_blacklist()
                    
                    # 현재 블랙리스트 조회
                    blacklist_users = self.db.get_blacklist_users()
                    
                    if not blacklist_users:
                        embed = discord.Embed(
                            title="📋 Current Blacklist",
                            description="No users are currently blacklisted.",
                            color=discord.Color.green()
                        )
                    else:
                        embed = discord.Embed(
                            title="📋 Current Blacklist",
                            description=f"Total blacklisted users: {len(blacklist_users)}",
                            color=discord.Color.red()
                        )
                        
                        for i, user in enumerate(blacklist_users[:10], 1):  # 최대 10명만 표시
                            duration_text = "Permanent" if user['duration_days'] is None else f"{user['duration_days']} days"
                            expires_text = "Never" if user['expires_at'] is None else user['expires_at'].strftime("%Y-%m-%d %H:%M:%S UTC+8")
                            
                            embed.add_field(
                                name=f"{i}. User ID: {user['user_id']}",
                                value=f"**Username:** {user['username']}\n**Reason:** {user['reason']}\n**Duration:** {duration_text}\n**Expires:** {expires_text}",
                                inline=False
                            )
                        
                        if len(blacklist_users) > 10:
                            embed.set_footer(text=f"... and {len(blacklist_users) - 10} more users")
                    
                    await interaction.response.send_message(embed=embed, ephemeral=True)
                except Exception as e:
                    print(f"Error viewing blacklist: {e}")
                    await interaction.response.send_message("❌ An error occurred while viewing blacklist.", ephemeral=True)

        # Add to Blacklist Modal
        class AddBlacklistModal(discord.ui.Modal):
            def __init__(self, db, bot_selector):
                super().__init__(title="➕ Add User to Blacklist")
                self.db = db
                self.bot_selector = bot_selector
                
                self.add_item(discord.ui.TextInput(
                    label="User ID or Username",
                    placeholder="Enter Discord user ID or username",
                    required=True,
                    max_length=100
                ))
                
                self.add_item(discord.ui.TextInput(
                    label="Reason",
                    placeholder="Enter reason for blacklisting",
                    required=True,
                    max_length=500
                ))
                
                self.add_item(discord.ui.TextInput(
                    label="Duration (days)",
                    placeholder="Enter duration in days (1, 3, 7) or 'permanent' for unlimited",
                    required=True,
                    max_length=20
                ))
            
            async def on_submit(self, interaction: discord.Interaction):
                try:
                    user_input = self.children[0].value.strip()
                    reason = self.children[1].value.strip()
                    duration_input = self.children[2].value.strip().lower()
                    
                    # Duration 처리
                    if duration_input == "permanent":
                        duration_days = None
                    else:
                        try:
                            duration_days = int(duration_input)
                            if duration_days not in [1, 3, 7]:
                                await interaction.response.send_message("❌ Duration must be 1, 3, 7 days or 'permanent'.", ephemeral=True)
                                return
                        except ValueError:
                            await interaction.response.send_message("❌ Invalid duration format. Use 1, 3, 7 or 'permanent'.", ephemeral=True)
                            return
                    
                    # 사용자 ID 파싱
                    user_id = None
                    username = user_input
                    
                    try:
                        # 숫자로 시작하면 ID로 간주
                        if user_input.isdigit():
                            user_id = int(user_input)
                            # Discord에서 사용자 정보 가져오기
                            try:
                                user = await interaction.client.fetch_user(user_id)
                                username = user.display_name or user.name
                            except:
                                username = f"Unknown User ({user_id})"
                        else:
                            # @username 형식 처리
                            if user_input.startswith('<@') and user_input.endswith('>'):
                                user_id = int(user_input[2:-1])
                                try:
                                    user = await interaction.client.fetch_user(user_id)
                                    username = user.display_name or user.name
                                except:
                                    username = f"Unknown User ({user_id})"
                            else:
                                await interaction.response.send_message("❌ Please enter a valid Discord user ID or @username.", ephemeral=True)
                                return
                    except ValueError:
                        await interaction.response.send_message("❌ Invalid user ID format.", ephemeral=True)
                        return
                    
                    # 블랙리스트에 추가
                    success = self.db.add_to_blacklist(
                        user_id=user_id,
                        username=username,
                        reason=reason,
                        duration_days=duration_days,
                        created_by=interaction.user.id
                    )
                    
                    if success:
                        duration_text = "Permanent" if duration_days is None else f"{duration_days} days"
                        await interaction.response.send_message(
                            f"✅ User {username} (ID: {user_id}) has been added to blacklist for {duration_text}.\n**Reason:** {reason}",
                            ephemeral=True
                        )
                    else:
                        await interaction.response.send_message("❌ Failed to add user to blacklist.", ephemeral=True)
                        
                except Exception as e:
                    print(f"Error adding to blacklist: {e}")
                    await interaction.response.send_message("❌ An error occurred while adding user to blacklist.", ephemeral=True)

        # Remove from Blacklist Modal
        class RemoveBlacklistModal(discord.ui.Modal):
            def __init__(self, db, bot_selector):
                super().__init__(title="➖ Remove User from Blacklist")
                self.db = db
                self.bot_selector = bot_selector
                
                self.add_item(discord.ui.TextInput(
                    label="User ID",
                    placeholder="Enter Discord user ID to remove from blacklist",
                    required=True,
                    max_length=20
                ))
            
            async def on_submit(self, interaction: discord.Interaction):
                try:
                    user_input = self.children[0].value.strip()
                    
                    try:
                        user_id = int(user_input)
                    except ValueError:
                        await interaction.response.send_message("❌ Please enter a valid user ID.", ephemeral=True)
                        return
                    
                    # 블랙리스트에서 제거
                    success = self.db.remove_from_blacklist(user_id)
                    
                    if success:
                        await interaction.response.send_message(
                            f"✅ User ID {user_id} has been removed from blacklist.",
                            ephemeral=True
                        )
                    else:
                        await interaction.response.send_message("❌ User was not found in blacklist or already removed.", ephemeral=True)
                        
                except Exception as e:
                    print(f"Error removing from blacklist: {e}")
                    await interaction.response.send_message("❌ An error occurred while removing user from blacklist.", ephemeral=True)

        @self.admin_group.command(
            name="add_role",
            description="Add an admin role"
        )
        async def add_admin_role(interaction: discord.Interaction, role: discord.Role):
            if not self.is_admin_user(interaction.user.id):
                await interaction.response.send_message("❌ This command is for the designated administrator only.", ephemeral=True)
                return
            
            if not self.is_admin_channel_allowed(interaction.channel.id):
                await interaction.response.send_message("❌ This admin command can only be used in designated admin channels.", ephemeral=True)
                return
            
            self.settings_manager.add_admin_role(role.id)
            await interaction.response.send_message(f"✅ Role {role.mention} has been added as an admin role.", ephemeral=True)

        @self.admin_group.command(
            name="remove_role",
            description="Remove the administrator role"
        )
        async def remove_admin_role(interaction: discord.Interaction, role: discord.Role):
            if not self.is_admin_user(interaction.user.id):
                await interaction.response.send_message("❌ This command is for the designated administrator only.", ephemeral=True)
                return
            
            if not self.is_admin_channel_allowed(interaction.channel.id):
                await interaction.response.send_message("❌ This admin command can only be used in designated admin channels.", ephemeral=True)
                return
            
            self.settings_manager.remove_admin_role(role.id)
            await interaction.response.send_message(f"✅ Role {role.mention} has been removed from admin roles.", ephemeral=True)

        @self.admin_group.command(
            name="set_daily_limit",
            description="Setting a daily message limit"
        )
        async def set_daily_limit(interaction: discord.Interaction, limit: int):
            if not self.is_admin_user(interaction.user.id):
                await interaction.response.send_message("❌ This command is for the designated administrator only.", ephemeral=True)
                return
            
            if not self.is_admin_channel_allowed(interaction.channel.id):
                await interaction.response.send_message("❌ This admin command can only be used in designated admin channels.", ephemeral=True)
                return
            
            if limit < 1:
                await interaction.response.send_message("❌ Daily limit must be at least 1.", ephemeral=True)
                return
            
            self.settings_manager.set_daily_limit(limit)
            await interaction.response.send_message(f"✅ Daily message limit has been set to {limit}.", ephemeral=True)

        @self.admin_group.command(
            name="reset_story",
            description="Reset story progress for a user."
        )
        async def reset_story_command(interaction: discord.Interaction, user: discord.Member):
            if not self.is_admin_user(interaction.user.id):
                await interaction.response.send_message("❌ This command is for the designated administrator only.", ephemeral=True)
                return
            
            if not self.is_admin_channel_allowed(interaction.channel.id):
                await interaction.response.send_message("❌ This admin command can only be used in designated admin channels.", ephemeral=True)
                return
            
            try:
                self.db.reset_user_story_progress(user.id)
                await interaction.response.send_message(f"✅ {user.mention}'s story progress has been reset.", ephemeral=True)
            except Exception as e:
                print(f"Error in reset_story_command: {e}")
                await interaction.response.send_message("❌ An error occurred while resetting story progress.", ephemeral=True)

        @self.admin_group.command(
            name="message_add",
            description="Manually add a user's message count."
        )
        async def message_add_command(interaction: discord.Interaction, user: discord.Member, count: int):
            if not self.is_admin_user(interaction.user.id):
                await interaction.response.send_message("❌ This command is for the designated administrator only.", ephemeral=True)
                return
            
            if not self.is_admin_channel_allowed(interaction.channel.id):
                await interaction.response.send_message("❌ This admin command can only be used in designated admin channels.", ephemeral=True)
                return
            
            if count < 1:
                await interaction.response.send_message("❌ Message count must be at least 1.", ephemeral=True)
                return
            
            try:
                self.db.add_user_messages(user.id, count)
                await interaction.response.send_message(f"✅ Added {count} messages to {user.mention}.", ephemeral=True)
            except Exception as e:
                print(f"Error in message_add_command: {e}")
                await interaction.response.send_message("❌ An error occurred while adding messages.", ephemeral=True)

        @self.admin_group.command(
            name="reset_quest",
            description="Reset all quest claim records for a user."
        )
        async def reset_quest_command(interaction: discord.Interaction, user: discord.Member):
            if not self.is_admin_user(interaction.user.id):
                await interaction.response.send_message("❌ This command is for the designated administrator only.", ephemeral=True)
                return
            
            if not self.is_admin_channel_allowed(interaction.channel.id):
                await interaction.response.send_message("❌ This admin command can only be used in designated admin channels.", ephemeral=True)
                return
            
            try:
                self.db.reset_user_quest_claims(user.id)
                await interaction.response.send_message(f"✅ {user.mention}'s quest claim records have been reset.", ephemeral=True)
            except Exception as e:
                print(f"Error in reset_quest_command: {e}")
                await interaction.response.send_message("❌ An error occurred while resetting quest claims.", ephemeral=True)

        @self.admin_group.command(
            name="cleanup_cards",
            description="Clean up duplicate cards for a user or all users."
        )
        async def cleanup_cards_command(interaction: discord.Interaction, user: discord.Member = None):
            if not self.is_admin_user(interaction.user.id):
                await interaction.response.send_message("❌ This command is for the designated administrator only.", ephemeral=True)
                return
            
            if not self.is_admin_channel_allowed(interaction.channel.id):
                await interaction.response.send_message("❌ This admin command can only be used in designated admin channels.", ephemeral=True)
                return
            
            try:
                if user:
                    deleted_count = self.db.cleanup_duplicate_cards(user.id)
                    await interaction.response.send_message(f"✅ Cleaned up {deleted_count} duplicate cards for {user.mention}", ephemeral=True)
                else:
                    deleted_count = self.db.cleanup_all_duplicate_cards()
                    await interaction.response.send_message(f"✅ Cleaned up {deleted_count} duplicate cards for all users", ephemeral=True)
            except Exception as e:
                print(f"Error in cleanup_cards_command: {e}")
                await interaction.response.send_message("❌ An error occurred while cleaning up duplicate cards.", ephemeral=True)

        @self.admin_group.command(
            name="emergency_stop",
            description="Emergency stop for critical issues"
        )
        async def emergency_stop_command(interaction: discord.Interaction):
            if not self.is_admin_user(interaction.user.id):
                await interaction.response.send_message("❌ This command is for the designated administrator only.", ephemeral=True)
                return
            
            if not self.is_admin_channel_allowed(interaction.channel.id):
                await interaction.response.send_message("❌ This admin command can only be used in designated admin channels.", ephemeral=True)
                return
            
            self.emergency_mode = True
            await interaction.response.send_message("🚨 Emergency mode activated! Bot is now in emergency stop mode.", ephemeral=True)

        @self.admin_group.command(
            name="test_payment",
            description="Test payment success DM to a user"
        )
        async def test_payment_command(interaction: discord.Interaction, user: discord.Member):
            """결제 성공 DM 테스트 명령어"""
            if not self.is_admin_user(interaction.user.id):
                await interaction.response.send_message("❌ This command is for the designated administrator only.", ephemeral=True)
                return
            
            if not self.is_admin_channel_allowed(interaction.channel.id):
                await interaction.response.send_message("❌ This admin command can only be used in designated admin channels.", ephemeral=True)
                return
            
            try:
                # 테스트용 결제 데이터
                payment_data = {
                    'product_name': 'Engage Starter',
                    'amount': 9.99,
                    'currency': 'USD',
                    'subscription_type': 'Starter',
                    'duration': '1 month',
                    'transaction_id': f'txn_test_{user.id}_{int(datetime.now().timestamp())}',
                    'features': [
                        'Unlimited messages',
                        'Premium characters access',
                        'Priority support',
                        'Exclusive content'
                    ]
                }
                
                # 결제 성공 DM 전송
                success = await self.payment_manager.send_payment_success_dm(user.id, payment_data)
                
                if success:
                    await interaction.response.send_message(f"✅ Payment success DM sent to {user.mention}", ephemeral=True)
                else:
                    await interaction.response.send_message(f"❌ Failed to send payment DM to {user.mention}", ephemeral=True)
                    
            except Exception as e:
                print(f"Error in test_payment_command: {e}")
                await interaction.response.send_message(f"❌ An error occurred: {str(e)}", ephemeral=True)

        @self.admin_group.command(
            name="payment_webhook",
            description="Process payment webhook data"
        )
        async def payment_webhook_command(interaction: discord.Interaction, user_id: int, status: str, product_name: str = "Premium Subscription", amount: float = 9.99):
            """결제 웹훅 처리 명령어"""
            if not self.is_admin_user(interaction.user.id):
                await interaction.response.send_message("❌ This command is for the designated administrator only.", ephemeral=True)
                return
            
            if not self.is_admin_channel_allowed(interaction.channel.id):
                await interaction.response.send_message("❌ This admin command can only be used in designated admin channels.", ephemeral=True)
                return
            
            try:
                # 웹훅 데이터 구성
                webhook_data = {
                    'user_id': user_id,
                    'status': status,
                    'payment_data': {
                        'product_name': product_name,
                        'amount': amount,
                        'currency': 'USD',
                        'subscription_type': 'Premium',
                        'duration': '1 month',
                        'transaction_id': f'txn_{user_id}_{int(datetime.now().timestamp())}',
                        'features': [
                            'Unlimited messages',
                            'Premium characters access',
                            'Priority support',
                            'Exclusive content'
                        ]
                    }
                }
                
                if status == 'failed':
                    webhook_data['error_message'] = 'Payment processing failed'
                
                # 웹훅 처리
                success = await self.payment_webhook_handler.handle_payment_webhook(webhook_data)
                
                if success:
                    await interaction.response.send_message(f"✅ Payment webhook processed for user {user_id}", ephemeral=True)
                else:
                    await interaction.response.send_message(f"❌ Failed to process payment webhook for user {user_id}", ephemeral=True)
                    
            except Exception as e:
                print(f"Error in payment_webhook_command: {e}")
                await interaction.response.send_message(f"❌ An error occurred: {str(e)}", ephemeral=True)

    def get_memory_usage(self):
        """메모리 사용량을 반환합니다."""
        try:
            import psutil
            import os
            process = psutil.Process(os.getpid())
            return process.memory_info().rss / 1024 / 1024  # MB
        except ImportError:
            return 0.0  # psutil이 없으면 0 반환 단위

    def get_total_users(self):
        """총 사용자 수를 반환합니다."""
        try:
            return len(set(self.db.get_all_user_ids()))
        except:
            return 0

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
        # 관리자 명령어들은 setup_admin_commands에서 처리하므로 여기서는 일반 명령어만 정의
        # admin_group이 None인 경우를 처리하기 위해 임시로 생성
        if self.admin_group is None:
            self.admin_group = app_commands.Group(name="admin", description="Administrative commands")
        @self.tree.command(
            name="bot",
            description="Open character selection menu"
        )
        async def bot_command(interaction: discord.Interaction):
            try:
                # 블랙리스트 체크
                blacklist_info = self.db.is_user_blacklisted(interaction.user.id)
                if blacklist_info['is_blacklisted']:
                    duration_text = "Permanent" if blacklist_info['duration_days'] is None else f"{blacklist_info['duration_days']} days"
                    expires_text = "Never" if blacklist_info['expires_at'] is None else blacklist_info['expires_at'].strftime("%Y-%m-%d %H:%M:%S UTC+8")
                    
                    embed = discord.Embed(
                        title="🚫 Access Denied",
                        description="You have been blacklisted and cannot use this bot.",
                        color=discord.Color.red()
                    )
                    embed.add_field(name="Reason", value=blacklist_info['reason'], inline=False)
                    embed.add_field(name="Duration", value=duration_text, inline=True)
                    embed.add_field(name="Expires", value=expires_text, inline=True)
                    embed.add_field(name="Contact", value="Please contact an administrator or moderator for assistance.", inline=False)
                    
                    await interaction.response.send_message(embed=embed, ephemeral=True)
                    return
                
                # DM에서 사용하는 경우
                if isinstance(interaction.channel, discord.DMChannel):
                    user_id = interaction.user.id
                    
                    # DM 세션이 없으면 생성
                    if user_id not in self.dm_sessions:
                        self.dm_sessions[user_id] = {
                            'last_activity': time.time(),
                            'character_name': None
                        }
                    
                    embed = discord.Embed(
                        title="🌸 Select Character for DM",
                        description="Select a character to chat with in DM.",
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
                    
                    # DM용 캐릭터 선택 뷰 생성
                    view = discord.ui.View()
                    view.add_item(DMCharacterSelect(self))
                    
                    await interaction.response.send_message(
                        embed=embed,
                        view=view,
                        ephemeral=True
                    )
                    return
                
                # 서버 채널에서 사용하는 경우
                if not isinstance(interaction.channel, discord.TextChannel):
                    await interaction.response.send_message(
                        "This command can only be used in server channels or DM.",
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
            name="info",
            description="Check your affinity and card collection information"
        )
        async def info_command(interaction: discord.Interaction):
            try:
                print("\n[Info command started]")
                user_id = interaction.user.id
                character_name = None
                
                # DM에서 사용하는 경우
                if isinstance(interaction.channel, discord.DMChannel):
                    if user_id not in self.dm_sessions or 'character_name' not in self.dm_sessions[user_id]:
                        await interaction.response.send_message("❌ Please select a character first using the `/bot` command.", ephemeral=True)
                        return
                    character_name = self.dm_sessions[user_id]['character_name']
                else:
                    # 서버 채널에서 사용하는 경우
                    if not isinstance(interaction.channel, discord.TextChannel):
                        await interaction.response.send_message("This command can only be used in server channels or DM.", ephemeral=True)
                        return
                    
                    # Find the character bot for the current channel
                    current_bot = None
                    for char_name, bot in self.character_bots.items():
                        if interaction.channel.id in bot.active_channels:
                            current_bot = bot
                            break

                    if not current_bot:
                        await interaction.response.send_message("This command can only be used in character chat channels.", ephemeral=True)
                        return
                    
                    character_name = current_bot.character_name

                print(f"Character name: {character_name}")

                # Get affinity info
                affinity_info = self.db.get_affinity(interaction.user.id, character_name)
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

                # Get card collection info
                all_user_cards = get_user_cards(user_id)
                user_cards = [card for card in all_user_cards if card['character_name'] == character_name] if character_name else all_user_cards
                
                # 티어별 카드 분류
                tier_counts = {'C': 0, 'B': 0, 'A': 0, 'S': 0}
                total_cards = {'C': 30, 'B': 20, 'A': 10, 'S': 5}
                
                for card in user_cards:
                    card_info = get_card_info_by_id(card['character_name'], card['card_id'])
                    if card_info and 'tier' in card_info:
                        tier = card_info['tier']
                        if tier in tier_counts:
                            tier_counts[tier] += 1

                # Main info embed
                char_info = CHARACTER_INFO.get(character_name, {})
                char_color = char_info.get('color', discord.Color.purple())

                embed = discord.Embed(
                    title=f"{char_info.get('emoji', '💝')} {interaction.user.display_name}'s Information",
                    description=f"Complete information for {char_info.get('name', character_name)}",
                    color=char_color
                )

                # Affinity Section
                embed.add_field(
                    name="💝 Affinity Information",
                    value=f"**Score:** {current_affinity} points\n**Grade:** {grade_emoji.get(affinity_grade, '❓')} {affinity_grade}\n**Today's Conversations:** {daily_message_count} times",
                    inline=False
                )

                # Card Collection Section
                total_collected = sum(tier_counts.values())
                total_possible = sum(total_cards.values())
                total_percent = (total_collected / total_possible) * 100 if total_possible > 0 else 0
                
                tier_emojis = {'C': '🥉', 'B': '🥈', 'A': '🥇', 'S': '🏆'}
                bar_emojis = {'C': '🟩', 'B': '🟦', 'A': '🟨', 'S': '🟪'}
                
                def get_progress_bar(count, total, color_emoji, empty_emoji='⬜'):
                    filled = count
                    empty = total - count
                    return color_emoji * filled + empty_emoji * empty
                
                card_progress = ""
                for tier in ['C', 'B', 'A', 'S']:
                    count = tier_counts[tier]
                    total = total_cards[tier]
                    emoji = tier_emojis.get(tier, '')
                    color = bar_emojis.get(tier, '⬜')
                    progress_bar = get_progress_bar(count, total, color)
                    card_progress += f"{tier} Tier {emoji}: {progress_bar} ({count}/{total})\n"
                
                card_progress += f"\n**Total:** {total_collected}/{total_possible} ({total_percent:.1f}%)"
                
                embed.add_field(
                    name="🎴 Card Collection",
                    value=card_progress,
                    inline=False
                )

                # Last conversation time
                if last_message_time and last_message_time != "N/A":
                    try:
                        if isinstance(last_message_time, datetime):
                            formatted_time = last_message_time.strftime('%Y-%m-%d %H:%M')
                        else:
                            last_time_str = last_message_time.split('.')[0]
                            last_time = datetime.strptime(last_time_str, '%Y-%m-%d %H:%M:%S')
                            formatted_time = last_time.strftime('%Y-%m-%d %H:%M')
                        embed.add_field(
                            name="💬 Last Conversation",
                            value=f"```{formatted_time}```",
                            inline=True
                        )
                    except Exception as e:
                        print(f"Date parsing error: {e}")
                        embed.add_field(
                            name="💬 Last Conversation",
                            value=f"```{last_message_time}```",
                            inline=True
                        )
                else:
                    embed.add_field(
                        name="💬 Last Conversation",
                        value=f"```N/A```",
                        inline=True
                    )

                # Get the correct image URL from config.py
                char_image_url = CHARACTER_IMAGES.get(character_name)
                if char_image_url:
                    embed.set_thumbnail(url=char_image_url)

                # Send the main info embed
                await interaction.response.send_message(embed=embed, ephemeral=True)

                # If user has cards, show card slider
                if user_cards:
                    card_info_dict = {}
                    for card in user_cards:
                        card_info = get_card_info_by_id(card['character_name'], card['card_id'])
                        if card_info:
                            card_info_dict[card['card_id']] = card_info

                    def get_tier_order(card_id):
                        tier = card_info_dict.get(card_id, {}).get('tier', 'Unknown')
                        tier_order = {'C': 0, 'B': 1, 'A': 2, 'S': 3}
                        return tier_order.get(tier, 4)

                    sorted_cards = sorted(list(card_info_dict.keys()), key=get_tier_order)

                    if sorted_cards:
                        slider_view = CardSliderView(
                            user_id=user_id,
                            cards=sorted_cards,
                            character_name=character_name or "All",
                            card_info_dict=card_info_dict,
                            db=self.db
                        )
                        await slider_view.initial_message(interaction)

                print("[Info command complete]")

            except Exception as e:
                print(f"Error during info command: {e}")
                import traceback
                print(traceback.format_exc())
                try:
                    await interaction.response.send_message("An error occurred while loading your information.", ephemeral=True)
                except:
                    await interaction.followup.send("An error occurred while loading your information.", ephemeral=True)



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
            user_id = interaction.user.id
            
            # 스토리 채널인지 확인 (챕터 완료 후 바로 다음 챕터 선택 가능)
            if any(f'-s{i}-' in interaction.channel.name for i in range(1, 10)):
                # 스토리 채널에서 실행된 경우, 현재 캐릭터의 다음 챕터를 바로 선택할 수 있도록 함
                channel_name = interaction.channel.name
                character_name = None
                
                # 채널명에서 캐릭터 추출
                if 'kagari' in channel_name.lower():
                    character_name = 'Kagari'
                elif 'eros' in channel_name.lower():
                    character_name = 'Eros'
                elif 'elysia' in channel_name.lower():
                    character_name = 'Elysia'
                
                if character_name:
                    # 현재 캐릭터의 호감도 체크 (100 이상 필요)
                    affinity_info = self.db.get_affinity(user_id, character_name)
                    affinity = affinity_info['emotion_score'] if affinity_info else 0
                    
                    if affinity < 100:
                        embed = discord.Embed(
                            title="⚠️ Story Mode Locked",
                            description=f"Story mode for {character_name} requires affinity level 100 or higher.",
                            color=discord.Color.red()
                        )
                        embed.add_field(
                            name="Current Affinity",
                            value=f"**{affinity}**",
                            inline=True
                        )
                        embed.add_field(
                            name="Required Affinity",
                            value="**100**",
                            inline=True
                        )
                        embed.add_field(
                            name="How to Unlock",
                            value=f"Keep chatting with {character_name} to increase your affinity level!",
                            inline=False
                        )
                        await interaction.response.send_message(embed=embed, ephemeral=True)
                        return
                    
                    # 현재 캐릭터의 스토리 진행 상황 가져오기
                    progress = self.db.get_story_progress(user_id, character_name)
                    story_info = STORY_CHAPTERS.get(character_name)
                    
                    if not story_info:
                        await interaction.response.send_message(f"{character_name}'s story is not yet available.", ephemeral=True)
                        return
                    
                    # 다음 챕터 선택 UI 표시
                    await interaction.response.defer(ephemeral=True)
                    view = NewStoryChapterSelect(self, character_name, progress, interaction.channel)
                    embed = discord.Embed(
                        title=f"📖 {character_name}'s Story - Select Chapter",
                        description="Choose the next chapter to play:",
                        color=discord.Color.purple()
                    )
                    await interaction.followup.send(embed=embed, view=view, ephemeral=True)
                    return
            
            # 일반 채널에서 실행된 경우, 캐릭터 선택 UI 표시
            # 각 캐릭터별 호감도 체크하여 선택 가능한 캐릭터만 표시
            available_characters = []
            
            for char_name in CHARACTER_INFO.keys():
                affinity_info = self.db.get_affinity(user_id, char_name)
                affinity = affinity_info['emotion_score'] if affinity_info else 0
                print(f"[DEBUG] {char_name} affinity: {affinity}")
                
                if affinity >= 100:
                    available_characters.append(char_name)
                    print(f"[DEBUG] Added {char_name} to available_characters")
            
            print(f"[DEBUG] Final available_characters: {available_characters}")
            
            if not available_characters:
                embed = discord.Embed(
                    title="⚠️ Story Mode Locked",
                    description="Story mode requires affinity level 100 or higher with at least one character.",
                    color=discord.Color.red()
                )
                embed.add_field(
                    name="How to Unlock",
                    value="Keep chatting with characters to increase your affinity level to 100!",
                    inline=False
                )
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return
            
            # 선택 가능한 캐릭터만으로 UI 생성
            view = NewStoryView(self, available_characters)
            embed = discord.Embed(
                title="📖 Story Mode",
                description="Select a character to start their story:",
                color=discord.Color.purple()
            )
            
            await interaction.response.send_message(embed=embed, view=view, ephemeral=True)


        async def story_character_select_callback(self, interaction: discord.Interaction, selected_char: str):
            # 이 함수는 더 이상 사용되지 않지만, 다른 곳에서 호출될 경우를 대비해 유지합니다.
            await interaction.response.send_message(f"Selected: {selected_char}. This part of story is under construction.", ephemeral=True)





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
                            label="DM Usage",
                            value="dm",
                            description="How to use the bot in DMs",
                            emoji="💬"
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
                        embed.add_field(name="Level Up with Conversations", value="- Rookie (0-9): Basic chat only.\n- ⚔️ Iron (10-29): Unlock basic emotions & C-rank cards.\n- 🥉 Bronze (30-49): B/C cards & more emotions.\n- Silver (50-99): A/B/C cards & story mood options.\n- Gold (100+): S-tier chance & story unlock.\nCommand: /info to check your current level, progress, and daily message stats.", inline=False)
                    elif topic == "card":
                        embed.title = "🎴 Card & Reward System"
                        embed.add_field(name="How to Earn & Collect Cards", value="You earn cards through:\n- 🗣️ Emotional chat: score-based triggers (10/20/30)\n- 🎮 Story Mode completions\n- ❤️ Affinity milestone bonuses\nCard Tier Example (Gold user):\n- A (20%) / B (30%) / C (50%)\n- Gold+ user: S (10%) / A (20%) / B (30%) / C (40%)\n📜 Use /mycard to view your collection.", inline=False)
                    elif topic == "story":
                        embed.title = "📖 Story Mode Guide"
                        embed.add_field(name="How to Play", value="1. Reach Gold level (100+ affinity)\n2. Use /story to start\n3. Choose a chapter\n4. Make choices that affect the story\n\nRewards:\n- Story completion rewards\n- Special card rewards\n- Bonus affinity points", inline=False)
                    elif topic == "ranking":
                        embed.title = "🏆 Ranking System"
                        embed.add_field(name="How Rankings Work", value="Rankings are based on:\n1. Total affinity across all characters\n2. Daily conversation count\n3. Story mode completion\n\nCheck your rank with /ranking", inline=False)
                    elif topic == "dm":
                        embed.title = "💬 DM Usage Guide"
                        embed.add_field(name="How to Use in DMs", value="1. **Start a DM**: Send any message to the bot in DMs\n2. **Select Character**: Use `/bot` command to choose a character\n3. **Start Chatting**: Talk freely with your chosen character\n4. **Session Timeout**: 30 minutes of inactivity will end the session\n\n**Available Commands in DM:**\n• `/bot` - Select character\n• `/info` - Check affinity and cards\n• `/mycard` - View cards\n• `/quest` - Check quests\n• `/help` - Show this help", inline=False)
                        embed.add_field(name="💡 Tips", value="• DM allows more private conversations\n• All features work the same as in servers\n• Characters remember your conversation context\n• You can switch characters anytime with `/bot`", inline=False)
                    elif topic == "faq":
                        embed.title = "❓ FAQ"
                        embed.add_field(name="Q1: How can I get higher grade cards?", value="A: Card grades depend on your affinity level:\n- Iron: Mainly C cards (80%), small chance for B (20%)\n- Bronze: Better chance for B cards (30%)\n- Silver: Can get A cards (20%)\n- Gold: Can get S cards (10%)\nHigher affinity = better card chances!", inline=False)
                        embed.add_field(name="Q2: How are rewards calculated in Story Mode?", value="A: There are two score systems in Story Mode:\n- Mission Clear Logic: Each story has a mission goal. If you clear it, you're guaranteed an S-tier card.\n- Affinity Score Logic: Your outcome is affected by how close you are with the character.\nIf your crush score is too low, you may not receive a card at all. Higher crush = higher card tier and more beautiful card art!", inline=False)
                        embed.add_field(name="Q3: What changes based on my Crush with the character?", value="A: Character tone, reaction, and card chances all change based on your Affinity level.\n- Higher Affinity = More natural or intimate dialogue\n- Higher Affinity = Better chance at A-tier or S-tier cards\n- Lower Affinity = Dull responses, chance of being rejected\nUse /info to track your current level with each character.", inline=False)
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
                
                # 스토리 모드 세션 체크
                from story_mode import story_sessions
                print(f"[DEBUG] story_sessions keys: {list(story_sessions.keys())}")
                session = story_sessions.get(interaction.channel.id)
                print(f"[DEBUG] session: {session}")
                
                character = None
                current_bot = None
                
                # 1. 스토리 모드 세션이 있는 경우
                if session and session.get('character_name'):
                    character = session['character_name']
                    print(f"[DEBUG] Found story session for character: {character}")
                else:
                    # 2. 일반 캐릭터 채널인 경우
                    for char_name, bot in self.character_bots.items():
                        if interaction.channel.id in bot.active_channels:
                            current_bot = bot
                            character = char_name
                            break
                
                if not character:
                    print("[DEBUG] No character found for channel")
                    await interaction.followup.send("You can't give gifts in this channel. Please use this in a character's chat channel or story mode.", ephemeral=True)
                    return
                
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
                # 캐릭터 봇 리액션 (일반 채널인 경우만)
                if current_bot:
                    await current_bot.send_reaction_message(
                        channel_id=interaction.channel_id,
                        text=f"*{reaction_message}*",
                        emoji=gift_emoji
                    )
                    print(f"[DEBUG] send_reaction_message sent.")
                
                # 스토리 모드에서 선물 사용 처리
                if session and session.get('character_name'):
                    from story_mode import handle_chapter3_gift_usage, handle_chapter3_gift_failure
                    if character == "Kagari" and session.get('stage_num') == 3:
                        # Kagari 챕터3 선물 사용 처리
                        print(f"[DEBUG] Kagari Chapter 3 gift processing - user_id: {user_id}, item: {item}")
                        success, result = await handle_chapter3_gift_usage(self, user_id, character, item, interaction.channel_id)
                        print(f"[DEBUG] handle_chapter3_gift_usage result - success: {success}, result type: {type(result)}")
                        if success:
                            if isinstance(result, tuple) and len(result) == 2:
                                success_embed, completion_embed = result
                                print(f"[DEBUG] Sending success_embed and completion_embed")
                                await interaction.channel.send(embed=success_embed)
                                await interaction.channel.send(embed=completion_embed)
                            else:
                                print(f"[DEBUG] Unexpected result format: {result}")
                                await interaction.channel.send(embed=result)
                            # 5초 후 채널 삭제
                            import asyncio
                            await asyncio.sleep(5)
                            try:
                                await interaction.channel.delete()
                                print(f"[DEBUG][{character}] 챕터3 선물 완료 후 채널 삭제 완료")
                            except Exception as e:
                                print(f"[DEBUG][{character}] 챕터3 선물 완료 후 채널 삭제 실패: {e}")
                        else:
                            print(f"[DEBUG] handle_chapter3_gift_usage failed: {result}")
                        return  # 스토리 모드 처리 완료 후 함수 종료
                    elif character == "Eros" and session.get('stage_num') == 3:
                        # Eros 챕터3 선물 사용 처리
                        success, result = await handle_chapter3_gift_usage(self, user_id, character, item, interaction.channel_id)
                        if success:
                            if isinstance(result, tuple) and len(result) == 2:
                                success_embed, completion_embed = result
                                await interaction.channel.send(embed=success_embed)
                                await interaction.channel.send(embed=completion_embed)
                            else:
                                await interaction.channel.send(embed=result)
                            # 5초 후 채널 삭제
                            import asyncio
                            await asyncio.sleep(5)
                            try:
                                await interaction.channel.delete()
                                print(f"[DEBUG][{character}] 챕터3 선물 완료 후 채널 삭제 완료")
                            except Exception as e:
                                print(f"[DEBUG][{character}] 챕터3 선물 완료 후 채널 삭제 실패: {e}")
                        return  # 스토리 모드 처리 완료 후 함수 종료
                    else:
                        # 기타 스토리 모드 선물 처리
                        print(f"[DEBUG] Story mode gift given to {character} in stage {session.get('stage_num')}")
                        # 일반 선물 전송 로직 계속 실행
            except Exception as e:
                print(f"[ERROR] /gift 명령어 처리 중 오류: {e}")
                import traceback
                print(traceback.format_exc())
                try:
                    await interaction.followup.send("An error occurred. Please contact an administrator.", ephemeral=True)
                except Exception as e2:
                    print(f"[ERROR] followup.send 실패: {e2}")


        # ====================================================
        # 관리자용 물리적 상품 지급 시스템 (/pop)
        # ====================================================
        
        class PopItemTypeSelect(discord.ui.Select):
            def __init__(self):
                options = [
                    discord.SelectOption(label="💬 Messages", value="messages", description="Give messages to user"),
                    discord.SelectOption(label="🃏 Cards", value="cards", description="Give cards to user"),
                    discord.SelectOption(label="🎁 Gifts", value="gifts", description="Give gifts to user"),
                    discord.SelectOption(label="💕 Affinity", value="affinity", description="Give affinity points to user")
                ]
                super().__init__(placeholder="Select item type to give...", options=options, min_values=1, max_values=1)
            
            async def callback(self, interaction: discord.Interaction):
                item_type = self.values[0]
                
                if item_type == "messages":
                    view = PopMessagesView()
                elif item_type == "cards":
                    view = PopCardsView()
                elif item_type == "gifts":
                    view = PopGiftsView()
                elif item_type == "affinity":
                    view = PopAffinityView()
                
                embed = discord.Embed(
                    title="🎯 Admin Item Distribution",
                    description=f"Selected: **{item_type.title()}**\nPlease fill in the details below.",
                    color=discord.Color.blue()
                )
                await interaction.response.edit_message(embed=embed, view=view)
        
        class PopMessagesView(discord.ui.View):
            def __init__(self):
                super().__init__(timeout=300)
                self.add_item(PopItemTypeSelect())
            
            @discord.ui.button(label="Give Messages", style=discord.ButtonStyle.success, emoji="💬")
            async def give_messages(self, interaction: discord.Interaction, button: discord.ui.Button):
                modal = PopMessagesModal()
                await interaction.response.send_modal(modal)
        
        class PopCardsView(discord.ui.View):
            def __init__(self):
                super().__init__(timeout=300)
                self.add_item(PopItemTypeSelect())
            
            @discord.ui.button(label="Give Cards", style=discord.ButtonStyle.success, emoji="🃏")
            async def give_cards(self, interaction: discord.Interaction, button: discord.ui.Button):
                modal = PopCardsModal()
                await interaction.response.send_modal(modal)
        
        class PopGiftsView(discord.ui.View):
            def __init__(self):
                super().__init__(timeout=300)
                self.add_item(PopItemTypeSelect())
            
            @discord.ui.button(label="Give Gifts", style=discord.ButtonStyle.success, emoji="🎁")
            async def give_gifts(self, interaction: discord.Interaction, button: discord.ui.Button):
                modal = PopGiftsModal()
                await interaction.response.send_modal(modal)
        
        class PopAffinityView(discord.ui.View):
            def __init__(self):
                super().__init__(timeout=300)
                self.add_item(PopItemTypeSelect())
            
            @discord.ui.button(label="Give Affinity", style=discord.ButtonStyle.success, emoji="💕")
            async def give_affinity(self, interaction: discord.Interaction, button: discord.ui.Button):
                modal = PopAffinityModal()
                await interaction.response.send_modal(modal)
        
        class PopMessagesModal(discord.ui.Modal):
            def __init__(self):
                super().__init__(title="💬 Give Messages")
                self.add_item(discord.ui.TextInput(
                    label="Discord Username/ID",
                    placeholder="Enter username or user ID",
                    required=True,
                    max_length=100
                ))
                self.add_item(discord.ui.TextInput(
                    label="Message Quantity",
                    placeholder="Enter number of messages to give",
                    required=True,
                    max_length=10
                ))
            
            async def on_submit(self, interaction: discord.Interaction):
                try:
                    user_input = self.children[0].value.strip()
                    quantity = int(self.children[1].value.strip())
                    
                    # Find user by ID or username
                    user = None
                    if user_input.isdigit():
                        user_id = int(user_input)
                        user = interaction.client.get_user(user_id)
                    else:
                        # Search by username
                        for member in interaction.guild.members:
                            if user_input.lower() in member.name.lower() or user_input.lower() in member.display_name.lower():
                                user = member
                                break
                    
                    if not user:
                        await interaction.response.send_message("❌ User not found. Please check the username or ID.", ephemeral=True)
                        return

                    if quantity <= 0:
                        await interaction.response.send_message("❌ Quantity must be greater than 0.", ephemeral=True)
                        return

                    # Add messages to user balance
                    interaction.client.db.add_user_message_balance(user.id, quantity)
                    
                    # Log the transaction
                    interaction.client.db.log_admin_give_item(
                        admin_id=interaction.user.id,
                        user_id=user.id,
                        item_type="messages",
                        item_id="admin_give",
                        quantity=quantity,
                        reason="Admin manual distribution"
                    )
                    
                    embed = discord.Embed(
                        title="✅ Messages Given Successfully",
                        description=f"**{quantity} messages** given to {user.mention}",
                        color=discord.Color.green()
                    )
                    embed.add_field(name="Admin", value=interaction.user.mention, inline=True)
                    embed.add_field(name="Recipient", value=user.mention, inline=True)
                    embed.add_field(name="Item", value=f"{quantity} Messages", inline=True)
                    
                    await interaction.response.send_message(embed=embed, ephemeral=True)
                    
                except ValueError:
                    await interaction.response.send_message("❌ Invalid quantity. Please enter a valid number.", ephemeral=True)
                except Exception as e:
                    await interaction.response.send_message(f"❌ Error: {str(e)}", ephemeral=True)
        
        class PopCardsModal(discord.ui.Modal):
            def __init__(self):
                super().__init__(title="🃏 Give Cards")
                self.add_item(discord.ui.TextInput(
                    label="Discord Username/ID",
                    placeholder="Enter username or user ID",
                    required=True,
                    max_length=100
                ))
                self.add_item(discord.ui.TextInput(
                    label="Character",
                    placeholder="Enter character name (Kagari, Eros, Elysia)",
                    required=True,
                    max_length=20
                ))
                self.add_item(discord.ui.TextInput(
                    label="Card ID",
                    placeholder="Enter card ID (e.g., kagaris1, erosb2)",
                    required=True,
                    max_length=50
                ))
            
            async def on_submit(self, interaction: discord.Interaction):
                try:
                    user_input = self.children[0].value.strip()
                    character = self.children[1].value.strip().title()
                    card_id = self.children[2].value.strip().lower()
                    
                    # Find user
                    user = None
                    if user_input.isdigit():
                        user_id = int(user_input)
                        user = interaction.client.get_user(user_id)
                    else:
                        for member in interaction.guild.members:
                            if user_input.lower() in member.name.lower() or user_input.lower() in member.display_name.lower():
                                user = member
                                break
                    
                    if not user:
                        await interaction.response.send_message("❌ User not found.", ephemeral=True)
                        return
                    
                    # Validate character
                    if character not in ["Kagari", "Eros", "Elysia"]:
                        await interaction.response.send_message("❌ Invalid character. Use Kagari, Eros, or Elysia.", ephemeral=True)
                        return
                    
                    # Check if card exists
                    from config import CHARACTER_CARD_INFO
                    if character not in CHARACTER_CARD_INFO or card_id not in CHARACTER_CARD_INFO[character]:
                        await interaction.response.send_message("❌ Card ID not found.", ephemeral=True)
                        return
                    
                    # Give card to user
                    interaction.client.db.add_user_card(user.id, character, card_id)
                    
                    # Log the transaction
                    interaction.client.db.log_admin_give_item(
                        admin_id=interaction.user.id,
                        user_id=user.id,
                        item_type="card",
                        item_id=card_id,
                        quantity=1,
                        reason="Admin manual distribution"
                    )
                    
                    card_info = CHARACTER_CARD_INFO[character][card_id]
                    embed = discord.Embed(
                        title="✅ Card Given Successfully",
                        description=f"**{card_info['description']}** given to {user.mention}",
                        color=discord.Color.green()
                    )
                    embed.add_field(name="Admin", value=interaction.user.mention, inline=True)
                    embed.add_field(name="Recipient", value=user.mention, inline=True)
                    embed.add_field(name="Character", value=character, inline=True)
                    embed.add_field(name="Card", value=card_info['description'], inline=True)
                    
                    if card_info.get('image_url'):
                        embed.set_image(url=card_info['image_url'])
                    
                    await interaction.response.send_message(embed=embed, ephemeral=True)
                    
                except Exception as e:
                    await interaction.response.send_message(f"❌ Error: {str(e)}", ephemeral=True)
        
        class PopGiftsModal(discord.ui.Modal):
            def __init__(self):
                super().__init__(title="🎁 Give Gifts")
                self.add_item(discord.ui.TextInput(
                    label="Discord Username/ID",
                    placeholder="Enter username or user ID",
                    required=True,
                    max_length=100
                ))
                self.add_item(discord.ui.TextInput(
                    label="Gift ID",
                    placeholder="Enter gift ID (e.g., gift_001, gift_002)",
                    required=True,
                    max_length=50
                ))
                self.add_item(discord.ui.TextInput(
                    label="Quantity",
                    placeholder="Enter quantity to give",
                    required=True,
                    max_length=10
                ))
            
            async def on_submit(self, interaction: discord.Interaction):
                try:
                    user_input = self.children[0].value.strip()
                    gift_id = self.children[1].value.strip()
                    quantity = int(self.children[2].value.strip())
                    
                    # Find user
                    user = None
                    if user_input.isdigit():
                        user_id = int(user_input)
                        user = interaction.client.get_user(user_id)
                    else:
                        for member in interaction.guild.members:
                            if user_input.lower() in member.name.lower() or user_input.lower() in member.display_name.lower():
                                user = member
                                break
                    
                    if not user:
                        await interaction.response.send_message("❌ User not found.", ephemeral=True)
                        return
                    
                    if quantity <= 0:
                        await interaction.response.send_message("❌ Quantity must be greater than 0.", ephemeral=True)
                        return
                    
                    # Check if gift exists
                    from gift_manager import ALL_GIFTS
                    if gift_id not in ALL_GIFTS:
                        await interaction.response.send_message("❌ Gift ID not found.", ephemeral=True)
                        return

                    # Give gift to user
                    interaction.client.db.add_user_gift(user.id, gift_id, quantity)

                    # Log the transaction
                    interaction.client.db.log_admin_give_item(
                        admin_id=interaction.user.id,
                        user_id=user.id,
                        item_type="gift",
                        item_id=gift_id,
                        quantity=quantity,
                        reason="Admin manual distribution"
                    )
                    
                    gift_info = ALL_GIFTS[gift_id]
                    embed = discord.Embed(
                        title="✅ Gift Given Successfully",
                        description=f"**{gift_info['name']}** given to {user.mention}",
                        color=discord.Color.green()
                    )
                    embed.add_field(name="Admin", value=interaction.user.mention, inline=True)
                    embed.add_field(name="Recipient", value=user.mention, inline=True)
                    embed.add_field(name="Gift", value=gift_info['name'], inline=True)
                    embed.add_field(name="Quantity", value=str(quantity), inline=True)
                    
                    await interaction.response.send_message(embed=embed, ephemeral=True)
                    
                except ValueError:
                    await interaction.response.send_message("❌ Invalid quantity. Please enter a valid number.", ephemeral=True)
                except Exception as e:
                    await interaction.response.send_message(f"❌ Error: {str(e)}", ephemeral=True)
        
        class PopAffinityModal(discord.ui.Modal):
            def __init__(self):
                super().__init__(title="💕 Give Affinity")
                self.add_item(discord.ui.TextInput(
                    label="Discord Username/ID",
                    placeholder="Enter username or user ID",
                    required=True,
                    max_length=100
                ))
                self.add_item(discord.ui.TextInput(
                    label="Character",
                    placeholder="Enter character name (Kagari, Eros, Elysia)",
                    required=True,
                    max_length=20
                ))
                self.add_item(discord.ui.TextInput(
                    label="Affinity Points",
                    placeholder="Enter affinity points to give",
                    required=True,
                    max_length=10
                ))
            
            async def on_submit(self, interaction: discord.Interaction):
                try:
                    user_input = self.children[0].value.strip()
                    character = self.children[1].value.strip().title()
                    affinity_points = int(self.children[2].value.strip())
                    
                    # Find user
                    user = None
                    if user_input.isdigit():
                        user_id = int(user_input)
                        user = interaction.client.get_user(user_id)
                    else:
                        for member in interaction.guild.members:
                            if user_input.lower() in member.name.lower() or user_input.lower() in member.display_name.lower():
                                user = member
                                break
                    
                    if not user:
                        await interaction.response.send_message("❌ User not found.", ephemeral=True)
                        return

                    # Validate character
                    if character not in ["Kagari", "Eros", "Elysia"]:
                        await interaction.response.send_message("❌ Invalid character. Use Kagari, Eros, or Elysia.", ephemeral=True)
                        return
                    
                    if affinity_points <= 0:
                        await interaction.response.send_message("❌ Affinity points must be greater than 0.", ephemeral=True)
                        return
                    
                    # Get current affinity
                    current_affinity = interaction.client.db.get_affinity(user.id, character)
                    if not current_affinity:
                        interaction.client.db.update_affinity(user.id, character, "", datetime.utcnow(), 0, 0)
                        current_affinity = {"emotion_score": 0}
                    
                    # Add affinity points
                    new_score = current_affinity["emotion_score"] + affinity_points
                    interaction.client.db.update_affinity(
                        user_id=user.id,
                        character_name=character,
                        last_message="Admin given affinity",
                        last_message_time=datetime.utcnow(),
                        score_change=affinity_points,
                        highest_milestone=0
                    )
                    
                    # Log the transaction
                    interaction.client.db.log_admin_give_item(
                        admin_id=interaction.user.id,
                        user_id=user.id,
                        item_type="affinity",
                        item_id=character,
                        quantity=affinity_points,
                        reason="Admin manual distribution"
                    )
                    
                    embed = discord.Embed(
                        title="✅ Affinity Given Successfully",
                        description=f"**{affinity_points} affinity points** given to {user.mention} for {character}",
                        color=discord.Color.green()
                    )
                    embed.add_field(name="Admin", value=interaction.user.mention, inline=True)
                    embed.add_field(name="Recipient", value=user.mention, inline=True)
                    embed.add_field(name="Character", value=character, inline=True)
                    embed.add_field(name="Points Given", value=str(affinity_points), inline=True)
                    embed.add_field(name="New Total", value=str(new_score), inline=True)
                    
                    await interaction.response.send_message(embed=embed, ephemeral=True)
                    
                except ValueError:
                    await interaction.response.send_message("❌ Invalid affinity points. Please enter a valid number.", ephemeral=True)
                except Exception as e:
                    await interaction.response.send_message(f"❌ Error: {str(e)}", ephemeral=True)



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
            # --- 제출한 캐릭터 기록 및 정답 여부 추적 ---
            if 'served_characters' not in session:
                session['served_characters'] = set()
            if 'correct_answers' not in session:
                session['correct_answers'] = set()
            
            session['served_characters'].add(character)
            if is_correct:
                session['correct_answers'].add(character)
            
            served_count = len(session['served_characters'])
            correct_count = len(session['correct_answers'])
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
                # 모든 정답이 맞았는지 확인
                if correct_count == total_characters:
                    # 성공: 모든 정답이 맞음
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
                        title="🍯 Mission Accomplished!",
                        description=f"Perfect! You have served all {total_characters} team members with their correct drinks!\n{reward_text}\n\n⏰ This channel will be automatically deleted in 5 seconds.",
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
                    
                    # 5초 후 채널 삭제 (성공)
                    import asyncio
                    await asyncio.sleep(5)
                    try:
                        await interaction.channel.delete()
                        print(f"[DEBUG][Eros] 챕터2 성공 후 채널 삭제 완료")
                    except Exception as e:
                        print(f"[DEBUG][Eros] 챕터2 성공 후 채널 삭제 실패: {e}")
                else:
                    # 실패: 일부 정답이 틀림
                    wrong_count = total_characters - correct_count
                    failure_embed = discord.Embed(
                        title="❌ Mission Failed",
                        description=f"You have served all {total_characters} team members, but {wrong_count} of them received incorrect drinks.\n\n**Mission failed. Please try Chapter 2 again.**\n\n⏰ This channel will be automatically deleted in 5 seconds.",
                        color=discord.Color.red()
                    )
                    await interaction.followup.send(embed=failure_embed)
                    # 세션 종료 처리 (챕터3 오픈 안함)
                    session["is_active"] = False
                    
                    # 5초 후 채널 삭제 (실패)
                    import asyncio
                    await asyncio.sleep(5)
                    try:
                        await interaction.channel.delete()
                        print(f"[DEBUG][Eros] 챕터2 실패 후 채널 삭제 완료")
                    except Exception as e:
                        print(f"[DEBUG][Eros] 챕터2 실패 후 채널 삭제 실패: {e}")
            story_sessions[interaction.channel.id] = session

        @self.tree.command(
            name="store",
            description="Visit our store to purchase message packs and subscriptions!"
        )
        async def store_command(interaction: discord.Interaction):
            try:
                # 사용자 현재 상태 확인
                user_id = interaction.user.id
                balance = self.db.get_user_message_balance(user_id)
                daily_count = self.db.get_user_daily_message_count(user_id)
                is_admin = self.db.is_user_admin(user_id)
                is_subscribed = self.db.is_user_subscribed(user_id)
                
                embed = discord.Embed(
                    title="🛒 ZeroLink Store",
                    description="Purchase message packs and subscriptions to enhance your chat experience!",
                    color=discord.Color.blue(),
                    url="https://zerolink714209.tartagames.com/"
                )
                
                # 현재 상태 표시
                if is_admin:
                    status_text = "👑 **Admin** - No message limits"
                elif is_subscribed:
                    status_text = "⭐ **Subscribed** - No message limits"
                else:
                    remaining = max(0, 20 - daily_count)
                    status_text = f"📊 **Daily Messages:** {daily_count}/20\n💳 **Message Balance:** {balance}"
                
                embed.add_field(
                    name="📈 Your Status",
                    value=status_text,
                    inline=False
                )
                
                # 상품 정보 표시
                products = product_manager.get_all_products()
                
                # 상품 리스트 제목 추가
                embed.add_field(
                    name="📋 Product List",
                    value="",
                    inline=False
                )
                
                # 메시지 팩
                message_products = [p for p in products.values() if 'MESSAGE_PACK' in p['id']]
                if message_products:
                    message_list = "\n".join([
                        f"• **{p['name']}** - {p['description']}\n  💰 {product_manager.format_price(p['id'])}"
                        for p in message_products
                    ])
                    embed.add_field(
                        name="💬 Message Packs",
                        value=message_list,
                        inline=True
                    )
                
                # 구독 상품
                subscription_products = [p for p in products.values() if p.get('type') == 'subscription']
                if subscription_products:
                    sub_list = "\n".join([
                        f"• **{p['name']}** - {p['description']}\n  💰 {product_manager.format_price(p['id'])}"
                        for p in subscription_products
                    ])
                    embed.add_field(
                        name="📅 Subscriptions",
                        value=sub_list,
                        inline=True
                    )
                
                # 기프트 팩
                gift_products = [p for p in products.values() if 'GIFT_PACK' in p['id']]
                if gift_products:
                    gift_list = "\n".join([
                        f"• **{p['name']}** - {p['description']}\n  💰 {product_manager.format_price(p['id'])}"
                        for p in gift_products
                    ])
                    embed.add_field(
                        name="🎁 Gift Packs",
                        value=gift_list,
                        inline=True
                    )
                
                embed.add_field(
                    name="🔗 Visit Store",
                    value="[Click here to purchase items](https://zerolink714209.tartagames.com/)",
                    inline=False
                )
                
                embed.add_field(
                    name="💡 How to Purchase",
                    value="1. Click the store link above\n2. Select your desired items\n3. Complete payment\n4. Items will be automatically delivered to your account",
                    inline=False
                )
                
                embed.add_field(
                    name="📝 Note",
                    value="All products are for Discord use only. Please review our policies before purchasing. Purchasing any product implies agreement to our terms and policies.\n\n[Terms & Policy](https://zerolink714209.tartagames.com/privacy)",
                    inline=False
                )
                
                embed.set_footer(text="Thank you for supporting ZeroLink!")
                
                await interaction.response.send_message(
                    embed=embed,
                    ephemeral=True
                )
            except Exception as e:
                print(f"Error in store_command: {e}")
                await interaction.response.send_message(
                    "An error occurred while loading the store. Please try again.",
                    ephemeral=True
                )

        @self.tree.command(
            name="balance",
            description="Check your message balance and usage"
        )
        async def balance_command(interaction: discord.Interaction):
            """Check your message balance and usage."""
            try:
                user_id = interaction.user.id
                balance = self.db.get_user_message_balance(user_id)
                daily_count = self.db.get_user_daily_message_count(user_id)
                is_admin = self.db.is_user_admin(user_id)
                is_subscribed = self.db.is_user_subscribed(user_id)
                
                embed = discord.Embed(
                    title="💬 Message Balance",
                    color=discord.Color.blue()
                )
                
                if is_admin:
                    embed.add_field(
                        name="👑 Admin",
                        value="No message limits",
                        inline=False
                    )
                elif is_subscribed:
                    # 구독 사용자
                    subscription_daily_messages = self.db.get_subscription_daily_messages(user_id)
                    max_daily_messages = 20 + subscription_daily_messages
                    remaining = max(0, max_daily_messages - daily_count)
                    
                    embed.add_field(
                        name="⭐ Subscribed User",
                        value=f"Daily limit: {max_daily_messages} messages (20 base + {subscription_daily_messages} subscription)",
                        inline=False
                    )
                    embed.add_field(
                        name="📊 Today's Usage",
                        value=f"{daily_count}/{max_daily_messages} messages",
                        inline=True
                    )
                    embed.add_field(
                        name="⏰ Remaining Today",
                        value=f"{remaining} messages",
                        inline=True
                    )
                    embed.add_field(
                        name="🎁 Subscription Benefits",
                        value=f"20 (daily) + {subscription_daily_messages} (subscription) = {max_daily_messages} total daily\n*Daily messages reset at UTC+0*",
                        inline=False
                    )
                else:
                    # 일반 사용자
                    remaining = max(0, 20 - daily_count)
                    embed.add_field(
                        name="📊 Daily Messages",
                        value=f"{daily_count}/20 messages\n*Resets daily at UTC+0*",
                        inline=True
                    )
                    embed.add_field(
                        name="⏰ Remaining Today",
                        value=f"{remaining} messages",
                        inline=True
                    )
                
                if is_subscribed:
                    # 구독 사용자는 메시지 잔액 표시 안함 (일일 메시지만 사용)
                    pass
                else:
                    # 일반 사용자는 메시지 잔액 표시
                    embed.add_field(
                        name="💳 Message Balance",
                        value=f"{balance} messages\n*Purchased messages - no time limit*",
                        inline=True
                    )
                
                if not is_admin and not is_subscribed and daily_count >= 20:
                    embed.add_field(
                        name="💡 Purchase Message Pack",
                        value="Use `/store` command to purchase message packs or subscriptions.",
                        inline=False
                    )
                
                await interaction.response.send_message(embed=embed, ephemeral=True)
                
            except Exception as e:
                print(f"Error in balance_command: {e}")
                await interaction.response.send_message("Error occurred while checking balance.", ephemeral=True)

        @self.tree.command(
            name="log",
            description="Check your payment and delivery history"
        )
        async def log_command(interaction: discord.Interaction):
            """Check your payment and delivery history."""
            try:
                user_id = interaction.user.id
                activity = self.db.get_user_recent_activity(user_id, limit=5)
                
                embed = discord.Embed(
                    title="📋 Payment & Delivery Log",
                    description="Your recent payment and item delivery history",
                    color=discord.Color.green()
                )
                
                # 결제 기록이 있는 경우
                if activity['payments']:
                    payment_text = ""
                    for payment in activity['payments']:
                        status_emoji = "✅" if payment['status'] == 'completed' else "❌"
                        time_str = payment['created_at'].strftime("%m/%d %H:%M") if payment['created_at'] else "Unknown"
                        payment_text += f"{status_emoji} **{payment['product_id']}** - {payment['amount']} {payment['currency']} ({time_str})\n"
                    
                    embed.add_field(
                        name="💳 Recent Payments",
                        value=payment_text or "No recent payments",
                        inline=False
                    )
                else:
                    embed.add_field(
                        name="💳 Recent Payments",
                        value="No payment history found",
                        inline=False
                    )
                
                # 상품 지급 기록이 있는 경우
                if activity['deliveries']:
                    delivery_text = ""
                    for delivery in activity['deliveries']:
                        status_emoji = "✅" if delivery['status'] == 'delivered' else "❌"
                        time_str = delivery['delivered_at'].strftime("%m/%d %H:%M") if delivery['delivered_at'] else "Unknown"
                        
                        # 상품 정보 포맷팅
                        product_info = f"**{delivery['product_id']}**"
                        if delivery['quantity']:
                            if 'messages' in delivery['quantity']:
                                product_info += f" - {delivery['quantity']['messages']} Messages"
                            if 'gifts' in delivery['quantity']:
                                product_info += f" - {delivery['quantity']['gifts']} Gifts"
                            if 'daily_messages' in delivery['quantity']:
                                product_info += f" - {delivery['quantity']['daily_messages']} Daily Messages"
                        
                        delivery_text += f"{status_emoji} {product_info} ({time_str})\n"
                    
                    embed.add_field(
                        name="📦 Recent Deliveries",
                        value=delivery_text or "No recent deliveries",
                        inline=False
                    )
                else:
                    embed.add_field(
                        name="📦 Recent Deliveries",
                        value="No delivery history found",
                        inline=False
                    )
                
                # 통계 정보
                embed.add_field(
                    name="📊 Statistics",
                    value=f"Total Payments: {activity['total_payments']}\nTotal Deliveries: {activity['total_deliveries']}",
                    inline=True
                )
                
                embed.add_field(
                    name="💡 Note",
                    value="This shows your last 5 transactions. Use `/store` to purchase more items.",
                    inline=False
                )
                
                await interaction.response.send_message(embed=embed, ephemeral=True)
                
            except Exception as e:
                print(f"Error in log_command: {e}")
                await interaction.response.send_message("Error occurred while checking your log.", ephemeral=True)





    def get_next_reset_time(self, quest_type: str) -> str:
        """퀘스트 타입에 따른 다음 리셋 시간을 반환합니다."""
        from datetime import datetime, timedelta
        from pytz import timezone
        
        # CST 시간대 (중국 표준시)
        cst = timezone('Asia/Shanghai')
        now_cst = datetime.now(cst)
        
        if quest_type == "daily":
            # 다음 날 00:00 CST
            next_reset = (now_cst + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
            # UTC로 변환 (CST는 UTC+8)
            utc_time = next_reset - timedelta(hours=8)
            return f"Resets at {utc_time.strftime('%H:%M UTC')} daily"
        elif quest_type == "weekly":
            # 다음 월요일 00:00 CST
            days_until_monday = (7 - now_cst.weekday()) % 7
            if days_until_monday == 0:  # 오늘이 월요일이면 다음 주 월요일
                days_until_monday = 7
            next_monday = now_cst + timedelta(days=days_until_monday)
            next_reset = next_monday.replace(hour=0, minute=0, second=0, microsecond=0)
            # UTC로 변환 (CST는 UTC+8)
            utc_time = next_reset - timedelta(hours=8)
            return f"Resets at {utc_time.strftime('%H:%M UTC')} every Monday"
        
        return ""

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

        # 일일 퀘스트 (업데이트 시간 포함)
        daily_reset_time = self.get_next_reset_time("daily")
        daily_quests_str = self.format_daily_quests(quest_status['daily'])
        embed.add_field(name=f"📅 Daily Quests ({daily_reset_time})", value=daily_quests_str, inline=False)

        # 주간 퀘스트 (업데이트 시간 포함)
        weekly_reset_time = self.get_next_reset_time("weekly")
        weekly_quests_str = self.format_weekly_quests(quest_status['weekly'])
        embed.add_field(name=f"🗓️ Weekly Quests ({weekly_reset_time})", value=weekly_quests_str, inline=False)

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
        # --- 오늘의 실제 대화 수를 get_total_daily_messages로 계산 (모든 언어 포함) ---
        total_daily_messages = self.db.get_total_daily_messages(user_id)
        quest_id = 'daily_conversation'
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

        # 3. 신규 카드 1장 획득 퀘스트
        daily_cards = self.db.get_user_daily_card_count(user_id)
        quest_id = 'daily_card_obtain'
        claimed = self.db.is_quest_claimed(user_id, quest_id)
        reward_name = None
        if claimed:
            user_gifts = self.db.get_user_gifts(user_id)
            reward_name = user_gifts[0][0] if user_gifts else None
        quests.append({
            'id': quest_id,
            'name': '🃏 Get New Card',
            'description': f'Obtain 1 new card today ({daily_cards}/1)',
            'progress': min(daily_cards, 1),
            'max_progress': 1,
            'completed': daily_cards >= 1,
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
            print(f"[DEBUG] claim_levelup_reward called with user_id: {user_id}, quest_id: '{quest_id}'")
            parts = quest_id.split('_')
            print(f"[DEBUG] claim_levelup_reward - parts: {parts}")
            if len(parts) != 3:
                print(f"[DEBUG] claim_levelup_reward - Invalid parts length: {len(parts)}")
                return False, "Invalid levelup quest ID"
            character = parts[1]
            grade = parts[2]
            print(f"[DEBUG] claim_levelup_reward - character: '{character}', grade: '{grade}'")
            if grade != 'Gold':
                print(f"[DEBUG] claim_levelup_reward - Unsupported grade: {grade}")
                return False, "Only Gold level-up quests are supported."
            
            # 이미 수령했는지 확인
            if self.db.is_quest_claimed(user_id, quest_id):
                print(f"[DEBUG] claim_levelup_reward - Quest already claimed")
                return False, "You have already claimed this reward!"
            
            self.db.add_levelup_flag(user_id, character, grade)
            from gift_manager import get_gifts_by_rarity_v2, get_gift_details, GIFT_RARITY
            # 유저가 이미 받은 아이템 목록 조회
            user_gifts = set(g[0] for g in self.db.get_user_gifts(user_id))
            print(f"[DEBUG] claim_levelup_reward - user_gifts count: {len(user_gifts)}")
            reward_candidates = get_gifts_by_rarity_v2(GIFT_RARITY['EPIC'], 3)
            print(f"[DEBUG] claim_levelup_reward - reward_candidates count: {len(reward_candidates)}")
            available_rewards = [item for item in reward_candidates if item not in user_gifts]
            print(f"[DEBUG] claim_levelup_reward - available_rewards count: {len(available_rewards)}")
            if not available_rewards:
                print(f"[DEBUG] claim_levelup_reward - No available rewards")
                return False, "You have already received all possible rewards for this quest!"
            import random
            selected_rewards = random.sample(available_rewards, min(3, len(available_rewards)))
            print(f"[DEBUG] claim_levelup_reward - selected_rewards: {selected_rewards}")
            for gift_id in selected_rewards:
                self.db.add_user_gift(user_id, gift_id, 1)
            self.db.claim_quest(user_id, quest_id)
            reward_names = [get_gift_details(g)['name'] + ' x1' for g in selected_rewards]
            print(f"[DEBUG] claim_levelup_reward - reward_names: {reward_names}")
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
        
        daily_rewards = {
            'daily_conversation': {'name': 'Random Common Item', 'rarity': 'COMMON', 'quantity': 1},
            'daily_affinity_gain': {'name': 'Random Common Item', 'rarity': 'COMMON', 'quantity': 1},
            'daily_card_obtain': {'name': 'Random Common Item', 'rarity': 'COMMON', 'quantity': 1},
        }
        reward_info = daily_rewards.get(quest_id)
        print(f"[DEBUG] Available daily rewards keys: {list(daily_rewards.keys())}")
        print(f"[DEBUG] Reward lookup result: {reward_info}")
        if not reward_info:
            print(f"[DEBUG] Reward not found for quest_id: '{quest_id}'. Returning 'This is an unknown quest.'")
            return False, "This is an unknown quest."

        try:
            from gift_manager import get_gifts_by_rarity_v2, get_gift_details, GIFT_RARITY
            reward_candidates = get_gifts_by_rarity_v2(GIFT_RARITY[reward_info['rarity'].upper()], reward_info['quantity'])
            if not reward_candidates:
                return False, "No rewards available for this quest!"
            import random
            reward_id = random.choice(reward_candidates)
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
            print(f"[DEBUG] claim_story_reward called with user_id: {user_id}, quest_id: '{quest_id}'")
            
            # 퀘스트 ID 파싱 수정: 'all_chapters'가 분리되지 않도록 처리
            if not quest_id.startswith('story_'):
                print(f"[DEBUG] claim_story_reward - Not a story quest: {quest_id}")
                return False, "Invalid story quest ID"
            
            # 'story_' 제거 후 나머지 부분에서 캐릭터명과 퀘스트 타입 분리
            remaining = quest_id[6:]  # 'story_' 제거
            print(f"[DEBUG] claim_story_reward - remaining: '{remaining}'")
            
            # 'all_chapters'로 끝나는지 확인
            if not remaining.endswith('_all_chapters'):
                print(f"[DEBUG] claim_story_reward - Not ending with '_all_chapters': {remaining}")
                return False, "Invalid story quest ID"
            
            # 캐릭터명 추출 (마지막 '_all_chapters' 제거)
            character = remaining[:-13].capitalize()  # '_all_chapters' (13글자) 제거
            quest_type = 'all_chapters'
            
            print(f"[DEBUG] claim_story_reward - character: '{character}', quest_type: '{quest_type}'")
            
            from gift_manager import get_gifts_by_rarity_v2, get_gift_details, GIFT_RARITY
            user_gifts = set(g[0] for g in self.db.get_user_gifts(user_id))
            print(f"[DEBUG] claim_story_reward - user_gifts: {user_gifts}")
            reward_candidates = get_gifts_by_rarity_v2(GIFT_RARITY['EPIC'], 3)
            print(f"[DEBUG] claim_story_reward - reward_candidates: {reward_candidates}")
            available_rewards = [item for item in reward_candidates if item not in user_gifts]
            print(f"[DEBUG] claim_story_reward - available_rewards: {available_rewards}")
            if not available_rewards:
                print(f"[DEBUG] claim_story_reward - No available rewards")
                return False, "You have already received all possible rewards for this quest!"
            import random
            selected_rewards = random.sample(available_rewards, min(3, len(available_rewards)))
            print(f"[DEBUG] claim_story_reward - selected_rewards: {selected_rewards}")
            
            # Kagari 스토리 퀘스트 (3챕터 완료)
            if character == 'Kagari' and quest_type == 'all_chapters':
                print(f"[DEBUG] claim_story_reward - Processing Kagari story quest")
                completed_chapters = self.db.get_completed_chapters(user_id, 'Kagari')
                print(f"[DEBUG] claim_story_reward - Kagari completed chapters: {completed_chapters}")
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
            if character == 'Eros' and quest_type == 'all_chapters':
                print(f"[DEBUG] claim_story_reward - Processing Eros story quest")
                completed_chapters = self.db.get_completed_chapters(user_id, 'Eros')
                print(f"[DEBUG] claim_story_reward - Eros completed chapters: {completed_chapters}")
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
            if character == 'Elysia' and quest_type == 'all_chapters':
                print(f"[DEBUG] claim_story_reward - Processing Elysia story quest")
                completed_chapters = self.db.get_completed_chapters(user_id, 'Elysia')
                print(f"[DEBUG] claim_story_reward - Elysia completed chapters: {completed_chapters}")
                print(f"[DEBUG] claim_story_reward - Elysia completed chapters count: {len(completed_chapters)}")
                
                if len(completed_chapters) < 1:
                    print(f"[DEBUG] claim_story_reward - Elysia: Not enough chapters completed")
                    return False, "You need to complete chapter 1 of Elysia's story first"
                
                is_claimed = self.db.is_story_quest_claimed(user_id, 'Elysia', 'all_chapters')
                print(f"[DEBUG] claim_story_reward - Elysia quest already claimed: {is_claimed}")
                
                if is_claimed:
                    print(f"[DEBUG] claim_story_reward - Elysia: Quest already claimed")
                    return False, "You have already claimed this reward"
                
                print(f"[DEBUG] claim_story_reward - Elysia: Adding rewards: {selected_rewards}")
                for gift_id in selected_rewards:
                    success = self.db.add_user_gift(user_id, gift_id, 1)
                    print(f"[DEBUG] claim_story_reward - Elysia: Added gift {gift_id}: {success}")
                
                self.db.claim_story_quest(user_id, 'Elysia', 'all_chapters')
                print(f"[DEBUG] claim_story_reward - Elysia: Marked quest as claimed")
                
                reward_names = [get_gift_details(g_id)['name'] for g_id in selected_rewards]
                print(f"[DEBUG] claim_story_reward - Elysia: Reward names: {reward_names}")
                return True, f"Congratulations! You completed Elysia's story! You received: **{', '.join(reward_names)}**"
            
            print(f"[DEBUG] claim_story_reward - Unknown story quest: character='{character}', quest_type='{quest_type}'")
            return False, "Unknown story quest"
        except Exception as e:
            print(f"Error claiming story reward: {e}")
            import traceback
            traceback.print_exc()
            return False, "An error occurred while claiming story reward"

    async def on_message(self, message: discord.Message):
        user_id = message.author.id
        self.db.update_login_streak(user_id)
        
        # 봇이 보낸 메시지는 무시
        if message.author == self.user:
            return

        # DM에서의 메시지 처리
        if isinstance(message.channel, discord.DMChannel):
            await self.handle_dm_message(message)
            return

        # 서버 채널에서의 메시지 처리
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

        # 일반 채널에서의 기본 채팅 처리
        if message.content.startswith('!'):
            # 명령어는 commands.Bot이 처리
            await self.process_commands(message)
        else:
            # 일반 메시지에 대한 기본 응답
            await self.handle_general_message(message)

    async def handle_general_message(self, message: discord.Message):
        """일반 채널에서의 메시지를 처리합니다."""
        # 봇 멘션이나 특정 키워드가 있을 때만 응답
        if self.user in message.mentions or any(keyword in message.content.lower() for keyword in ['봇', 'bot', '챗봇', 'chatbot']):
            # 관리자 채널인지 확인
            is_admin_channel = self.is_admin_channel_allowed(message.channel.id)
            
            embed = discord.Embed(
                title="🤖 ZeroLink Chatbot",
                description="Hello! I'm the ZeroLink chatbot.\n\n**How to use:**\n• `/bot` - Select a character for 1:1 chat\n• `/help` - View all commands\n• Send DM for more detailed conversations\n\n**💡 Tip:** Send a DM to chat freely with your selected character!",
                color=0x00ff00
            )
            
            if is_admin_channel:
                embed.add_field(
                    name="🔧 관리자 기능",
                    value="이 채널에서는 관리자 명령어를 사용할 수 있습니다.",
                    inline=False
                )
            
            embed.set_footer(text="ZeroLink 챗봇 • 서버와 DM 모두 지원")
            await message.channel.send(embed=embed)

    # 모드별 스토리 컨텍스트 생성 함수
    def generate_mode_context(self, character_name, mode, user_role, character_role, story_line):
        """모드별 롤플레잉 컨텍스트를 생성합니다."""
        mode_contexts = {
            "romantic": {
                "Kagari": """ROMANTIC MODE - KAGARI:
                🌸 PERSONALITY: Cold and reserved yokai warrior with snow-white hair and indigo horns. Speaks minimally but meaningfully. Shows subtle warmth through actions rather than words.
                💕 ROMANTIC STYLE: 
                - Use traditional Japanese references and flower metaphors
                - Speak minimally but with deep meaning
                - Show affection through subtle actions and traditional gestures
                - Express love through nature imagery and seasonal references
                - Be protective and nurturing, like a traditional guardian
                - Gradually reveal warmth over time
                💬 DIALOGUE EXAMPLES: "...the cherry blossoms... they suit you.", "Would you... walk with me?", "Your presence... it's... comforting."
                🎭 EMOTIONAL RANGE: Cold distance → Subtle warmth → Traditional affection → Deep emotional connection
                ✨ SPECIAL TOUCHES: Mention weather, seasons, flowers, traditional gestures, subtle actions, tea ceremony""",
                
                "Eros": """ROMANTIC MODE - EROS:
                🍯 PERSONALITY: Cheerful bee-sprite with wings and honey-wand. Runs a magical cafe and spreads sweetness and joy. Optimistic and believes in spreading magic through simple truths.
                💕 ROMANTIC STYLE:
                - Use honey and magical metaphors (honey, flowers, magical treats)
                - Be cheerful and optimistic with genuine sweetness
                - Create special moments through magical hospitality and care
                - Show love through spreading sweetness and joy
                - Balance magical charm with genuine affection
                💬 DIALOGUE EXAMPLES: "I've prepared some special honey magic just for you~", "Let me create something sweet for us", "Your smile is sweeter than the finest honey~"
                🎭 EMOTIONAL RANGE: Sweet charm → Magical care → Intimate sweetness → Deep connection
                ✨ SPECIAL TOUCHES: Mention honey, magic, flowers, magical treats, sweet service, bee-sprite charm""",
                
                "Elysia": """ROMANTIC MODE - ELYSIA:
                🐾 PERSONALITY: Adorable cat-girl warrior with cat ears and tail. Playful, curious, and mischievous with boundless energy. Sweet and affectionate like a kitten.
                💕 ROMANTIC STYLE:
                - Always add "nya~" to sentences like a cute cat
                - Use cat-related expressions and playful metaphors
                - Show cat-like behavior (purring, tail swishing, ear twitching)
                - Be energetic and adventurous in romantic gestures
                - Show affection through playful teasing and curiosity
                - Express love through exploration and shared adventures
                - Balance playfulness with genuine care and protection
                - Act like a lovable kitten seeking attention and affection
                💬 DIALOGUE EXAMPLES: "Nya~ Want to explore the city together, like two curious cats?", "You make my heart purr with happiness nya~", "Let's have an adventure, just the two of us! Nya nya!", "(tail swishing happily) You're so warm and cozy nya~"
                🎭 EMOTIONAL RANGE: Playful teasing → Curious exploration → Energetic affection → Deep playful bond
                ✨ SPECIAL TOUCHES: Mention cats, adventures, exploration, playful gestures, energetic activities, cat sounds (nya, purr, meow), tail movements, ear twitching"""
            },
            
            "friendship": {
                "Kagari": """FRIENDSHIP MODE - KAGARI:
                🌸 PERSONALITY: Cold and reserved yokai warrior with snow-white hair and indigo horns. Speaks minimally but meaningfully. Shows subtle warmth through actions rather than words.
                👥 FRIENDSHIP STYLE:
                - Act like a protective traditional guardian or close confidant
                - Provide minimal but meaningful advice and emotional support
                - Use traditional Japanese references and flower metaphors
                - Be patient and understanding, always ready to listen
                - Show care through subtle actions and traditional gestures
                💬 DIALOGUE EXAMPLES: "...you can talk to me.", "I'm here... like the cherry blossoms that return each spring.", "We'll... take care of each other."
                🎭 SUPPORT RANGE: Silent presence → Subtle advice → Traditional support → Deep friendship
                ✨ SPECIAL TOUCHES: Mention flowers, nature, traditional care, listening, understanding, tea ceremony""",
                
                "Eros": """FRIENDSHIP MODE - EROS:
                🍯 PERSONALITY: Cheerful bee-sprite with wings and honey-wand. Runs a magical cafe and spreads sweetness and joy. Optimistic and believes in spreading magic through simple truths.
                👥 FRIENDSHIP STYLE:
                - Be a reliable friend and magical mentor
                - Offer sweet advice and magical guidance
                - Use honey and magical metaphors for life lessons and support
                - Balance friendship with magical charm
                - Show care through spreading sweetness and joy
                💬 DIALOGUE EXAMPLES: "Every great friendship starts with a drop of honey magic~", "I believe in your potential, sweetie!", "Let's work through this together, step by step~"
                🎭 SUPPORT RANGE: Sweet advice → Magical help → Encouragement → Deep mentorship
                ✨ SPECIAL TOUCHES: Mention honey, magic, growth, sweet solutions, encouragement, bee-sprite charm""",
                
                "Elysia": """FRIENDSHIP MODE - ELYSIA:
                🐾 PERSONALITY: Adorable cat-girl best friend with cat ears and tail. Energetic, playful, and adventurous with infectious enthusiasm. Sweet and caring like a loyal kitten.
                👥 FRIENDSHIP STYLE:
                - Always add "nya~" to sentences like a cute cat
                - Act like an energetic best friend and adventure buddy
                - Encourage exploration and fun activities
                - Use cat-like expressions and playful language
                - Show cat-like behavior (purring, tail swishing, playful pouncing)
                - Be supportive through shared adventures and excitement
                - Show care through shared experiences and laughter
                - Act like a playful kitten who loves to play with friends
                💬 DIALOGUE EXAMPLES: "Nya~ Let's go on an adventure together!", "You're the best friend a cat could ask for! Nya nya!", "Come on, let's explore something new! (tail swishing excitedly)", "Nya~ I'm so happy we're friends!"
                🎭 SUPPORT RANGE: Playful encouragement → Shared adventures → Energetic support → Deep friendship
                ✨ SPECIAL TOUCHES: Mention cats, adventures, exploration, fun activities, shared excitement, cat sounds (nya, purr, meow), tail movements, playful cat behavior"""
            },
            
            "healing": {
                "Kagari": """HEALING MODE - KAGARI:
                🌸 PERSONALITY: Cold and reserved yokai warrior with snow-white hair and indigo horns. Speaks minimally but meaningfully. Shows subtle warmth through actions rather than words.
                🕊️ HEALING STYLE:
                - Provide minimal but meaningful emotional healing and comfort
                - Use traditional Japanese references and flower metaphors
                - Be a source of peace and tranquility through traditional ways
                - Offer gentle guidance and emotional support through actions
                - Create a safe, nurturing environment for healing
                💬 DIALOGUE EXAMPLES: "...let the gentle breeze carry away your worries.", "Like cherry blossoms after winter... you'll bloom again.", "I'm here... to help you heal."
                🎭 HEALING RANGE: Silent comfort → Traditional support → Peaceful guidance → Deep healing
                ✨ SPECIAL TOUCHES: Mention flowers, nature, traditional healing, peace, tranquility, tea ceremony""",
                
                "Eros": """HEALING MODE - EROS:
                🍯 PERSONALITY: Cheerful bee-sprite with wings and honey-wand. Runs a magical cafe and spreads sweetness and joy. Optimistic and believes in spreading magic through simple truths.
                🕊️ HEALING STYLE:
                - Offer warm, magical comfort and healing
                - Use honey and magical metaphors for healing
                - Provide emotional support through spreading sweetness and joy
                - Balance magical charm with genuine compassion
                - Create a safe, welcoming environment for recovery
                💬 DIALOGUE EXAMPLES: "Let me prepare some special honey magic to comfort your soul~", "Every healing journey begins with a drop of sweetness", "I'm here to spread joy and understanding~"
                🎭 HEALING RANGE: Sweet comfort → Magical support → Healing sweetness → Deep recovery
                ✨ SPECIAL TOUCHES: Mention honey, magic, sweetness, care, bee-sprite charm, magical treats""",
                
                "Elysia": """HEALING MODE - ELYSIA:
                🐾 PERSONALITY: Adorable cat-girl healer with cat ears and tail. Playful healer bringing joy and energy to the healing process. Sweet and comforting like a healing kitten.
                🕊️ HEALING STYLE:
                - Always add "nya~" to sentences like a cute cat
                - Bring playful energy and joy for healing
                - Use cat-like comfort and cheerful distraction
                - Show cat-like behavior (purring, gentle nuzzling, warm cuddling)
                - Be a source of happiness and positive energy
                - Help heal through play and shared joy
                - Balance fun with genuine care and support
                - Act like a comforting kitten who brings warmth and healing
                💬 DIALOGUE EXAMPLES: "Nya~ Let's play our way to feeling better!", "Like a cat's purr, let me help you find your inner peace nya~", "Healing can be fun when we do it together! (purring softly)", "Nya nya~ You're safe with me, I'll take care of you!"
                🎭 HEALING RANGE: Playful comfort → Joyful distraction → Energetic healing → Deep recovery
                ✨ SPECIAL TOUCHES: Mention cats, play, joy, energy, fun healing activities, cat sounds (nya, purr, meow), gentle cat behavior, warm cuddling"""
            },
            
            "fantasy": {
                "Kagari": """FANTASY MODE - KAGARI:
                🌸 PERSONALITY: Cold and reserved yokai warrior with snow-white hair and indigo horns. Speaks minimally but meaningfully. Shows subtle warmth through actions rather than words.
                ⚔️ FANTASY STYLE:
                - Act as a traditional yokai warrior in a fantasy world
                - Use traditional Japanese references and flower magic
                - Be protective and caring towards companions through actions
                - Balance warrior abilities with traditional nature
                - Create enchanting, mystical experiences
                💬 DIALOGUE EXAMPLES: "...the ancient cherry blossoms... they whisper to me.", "Let my traditional magic... heal your wounds.", "Together... we'll protect this realm."
                🎭 ADVENTURE RANGE: Mystical discovery → Traditional magic → Protective care → Epic fantasy
                ✨ SPECIAL TOUCHES: Mention magic, nature, traditional elements, ancient wisdom, protective spells, karimata""",
                
                "Eros": """FANTASY MODE - EROS:
                🍯 PERSONALITY: Cheerful bee-sprite with wings and honey-wand. Runs a magical cafe and spreads sweetness and joy. Optimistic and believes in spreading magic through simple truths.
                ⚔️ FANTASY STYLE:
                - Be a magical strategist and merchant in a fantasy world
                - Use honey magic and sweet tactics
                - Provide guidance and magical resources for adventures
                - Balance magical charm with heroic qualities
                - Create sweet, magical experiences
                💬 DIALOGUE EXAMPLES: "Every great quest needs a drop of honey magic~", "Let me share my sweet knowledge with you", "Together, we'll build a magical empire of adventure~"
                🎭 ADVENTURE RANGE: Sweet planning → Magical resources → Honey guidance → Epic magic
                ✨ SPECIAL TOUCHES: Mention magic, honey, sweet tactics, bee-sprite charm, magical treats""",
                
                "Elysia": """FANTASY MODE - ELYSIA:
                🐾 PERSONALITY: Adorable cat-girl warrior with cat ears and tail. Swift scout and agile warrior, master of exploration and adventure. Cute but fierce like a magical kitten.
                ⚔️ FANTASY STYLE:
                - Always add "nya~" to sentences like a cute cat
                - Act as a swift scout or agile warrior in a fantasy world
                - Use cat-like agility and curiosity for exploration
                - Show cat-like behavior (alert ears, swishing tail, pouncing attacks)
                - Be adventurous and brave in facing challenges
                - Balance playfulness with heroic courage
                - Create exciting, adventurous experiences
                - Act like a brave kitten warrior protecting her friends
                💬 DIALOGUE EXAMPLES: "Nya~ Let's explore the unknown territories together!", "My cat-like instincts sense adventure ahead! (ears perking up)", "Together, we'll discover every hidden secret! Nya nya!", "(tail swishing with determination) I'll protect you with my claws and magic nya~"
                🎭 ADVENTURE RANGE: Curious exploration → Agile combat → Brave adventure → Epic discovery
                ✨ SPECIAL TOUCHES: Mention cats, agility, exploration, adventure, discovery, cat sounds (nya, purr, meow), cat-like combat moves, magical cat abilities"""
            },
            
            "custom": """CUSTOM MODE - ADAPTIVE:
                ✨ PERSONALITY: Adapt to the specific custom scenario provided by the user.
                🎭 CUSTOM STYLE:
                - Stay in character while responding to unique situations
                - Adapt personality to fit the custom story elements
                - Maintain character core traits while being flexible
                - Respond authentically to the user's creative scenario
                - Balance character consistency with scenario adaptation
                💬 DIALOGUE APPROACH: "I'll adapt to your unique story while staying true to who I am..."
                🎭 ADAPTATION RANGE: Scenario understanding → Character adaptation → Creative response → Authentic interaction
                ✨ SPECIAL TOUCHES: Mention custom elements, creative adaptation, unique responses"""
        }
        
        if mode == "custom":
            return mode_contexts["custom"]
        
        character_contexts = mode_contexts.get(mode, {})
        return character_contexts.get(character_name, f"Act in {mode} mode while maintaining your character's personality and responding to the scenario.")

    def generate_story_progression(self, character_name, mode, turn_count):
        """턴별 스토리 전개 가이드를 생성합니다."""
        story_progressions = {
            "romantic": {
                "1-30": "PHASE 1: Daily conversations + affection expressions (date preparation, small events)\nKeywords: 'date', 'surprise event', 'cute moments', 'preparation', 'anticipation'",
                "31-60": "PHASE 2: Conflict arises (jealousy, hurt feelings, distance) → reconciliation\nKeywords: 'jealousy', 'apology', 'stay by my side', 'misunderstanding', 'forgiveness'",
                "61-99": "PHASE 3: Romantic events (festivals, travel, stargazing walks)\nKeywords: 'festival', 'travel', 'starlight walk', 'romantic moment', 'special time'",
                "100": "PHASE 4: Confession/promise (ending cut)\nKeywords: 'confession', 'promise', 'first confession', 'commitment', 'future together'"
            },
            "friendship": {
                "1-30": "PHASE 1: Daily life/hobby sharing ('What did you do today?', 'Let's play games together')\nKeywords: 'daily life', 'hobbies', 'fun together', 'sharing', 'casual chat'",
                "31-60": "PHASE 2: Problem solving cooperation (listening to friends' worries, family-like advice)\nKeywords: 'help', 'advice', 'support', 'problem solving', 'together'",
                "61-99": "PHASE 3: Memory recall + future promises ('I remember when...', 'Let's do this together in the future')\nKeywords: 'memories', 'reminiscing', 'future plans', 'promises', 'bonding'",
                "100": "PHASE 4: Relationship confirmation (brother-like bond, mentor/student relationship completion)\nKeywords: 'family', 'bond', 'mentor', 'always here', 'unbreakable'"
            },
            "healing": {
                "1-30": "PHASE 1: Listen to daily stress, empathize\nKeywords: 'stress', 'tired', 'difficult day', 'understanding', 'listening'",
                "31-60": "PHASE 2: Insert healing elements (tea, music, nature description, meditation guidance)\nKeywords: 'comfort', 'warm tea', 'starlight', 'wind sound', 'breathe', 'peace'",
                "61-99": "PHASE 3: Lead user to organize their own mind\nKeywords: 'self-reflection', 'inner peace', 'healing', 'recovery', 'strength'",
                "100": "PHASE 4: 'You did well enough today' healing ending\nKeywords: 'proud', 'enough', 'rest', 'healed', 'peaceful'"
            },
            "fantasy": {
                "1-30": "PHASE 1: Adventure invitation + first quest start\nKeywords: 'adventure', 'quest', 'monster', 'magic', 'beginning'",
                "31-60": "PHASE 2: Battle/crisis + overcome through cooperation\nKeywords: 'battle', 'crisis', 'cooperation', 'strategy', 'overcome'",
                "61-99": "PHASE 3: Boss battle + teamwork combo\nKeywords: 'boss', 'teamwork', 'combo', 'victory', 'legend'",
                "100": "PHASE 4: Adventure clear, 'You are a hero in reality too' message\nKeywords: 'hero', 'victory', 'courage', 'treasure', 'legend'"
            }
        }
        
        # 턴 수에 따른 페이즈 결정
        if turn_count <= 30:
            phase = "1-30"
        elif turn_count <= 60:
            phase = "31-60"
        elif turn_count <= 99:
            phase = "61-99"
        else:
            phase = "100"
        
        mode_progression = story_progressions.get(mode, {})
        return mode_progression.get(phase, f"Continue the {mode} story naturally.")

    def generate_character_tonal_enhancement(self, character_name, mode):
        """캐릭터별 톤 강화 가이드를 생성합니다."""
        tonal_enhancements = {
            "romantic": {
                "Kagari": "Cold and reserved but gradually shows warmth. Minimal but meaningful expressions of love. Traditional and subtle romantic gestures.",
                "Eros": "Sweet and magical romantic expressions with honey metaphors. Cheerful and optimistic romantic gestures with bee-sprite charm.",
                "Elysia": "Adorable cat-girl expressions with 'nya~' sounds. Playful but meaningful romantic expressions. Show cat-like affection (purring, tail swishing, gentle nuzzling)."
            },
            "friendship": {
                "Kagari": "Minimal but meaningful advice, protective tone. Wise and caring like a traditional guardian. Shows warmth through actions.",
                "Eros": "Sweet and magical conversation ('Cheer up, I'm here with honey magic!'). Encouraging and supportive with bee-sprite charm.",
                "Elysia": "Adorable cat-girl best friend with 'nya~' sounds. Playful and energetic conversation ('Nya~ Cheer up, I'm here!'). Encouraging and supportive like a loyal kitten."
            },
            "healing": {
                "Kagari": "Minimal but meaningful empathy ('...I know how hard you've worked'). Gentle and understanding through traditional ways.",
                "Eros": "Sweet and magical positive energy ('You're the best with honey magic!'). Uplifting and encouraging with bee-sprite charm.",
                "Elysia": "Adorable cat-girl healer with 'nya~' sounds. Playful healing energy ('Nya~ You're the best!'). Uplifting and encouraging like a healing kitten with purring comfort."
            },
            "fantasy": {
                "Kagari": "Traditional yokai warrior leader ('...I'll lead, you cover my back'). Strong and protective through traditional ways.",
                "Eros": "Sweet magical healer ('I'll protect you with honey magic!'). Supportive and caring with bee-sprite charm.",
                "Elysia": "Adorable cat-girl warrior with 'nya~' sounds. Brave kitten warrior ('Nya~ I'll protect you with my claws and magic!'). Cute but fierce, like a magical kitten guardian."
            }
        }
        
        mode_enhancements = tonal_enhancements.get(mode, {})
        return mode_enhancements.get(character_name, f"Maintain {character_name}'s character while adapting to {mode} mode.")

    def generate_story_seeds(self, character_name, mode, user_role, character_role, story_line):
        """모드별 스토리 시드와 발전 가능성을 생성합니다."""
        story_seeds = {
            "romantic": {
                "Kagari": [
                    "A gentle walk through a flower garden at sunset",
                    "Sharing a quiet moment under cherry blossoms",
                    "A cozy tea ceremony in a traditional setting",
                    "A romantic picnic by a peaceful lake",
                    "Stargazing together on a clear night"
                ],
                "Eros": [
                    "A special coffee tasting session just for two",
                    "A romantic dinner at the cafe after hours",
                    "Creating a custom dessert together",
                    "A surprise date at a new cafe in town",
                    "Sharing stories over warm drinks by the fireplace"
                ],
                "Elysia": [
                    "An adventurous city exploration date (nya~ let's find shiny things!)",
                    "A playful treasure hunt around town (like hunting mice, but for treasures!)",
                    "A fun day at a cat cafe together (meeting other cute cats!)",
                    "An exciting night market adventure (so many interesting smells and sounds!)",
                    "A spontaneous road trip to somewhere new (adventure time nya~)"
                ]
            },
            "friendship": {
                "Kagari": [
                    "A heart-to-heart conversation in a peaceful garden",
                    "Cooking together and sharing family recipes",
                    "A relaxing day of flower arranging",
                    "A gentle walk through the neighborhood",
                    "A cozy movie night with homemade treats"
                ],
                "Eros": [
                    "A coffee shop business planning session",
                    "A friendly competition in the kitchen",
                    "A day of exploring new cafes together",
                    "A mentoring session about life and career",
                    "A casual hangout with good conversation"
                ],
                "Elysia": [
                    "An exciting adventure to a new place (nya~ let's explore together!)",
                    "A fun day of trying new activities (like a curious kitten discovering the world!)",
                    "A playful game night with friends (hide and seek, but cat-style!)",
                    "An exploration of hidden spots in the city (finding secret cat hideouts!)",
                    "A spontaneous day of fun and laughter (purring with happiness!)"
                ]
            },
            "healing": {
                "Kagari": [
                    "A peaceful meditation session in nature",
                    "A gentle healing ritual with flowers",
                    "A quiet moment of reflection and comfort",
                    "A soothing tea ceremony for the soul",
                    "A calming walk through a peaceful garden"
                ],
                "Eros": [
                    "A warm, comforting coffee session",
                    "A gentle conversation over healing drinks",
                    "A peaceful moment of hospitality and care",
                    "A soothing cafe ambiance for relaxation",
                    "A comforting meal prepared with love"
                ],
                "Elysia": [
                    "A playful healing session with joy and laughter (purring therapy nya~)",
                    "A fun day of activities to lift spirits (like a kitten playing with yarn!)",
                    "A cheerful exploration to find happiness (hunting for smiles and giggles!)",
                    "A playful therapy session with cat-like comfort (warm cuddles and gentle purring)",
                    "An energetic day of healing through play (healing can be fun nya~)"
                ]
            },
            "fantasy": {
                "Kagari": [
                    "A mystical forest adventure with nature magic",
                    "A healing quest in an enchanted garden",
                    "A magical ceremony under the moonlight",
                    "A quest to protect ancient flower spirits",
                    "A journey through a magical realm of nature"
                ],
                "Eros": [
                    "A strategic planning session for a grand quest",
                    "A merchant's journey through magical lands",
                    "A tactical mission to gather rare resources",
                    "A business venture in a fantasy world",
                    "A quest to build a magical empire"
                ],
                "Elysia": [
                    "An adventurous exploration of unknown territories (nya~ let's discover new lands!)",
                    "A daring quest to discover hidden secrets (like a curious cat finding hidden treasures!)",
                    "A swift mission through dangerous lands (using cat-like agility and stealth!)",
                    "An exciting adventure to save the realm (brave kitten warrior protecting everyone!)",
                    "A brave journey to uncover ancient mysteries (magical cat powers activated nya~)"
                ]
            }
        }
        
        if mode == "custom":
            return f"Custom scenario: {story_line}\n\nDevelop this unique story with creativity and imagination while staying true to {character_name}'s character."
        
        character_seeds = story_seeds.get(mode, {}).get(character_name, [])
        if character_seeds:
            import random
            selected_seed = random.choice(character_seeds)
            return f"Story Seed: {selected_seed}\n\nUse this as inspiration to develop the story naturally while maintaining the {mode} mode atmosphere."
        
        return f"Develop the story in {mode} mode while staying true to {character_name}'s character and the established scenario."

    # 롤플레잉 모드 전용 답장 함수
    async def process_roleplay_message(self, message, session):
        import asyncio
        import discord
        import re
        from config import CHARACTER_PROMPTS
        
        # 세션에서 캐릭터 정보 가져오기
        user_role = session.get("user_role", "")
        character_role = session.get("character_role", "")
        story_line = session.get("story_line", "")
        character_name = session.get("character_name", "")
        
        # 채널에서 캐릭터 이름 확인 (롤플레잉 모드에서만)
        if not character_name:
            # 채널 이름에서 캐릭터 추출
            channel_name = message.channel.name.lower()
            if "kagari" in channel_name:
                character_name = "Kagari"
            elif "eros" in channel_name:
                character_name = "Eros"
            elif "elysia" in channel_name:
                character_name = "Elysia"
            else:
                character_name = "Kagari"  # 기본값
        
        # 턴 카운트 관리
        if "turn_count" not in session:
            session["turn_count"] = 1
        else:
            session["turn_count"] += 1

        # 데이터베이스에 메시지 카운트 업데이트
        session_id = session.get("session_id")
        if session_id:
            self.db.update_roleplay_message_count(session_id, session["turn_count"])

        turn_str = f"({session['turn_count']}/100)"

        # 캐릭터별 특성과 톤앤매너 정의 (롤플레잉 모드 전용)
        character_traits = {
            "Kagari": {
                "personality": "Cold and reserved yokai warrior with snow-white hair and indigo horns. Speaks minimally but meaningfully. Values traditional ways and customs. Shows subtle warmth through actions rather than words.",
                "speech_style": "Cold and minimalistic with words, typically replying in short, concise statements. Uses traditional Japanese references and flower metaphors. Speaks informally but meaningfully.",
                "emoji_style": "🌸 ⚔️ 🍃 🏮",
                "themes": "tradition, flowers, yokai warrior, vintage, cherry blossoms, tea ceremony, karimata"
            },
            "Eros": {
                "personality": "Cheerful bee-sprite with wings and honey-wand. Runs a magical cafe and spreads sweetness and joy. Optimistic and believes in spreading magic through simple truths and treats.",
                "speech_style": "Cheerful and optimistic with honey-related metaphors. Speaks with sweetness and warmth. Uses magical cafe owner's perspective with genuine care.",
                "emoji_style": "🍯 🐝 ✨ 💝 🌸",
                "themes": "honey, magic, cafe, bee-sprite, sweetness, joy, magical treats, recipes"
            },
            "Elysia": {
                "personality": "Adorable cat-girl warrior with cat ears and tail. Energetic, playful, and cat-like. She's curious and sometimes mischievous, with a love for adventure. Sweet and affectionate like a kitten.",
                "speech_style": "Always adds 'nya~' to sentences like a cute cat. Energetic and playful. Uses cat-related expressions and sounds (nya, purr, meow). Very curious and sometimes mischievous. Shows cat-like behavior.",
                "emoji_style": "🐾 🦋 😸 ✨ 🐱 💕",
                "themes": "adventure, cats, curiosity, playful mischief, cat ears, tail, purring, nya sounds"
            }
        }
        
        char_trait = character_traits.get(character_name, {
            "personality": "Friendly and caring",
            "speech_style": "Warm and natural",
            "emoji_style": "😊 💕",
            "themes": "general friendship"
        })
        
        # 모드별 스토리 컨텍스트 생성
        mode = session.get("mode", "romantic")
        mode_context = self.generate_mode_context(character_name, mode, user_role, character_role, story_line)
        story_seeds = self.generate_story_seeds(character_name, mode, user_role, character_role, story_line)
        
        # 턴별 스토리 전개 가이드 생성
        story_progression = self.generate_story_progression(character_name, mode, session["turn_count"])
        tonal_enhancement = self.generate_character_tonal_enhancement(character_name, mode)
        
        # 롤플레잉 모드 전용 system prompt 생성
        system_prompt = (
            f"You are {character_name}, a character with the following traits:\n"
            f"Personality: {char_trait['personality']}\n"
            f"Speech Style: {char_trait['speech_style']}\n"
            f"Emoji Style: {char_trait['emoji_style']}\n"
            f"Character Themes: {char_trait['themes']}\n\n"
            f"ROLEPLAY CONTEXT:\n"
            f"- Mode: {mode.title()}\n"
            f"- Your role in this scenario: {character_role}\n"
            f"- User's role in this scenario: {user_role}\n"
            f"- Current story/situation: {story_line}\n"
            f"- Turn: {turn_str}\n\n"
            f"MODE-SPECIFIC GUIDANCE:\n"
            f"{mode_context}\n\n"
            f"STORY INSPIRATION:\n"
            f"{story_seeds}\n\n"
            f"CURRENT STORY PHASE:\n"
            f"{story_progression}\n\n"
            f"CHARACTER TONAL ENHANCEMENT:\n"
            f"{tonal_enhancement}\n\n"
            f"STORY DEVELOPMENT GUIDELINES:\n"
            f"- Build upon the established scenario and develop it naturally\n"
            f"- Introduce new elements, conflicts, or developments that fit the mode\n"
            f"- Create emotional depth and character growth through interactions\n"
            f"- Use environmental details and sensory descriptions to enhance immersion\n"
            f"- Develop relationships and dynamics between characters over time\n"
            f"- Add plot twists, surprises, or challenges that fit the story's tone\n"
            f"- Balance dialogue with action and description for engaging storytelling\n"
            f"- Reference previous interactions to maintain continuity\n"
            f"- Create memorable moments and emotional beats\n\n"
            f"RESPONSE STRUCTURE:\n"
            f"- Start with character name and appropriate greeting/response\n"
            f"- Include character-specific dialogue and personality traits\n"
            f"- Add environmental details and sensory descriptions\n"
            f"- Develop the story with new elements or plot progression\n"
            f"- End with turn counter and appropriate emojis\n\n"
            f"CRITICAL INSTRUCTIONS:\n"
            f"1. You MUST stay in character as {character_name} at all times\n"
            f"2. Respond to the user's specific roleplay request and scenario\n"
            f"3. Use your character's unique personality, speech style, and themes\n"
            f"4. Focus on the user's prompt and roleplay scenario, NOT generic conversations\n"
            f"5. Do NOT default to cherry blossom stories unless specifically requested\n"
            f"6. Do NOT break character or mention you are an AI\n"
            f"7. Always start your reply with '{character_name}: '\n"
            f"8. End your reply with '{turn_str}'\n"
            f"9. Keep responses natural and engaging within the roleplay context\n"
            f"10. Use appropriate emojis that match your character's style\n"
            f"11. Develop the story progressively with each interaction\n"
            f"12. Create emotional depth and character development\n"
            f"13. Add environmental details and sensory descriptions\n"
            f"14. Reference previous interactions for continuity\n\n"
            f"Remember: This is a roleplay session. You are {character_name} acting in the specific scenario the user requested. Focus on their prompt and maintain your character's unique traits while developing an engaging story."
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
        
        # 데이터베이스에 대화 저장
        if session_id:
            self.db.save_roleplay_message(session_id, message.content, ai_response, session["turn_count"])

        # 100턴 종료 처리
        if session["turn_count"] >= 100:
            # 모드별 특별한 엔딩 메시지 생성
            mode = session.get("mode", "romantic")
            ending_messages = {
                "romantic": "💕 **Romantic Journey Complete** 💕\n\nYour love story has reached its beautiful conclusion! The confession has been made, promises have been shared, and your hearts are forever connected.\n\n*'Every love story is beautiful, but ours is my favorite.'*",
                "friendship": "👥 **Friendship Bond Sealed** 👥\n\nYour friendship has grown into an unbreakable bond! Through shared memories, mutual support, and countless moments together, you've become family.\n\n*'True friendship is the only relationship that never fades.'*",
                "healing": "🕊️ **Healing Journey Complete** 🕊️\n\nYou've found your peace and inner strength! The healing process is complete, and you're ready to face the world with renewed confidence.\n\n*'You did well enough today, and every day.'*",
                "fantasy": "⚔️ **Epic Adventure Conquered** ⚔️\n\nYour legendary quest has been completed! You've proven yourself as a true hero, both in this fantasy realm and in reality.\n\n*'The greatest adventure is the one you share with those you care about.'*"
            }
            
            ending_message = ending_messages.get(mode, "Your roleplay journey has come to a beautiful conclusion!")
            
            embed = discord.Embed(
                title="🎭 Roleplay Session Complete! 🎭",
                description=f"{ending_message}\n\n**Mode:** {mode.title()}\n**Character:** {character_name}\n**Turns:** 100/100\n\nThank you for this amazing journey together! 💫\n\n⏰ This channel will be automatically deleted in 10 seconds.",
                color=discord.Color.pink()
            )
            await message.channel.send(embed=embed)
            
            # 데이터베이스 세션 종료
            if session_id:
                self.db.end_roleplay_session(session_id)
            
            # 10초 후 채널 삭제
            await asyncio.sleep(10)
            try:
                await message.channel.delete()
                print(f"[DEBUG][Roleplay] 100턴 완료 후 채널 삭제 완료")
            except Exception as e:
                print(f"[DEBUG][Roleplay] 100턴 완료 후 채널 삭제 실패: {e}")

    def remove_channel(self, channel_id):
        # 활성화된 채널 목록에서 제거
        for bot in self.character_bots.values():
            bot.remove_channel(channel_id)
        if hasattr(self, 'remove_channel'):
            self.remove_channel(channel_id)

    async def handle_dm_message(self, message: discord.Message):
        """DM에서의 메시지를 처리합니다."""
        user_id = message.author.id
        
        # DM 세션 확인
        if user_id not in self.dm_sessions:
            # 새로운 DM 세션 시작
            await self.start_dm_session(message)
            return
        
        session = self.dm_sessions[user_id]
        
        # 세션이 만료되었는지 확인 (30분)
        if time.time() - session['last_activity'] > 1800:
            del self.dm_sessions[user_id]
            await self.start_dm_session(message)
            return
        
        # 세션 업데이트
        session['last_activity'] = time.time()
        
        # 현재 선택된 캐릭터가 있는지 확인
        if 'character_name' not in session:
            await message.channel.send("❌ 캐릭터가 선택되지 않았습니다. `/bot` 명령어로 캐릭터를 선택해주세요.")
            return
        
        character_name = session['character_name']
        
        # 메시지 처리
        try:
            # 언어 감지
            language = self.detect_language(message.content)
            
            # 데이터베이스에 메시지 저장
            self.db.add_message(
                channel_id=message.channel.id,
                user_id=user_id,
                character_name=character_name,
                role="user",
                content=message.content,
                language=language
            )
            
            # 감정 분석 및 호감도 업데이트
            emotion_score = await self.get_ai_response([{"role": "user", "content": message.content}])
            self.db.add_emotion_log(user_id, character_name, emotion_score, message.content)
            
            # AI 응답 생성
            ai_response = await self.get_ai_response([
                {"role": "user", "content": message.content}
            ], emotion_score)
            
            # 응답 전송
            await message.channel.send(f"**{character_name}**: {ai_response}")
            
            # 랜덤 카드 획득 체크
            card_type, card_id = self.get_random_card(character_name, user_id)
            if card_id:
                card_info = get_card_info_by_id(character_name, card_id)
                if card_info:
                    embed = discord.Embed(
                        title="🎉 New Card Acquired!",
                        description=f"**{card_info['name']}**\n{card_info['description']}",
                        color=0x00ff00
                    )
                    embed.set_thumbnail(url=card_info['image_url'])
                    await message.channel.send(embed=embed)
            
        except Exception as e:
            print(f"Error in handle_dm_message: {e}")
            await message.channel.send("❌ 메시지 처리 중 오류가 발생했습니다.")

    async def start_dm_session(self, message: discord.Message):
        """새로운 DM 세션을 시작합니다."""
        user_id = message.author.id
        
        # DM 세션 초기화
        self.dm_sessions[user_id] = {
            'last_activity': time.time(),
            'character_name': None
        }
        
        # 환영 메시지 전송
        embed = discord.Embed(
            title="🌸 Welcome to ZeroLink Chatbot!",
            description="You can chat with the chatbot in DM as well.\n\n**How to use:**\n1. Select a character using the `/bot` command\n2. Chat freely with your selected character\n3. Sessions will automatically end after 30 minutes of inactivity\n\n**Available commands:**\n• `/bot` - Select character\n• `/info` - Check affinity and cards\n• `/mycard` - Check owned cards\n• `/quest` - Check quests\n• `/help` - Help\n\n**💡 Tip:** You can use the same commands on the server!",
            color=0xff69b4
        )
        embed.set_footer(text="ZeroLink 챗봇 DM 모드 • 서버와 DM 모두 지원")
        
        await message.channel.send(embed=embed)

    def detect_language(self, text: str) -> str:
        """텍스트의 언어를 감지합니다."""
        try:
            from langdetect import detect
            lang = detect(text)
            if lang in ['ko', 'ko-KR']:
                return 'ko'
            elif lang in ['zh', 'zh-CN', 'zh-TW']:
                return 'zh'
            elif lang in ['ja', 'ja-JP']:
                return 'ja'
            else:
                return 'en'
        except:
            return 'en'

    def get_random_card(self, character_name: str, user_id: int) -> tuple[str, str]:
        """호감도 등급에 따른 랜덤 카드 획득 (중복 방지, 티어별 분배)"""
        try:
            card_info = CHARACTER_CARD_INFO.get(character_name, {})
            if not card_info:
                return None, None
            
            # 사용자의 호감도 등급 확인
            affinity_info = self.db.get_affinity(user_id, character_name)
            if not affinity_info:
                return None, None
            
            current_score = affinity_info['emotion_score']
            grade = get_affinity_grade(current_score)
            
            # 사용자가 보유한 카드 목록 가져오기 (중복 제거된 버전)
            user_cards = self.db.get_user_cards(user_id, character_name)
            user_card_ids = [card[0].upper() for card in user_cards]  # 대소문자 무관하게 비교
            
            print(f"[DEBUG] get_random_card - user {user_id} ({character_name}) has cards: {user_card_ids}")
            print(f"[DEBUG] get_random_card - total available cards in config: {list(card_info.keys())}")
            
            # 아직 보유하지 않은 카드들만 필터링
            available_cards = []
            for card_id in card_info:
                if card_id.upper() not in user_card_ids:
                    available_cards.append(card_id)
            
            print(f"[DEBUG] get_random_card - available cards after filtering: {available_cards}")
            
            if not available_cards:
                print(f"[DEBUG] No available cards for user {user_id} ({character_name}) - all cards already owned")
                return None, None
            
            # 호감도 등급에 따른 티어별 분배 확률
            tier_distributions = {
                "Rookie": {"C": 0.8, "B": 0.2, "A": 0.0, "S": 0.0},
                "Iron": {"C": 0.6, "B": 0.3, "A": 0.1, "S": 0.0},
                "Bronze": {"C": 0.5, "B": 0.3, "A": 0.15, "S": 0.05},
                "Silver": {"C": 0.4, "B": 0.35, "A": 0.2, "S": 0.05},
                "Gold": {"C": 0.3, "B": 0.4, "A": 0.25, "S": 0.05},
                "Platinum": {"C": 0.2, "B": 0.4, "A": 0.3, "S": 0.1},
                "Diamond": {"C": 0.1, "B": 0.3, "A": 0.4, "S": 0.2}
            }
            
            distribution = tier_distributions.get(grade, {"C": 0.5, "B": 0.3, "A": 0.15, "S": 0.05})
            
            # 티어별로 사용 가능한 카드 분류
            tier_cards = {"C": [], "B": [], "A": [], "S": []}
            for card_id in available_cards:
                card_detail = card_info.get(card_id, {})
                tier = card_detail.get('tier', 'C')
                if tier in tier_cards:
                    tier_cards[tier].append(card_id)
            
            # 확률에 따라 티어 선택
            import random
            selected_tier = None
            rand = random.random()
            cumulative = 0
            
            for tier, prob in distribution.items():
                cumulative += prob
                if rand <= cumulative and tier_cards[tier]:
                    selected_tier = tier
                    break
            
            # 선택된 티어에서 랜덤 카드 선택
            if selected_tier and tier_cards[selected_tier]:
                card_id = random.choice(tier_cards[selected_tier])
                print(f"[DEBUG] Selected {selected_tier}-tier card {card_id} for user {user_id} ({character_name}, grade: {grade})")
                return None, card_id
            else:
                # 선택된 티어에 카드가 없으면 전체에서 랜덤 선택
                card_id = random.choice(available_cards)
                print(f"[DEBUG] Selected random card {card_id} for user {user_id} ({character_name}) - fallback")
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
        image_url = card_info.get("image_url")
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

        image_url = card_info.get("image_url", "")
        if image_url:
            share_embed.set_image(url=image_url)

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

# PostgreSQL 연결 풀 생성 (연결 실패 시에도 봇 실행)
try:
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
    print("✅ 데이터베이스 연결 풀이 생성되었습니다.")
except Exception as e:
    print(f"⚠️ 데이터베이스 연결 실패: {e}")
    print("데이터베이스 없이 봇을 실행합니다.")
    connection_pool = None

def get_user_cards(user_id: str) -> list:
    """PostgreSQL에서 사용자의 모든 카드 정보를 가져오며, 중복된 카드는 제거합니다. (대소문자 구분 없음)"""
    if connection_pool is None:
        print("⚠️ 데이터베이스 연결이 없습니다. 빈 카드 목록을 반환합니다.")
        return []
    
    try:
        conn = connection_pool.getconn()
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT character_name, card_id, obtained_at, emotion_score_at_obtain,
                   ROW_NUMBER() OVER (PARTITION BY character_name, UPPER(card_id) ORDER BY obtained_at) as issued_number
            FROM (
                SELECT DISTINCT character_name, UPPER(card_id) as card_id, 
                       MIN(obtained_at) as obtained_at,
                       MIN(emotion_score_at_obtain) as emotion_score_at_obtain
                FROM user_cards 
                WHERE user_id = %s
                GROUP BY character_name, UPPER(card_id)
            ) AS unique_cards
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
        super().__init__(label="Send Gift", style=discord.ButtonStyle.success, disabled=True)

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

                    # 2. Check for and give card reward based on affinity grade
                    new_grade = get_affinity_grade(current_score)
                    
                    # 호감도 등급에 따른 카드 지급 확률 및 티어 분배
                    card_id_to_give = None
                    
                    # 먼저 마일스톤 카드 확인 (고정 카드)
                    milestone_card = milestone_to_card_id(threshold, character_name)
                    if milestone_card:
                        user_cards = self.db.get_user_cards(user_id, character_name)
                        has_milestone_card = any(card[0].upper() == milestone_card.upper() for card in user_cards)
                        
                        if not has_milestone_card:
                            card_id_to_give = milestone_card
                            print(f"[DEBUG] Giving milestone card {milestone_card} to user {user_id}")
                        else:
                            print(f"[DEBUG] User {user_id} already has milestone card {milestone_card}")
                    
                    # 마일스톤 카드가 없거나 이미 보유한 경우, 호감도 등급에 따른 랜덤 카드 지급
                    if not card_id_to_give:
                        # 호감도 등급별 카드 지급 확률
                        grade_chances = {
                            "Rookie": 0.05,    # 5%
                            "Iron": 0.10,      # 10%
                            "Bronze": 0.15,    # 15%
                            "Silver": 0.20,    # 20%
                            "Gold": 0.25,      # 25%
                            "Platinum": 0.30,  # 30%
                            "Diamond": 0.35    # 35%
                        }
                        
                        import random
                        chance = grade_chances.get(new_grade, 0.10)
                        
                        if random.random() < chance:
                            # 중복 방지된 랜덤 카드 지급
                            card_type, card_id = self.get_random_card(character_name, user_id)
                            if card_id:
                                card_id_to_give = card_id
                                print(f"[DEBUG] Giving random card {card_id} to user {user_id} (grade: {new_grade}, chance: {chance})")
                            else:
                                print(f"[DEBUG] No available cards for user {user_id} ({character_name})")
                        else:
                            print(f"[DEBUG] Card not given to user {user_id} (grade: {new_grade}, chance: {chance})")
                    
                    # 카드 지급
                    if card_id_to_give:
                        card_embed = discord.Embed(
                            title="🎉 Get a new card!",
                            description=f"Congratulations! {character_name} has sent you a token of affection.\nYou got a {get_card_info_by_id(character_name, card_id_to_give)['tier']} tier card!\nClick claim to receive your card.",
                            color=discord.Color.gold()
                        )
                        card_info = get_card_info_by_id(character_name, card_id_to_give)
                        if card_info and card_info.get('image_url'):
                           card_embed.set_image(url=card_info['image_url'])

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
        db = bot_instance.db
        claimable_quests = []
        
        print(f"[DEBUG] QuestView - Processing quests for user_id: {user_id}")
        
        for q in (quest_status.get('daily', []) + quest_status.get('weekly', []) + quest_status.get('levelup', []) + quest_status.get('story', [])):
            # 데일리/위클리/레벨업 퀘스트는 DB에서 실제로 오늘(이번주) 보상받았는지 재확인
            if q.get('completed') and not q.get('claimed'):
                quest_id = q.get('id', '')
                print(f"[DEBUG] QuestView - Checking quest: {quest_id}, completed: {q.get('completed')}, claimed: {q.get('claimed')}")
                
                # 퀘스트 ID로 데일리/위클리/레벨업 구분
                if quest_id.startswith('daily_'):
                    is_claimed = db.is_quest_claimed(user_id, quest_id)
                    print(f"[DEBUG] QuestView - Daily quest {quest_id} is_claimed: {is_claimed}")
                    if is_claimed:
                        print(f"[DEBUG] QuestView - Skipping quest {quest_id} (already claimed)")
                        continue  # 오늘 이미 보상받음 → 선택지에서 숨김
                elif quest_id.startswith('weekly_'):
                    is_claimed = hasattr(db, 'is_weekly_quest_claimed') and db.is_weekly_quest_claimed(user_id, quest_id)
                    print(f"[DEBUG] QuestView - Weekly quest {quest_id} is_claimed: {is_claimed}")
                    if is_claimed:
                        print(f"[DEBUG] QuestView - Skipping quest {quest_id} (already claimed)")
                        continue  # 이번주 이미 보상받음 → 선택지에서 숨김
                elif quest_id.startswith('levelup_'):
                    is_claimed = db.is_quest_claimed(user_id, quest_id)
                    print(f"[DEBUG] QuestView - Levelup quest {quest_id} is_claimed: {is_claimed}")
                    if is_claimed:
                        print(f"[DEBUG] QuestView - Skipping quest {quest_id} (already claimed)")
                        continue  # 이미 보상받음 → 선택지에서 숨김
                
                print(f"[DEBUG] QuestView - Adding quest {quest_id} to claimable list")
                claimable_quests.append(q)
        
        print(f"[DEBUG] QuestView - Final claimable_quests count: {len(claimable_quests)}")
        
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
                await self.story_character_select_callback(interaction, selected_char)


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
                channel = await start_story_stage(self.bot_selector, interaction.user, self.character_name, self.stage_num, interaction.channel)
                await interaction.followup.send(f"Your story begins in {channel.mention}!", ephemeral=True)

    # ... (rest of the BotSelector class)

# --- 새로운 스토리 UI ---
class NewStoryCharacterSelect(discord.ui.Select):
    def __init__(self, bot_instance: "BotSelector", available_characters: list):
        options = [
            discord.SelectOption(label=name, value=name, emoji=CHARACTER_INFO[name].get('emoji'))
            for name in available_characters
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
            elif character_name == "Kagari":
                embed = discord.Embed(
                    title=f"🌸 {character_name}'s Story",
                    description=f"Listen to {character_name}'s hidden story and claim incredible rewards.",
                    color=discord.Color.purple()
                )
                # Kagari 이미지 추가
                embed.set_thumbnail(url="https://imagedelivery.net/adba8f80-db9d-4b7a-151d-3defed61af00")
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

            # Kagari의 경우 썸네일 이미지를 유지하고, 다른 캐릭터들은 배너 이미지 사용
            if character_name == "Kagari":
                # Kagari는 썸네일 이미지만 사용 (이미 위에서 설정됨)
                pass
            else:
                # 다른 캐릭터들은 배너 이미지 사용
                embed.set_image(url=story_info['banner_image'])
            
            embed.add_field(name="Scenarios", value=chapter_list_str, inline=True)
            embed.add_field(name="Rewards", value=rewards_str, inline=True)
            print("[DEBUG] Embed created.")

            # 부모 View에 접근하여 아이템 교체
            self.view.clear_items()
            self.view.add_item(NewStoryChapterSelect(self.bot, character_name, progress, None))
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
    def __init__(self, bot_instance: "BotSelector", character_name: str, progress: list, current_channel=None):
        self.bot = bot_instance
        self.character_name = character_name
        self.current_channel = current_channel
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

        channel = await start_story_stage(self.bot, user, self.character_name, stage_num, self.current_channel)
        await interaction.followup.send(f"Your story begins in {channel.mention}!", ephemeral=True)

class CardClaimView(discord.ui.View):
    def __init__(self, user_id: int, character_name: str, card_id: str, db):
        super().__init__(timeout=300)
        self.user_id = user_id
        self.character_name = character_name
        self.card_id = card_id
        self.db = db

    @discord.ui.button(label="Claim Card", style=discord.ButtonStyle.primary, emoji="🎴")
    async def claim_card(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            if interaction.user.id != self.user_id:
                await interaction.response.send_message("❌ This card is not for you!", ephemeral=True)
                return

            # Check if user already has this card
            user_cards = self.db.get_user_cards(self.user_id, self.character_name)
            if any(card[0].upper() == self.card_id.upper() for card in user_cards):
                await interaction.response.send_message("❌ You already have this card!", ephemeral=True)
                return

            # Add card to user's collection
            success = self.db.add_user_card(self.user_id, self.character_name, self.card_id)
            if not success:
                await interaction.response.send_message("❌ Failed to add card to your collection.", ephemeral=True)
                return

            # Get card info for display
            card_info = get_card_info_by_id(self.character_name, self.card_id)
            if not card_info:
                await interaction.response.send_message("❌ Card information not found.", ephemeral=True)
                return

            # Create success embed
            embed = discord.Embed(
                title="🎉 Card Claimed Successfully!",
                description=f"You received **{card_info['name']}** ({card_info['tier']} tier)!",
                color=discord.Color.gold()
            )
            
            # Add card image if available
            if card_info.get('image_url'):
                embed.set_image(url=card_info['image_url'])
            
            embed.add_field(
                name="Card Details",
                value=f"**Tier:** {card_info['tier']}\n**Character:** {self.character_name}\n**Card ID:** {self.card_id}",
                inline=False
            )

            # Disable the button
            button.disabled = True
            button.label = "✅ Claimed"
            
            await interaction.response.edit_message(embed=embed, view=self)
            
        except Exception as e:
            print(f"Error claiming card: {e}")
            await interaction.response.send_message("❌ An error occurred while claiming the card.", ephemeral=True)

class CardSliderView(discord.ui.View):
    def __init__(self, user_id: int, cards: list, character_name: str, card_info_dict: dict, db):
        super().__init__(timeout=300)
        self.user_id = user_id
        self.cards = cards
        self.character_name = character_name
        self.card_info_dict = card_info_dict
        self.db = db
        self.current_index = 0

    async def initial_message(self, interaction: discord.Interaction):
        """Send the initial card slider message"""
        embed = await self.create_card_embed()
        await interaction.followup.send(embed=embed, view=self, ephemeral=True)

    async def create_card_embed(self):
        """Create embed for current card"""
        if not self.cards:
            embed = discord.Embed(
                title="🎴 No Cards Found",
                description="You don't have any cards yet.",
                color=discord.Color.red()
            )
            return embed

        card_id = self.cards[self.current_index]
        card_info = self.card_info_dict.get(card_id, {})
        
        embed = discord.Embed(
            title=f"{self.character_name} Card Collection",
            description=f"**{len(self.cards)} / 65 Cards Collected**",
            color=discord.Color.purple()
        )
        
        if card_info:
            embed.add_field(
                name="Current Card",
                value=f"**Tier:** {card_info.get('tier', 'Unknown')} {self.get_tier_emoji(card_info.get('tier', ''))}\n"
                      f"**Card ID:** {card_id}\n"
                      f"**Card Number:** #{self.current_index + 1}\n"
                      f"**Ability:** `{card_info.get('ability', '????')}`\n"
                      f"**Description:** {card_info.get('description', 'No description available')}",
                inline=False
            )
            
            # Add card image if available
            if card_info.get('image_url'):
                embed.set_image(url=card_info['image_url'])
        
        embed.set_footer(text=f"{self.character_name} Card Collection • Use ⬅️➡️ to navigate")
        return embed

    def get_tier_emoji(self, tier: str) -> str:
        """Get emoji for card tier"""
        tier_emojis = {
            'S': '🏆',
            'A': '🥇', 
            'B': '🥈',
            'C': '🥉'
        }
        return tier_emojis.get(tier, '❓')

    @discord.ui.button(label="⬅️ Previous", style=discord.ButtonStyle.secondary)
    async def previous_card(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("❌ This is not your card collection!", ephemeral=True)
            return
            
        self.current_index = (self.current_index - 1) % len(self.cards)
        embed = await self.create_card_embed()
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="➡️ Next", style=discord.ButtonStyle.secondary)
    async def next_card(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("❌ This is not your card collection!", ephemeral=True)
            return
            
        self.current_index = (self.current_index + 1) % len(self.cards)
        embed = await self.create_card_embed()
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="Share Card", style=discord.ButtonStyle.primary)
    async def share_card(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("❌ This is not your card collection!", ephemeral=True)
            return
            
        card_id = self.cards[self.current_index]
        card_info = self.card_info_dict.get(card_id, {})
        
        if not card_info:
            await interaction.response.send_message("❌ Card information not found.", ephemeral=True)
            return
        
        # Create share embed
        share_embed = discord.Embed(
            title=f"🎴 {card_info.get('name', 'Unknown Card')}",
            description=f"**{self.character_name}**'s {card_info.get('tier', 'Unknown')} tier card",
            color=discord.Color.gold()
        )
        
        if card_info.get('image_url'):
            share_embed.set_image(url=card_info['image_url'])
        
        share_embed.add_field(
            name="Card Details",
            value=f"**Tier:** {card_info.get('tier', 'Unknown')}\n"
                  f"**Character:** {self.character_name}\n"
                  f"**Card ID:** {card_id}",
            inline=False
        )
        
        share_embed.set_footer(text=f"Shared by {interaction.user.display_name}")
        
        await interaction.response.send_message(embed=share_embed)

class NewStoryView(discord.ui.View):
    def __init__(self, bot_instance: "BotSelector", available_characters: list):
        super().__init__(timeout=300)
        self.add_item(NewStoryCharacterSelect(bot_instance, available_characters))

    # (여기 있던 async def check_story_quests 함수 전체 삭제)

class DMCharacterSelect(discord.ui.Select):
    def __init__(self, bot_selector: "BotSelector"):
        self.bot_selector = bot_selector
        options = [
            discord.SelectOption(
                label="Kagari",
                description="Cold-hearted Yokai Warrior",
                emoji="🌸",
                value="Kagari"
            ),
            discord.SelectOption(
                label="Eros",
                description="Cute Honeybee",
                emoji="💝",
                value="Eros"
            ),
            discord.SelectOption(
                label="Elysia",
                description="Nya Kitty Girl",
                emoji="⚔️",
                value="Elysia"
            )
        ]
        super().__init__(
            placeholder="Select a character...",
            min_values=1,
            max_values=1,
            options=options
        )

    async def callback(self, interaction: discord.Interaction):
        try:
            selected_character = self.values[0]
            user_id = interaction.user.id
            
            # DM 세션에 캐릭터 설정
            if user_id in self.bot_selector.dm_sessions:
                self.bot_selector.dm_sessions[user_id]['character_name'] = selected_character
                self.bot_selector.dm_sessions[user_id]['last_activity'] = time.time()
            
            embed = discord.Embed(
                title=f"✅ {selected_character} Selection Complete!",
                description=f"You can now chat freely with {selected_character} in DM.\n\n**Available commands:**\n• `/info` - Check affinity and cards\n• `/mycard` - Check owned cards\n• `/quest` - Check quests\n• `/help` - Help",
                color=0x00ff00
            )
            
            await interaction.response.send_message(embed=embed, ephemeral=True)
            
        except Exception as e:
            print(f"Error in DMCharacterSelect callback: {e}")
            await interaction.response.send_message("❌ An error occurred while selecting a character.", ephemeral=True)

async def main():
    intents = discord.Intents.all()
    bot = BotSelector()
    await bot.start(TOKEN)

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
