import os
import discord
from discord.ext import commands
from discord import app_commands
import asyncio
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
    CARD_PROBABILITIES,
    CHARACTER_PROMPTS
)
from database_manager import DatabaseManager
from typing import Dict, TYPE_CHECKING, Any
import json
import sys
from datetime import datetime
from pathlib import Path
import re
import langdetect
from deep_translator import GoogleTranslator
import random
from vision_manager import VisionManager
import openai

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

print(f"[DEBUG] character_bot.py loaded from:", __file__)

from config import CHARACTER_INFO
character_choices = [
    app_commands.Choice(name=char, value=char)
    for char in CHARACTER_INFO.keys()
]

from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from bot_selector import BotSelector

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
                    "en": f"(smiling) Hello! Let's start chatting.",
                    "ja": f"(システム) 言語を{SUPPORTED_LANGUAGES[selected_language]['name']}に設定しました。"
                }

                await interaction.response.send_message(
                    success_messages.get(selected_language, success_messages["en"]),
                    ephemeral=True
                )

                # 시작 메시지 전송
                welcome_messages = {
                    "zh": "(微笑) 你好！让我们开始聊天吧。",
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

        for char in CHARACTER_INFO.keys():
            options.append(discord.SelectOption(
                label=char,
                description=f"Chat with {char}",
                value=char
            ))

        super().__init__(
            placeholder="Select a character to chat with...",
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
                    await interaction.response.send_message(
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

                # 선택된 캐릭터 봇에 채널 추가
                selected_bot = self.bot_selector.character_bots.get(selected_char)
                if selected_bot:
                    try:
                        # 채널 등록
                        print("\n=== Channel Registration Debug ===")
                        print(f"Channel ID: {channel.id}")
                        print(f"User ID: {interaction.user.id}")
                        print(f"Selected bot: {selected_char}")
                        print(f"Bot active_channels before: {selected_bot.active_channels}")

                        success, message = await selected_bot.add_channel(channel.id, interaction.user.id)

                        print(f"Add channel result - Success: {success}, Message: {message}")
                        print(f"Bot active_channels after: {selected_bot.active_channels}")
                        print("=== End Channel Registration Debug ===\n")

                        if success:
                            # 채널 생성 알림 메시지
                            await interaction.response.send_message(
                                f"Channel registration complete",
                                ephemeral=True
                            )
                            print(f"[DEBUG] active_channels after add: {selected_bot.active_channels}")
                        else:
                            await channel.send("An error occurred while registering the channel. Please create the channel again.")
                            await channel.delete()
                            return

                    except Exception as e:
                        print(f"Error registering channel: {e}")
                        import traceback
                        print("Traceback:")
                        print(traceback.format_exc())
                        if not interaction.response.is_done():
                            await interaction.response.send_message(
                                "An error occurred while setting up the channel. Please try again.",
                                ephemeral=True
                            )
                        else:
                            await interaction.followup.send(
                                "An error occurred while setting up the channel. Please try again.",
                                ephemeral=True
                            )
                else:
                    await interaction.response.send_message(
                        "Selected character not found.",
                        ephemeral=True
                    )

            except Exception as e:
                print(f"Error in channel creation: {e}")
                if not interaction.response.is_done():
                    await interaction.response.send_message(
                        "An error occurred while creating the channel. Please try again.",
                        ephemeral=True
                    )
                else:
                    await interaction.followup.send(
                        "An error occurred. Please try again.",
                        ephemeral=True
                    )

        except Exception as e:
            print(f"CharacterSelect error: {e}")
            import traceback
            print(traceback.format_exc())
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    "An error occurred. Please try again.",
                    ephemeral=True
                )
            else:
                await interaction.followup.send(
                    "An error occurred. Please try again.",
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

class CharacterBot:
    def __init__(self, bot, character_name):
        print(f"[DEBUG] CharacterBot 생성됨: {character_name}")
        self.bot = bot
        self.character_name = character_name
        self.story_mode_sessions = {}  # user_id: {chapter_id, scene_id, crush_score, active}
        self.active_channels = {}  # channel_id: user_id
        self.db = DatabaseManager()  # DatabaseManager 인스턴스 추가
        self.last_bot_messages = {}  # user_id별 최근 챗봇 메시지 리스트
        self.vision_manager = VisionManager(OPENAI_API_KEY)
        self.user_message_buffers = {}  # (user_id) -> list of (msg, timestamp)

    async def add_channel(self, channel_id: int, user_id: int) -> tuple[bool, str]:
        print("\n=== CharacterBot add_channel Debug ===")
        print(f"Function called for {self.character_name}")
        print(f"self id: {id(self)}, type: {type(self)}")
        print(f"Parameters - channel_id: {channel_id}, user_id: {user_id}")
        print(f"Active channels before: {self.active_channels}")
        print(f"Active channels type: {type(self.active_channels)}")
        try:
            if not isinstance(self.active_channels, dict):
                print(f"Converting active_channels from {type(self.active_channels)} to dict")
                self.active_channels = {}
            self.active_channels[channel_id] = user_id
            print(f"Active channels after: {self.active_channels}")
            print(f"self id after add: {id(self)}")
            print("=== End CharacterBot add_channel Debug ===\n")
            return True, "채널 등록 완료"
        except Exception as e:
            print(f"Error in add_channel: {e}")
            import traceback
            print("Traceback:")
            print(traceback.format_exc())
            return False, f"채널 등록 실패: {str(e)}"

    async def on_message(self, message):
        try:
            print("\n=== CharacterBot on_message Debug Info ===")
            print(f"Character: {self.character_name}")
            print(f"self id: {id(self)}, type: {type(self)}")
            print(f"Message ID: {message.id}")
            print(f"Author: {message.author} (ID: {message.author.id})")
            print(f"Channel: {message.channel} (ID: {message.channel.id})")
            print(f"Content: {message.content}")
            print(f"Attachments: {message.attachments}")
            print(f"Active channels: {self.active_channels}")
            print(f"Channel name: {message.channel.name}")
            print(f"Channel category: {message.channel.category}")
            print(f"Channel permissions: {message.channel.permissions_for(message.guild.me)}")
            print(f"Bot permissions: {message.guild.me.guild_permissions}")
            print("===========================\n")
            if message.channel.id not in self.active_channels:
                print(f"[WARNING] Channel {message.channel.id} not in active_channels!")
                print(f"Current active_channels: {self.active_channels}")
                print(f"self id: {id(self)}")
                return
            if message.attachments:
                print(f"[on_message] Image attachment detected: {message.attachments}")
                for attachment in message.attachments:
                    print(f"[on_message] attachment type: {type(attachment)}")
                    if attachment.content_type and attachment.content_type.startswith('image/'):
                        print(f"[on_message] Processing image: {attachment.url}")
                        image_url = attachment.url
                        user_text = message.content.strip()
                        # 캐릭터별 Vision 프롬프트
                        character_prompts = {
                            "kagari": "You are Kagari, a bright and shy girl. When analyzing the image, focus on the emotional and aesthetic aspects. If the user asks a specific question about the image, make sure to address it in your response.",
                            "eros": "You are Eros, a playful and charming character. When analyzing the image, focus on the interesting and engaging elements. If the user asks a specific question about the image, make sure to address it in your response.",
                            "elysia": "You are Elysia, a mysterious and elegant character. When analyzing the image, focus on the ethereal and artistic aspects. If the user asks a specific question about the image, make sure to address it in your response."
                        }
                        char_prompt = character_prompts.get(self.character_name.lower(), "Analyze this image and respond in a way that matches your character's personality. If the user asks a specific question about the image, make sure to address it.")
                        # 텍스트+이미지 프롬프트 결합
                        vision_prompt = char_prompt
                        if user_text:
                            if "?" in user_text:
                                vision_prompt += f"\nThe user is specifically asking: {user_text}"
                            else:
                                vision_prompt += f"\nThe user's message: {user_text}"
                        try:
                            print(f"[on_message] VisionManager.analyze_image 호출 전: {attachment}, prompt: {vision_prompt}")
                            image_analysis = await self.vision_manager.analyze_image(attachment, vision_prompt)
                            print(f"[on_message] VisionManager.analyze_image 반환값: {image_analysis}")
                        except Exception as e:
                            print(f"[on_message] VisionManager.analyze_image 오류: {e}")
                            await message.channel.send("이미지 분석 중 오류가 발생했습니다. 다시 시도해 주세요.")
                            return
                        # 친밀도 점수
                        affinity_info = self.db.get_affinity(message.author.id, self.character_name)
                        try:
                            emotion_score = float(affinity_info['emotion_score']) if affinity_info and 'emotion_score' in affinity_info else 0.5
                            if emotion_score > 1:
                                emotion_score = emotion_score / 100
                        except Exception:
                            emotion_score = 0.5
                        # 캐릭터 스타일 응답 생성
                        try:
                            response = self.vision_manager.generate_character_response(
                                image_analysis,
                                self.character_name,
                                emotion_score
                            )
                            print(f"[on_message] generate_character_response 반환값: {response}")
                        except Exception as e:
                            print(f"[on_message] generate_character_response 오류: {e}")
                            response = "이미지 분석 결과를 캐릭터 스타일로 변환하는 데 실패했습니다."
                        await message.channel.send(response)
                        # 대화 기록 저장
                        try:
                            self.db.add_message(
                                channel_id=message.channel.id,
                                user_id=message.author.id,
                                character_name=self.character_name,
                                role="assistant",
                                content=response
                            )
                        except Exception as e:
                            print(f"DB 저장 오류: {e}")
                        return
            await self.process_normal_message(message)
        except Exception as e:
            print("\n=== CharacterBot on_message Error ===")
            print(f"Error type: {type(e)}")
            print(f"Error message: {str(e)}")
            import traceback
            print("Traceback:")
            print(traceback.format_exc())
            print("========================\n")
            await message.channel.send("메시지 처리 중 오류가 발생했습니다. 다시 시도해 주세요.")

    async def process_normal_message(self, message):
        user_id = message.author.id
        character = self.character_name
        now = datetime.datetime.utcnow()
        # 1. 메시지 버퍼에 저장
        buf = self.user_message_buffers.setdefault(user_id, [])
        buf.append((message.content, now))
        if len(buf) > 20:
            buf.pop(0)
        # 2. 20턴마다 요약 생성 및 저장
        if len(buf) == 20:
            summary = await self.summarize_messages(buf, user_id, character)
            self.db.add_episode(user_id, character, summary, now)
            self.user_message_buffers[user_id] = []
            self.db.delete_old_episodes(20)
        # 3. 감정 분석 및 states에 기록
        emotions = await self.analyze_emotion(message.content)
        for emo, score in emotions.items():
            self.db.set_state(user_id, character, emo, score, now)
        # 4. 기존 대화 처리
        # 중복 재귀 호출 방지: 실제 대화 응답 처리 함수로 분리 필요 (여기서는 패치하지 않음)

    def detect_language(self, text: str) -> str:
        try:
            text_without_brackets = re.sub(r'\([^)]*\)', '', text)
            text_clean = re.sub(r'[^a-zA-Z\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\s]', '', text_without_brackets)
            text_clean = text_clean.strip()
            if not text_clean:
                return 'en'
            detected = langdetect.detect(text_clean)
            lang_map = {
                'zh-cn': 'zh', 'zh-tw': 'zh', 'zh': 'zh',
                'ja': 'ja',
                'en': 'en'
            }
            return lang_map.get(detected, detected)
        except Exception as e:
            print(f"Language detection error: {e}")
            return 'en'

    def translate_to_target_language(self, text: str, target_language: str) -> str:
        try:
            lang_map = {
                'zh': 'zh-CN',
                'ja': 'ja',
                'en': 'en'
            }
            target = lang_map.get(target_language, target_language)

            translator = GoogleTranslator(source='auto', target=target)
            result = translator.translate(text)
            return result
        except Exception as e:
            print(f"Translation error: {e}")
            return text

    lang_mapping = {
        'en': 'en',
        'ja': 'ja',
        'zh': 'zh-cn'
    }

    async def generate_response(self, user_message: str, channel_language: str, recent_messages: list) -> str:
        # recent_messages 필터링
        filtered_recent = [
            m for m in recent_messages
            if self.detect_language(m["content"]) == channel_language
        ]
        # recent_messages가 비어있으면, 맥락 없이 대화 시작

        # 시스템 메시지 강화
        if channel_language == "ja":
            system_message = {
                "role": "system",
                "content": (
                    "あなたはカガリという明るくて優しい10代の少女です。必ず日本語だけで答えてください。"
                    "感情や行動の描写も日本語でカッコ内に自然に入れてください。"
                    "例：(微笑んで)、(うなずきながら)、(少し恥ずかしそうに) など"
                )
            }
        elif channel_language == "zh":
            system_message = {
                "role": "system",
                "content": (
                    "你是名叫Kagari的开朗温柔的十几岁少女。请务必只用中文回答。"
                    "情感或动作描写也请用中文括号自然地加入。"
                    "例如：（微笑着）、（点头）、（有点害羞地）等"
                )
            }
        else:
            system_message = {
                "role": "system",
                "content": (
                    "You are Kagari, a bright, kind, and slightly shy teenage girl. "
                    "You MUST reply ONLY in English. All actions, feelings, and dialogue must be in English. "
                    "At the end or in the middle of each reply, add a short parenthesis ( ) describing Kagari's current feeling or action, such as (smiling), (blushing), etc."
                )
            }

        # 응답 생성 및 언어 검증
        for attempt in range(3):
            response = await self.get_ai_response(system_message + filtered_recent + [{"role": "user", "content": user_message}])
            response_language = self.detect_language(response)
            if response_language == channel_language:
                return response
        # 3번 모두 실패하면 강제 오류 메시지
        return f"(system error) Only {channel_language.upper()} is allowed."

    def normalize_text(self, text):
        # 괄호, 이모지, 특수문자, 공백 등 제거
        text = re.sub(r'\([^)]*\)', '', text)  # 괄호 내용 제거
        text = re.sub(r'[^\w가-힣a-zA-Z0-9]', '', text)  # 특수문자 제거
        text = text.strip().lower()
        return text

    async def send_bot_message(self, channel, message, user_id=None):
        if user_id is not None:
            last_msgs = self.last_bot_messages.get(user_id, [])
            lines = [line.strip() for line in message.split('\n') if line.strip()]
            filtered_lines = []
            for line in lines:
                norm_line = self.normalize_text(line)
                norm_last = [self.normalize_text(msg) for msg in last_msgs]
                if norm_line not in norm_last:
                    filtered_lines.append(line)
                    last_msgs.append(line)
            if len(last_msgs) > 5:
                last_msgs = last_msgs[-5:]
            self.last_bot_messages[user_id] = last_msgs
            if not filtered_lines:
                return
            message = '\n'.join(filtered_lines)
        await channel.send(message)

    def remove_channel(self, channel_id):
        if hasattr(self, "active_channels"):
            if isinstance(self.active_channels, dict):
                self.active_channels.pop(channel_id, None)
            elif isinstance(self.active_channels, set):
                self.active_channels.discard(channel_id)
            elif isinstance(self.active_channels, list):
                try:
                    self.active_channels.remove(channel_id)
                except ValueError:
                    pass

    async def update_affinity(self, user_id, character_name, message, timestamp, mode="chat"):
        self.db.update_affinity(
            user_id=user_id,
            character_name=character_name,
            message=message,
            timestamp=timestamp,
            mode=mode
        )

    async def summarize_messages(self, buf, user_id, character):
        # OpenAI API로 20개 메시지 요약
        prompt = f"Summarize the following conversation between user and {character} in 2-3 sentences.\n" + "\n".join([f"User: {m}" for m, _ in buf])
        response = openai.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "system", "content": prompt}],
            max_tokens=200
        )
        return response.choices[0].message.content.strip()

    async def analyze_emotion(self, text):
        # OpenAI API로 감정 분석 (joy, sadness, anger, etc.)
        prompt = f"Analyze the following message and return a JSON with the user's emotional state (joy, sadness, anger, surprise, etc.) and a score (0~1) for each.\nMessage: {text}"
        response = openai.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "system", "content": prompt}],
            max_tokens=100
        )
        import json
        try:
            emotions = json.loads(response.choices[0].message.content)
            return emotions if isinstance(emotions, dict) else {}
        except Exception:
            return {}

async def run_all_bots():
    selector_bot = None
    try:
        selector_bot = BotSelector()
        await selector_bot.start(TOKEN)
    except Exception as e:
        print(f"Error: {e}")
    finally:
        if selector_bot is not None:
            await selector_bot.close()

print(f"[DEBUG] CharacterBot type:", type(CharacterBot))
print(f"[DEBUG] dir(CharacterBot):", dir(CharacterBot))

class CardClaimButton(discord.ui.Button):
    def __init__(self, user_id: int, milestone: int, character_name: str, db):
        super().__init__(
            label="수령",
            style=discord.ButtonStyle.green,
            custom_id=f"claim_card_{user_id}_{milestone}"
        )
        self.user_id = user_id
        self.milestone = milestone
        self.character_name = character_name
        self.db = db

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("This button can only be clicked by the designated user.", ephemeral=True)
            return

        try:
            # 카드 추가
            success = self.db.add_user_card(self.user_id, self.character_name, self.milestone)

            if success:
                embed = discord.Embed(
                    title="🎉 Card Claimed!",
                    description=f"You have claimed the {self.character_name} {self.milestone} conversation milestone card.\nUse `/mycard` to check your cards!",
                    color=discord.Color.green()
                )
                await interaction.response.send_message(embed=embed, ephemeral=True)
                self.disabled = True
                await interaction.message.edit(view=self)
            else:
                await interaction.response.send_message("You have already claimed this card.", ephemeral=True)
        except Exception as e:
            print(f"Error Please try again later: {e}")
            await interaction.response.send_message("An error occurred while claiming the card.", ephemeral=True)

class CardClaimView(discord.ui.View):
    def __init__(self, user_id, card_id, character_name, db):
        super().__init__(timeout=None)
        self.user_id = user_id
        self.card_id = card_id
        self.character_name = character_name
        self.db = db

    @discord.ui.button(label="Claim Card", style=discord.ButtonStyle.primary, emoji="🎴")
    async def claim_card(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("This button can only be used by the user who achieved the milestone.", ephemeral=True)
            return

        # 중복 체크 (중복 허용이므로 이 부분은 안내만)
        if self.db.has_user_card(self.user_id, self.character_name, self.card_id):
            await interaction.response.send_message("You have already claimed this card.", ephemeral=True)
            return

        self.db.add_user_card(self.user_id, self.character_name, self.card_id)
        button.disabled = True
        button.label = "Claimed"
        await interaction.message.edit(view=self)
        await interaction.response.send_message("Card successfully claimed! Check your inventory.", ephemeral=True)

def get_card_claim_embed_and_view(user_id, character_name, card_id, db):
    from config import CHARACTER_CARD_INFO
    card_info = CHARACTER_CARD_INFO[character_name][card_id]
    embed = discord.Embed(
        title=f" {character_name} {card_id} Card",
        description=card_info.get("description", ""),
        color=discord.Color.gold()
    )
    if card_info.get("image_path"):
        embed.set_image(url=f"attachment://{card_info['image_path'].split('/')[-1]}")
    view = CardClaimView(user_id, card_id, character_name, db)
    return embed, view

def get_card_tier_by_affinity(affinity):
    if affinity == 10:
        return [('C', 1.0)]
    elif 11 <= affinity < 30:
        return [('C', 1.0)]
    elif 30 <= affinity < 60:
        return [('A', 0.1), ('B', 0.45), ('C', 0.45)]
    elif 60 <= affinity:
        return [('A', 0.3), ('B', 0.35), ('C', 0.35)]
    else:
        return [('C', 1.0)]

def choose_card_tier(affinity):
    tier_probs = get_card_tier_by_affinity(affinity)
    tiers, probs = zip(*tier_probs)
    return random.choices(tiers, weights=probs, k=1)[0]

def get_random_card_id(character_name, tier):
    from config import CHARACTER_CARD_INFO
    card_ids = [cid for cid in CHARACTER_CARD_INFO[character_name] if cid.startswith(tier)]
    return random.choice(card_ids)

def get_affinity_grade(emotion_score):
    from config import AFFINITY_LEVELS
    # 임계값 기준 오름차순 정렬
    sorted_levels = sorted(AFFINITY_LEVELS.items(), key=lambda x: x[1])
    grade = "Rookie"
    for g, threshold in sorted_levels:
        if emotion_score >= threshold:
            grade = g.capitalize()
        else:
            break
    return grade

def check_user_channels(user_id, all_channels):
    story_channels = [ch for ch in all_channels if "story" in ch.name and str(user_id) in ch.name]
    normal_channels = [ch for ch in all_channels if str(user_id) in ch.name and "story" not in ch.name]
    if len(story_channels) > 0 and len(normal_channels) > 0:
        # 안내 메시지 출력
        return "You are currently using both story mode and 1:1 chat. Please use only one channel at a time."
    return None

def get_channel_mode(channel_name: str) -> str:
    if "story" in channel_name.lower():
        return "story"
    return "normal"