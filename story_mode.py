import random
import logging
import discord
import asyncio
from config import STORY_CHAPTERS, CHARACTER_INFO, CLOUDFLARE_IMAGE_BASE_URL, CHARACTER_IMAGES, CHARACTER_CARD_INFO
import re
from database_manager import get_db_manager
from openai_manager import call_openai, analyze_emotion_with_gpt_and_pattern
from gift_manager import get_gifts_by_rarity_v2, get_gift_details, ALL_GIFTS, GIFT_RARITY
from typing import TYPE_CHECKING, Dict, Any

if TYPE_CHECKING:
    from bot_selector import BotSelector

logger = logging.getLogger(__name__)
db_manager = get_db_manager()

# 인메모리 세션 저장소
story_sessions: Dict[int, Dict[str, Any]] = {}

# --- Eros 손님별 리액션 데이터 ---
EROS_CUSTOMER_REACTIONS = [
    {"success": "Wow! It's perfect! This drink is really the best! 😊", "fail": "Hmm... something's a bit different. Can I try again? 😕"},
    {"success": "This is the first time I've tasted something like this! Thank you! ✨", "fail": "Hmm... it's not quite right. Can I try again? 😅"},
    {"success": "Exactly what I wanted! It's amazing! 😍", "fail": "A bit disappointing. Can you make it again? 🙏"},
    {"success": "It's delicious! I want to drink it again! 🍹", "fail": "It's not quite right... please make it better next time!"},
    {"success": "This drink is amazing! Thank you! 💖", "fail": "Hmm... it's not quite right. 😔"},
    {"success": "It's perfect! The best! 🥰", "fail": "A bit more sweetness would be better... can you try again?"},
    {"success": "This drink made me feel so good! Thank you! 🌈", "fail": "It's not quite right... please make it better next time!"},
    {"success": "This is the best drink I've ever tasted! Thank you! 🎉", "fail": "A bit more sweetness would be better... can you try again?"},
    {"success": "This is the best drink I've ever tasted! Thank you! 🎉", "fail": "A bit more sweetness would be better... can you try again?"},
]

# --- Helper Functions ---

async def classify_emotion(user_message: str) -> int:
    """사용자 메시지의 감정을 분석하여 점수를 반환합니다. (임시 로직)"""
    # 실제 구현에서는 더 정교한 NLP 모델을 사용할 수 있습니다.
    positive_words = ['beautiful', 'like', 'love', 'happy', 'great', 'nice', 'awesome', 'wonderful']
    negative_words = ['hate', 'dislike', 'sad', 'bad', 'boring']

    score = 1  # Neutral
    if any(word in user_message.lower() for word in positive_words):
        score = 2
    elif any(word in user_message.lower() for word in negative_words):
        score = -1
    return score

def get_chapter_info(character_name: str, stage_num: int) -> Dict[str, Any]:
    """캐릭터와 스테이지 번호로 챕터 정보를 가져옵니다."""
    character_story = STORY_CHAPTERS.get(character_name, {})
    chapters = character_story.get('chapters', [])
    return next((chapter for chapter in chapters if chapter['id'] == stage_num), None)

def create_story_intro_embed(character_name: str, stage_info: dict) -> discord.Embed:
    """스토리 시작 임베드를 생성합니다."""
    char_info = CHARACTER_INFO[character_name]

    # 챕터별 스토리 소개 텍스트
    story_intros = {
        "Kagari": {
            1: "🌸 **Chapter 1: Cherry Blossom Date**\n\nYou and Kagari are walking through a beautiful cherry blossom garden. The pink petals are falling gently around you as you enjoy this peaceful moment together. Kagari seems a bit shy but happy to spend time with you.\n\n**Goal:** Reach +10 affinity with Kagari through conversation!",
            2: "🍵 **Chapter 2: Memories of Mother and Tea**\n\nYou and Kagari have entered a quiet, antique coffee shop. The aroma of tea and old wood fills the air. Kagari seems unusually calm and nostalgic. She shares stories about her mother and the precious memories they shared through tea ceremonies.\n\n**Goal:** Answer the quiz about what object holds Kagari's precious memories with her mother!",
            3: "🌙 **Chapter 3: This Moment Forever**\n\nThe streetlights are on, and you and Kagari are walking down a quiet alley, ending your date. She asks how you felt about today and expresses that she enjoyed it and would like to go on another date in the future.\n\n**Goal:** Give her a gift to make this moment special!"
        },
        "Eros": {
            1: "☕ **Chapter 1: Spot Zero Café One-Day Experience**\n\nEros has an urgent mission and asks you to take care of the Spot Zero Café for one day. The café is filled with the sweet scent of honey and warm lights. Various customers with unique personalities will visit and order drinks by their exact recipes.\n\n**Goal:** Successfully serve 8 or more customers with the correct drinks!",
            2: "🍯 **Chapter 2: Gifts for the Team**\n\nEros wants to cheer up the Spot Zero team by gifting them special drinks! Help Eros make and deliver the perfect drink for each teammate based on their preferences.\n\n**Goal:** Serve all 7 team members with their preferred drinks!",
            3: "🔍 **Chapter 3: Find the Café Culprit!**\n\nEros worked hard to prepare gifts for everyone, but when she came to the café this morning, the gift box was gone! Help Eros investigate and find out who took it by asking questions and looking for clues.\n\n**Goal:** Ask up to 30 questions to figure out who the culprit is!"
        }
    }
    # 챕터별 이미지ID 매핑
    kagari_story_images = {
        1: "e6086bc5-fbbd-4e3c-44cc-107154e76b00",
        2: "68766849-2bae-4f26-174b-068914f72200",
        3: "c35efad6-bc50-4642-ba0e-91840282b100"
    }
    eros_story_images = {
        1: "57ce8d9c-878d-4215-1e8a-99b39b398400",
        2: "7f107944-55c5-4e27-8b1a-725ec84f7000",
        3: "57ce8d9c-878d-4215-1e8a-99b39b398400"
    }
    intro_text = story_intros.get(character_name, {}).get(stage_info['id'], 
        f"**Chapter {stage_info['id']}: {stage_info['title']}**\n\nBegin your story with {character_name}!")
    embed = discord.Embed(
        title=f"📖 {character_name}'s Story",
        description=intro_text,
        color=char_info.get('color', discord.Color.default())
    )
    embed.set_thumbnail(url=char_info.get('image_url'))
    # 챕터별 이미지 추가
    if character_name == "Kagari" and stage_info['id'] in kagari_story_images:
        image_id = kagari_story_images[stage_info['id']]
        embed.set_image(url=f"{CLOUDFLARE_IMAGE_BASE_URL}/{image_id}/public")
    elif character_name == "Eros" and stage_info['id'] == 3:
        # 챕터3만 별도 이미지 사용
        embed.set_image(url=f"{CLOUDFLARE_IMAGE_BASE_URL}/64071edc-b8a4-473c-a8b3-785f3ab43100/public")
    elif character_name == "Eros" and stage_info['id'] in eros_story_images:
        image_id = eros_story_images[stage_info['id']]
        embed.set_image(url=f"{CLOUDFLARE_IMAGE_BASE_URL}/{image_id}/public")
    embed.set_footer(text="Start chatting with the character to begin your story!")
    return embed

# --- Stage Completion and Transition Views ---

class KagariStage1CompleteView(discord.ui.View):
    """카가리 1장 완료 후 다음 단계로 넘어갈지 묻는 View"""
    def __init__(self, bot: "BotSelector", session: Dict[str, Any]):
        super().__init__(timeout=180)
        self.bot = bot
        self.session = session

    @discord.ui.button(label="Sure, let's go", style=discord.ButtonStyle.success)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.session['user_id']:
            return await interaction.response.send_message("This is not for you.", ephemeral=True)

        await interaction.response.defer()
        db_manager.complete_story_stage(self.session['user_id'], self.session['character_name'], self.session['stage_num'])

        # 2장 시작 로직 또는 안내
        await interaction.message.edit(content="**Chapter 2 is now unlocked!**\n(The story continues in a new channel...)\n👉 `/story` Continue with Chapter 2 by entering the command!\n\n⏰ This channel will be automatically deleted in 5 seconds.", view=None)
        
        # 5초 후 채널 삭제
        import asyncio
        await asyncio.sleep(5)
        try:
            await interaction.channel.delete()
            print(f"[DEBUG][Kagari] 챕터1 완료 후 채널 삭제 완료")
        except Exception as e:
            print(f"[DEBUG][Kagari] 챕터1 완료 후 채널 삭제 실패: {e}")
        
        await start_story_stage(self.bot, interaction.user, self.session['character_name'], 2)

    @discord.ui.button(label="Not today, maybe next time", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.session['user_id']:
            return await interaction.response.send_message("This is not for you.", ephemeral=True)

        await interaction.response.defer()
        db_manager.complete_story_stage(self.session['user_id'], self.session['character_name'], self.session['stage_num'])
        await interaction.message.edit(content="Understood. The story channel will be closed. You can continue to Chapter 2 from the `/story` command later.\n\n⏰ This channel will be automatically deleted in 5 seconds.", view=None)
        
        # 5초 후 채널 삭제
        import asyncio
        await asyncio.sleep(5)
        try:
            await interaction.channel.delete()
            print(f"[DEBUG][Kagari] 챕터1 취소 후 채널 삭제 완료")
        except Exception as e:
            print(f"[DEBUG][Kagari] 챕터1 취소 후 채널 삭제 실패: {e}")


class KagariStage2QuizView(discord.ui.View):
    """카가리 2장 퀴즈 View"""
    def __init__(self, bot: "BotSelector", session: Dict[str, Any]):
        super().__init__(timeout=300)
        self.bot = bot
        self.session = session

        quiz_info = get_chapter_info(session['character_name'], session['stage_num'])['quiz_data']

        for option_text in quiz_info['options']:
            self.add_item(self.QuizButton(label=option_text, style=discord.ButtonStyle.primary))

    class QuizButton(discord.ui.Button):
        async def callback(self, interaction: discord.Interaction):
            view: 'KagariStage2QuizView' = self.view
            session = view.session
            quiz_info = get_chapter_info(session['character_name'], session['stage_num'])['quiz_data']

            if interaction.user.id != session['user_id']:
                return await interaction.response.send_message("This is not for you.", ephemeral=True)

            await interaction.response.defer()

            is_correct = (self.label == quiz_info['correct_answer'])

            for child in view.children: # 모든 버튼 비활성화
                child.disabled = True

            if is_correct:
                self.style = discord.ButtonStyle.success
                db_manager.complete_story_stage(session['user_id'], session['character_name'], session['stage_num'])
                # 보상 지급 로직 (챕터1과 동일하게, 랜덤 커먼 Gift 3개)
                chapter_info = get_chapter_info(session['character_name'], session['stage_num'])
                rewards_info = chapter_info['rewards']
                reward_text = ""
                if rewards_info['type'] == 'specific_gift':
                    gift_ids = get_gifts_by_rarity_v2(rewards_info['rarity'].upper(), rewards_info['quantity'])
                    if gift_ids:
                        for gift_id in gift_ids:
                            db_manager.add_user_gift(session['user_id'], gift_id, 1)
                        gift_names = [get_gift_details(g)['name'] for g in gift_ids if get_gift_details(g)]
                        reward_text = f"You received: **{', '.join(gift_names)}**\nCheck your inventory with `/inventory`."
                    else:
                        reward_text = "You received: **No gifts available for this rarity.**\nCheck your inventory with `/inventory`."
                elif rewards_info['type'] == 'random_item':
                    from gift_manager import GIFT_RARITY
                    rarity_str = GIFT_RARITY.get(rewards_info['rarity'].upper(), rewards_info['rarity'].capitalize())
                    gift_ids = get_gifts_by_rarity_v2(rarity_str, rewards_info['quantity'])
                    if gift_ids:
                        for gift_id in gift_ids:
                            db_manager.add_user_gift(session['user_id'], gift_id, 1)
                        gift_names = [get_gift_details(g)['name'] for g in gift_ids if get_gift_details(g)]
                        reward_text = f"You received: **{', '.join(gift_names)}**\nCheck your inventory with `/inventory`."
                    else:
                        reward_text = "You received: **No gifts available for this rarity.**\nCheck your inventory with `/inventory`."
                else:
                    reward_text = "Reward processed."
                reward_embed = discord.Embed(
                    title="🎁 Reward!",
                    description=reward_text,
                    color=discord.Color.gold()
                )
                await interaction.followup.send(embed=reward_embed)
                # 챕터2 클리어 및 챕터3 오픈 안내
                congrats_embed = discord.Embed(
                    title="🌙 The day is getting late, shall we go back?",
                    description="Congratulations! You have cleared Chapter 2.\n\n**Chapter 3 is now unlocked!**\nUse `/story` to play Chapter 3!\n\n⏰ This channel will be automatically deleted in 5 seconds.",
                    color=discord.Color.blue()
                )
                await interaction.followup.send(embed=congrats_embed)
                await interaction.message.edit(content="Wow, you listened to my story well... (blushes)", view=view)
                await interaction.followup.send("The day is getting late, shall we go back?", ephemeral=True) # 다음 행동 유도
                
                # 5초 후 채널 삭제
                import asyncio
                await asyncio.sleep(5)
                try:
                    await interaction.channel.delete()
                    print(f"[DEBUG][Kagari] 챕터2 완료 후 채널 삭제 완료")
                except Exception as e:
                    print(f"[DEBUG][Kagari] 챕터2 완료 후 채널 삭제 실패: {e}")
            else:
                self.style = discord.ButtonStyle.danger
                session['quiz_attempts'] += 1

                if session['quiz_attempts'] >= quiz_info['max_attempts']:
                    await interaction.message.edit(content="Hmm... I don't think this item is special to me.", view=view)
                    await interaction.followup.send("Sorry, I'm not feeling well today, so I'll go back first...", ephemeral=True)
                    
                    # 5초 후 채널 삭제
                    import asyncio
                    await asyncio.sleep(5)
                    try:
                        await interaction.channel.delete()
                        print(f"[DEBUG][Kagari] 챕터2 실패 후 채널 삭제 완료")
                    except Exception as e:
                        print(f"[DEBUG][Kagari] 챕터2 실패 후 채널 삭제 실패: {e}")
                else:
                    remaining = quiz_info['max_attempts'] - session['quiz_attempts']
                    await interaction.message.edit(content=f"Hmm... I don't think this item is special to me. ({remaining} attempts left)", view=view)
                    # 퀴즈 재시도를 위해 새로운 View를 보내거나, 현재 View를 재활성화해야 함
                    new_view = KagariStage2QuizView(view.bot, session)
                    await interaction.followup.send("Let's think again?", view=new_view, ephemeral=True)

class ErosStage1StartView(discord.ui.View):
    """Eros Chapter 1: Menu explanation and cafe open button view"""
    def __init__(self, bot: "BotSelector", session: dict):
        super().__init__(timeout=180)
        self.bot = bot
        self.session = session

    @discord.ui.button(label="Let's Start!", style=discord.ButtonStyle.success)
    async def start_cafe(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.session['user_id']:
            return await interaction.response.send_message("Only you can use this button!", ephemeral=True)
        await interaction.response.defer()

        self.session['cafe_opened'] = True

        # 1. Drink recipe image embed (이미지로 대체)
        chapter_info = get_chapter_info(self.session['character_name'], self.session['stage_num'])
        menu = chapter_info.get('menu', [])
        CLOUDFLARE_IMAGE_BASE_URL = "https://imagedelivery.net/ZQ-g2Ke3i84UnMdCSDAkmw"
        menu_embed1 = discord.Embed(
            title="🥤 Drink Recipes",
            description="Please refer to the images below to make the drinks for each customer!",
            color=discord.Color.green()
        )
        menu_embed1.set_image(url=f"{CLOUDFLARE_IMAGE_BASE_URL}/37409a30-d07b-425a-e227-2ea05dd51d00/public")
        menu_embed1.set_footer(text="Use the /serve command to make the drinks!")
        menu_embed2 = discord.Embed(
            description="(continued)",
            color=discord.Color.green()
        )
        menu_embed2.set_image(url=f"{CLOUDFLARE_IMAGE_BASE_URL}/b71f71e5-e477-4903-3f31-7ebf09911800/public")
        await interaction.followup.send(embed=menu_embed1)
        await interaction.followup.send(embed=menu_embed2)

        # 2. First customer embed (Order = drink name, order 재료 순서 랜덤)
        import random
        customers = chapter_info.get('customers', [])
        if customers:
            first_customer = customers[0]
            order_recipe = first_customer['order'][:]
            random.shuffle(order_recipe)
            # 세션에 랜덤 순서로 저장
            if 'random_orders' not in self.session:
                self.session['random_orders'] = {}
            self.session['random_orders'][0] = order_recipe
            drink_name = None
            for drink in menu:
                if set(drink['recipe']) == set(first_customer['order']):
                    drink_name = drink['name']
                    break
            customer_embed = discord.Embed(
                title=f"👋 {first_customer['name']} Arrives!",
                description=first_customer['personality'],
                color=discord.Color.blue()
            )
            # 손님별 이미지 적용
            image_url = CHARACTER_IMAGES["Eros"]
            if 'image_id' in first_customer:
                image_url = f"https://imagedelivery.net/ZQ-g2Ke3i84UnMdCSDAkmw/{first_customer['image_id']}/public"
            customer_embed.set_thumbnail(url=image_url)
            customer_embed.add_field(
                name="📋 Order",
                value=f"**{drink_name if drink_name else 'Unknown Drink'}**",
                inline=False
            )
            customer_embed.set_footer(text="Customer 1/10 • Use /serve to make the drink!")
            await interaction.followup.send(embed=customer_embed)

        await interaction.message.edit(view=None)

class ErosChapter2StartView(discord.ui.View):
    """Eros Chapter 2: Start View"""
    def __init__(self, bot: "BotSelector", session: dict):
        super().__init__(timeout=180)
        self.bot = bot
        self.session = session

    @discord.ui.button(label="Yes, I'll help!", style=discord.ButtonStyle.success)
    async def start_mission(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.session['user_id']:
            return await interaction.response.send_message("Only you can use this button!", ephemeral=True)
        await interaction.response.defer()

        chapter_info = get_chapter_info(self.session['character_name'], self.session['stage_num'])

        # 1. Eros's Reply Embed (썸네일 원래대로, 본문 이미지 1장)
        eros_reply_embed = discord.Embed(
            title="🍯 Eros's Reply",
            description=(
                "Here's a list of what our teammates like! I've prepared drinks based on these preferences—please deliver them to each team member."
            ),
            color=0xE74C3C
        )
        eros_reply_embed.set_thumbnail(url=CHARACTER_IMAGES["Eros"])
        eros_reply_embed.set_image(url="https://imagedelivery.net/ZQ-g2Ke3i84UnMdCSDAkmw/384121e1-4e0a-4f9f-92c4-f1bfca8d8300/public")
        eros_reply_embed.set_footer(text="Thank you for helping! 🍯")
        await interaction.followup.send(embed=eros_reply_embed)

        # 2. 두 번째 본문 이미지만 별도 임베드로 전송
        eros_reply_img2 = discord.Embed(color=0xE74C3C)
        eros_reply_img2.set_image(url="https://imagedelivery.net/ZQ-g2Ke3i84UnMdCSDAkmw/dfe63873-afb3-42e9-2ab9-e423d51bb900/public")
        await interaction.followup.send(embed=eros_reply_img2)

        # 3. Drink Menu Embed
        drink_embed = discord.Embed(
            title="🍹 Drink Menu",
            description="Choose the perfect drink for each friend! 🎯",
            color=discord.Color.green()
        )
        drink_embed.set_thumbnail(url=CHARACTER_IMAGES["Eros"])
        for drink in chapter_info['drink_list']:
            drink_embed.add_field(
                name=f"{drink['emoji']} {drink['name']}",
                value="\u200b",
                inline=True
            )
        drink_embed.set_footer(text="All drinks are made with love! 💕")
        await interaction.followup.send(embed=drink_embed)

        # 4. How to Play Embed
        guide_embed = discord.Embed(
            title="🎮 How to Play",
            description=(
                "Use `/serve_team <character> <drink>` to serve each member!\n"
                "**Example:** `/serve_team Kagari mike tea `\n\n"
                "Check the preference chart and drink menu above!"
            ),
            color=discord.Color.blue()
        )
        guide_embed.set_thumbnail(url=CHARACTER_IMAGES["Eros"])
        guide_embed.set_footer(text="Good luck! You can do it! ✨")
        await interaction.followup.send(embed=guide_embed)

        await interaction.message.edit(view=None)

class ErosChapter3IntroView(discord.ui.View):
    """Eros Chapter 3: Intro View (도입)"""
    def __init__(self, bot: "BotSelector", session: dict):
        super().__init__(timeout=180)
        self.bot = bot
        self.session = session

    @discord.ui.button(label="Help Eros!", style=discord.ButtonStyle.success)
    async def start_investigation(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.session['user_id']:
            return await interaction.response.send_message("Only you can use this button!", ephemeral=True)
        await interaction.response.defer()

        # 탐문/추리 모드 진입
        self.session['investigation_mode'] = True
        self.session['turn_count'] = 0

        investigation_embed = discord.Embed(
            title="🔎 Investigation Begins!",
            description=(
                "You can now ask Eros any questions to find clues about who took the gift box!\n\n"
                "**How to play:**\n"
                "• Ask Eros questions about each team member\n"
                "• Look for inconsistencies in their stories\n"
                "• You have **30 questions** to figure out the culprit\n"
                "• After 30 questions, you'll choose who you think is guilty\n"
            ),
            color=discord.Color.purple()
        )
        investigation_embed.set_thumbnail(url=CHARACTER_IMAGES["Eros"])
        investigation_embed.set_footer(text="Ask your first question to begin the investigation!")
        await interaction.followup.send(embed=investigation_embed)
        await interaction.message.edit(view=None)

class ErosChapter3CulpritSelectView(discord.ui.View):
    """Eros Chapter 3: 범인 선택 View"""
    def __init__(self, bot: "BotSelector", session: dict):
        super().__init__(timeout=300)
        self.bot = bot
        self.session = session

    @discord.ui.button(label="Kagari", style=discord.ButtonStyle.secondary)
    async def select_kagari(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.select_culprit(interaction, "Kagari")

    @discord.ui.button(label="Ira", style=discord.ButtonStyle.secondary)
    async def select_ira(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.select_culprit(interaction, "Ira")

    @discord.ui.button(label="Dolores", style=discord.ButtonStyle.secondary)
    async def select_dolores(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.select_culprit(interaction, "Dolores")

    @discord.ui.button(label="Cang", style=discord.ButtonStyle.secondary)
    async def select_cang(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.select_culprit(interaction, "Cang")

    @discord.ui.button(label="Elysia", style=discord.ButtonStyle.secondary)
    async def select_elysia(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.select_culprit(interaction, "Elysia")

    async def select_culprit(self, interaction: discord.Interaction, selected_culprit: str):
        if interaction.user.id != self.session['user_id']:
            return await interaction.response.send_message("Only you can make this choice!", ephemeral=True)

        await interaction.response.defer()

        chapter_info = get_chapter_info(self.session['character_name'], self.session['stage_num'])
        correct_culprit = chapter_info['culprit']

        # 모든 버튼 비활성화
        for child in self.children:
            child.disabled = True

        # 실패 카운트 세션에 저장
        if 'culprit_attempts' not in self.session:
            self.session['culprit_attempts'] = 0

        if selected_culprit == correct_culprit:
            # 성공!
            success_embed = discord.Embed(
                title="🎉 You Found the Culprit!",
                description=(
                    f"**Correct!** {selected_culprit} was the one who took the gift box!\n\n"
                    f"**Reason:** {chapter_info['culprit_reason']}\n\n"
                    "Eros is impressed by your detective skills!"
                ),
                color=discord.Color.green()
            )
            success_embed.set_thumbnail(url=CHARACTER_IMAGES["Eros"])

            # 보상 지급
            rewards = chapter_info['rewards']['success']
            reward_text = ""
            if rewards['type'] == 'specific_card':
                self.bot.db.add_user_card(self.session['user_id'], rewards['card'], 1)
                # 퀘스트 진행률 업데이트 트리거
                try:
                    from bot_selector import BotSelector
                    bot_selector = BotSelector()
                    bot_selector.trigger_card_quest_completion(self.session['user_id'], self.session['character'])
                except Exception as e:
                    print(f"Error triggering quest completion: {e}")
                reward_text = f"**Reward:** {rewards['rarity']} Card **{rewards['card']}**\nCheck your cards with `/cards`!"
            else:
                reward_text = "Reward processed."

            success_embed.add_field(name="🎁 Reward", value=reward_text, inline=False)
            success_embed.set_footer(text="Congratulations! You're a great detective! 🔍✨")

            # Claim 버튼이 있는 카드 임베드
            class ClaimCardView(discord.ui.View):
                def __init__(self, user_id, card_id, bot_instance):
                    super().__init__(timeout=60)
                    self.user_id = user_id
                    self.card_id = card_id
                    self.claimed = False
                    self.bot = bot_instance

                @discord.ui.button(label="Claim Card", style=discord.ButtonStyle.success)
                async def claim(self, interaction: discord.Interaction, button: discord.ui.Button):
                    if interaction.user.id != self.user_id:
                        return await interaction.response.send_message("Only you can claim this card!", ephemeral=True)
                    if self.claimed:
                        return await interaction.response.send_message("You have already claimed your card!", ephemeral=True)
                    
                    # Discord 타임아웃 방지
                    await interaction.response.defer(ephemeral=True)
                    
                    # 실제로 DB에 카드 저장
                    try:
                        success = self.bot.db.add_user_card(self.user_id, "Eros", self.card_id)
                        if success:
                            # 퀘스트 진행률 업데이트 트리거
                            try:
                                from bot_selector import BotSelector
                                bot_selector = BotSelector()
                                bot_selector.trigger_card_quest_completion(self.user_id, "Eros")
                            except Exception as e:
                                print(f"Error triggering quest completion: {e}")
                            
                            self.claimed = True
                            # 버튼 비활성화 및 텍스트 변경
                            button.disabled = True
                            button.label = "Claimed"
                            button.style = discord.ButtonStyle.grey
                            
                            # 메시지 업데이트
                            await interaction.message.edit(view=self)
                            await interaction.followup.send(f"You have claimed your card: **{self.card_id}**! Check your cards with `/mycard`.", ephemeral=True)
                            
                            # 5초 후 채널 삭제
                            import asyncio
                            await asyncio.sleep(5)
                            try:
                                await interaction.channel.delete()
                                print(f"[DEBUG][Eros] 챕터3 카드 클레임 후 채널 삭제 완료")
                            except Exception as e:
                                print(f"[DEBUG][Eros] 챕터3 카드 클레임 후 채널 삭제 실패: {e}")
                        else:
                            await interaction.followup.send("Failed to claim the card. Please try again.", ephemeral=True)
                    except Exception as e:
                        print(f"Error claiming card {self.card_id} for user {self.user_id}: {e}")
                        await interaction.followup.send("An error occurred while claiming the card. Please try again.", ephemeral=True)
                    
                    self.stop()

            card_embed = discord.Embed(
                title="🎴 Card Reward",
                description=f"You have earned the special card: **{rewards['card']}**!",
                color=discord.Color.gold()
            )
            from config import CHARACTER_CARD_INFO
            card_id = rewards['card']
            card_image_url = CHARACTER_CARD_INFO["Eros"].get(card_id, {}).get("image_url")
            if card_image_url:
                card_embed.set_image(url=card_image_url)
            card_embed.set_footer(text="Press the button below to claim your card!")
            await interaction.message.edit(view=self)
            await interaction.followup.send(embed=success_embed)
            await interaction.followup.send(embed=card_embed, view=ClaimCardView(self.session['user_id'], rewards['card'], self.bot))

            # 스토리 완료 처리
            self.bot.db.complete_story_stage(self.session['user_id'], self.session['character_name'], self.session['stage_num'])
            self.session['is_active'] = False

        else:
            # 오답: 기회 3번 제공
            self.session['culprit_attempts'] += 1
            attempts_left = 3 - self.session['culprit_attempts']
            if attempts_left > 0:
                fail_embed = discord.Embed(
                    title="😔 Wrong Guess",
                    description=(
                        f"**Incorrect.** {selected_culprit} was not the culprit.\n\n"
                        f"You have {attempts_left} attempts left. Please try again."
                    ),
                    color=discord.Color.red()
                )
                fail_embed.set_thumbnail(url=CHARACTER_IMAGES["Eros"])
                fail_embed.set_footer(text="Don't give up! You can try again! 💪")
                await interaction.message.edit(view=self)
                await interaction.followup.send(embed=fail_embed)
            else:
                # 3번 모두 실패
                fail_embed = discord.Embed(
                    title="❌ All Attempts Used",
                    description="You have used all your attempts. Please try again.\n\n⏰ This channel will be automatically deleted in 5 seconds.",
                    color=discord.Color.red()
                )
                fail_embed.set_thumbnail(url=CHARACTER_IMAGES["Eros"])
                fail_embed.set_footer(text="The story will end now.")
                self.session['is_active'] = False
                await interaction.message.edit(view=self)
                await interaction.followup.send(embed=fail_embed)
                
                # 5초 후 채널 삭제 (실패)
                import asyncio
                await asyncio.sleep(5)
                try:
                    await interaction.channel.delete()
                    print(f"[DEBUG][Eros] 챕터3 실패 후 채널 삭제 완료")
                except Exception as e:
                    print(f"[DEBUG][Eros] 챕터3 실패 후 채널 삭제 실패: {e}")

        # 스토리 완료 안내(정답/실패 모두)
        if self.session['is_active'] is False:
            completion_embed = discord.Embed(
                title="🔍 Investigation Complete!",
                description=(
                    "The investigation has concluded. Thank you for helping Eros solve the mystery!\n\n"
                    "The channel will be automatically deleted in 10 seconds."
                ),
                color=discord.Color.blue()
            )
            completion_embed.set_footer(text="See you next time, detective! 👋")
            await interaction.followup.send(embed=completion_embed)

# --- Main Story Logic ---

async def start_story_stage(bot: "BotSelector", user: discord.User, character_name: str, stage_num: int, current_channel=None):
    """지정된 스토리 스테이지를 시작하고, 전용 채널을 생성합니다."""
    guild = user.guild
    stage_info = get_chapter_info(character_name, stage_num)
    if not stage_info:
        logger.error(f"Stage info not found for {character_name} - Stage {stage_num}")
        return

    # 채널 이름 및 생성
    channel_name = f"{character_name.lower()}-s{stage_num}-{user.name.lower()[:10]}"
    category = discord.utils.get(guild.categories, name="chatbot")
    
    # 현재 스토리 채널이 있으면 삭제 (다른 챕터로 이동하는 경우)
    if current_channel and any(f'-s{i}-' in current_channel.name for i in range(1, 10)):
        try:
            await current_channel.delete()
            print(f"[DEBUG] Deleted current story channel: {current_channel.name}")
        except Exception as e:
            print(f"[DEBUG] Failed to delete current story channel: {e}")
    
    if category:
        # 같은 이름의 기존 채널 정리 (혹시 모를 중복 방지)
        for ch in category.text_channels:
            if ch.name == channel_name:
                await ch.delete()
                logger.info(f"Deleted existing story channel: {channel_name}")

    overwrites = {
        guild.default_role: discord.PermissionOverwrite(read_messages=False),
        user: discord.PermissionOverwrite(read_messages=True, send_messages=True),
        guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True)
    }
    channel = await guild.create_text_channel(
        name=channel_name,
        category=category,
        topic=f"Story with {character_name} for {user.name}"
    )

    # 세션 초기화 (이미 있으면 덮어쓰지 않음)
    if channel.id not in story_sessions:
     story_sessions[channel.id] = {
        "user_id": user.id,
        "character_name": character_name,
        "stage_num": stage_num,
        "internal_affinity": 0,
            "turn_count": 0,
        "quiz_attempts": 0,
            "is_active": True,
            "history": [], # 대화 기록 추가
            "investigation_mode": False, # 챕터3 탐문 모드
            "chapter2_started": False, # 챕터2 시작 플래그
            "chapter3_started": False, # 챕터3 시작 플래그
        }
    print(f"[DEBUG][Elysia] story_sessions keys after creation: {list(story_sessions.keys())}, new channel.id: {channel.id}")

    embed = create_story_intro_embed(character_name, stage_info)
    await channel.send(embed=embed)
    return channel

# --- 임베드 생성 함수 ---
def create_elysia_intro_embed():
    from config import STORY_CHAPTERS
    chapter_info = get_chapter_info('Elysia', 1)
    embed = discord.Embed(
        title="🐾 Elysia's Favorite Thing?",
        description=chapter_info['prompt'] + "\n\nGame Rule: Deduce the answer by asking questions for 24 turns. Hints will be revealed at the start, and on turns 6, 12, and 18. Submit your answer after 24 turns!",
        color=discord.Color.teal()
    )
    embed.set_image(url=chapter_info['banner_image'])
    embed.set_footer(text="Start chatting with Elysia!")
    return embed

async def process_story_message(bot: "BotSelector", message: discord.Message):
    """스토리 채널의 메시지를 처리하는 메인 핸들러"""
    session = story_sessions.get(message.channel.id)
    if not session or not session.get("is_active"):
        return
    handler = handler_map.get(session["character_name"])
    if handler:
        await handler(bot, message, session)

async def handle_kagari_story(bot: "BotSelector", message: discord.Message, session: dict):
    session["turn_count"] += 1

    # --- 챕터3: 30턴 도달 시 대화 임베드 차단 (early return) ---
    if session["stage_num"] == 3:
        chapter_info = get_chapter_info(session['character_name'], session['stage_num'])
        turn_limit = chapter_info['clear_condition']['turn_limit']
        if session.get("waiting_for_gift", False):
            return
        if session["turn_count"] > turn_limit:
            return
        if session["turn_count"] == turn_limit:
            clear_embed = discord.Embed(
                title="🌙 This Moment Forever",
                description=(
                    "The date with Kagari is coming to an end...\n"
                    "She says she's grateful for spending the day with you and wants to see you again next time.\n\n"
                    "💡 Use `/gift` to give a present and complete the story!\n"
                    "Choose your gift carefully—your choice will determine whether you receive a special card or fail the mission."
                ),
                color=discord.Color.purple()
            )
            clear_embed.set_footer(text="Use /gift to give a present and complete the story!")
            await message.channel.send(embed=clear_embed)
            session["waiting_for_gift"] = True
            session["gift_attempts"] = 0
            session["max_gift_attempts"] = chapter_info['clear_condition']['max_attempts']
            return

    # --- 1. AI 응답 생성 ---
    try:
        async with message.channel.typing():
            chapter_info = get_chapter_info(session['character_name'], session['stage_num'])
            system_prompt = chapter_info['prompt']

            # 대화 히스토리 구성
            messages = [{"role": "system", "content": system_prompt}]
            messages.extend(session.get('history', []))
            messages.append({"role": "user", "content": message.content})

            # OpenAI 호출
            ai_response_text = await call_openai(messages)

            # 히스토리 업데이트
            session['history'].append({"role": "user", "content": message.content})
            session['history'].append({"role": "assistant", "content": ai_response_text})

            # 임베드로 몰입감 있게 출력
            char_info = CHARACTER_INFO[session['character_name']]
            embed = discord.Embed(
                description=f"{ai_response_text}",
                color=char_info.get('color', discord.Color.blue())
            )
            embed.set_author(name=session['character_name'], icon_url=char_info.get('image_url'))
            embed.set_thumbnail(url=char_info.get('image_url'))
            # 챕터2, 3일 때 턴 정보 표시
            if session["stage_num"] in [2, 3]:
                turn = session["turn_count"]
                total = chapter_info['clear_condition']['turn_limit']
                embed.set_footer(text=f"Turn {turn}/{total}")
            await message.channel.send(embed=embed)

    except Exception as e:
        logger.error(f"Error generating story response for Kagari: {e}")
        await message.channel.send("... (카가리는 잠시 생각에 잠겨있다.)")
        return

    # --- 2. 챕터1: 호감도 체크 및 클리어 조건 ---
    if session["stage_num"] == 1:
        # 1:1 대화와 동일한 감정 분석 로직 사용 (+1/0/-1)
        emotion_score = await analyze_emotion_with_gpt_and_pattern(message.content)
        # 점수는 반드시 -1, 0, +1로만 제한
        if emotion_score > 0:
            emotion_score = 1
        elif emotion_score < 0:
            emotion_score = -1
        else:
            emotion_score = 0
        session["internal_affinity"] = session.get("internal_affinity", 0) + emotion_score

        # 호감도 10 미만이면 계속 대화만 진행 (결과/리워드/전환 임베드 출력 X)
        if session["internal_affinity"] < 10:
            return

        # 호감도 10점 달성 시 클리어 처리 및 리워드 지급
        session["is_active"] = False
        chapter_info = get_chapter_info(session['character_name'], session['stage_num'])
        rewards_info = chapter_info['rewards']
        reward_text = ""
        if rewards_info['type'] == 'specific_gift':
            gift_ids = get_gifts_by_rarity_v2(rewards_info['rarity'].upper(), rewards_info['quantity'])
            if gift_ids:
                for gift_id in gift_ids:
                    db_manager.add_user_gift(session['user_id'], gift_id, 1)
                gift_names = [get_gift_details(g)['name'] for g in gift_ids if get_gift_details(g)]
                reward_text = f"You received: **{', '.join(gift_names)}**\nCheck your inventory with `/inventory`."
            else:
                reward_text = "You received: **No gifts available for this rarity.**\nCheck your inventory with `/inventory`."
        elif rewards_info['type'] == 'random_item':
            from gift_manager import GIFT_RARITY
            rarity_str = GIFT_RARITY.get(rewards_info['rarity'].upper(), rewards_info['rarity'].capitalize())
            gift_ids = get_gifts_by_rarity_v2(rarity_str, rewards_info['quantity'])
            if gift_ids:
                for gift_id in gift_ids:
                    db_manager.add_user_gift(session['user_id'], gift_id, 1)
                gift_names = [get_gift_details(g)['name'] for g in gift_ids if get_gift_details(g)]
                reward_text = f"You received: **{', '.join(gift_names)}**\nCheck your inventory with `/inventory`."
            else:
                reward_text = "You received: **No gifts available for this rarity.**\nCheck your inventory with `/inventory`."
        else:
            reward_text = "Reward processed."
        embed = discord.Embed(title="🌸 Goal Achieved!", description=f"You've reached +10 affinity with Kagari!\n{reward_text}", color=discord.Color.green())
        await message.channel.send(embed=embed)
        # 전환 UI
        transition_embed = discord.Embed(
            title="...A quiet moment passes...",
            description="Kagari: I think we've seen all the cherry blossoms now. Shall we go have some tea at that café over there?",
            color=discord.Color.light_grey()
        )
        view = KagariStage1CompleteView(bot, session)
        await message.channel.send(embed=transition_embed, view=view)

    # --- 챕터2, 3 기존 로직은 그대로 유지 ---
    if session["stage_num"] == 2:
        chapter_info = get_chapter_info(session['character_name'], session['stage_num'])
        if session["turn_count"] >= chapter_info['clear_condition']['turn_limit']:
            session["is_active"] = False
            quiz_info = chapter_info['quiz_data']
            view = KagariStage2QuizView(bot, session)
            await message.channel.send(quiz_info["question"], view=view)

    if session["stage_num"] == 3:
        chapter_info = get_chapter_info(session['character_name'], session['stage_num'])
        turn_limit = chapter_info['clear_condition']['turn_limit']
        if session["turn_count"] >= turn_limit:
            clear_embed = discord.Embed(
                title="🌙 This Moment Forever",
                description=(
                    "The date with Kagari is coming to an end...\n"
                    "She says she's grateful for spending the day with you and wants to see you again next time.\n\n"
                    "💡 Use `/gift` to give a present and complete the story!\n"
                    "Choose your gift carefully—your choice will determine whether you receive a special card or fail the mission."
                ),
                color=discord.Color.purple()
            )
            clear_embed.set_footer(text="Use /gift to give a present and complete the story!")
            await message.channel.send(embed=clear_embed)
            session["waiting_for_gift"] = True
            session["gift_attempts"] = 0
            session["max_gift_attempts"] = chapter_info['clear_condition']['max_attempts']

# --- Gift Usage Handler for Chapter 3 ---

async def handle_chapter3_gift_usage(bot: "BotSelector", user_id: int, character_name: str, gift_id: str, channel_id: int):
    """챕터3에서 선물 사용을 처리합니다."""
    print(f"[DEBUG] handle_chapter3_gift_usage called - user_id: {user_id}, character: {character_name}, gift_id: {gift_id}, channel_id: {channel_id}")
    
    session = story_sessions.get(channel_id)
    print(f"[DEBUG] Session found: {session is not None}")
    if not session or session.get("stage_num") != 3 or not session.get("waiting_for_gift"):
        print(f"[DEBUG] Session validation failed - stage_num: {session.get('stage_num') if session else 'None'}, waiting_for_gift: {session.get('waiting_for_gift') if session else 'None'}")
        return False, "This is not a Chapter 3 story session waiting for a gift."

    if session["user_id"] != user_id:
        print(f"[DEBUG] User ID mismatch - session user: {session['user_id']}, current user: {user_id}")
        return False, "This story session is not yours."

    session["gift_attempts"] += 1
    print(f"[DEBUG] Gift attempts: {session['gift_attempts']}")

    # 선물 사용은 이미 bot_selector.py에서 처리되었으므로 여기서는 건너뜀
    # if not bot.db.use_user_gift(user_id, gift_id, 1):
    #     print(f"[DEBUG] Failed to use gift: {gift_id}")
    #     return False, "Failed to use the gift. Please check your inventory."

    # 선물 등급 확인
    gift_details = get_gift_details(gift_id)
    gift_rarity = gift_details.get('rarity', 'Common')
    print(f"[DEBUG] Gift details: {gift_details}, rarity: {gift_rarity}")

    # 등급별 보상 결정
    chapter_info = get_chapter_info(character_name, 3)
    rewards = chapter_info['rewards']
    print(f"[DEBUG] Chapter rewards: {rewards}")

    if gift_rarity == "Epic":
        reward_card = rewards['epic']['card']
        reward_rarity_text = "🟣 Epic"
    elif gift_rarity == "Rare":
        reward_card = rewards['rare']['card']
        reward_rarity_text = "🔵 Rare"
    else:  # Common
        reward_card = rewards['common']['card']
        reward_rarity_text = "⚪ Common"

    print(f"[DEBUG] Reward card: {reward_card}, rarity text: {reward_rarity_text}")

    # 카드 보상 지급
    bot.db.add_user_card(user_id, character_name, reward_card)
    # 퀘스트 진행률 업데이트 트리거
    try:
        from bot_selector import BotSelector
        bot_selector = BotSelector()
        bot_selector.trigger_card_quest_completion(user_id, character_name)
    except Exception as e:
        print(f"Error triggering quest completion: {e}")
    print(f"[DEBUG] Card added to user: {reward_card}")

    # 스토리 완료 처리
    bot.db.complete_story_stage(user_id, character_name, 3)
    session["is_active"] = False
    session["waiting_for_gift"] = False
    print(f"[DEBUG] Story stage completed and session updated")

    # 성공 메시지
    success_embed = discord.Embed(
        title="💝 Gift Delivered",
        description=(
            f"Kagari is happy to receive **{gift_details['name']}**.\n"
            f"She says she'll never forget this moment and gives you a warm smile.\n\n"
            f"**Reward:** {reward_rarity_text} Card **{reward_card}** obtained!\n"
            f"Check your cards with `/mycard`."
        ),
        color=discord.Color.pink()
    )

    # 스토리 완료 안내
    completion_embed = discord.Embed(
        title="🌙 This Moment Forever - Completed!",
        description=(
            "Congratulations! You have completed Chapter 3 of Kagari's story.\n"
            "The special date with Kagari has been successfully concluded.\n\n"
            "⏰ This channel will be automatically deleted in 5 seconds."
        ),
        color=discord.Color.gold()
    )

    print(f"[DEBUG] Returning success with embeds")
    return True, (success_embed, completion_embed)

async def handle_chapter3_gift_failure(bot: "BotSelector", user_id: int, character_name: str, channel_id: int):
    """챕터3에서 선물 사용 실패를 처리합니다."""
    session = story_sessions.get(channel_id)
    if not session or session.get("stage_num") != 3 or not session.get("waiting_for_gift"):
        return False, "This is not a Chapter 3 story session waiting for a gift."

    if session["user_id"] != user_id:
        return False, "This story session is not yours."

    session["gift_attempts"] += 1
    max_attempts = session["max_gift_attempts"]
    remaining_attempts = max_attempts - session["gift_attempts"]

    if remaining_attempts <= 0:
        # 최대 시도 횟수 초과 - 스토리 실패
        session["is_active"] = False
        session["waiting_for_gift"] = False

        failure_embed = discord.Embed(
            title="😔 Story Failed",
            description=(
                "Kagari has been waiting for your gift, but she received nothing.\n"
                "She walks away with a disappointed expression.\n\n"
                "**To try again, use the `/story` command again.**\n\n"
                "⏰ This channel will be automatically deleted in 5 seconds."
            ),
            color=discord.Color.red()
        )

        return True, failure_embed
    else:
        # 재시도 안내
        retry_embed = discord.Embed(
            title="💭 Waiting for Gift...",
            description=(
                f"Kagari is waiting for your gift.\n"
                f"Use the `/gift` command to give her a present.\n\n"
                f"**Remaining Attempts:** {remaining_attempts}"
            ),
            color=discord.Color.orange()
        )

        return False, retry_embed

# --- 메뉴 재료 매칭 유틸리티 ---
def find_menu_by_recipe(menu, recipe_list):
    # 재료(순서 무관)로 메뉴 찾기
    for item in menu:
        if set(item['recipe']) == set(recipe_list):
            return item
    return None

# --- Elysia 챕터1: 좋아하는 물건 맞히기 ---
class ElysiaStage1StartView(discord.ui.View):
    def __init__(self, bot, session):
        super().__init__(timeout=180)
        self.bot = bot
        self.session = session
        print(f"[DEBUG][Elysia] ElysiaStage1StartView 생성됨")

    @discord.ui.button(label="Let's Start!", style=discord.ButtonStyle.success)
    async def start_game(self, interaction: discord.Interaction, button: discord.ui.Button):
        print(f"[DEBUG][Elysia] 버튼 클릭됨 - user_id: {interaction.user.id}, session_user_id: {self.session['user_id']}")
        if interaction.user.id != self.session['user_id']:
            print(f"[DEBUG][Elysia] 잘못된 사용자 - 차단됨")
            return await interaction.response.send_message("Only you can use this button!", ephemeral=True)

        print(f"[DEBUG][Elysia] 챕터1 시작 - 세션 초기화 전")
        await interaction.response.defer()

        # 세션 초기화
        self.session['chapter1_started'] = True
        self.session['turn'] = 0
        self.session['hints_shown'] = [0]  # 힌트1은 바로 출력되므로 0번 인덱스 추가
        self.session['awaiting_answer'] = False
        self.session['history'] = []

        # 세션을 story_sessions에 명시적으로 저장
        story_sessions[interaction.channel.id] = self.session
        print(f"[DEBUG][Elysia] 세션 저장됨 - channel_id: {interaction.channel.id}")
        print(f"[DEBUG][Elysia] 세션 상태: {self.session}")

        intro_embed = create_elysia_intro_embed()
        await interaction.followup.send(embed=intro_embed)
        # 힌트1 바로 출력
        from config import STORY_CHAPTERS
        chapter_info = get_chapter_info('Elysia', 1)
        hint1 = chapter_info['hints'][0][0] if chapter_info['hints'][0] else ""
        hint_embed = discord.Embed(
            title="💡 Hint 1",
            description=hint1,
            color=discord.Color.blue()
        )
        await interaction.followup.send(embed=hint_embed)
        await interaction.message.edit(view=None)
        print(f"[DEBUG][Elysia] 챕터1 시작 완료 - 인트로 임베드+힌트1 전송됨")

async def handle_elysia_story(bot, message, session):
    print(f"[DEBUG][Elysia] handle_elysia_story 호출됨")
    print(f"[DEBUG][Elysia] channel_id: {message.channel.id}")
    print(f"[DEBUG][Elysia] session 상태: {session}")
    print(f"[DEBUG][Elysia] chapter1_started: {session.get('chapter1_started', False)}")

    try:
        from config import STORY_CHAPTERS
        chapter_info = get_chapter_info(session['character_name'], session['stage_num'])
        yes_replies = chapter_info['yes_replies']
        no_replies = chapter_info['no_replies']
        answer_keywords = ["공", "고무", "둥글", "스포츠", "놀이", "장난감", "어린이", "고양이", "강아지"]
        hints = chapter_info['hints']
        answer_list = chapter_info['answer']

        # 1. 챕터1 시작 체크 (인트로+버튼)
        if not session.get('chapter1_started', False):
            print(f"[DEBUG][Elysia] 챕터1 시작 안됨 - 인트로+버튼 전송")
            view = ElysiaStage1StartView(bot, session)
            intro_embed = discord.Embed(
                title="🐾 Elysia's Story",
                description="**Chapter 1: Elysia's Favorite Thing?**\n\nBegin your story with Elysia!\nStart chatting with the character to begin your story!",
                color=discord.Color.teal()
            )
            intro_embed.set_footer(text="Start chatting with the character to begin your story!")
            await message.channel.send(embed=intro_embed, view=view)
            print(f"[DEBUG][Elysia] 인트로+버튼 전송 완료")
            return

        print(f"[DEBUG][Elysia] 챕터1 진행 중 - turn: {session.get('turn', 0)}")

        # 2. 정답 제출 대기
        if session.get('awaiting_answer', False):
            print(f"[DEBUG][Elysia] 정답 제출 대기 중")
            user_answer = message.content.strip()
            print(f"[DEBUG][Elysia] 사용자 정답: {user_answer}")
            print(f"[DEBUG][Elysia] 정답 리스트: {answer_list}")

            if any(ans in user_answer.lower() for ans in [a.lower() for a in answer_list]):
                print(f"[DEBUG][Elysia] 정답! 보상 지급")
                from gift_manager import GIFT_RARITY, get_gifts_by_rarity_v2, get_gift_details
                rarity_str = GIFT_RARITY['RARE']
                gift_ids = get_gifts_by_rarity_v2(rarity_str, 2)
                if gift_ids:
                    for gift_id in gift_ids:
                        bot.db.add_user_gift(session['user_id'], gift_id, 1)
                    gift_names = [get_gift_details(g)['name'] for g in gift_ids if get_gift_details(g)]
                    reward_text = f"You received: **{', '.join(gift_names)}**\nCheck your inventory with `/inventory`."
                else:
                    reward_text = "You received: **No gifts available for this rarity.**\nCheck your inventory with `/inventory`."
                embed = discord.Embed(
                    title="🎉 Correct!",
                    description=f"Congratulations! You guessed Elysia's favorite thing!\n{reward_text}",
                    color=discord.Color.green()
                )
                await message.channel.send(embed=embed)
                bot.db.complete_story_stage(session['user_id'], session['character_name'], session['stage_num'])
                session['is_active'] = False
                story_sessions[message.channel.id] = session
                print(f"[DEBUG][Elysia] 챕터1 완료 - 세션 종료")
                
                # 5초 후 채널 삭제
                import asyncio
                await asyncio.sleep(5)
                try:
                    await message.channel.delete()
                    print(f"[DEBUG][Elysia] 채널 삭제 완료")
                except Exception as e:
                    print(f"[DEBUG][Elysia] 채널 삭제 실패: {e}")
            else:
                print(f"[DEBUG][Elysia] 오답 - 재시도 안내")
                embed = discord.Embed(
                    title="😢 Incorrect",
                    description="Sorry, that's not the answer. You can try again by playing /story!",
                    color=discord.Color.red()
                )
                await message.channel.send(embed=embed)
                session['is_active'] = False
                story_sessions[message.channel.id] = session
                print(f"[DEBUG][Elysia] 챕터1 실패 - 세션 종료")
                
                # 5초 후 채널 삭제
                import asyncio
                await asyncio.sleep(5)
                try:
                    await message.channel.delete()
                    print(f"[DEBUG][Elysia] 채널 삭제 완료")
                except Exception as e:
                    print(f"[DEBUG][Elysia] 채널 삭제 실패: {e}")
            return

        # 3. 질문 턴 진행
        session['turn'] += 1
        print(f"[DEBUG][Elysia] 턴 증가: {session['turn']}")

        # 세션 저장
        story_sessions[message.channel.id] = session
        print(f"[DEBUG][Elysia] 세션 저장됨 - turn: {session['turn']}")

        # 힌트 공개
        if session['turn'] == 6 and 1 not in session['hints_shown']:
            hint2 = hints[1][0] if len(hints) > 1 and hints[1] else ""
            hint_embed = discord.Embed(
                title="💡 Hint 2",
                description=hint2,
                color=discord.Color.blue()
            )
            hint_embed.set_image(url="https://imagedelivery.net/ZQ-g2Ke3i84UnMdCSDAkmw/beb49c57-980c-49ff-827d-f70c5a9d3100/public")
            await message.channel.send(embed=hint_embed)
            session['hints_shown'].append(1)
            story_sessions[message.channel.id] = session
            print(f"[DEBUG][Elysia] 힌트2 전송 완료")
        elif session['turn'] == 12 and 2 not in session['hints_shown']:
            hint3 = hints[2][0] if len(hints) > 2 and hints[2] else ""
            hint_embed = discord.Embed(
                title="💡 Hint 3",
                description=hint3,
                color=discord.Color.blue()
            )
            hint_embed.set_image(url="https://imagedelivery.net/ZQ-g2Ke3i84UnMdCSDAkmw/beb49c57-980c-49ff-827d-f70c5a9d3100/public")
            await message.channel.send(embed=hint_embed)
            session['hints_shown'].append(2)
            story_sessions[message.channel.id] = session
            print(f"[DEBUG][Elysia] 힌트3 전송 완료")
        elif session['turn'] == 18 and 3 not in session['hints_shown']:
            hint4 = "Rolling rolling....."
            hint_embed = discord.Embed(
                title="💡 Hint 4",
                description=hint4,
                color=discord.Color.blue()
            )
            hint_embed.set_image(url="https://imagedelivery.net/ZQ-g2Ke3i84UnMdCSDAkmw/beb49c57-980c-49ff-827d-f70c5a9d3100/public")
            await message.channel.send(embed=hint_embed)
            session['hints_shown'].append(3)
            story_sessions[message.channel.id] = session
            print(f"[DEBUG][Elysia] 힌트4 전송 완료")

        # 24턴 도달 시 정답 제출 안내
        if session['turn'] >= 24:
            print(f"[DEBUG][Elysia] 24턴 도달 - 정답 제출 모드로 전환")
            session['awaiting_answer'] = True
            story_sessions[message.channel.id] = session
            answer_embed = discord.Embed(
                title="⏰ Time to Answer!",
                description="It's time! What do you think is the answer? Type your answer in the chat!",
                color=discord.Color.purple()
            )
            await message.channel.send(embed=answer_embed)
            print(f"[DEBUG][Elysia] 정답 제출 안내 전송 완료")
            return

        # 질문-답변 처리
        user_msg = message.content.strip()
        print(f"[DEBUG][Elysia] 사용자 메시지: {user_msg}")

        if any(keyword in user_msg for keyword in answer_keywords):
            reply = random.choice(yes_replies)
            print(f"[DEBUG][Elysia] Yes 답변 선택")
        else:
            reply = random.choice(no_replies)
            print(f"[DEBUG][Elysia] No 답변 선택")

        reply_embed = discord.Embed(
            title="Elysia's Answer",
            description=reply,
            color=discord.Color.teal()
        )
        reply_embed.set_footer(text=f"Turn {session['turn']}/24")
        await message.channel.send(embed=reply_embed)
        story_sessions[message.channel.id] = session
        print(f"[DEBUG][Elysia] 답변 전송 완료 - turn: {session['turn']}")

    except Exception as e:
        print(f"[DEBUG][Elysia] Error in handle_elysia_story: {e}")
        import traceback
        traceback.print_exc()

# --- Eros 전용 스토리 핸들러 ---
async def handle_eros_story(bot: "BotSelector", message, session):
    from config import STORY_CHAPTERS, CHARACTER_INFO
    import random
    chapter_info = get_chapter_info(session['character_name'], session['stage_num'])
    char_info = CHARACTER_INFO[session['character_name']]

    # 챕터1: 카페 손님 응대
    if session["stage_num"] == 1:
        # 첫 메시지(카페 오픈 X)면 인트로/메뉴/첫 손님 안내
        if not session.get("cafe_opened"):
            view = ErosStage1StartView(bot, session)
            intro_embed = create_story_intro_embed("Eros", chapter_info)
            await message.channel.send(embed=intro_embed, view=view)
            return
        # 카페 오픈 후, 첫 손님 안내가 아직 안 됐고, 유저가 아무 메시지(serve 명령이 아니어도) 입력 시 안내
        if session.get("cafe_opened") and not session.get('first_customer_announced'):
            customers = chapter_info.get('customers', [])
            if customers:
                customer = customers[0]
                first_embed = discord.Embed(
                    title=f"👋 {customer['name']} Arrives!",
                    description=customer['personality'],
                    color=discord.Color.blue()
                )
                image_url = CHARACTER_IMAGES["Eros"]
                if 'image_id' in customer:
                    image_url = f"https://imagedelivery.net/ZQ-g2Ke3i84UnMdCSDAkmw/{customer['image_id']}/public"
                first_embed.set_thumbnail(url=image_url)
                drink_name = customer['order'] if isinstance(customer['order'], str) else customer['order'][0]
                first_embed.add_field(name="📋 Order", value=f"**{drink_name}**", inline=False)
                first_embed.set_footer(text=f"Customer 1/{len(customers)} • Use /serve to make the drink!")
                await message.channel.send(embed=first_embed)
                session['first_customer_announced'] = True
                story_sessions[message.channel.id] = session
            return
        # else: 아무것도 하지 않음 (손님 안내 X)
        return

    # 챕터2: 팀원별 음료 서빙 (serve 명령어에서 실제 처리)
    if session["stage_num"] == 2:
        if not session.get("chapter2_started"):
            view = ErosChapter2StartView(bot, session)
            intro_embed = create_story_intro_embed("Eros", chapter_info)
            await message.channel.send(embed=intro_embed, view=view)
            session["chapter2_started"] = True
            story_sessions[message.channel.id] = session
            return
        embed = discord.Embed(
            title="🍯 Gifts for the Team",
            description="Use `/serve_team <character> <drink>` to serve each team member!",
            color=discord.Color.orange()
        )
        embed.set_footer(text="Check the drink menu and preference chart above!")
        await message.channel.send(embed=embed)
        return

    # 챕터3: 탐문/범인찾기
    if session["stage_num"] == 3:
        print(f"[PRINT][EROS][CH3] 진입: turn_count={session.get('turn_count')}, investigation_mode={session.get('investigation_mode')}, is_active={session.get('is_active')}, channel_id={message.channel.id}")
        print(f"[PRINT][EROS][CH3] story_sessions keys: {list(story_sessions.keys())}")
        turn_limit = chapter_info['clear_condition']['turn_limit']
        print(f"[PRINT][EROS][CH3] 선택임베드 체크: turn_count={session['turn_count']}, turn_limit={turn_limit}, is_active={session.get('is_active')}")
        if not session.get("investigation_mode"):
            print(f"[PRINT][EROS][CH3] 인트로 진입: investigation_mode={session.get('investigation_mode')}, turn_count={session.get('turn_count')}")
            view = ErosChapter3IntroView(bot, session)
            intro_embed = create_story_intro_embed("Eros", chapter_info)
            await message.channel.send(embed=intro_embed, view=view)
            session["investigation_mode"] = True
            session["turn_count"] = 0
            story_sessions[message.channel.id] = session
            return
        if session["turn_count"] == turn_limit:
            print(f"[PRINT][EROS][CH3] 선택임베드 분기 진입: turn_count={session['turn_count']}, turn_limit={turn_limit}")
            try:
                view = ErosChapter3CulpritSelectView(bot, session)
                embed = discord.Embed(
                    title="🔍 Time to Choose the Culprit!",
                    description="Eros is desperately waiting for your deduction...\n\n"
                        "Who do you think took the missing gift box?\n"
                        "Select one person below!\n\n"
                        "⚠️ **Be careful—You only have 3 chances!**",
                    color=discord.Color.purple()
                )
                await message.channel.send(embed=embed, view=view)
                print("[PRINT][EROS][CH3] 선택임베드 전송 성공")
            except Exception as e:
                print(f"[PRINT][EROS][CH3] 선택임베드 전송 실패: {e}")
            session["is_active"] = False
            story_sessions[message.channel.id] = session
            return
        if session["turn_count"] > turn_limit:
            print(f"[PRINT][EROS][CH3] turn_count 초과: turn_count={session['turn_count']}, turn_limit={turn_limit}")
            return
        # turn_count 증가를 여기로 이동
        session["turn_count"] = session.get("turn_count", 0) + 1
        print(f"[PRINT][EROS][CH3] AI 답변 분기 진입: turn_count={session['turn_count']}, turn_limit={turn_limit}")
        try:
            async with message.channel.typing():
                system_prompt = chapter_info['prompt']
                messages = [{"role": "system", "content": system_prompt}]
                messages.extend(session.get('history', []))
                messages.append({"role": "user", "content": message.content})
                ai_response_text = await call_openai(messages)
                session['history'].append({"role": "user", "content": message.content})
                session['history'].append({"role": "assistant", "content": ai_response_text})
                embed = discord.Embed(
                    description=f"{ai_response_text}",
                    color=char_info.get('color', discord.Color.blue())
                )
                embed.set_author(name=session['character_name'], icon_url=char_info.get('image_url'))
                embed.set_thumbnail(url=char_info.get('image_url'))
                embed.set_footer(text=f"Turn {session['turn_count']}/{turn_limit}")
                await message.channel.send(embed=embed)
                story_sessions[message.channel.id] = session
        except Exception as e:
            print(f"[PRINT][EROS][CH3] Error generating story response for Eros: {e}")
            await message.channel.send("... (Eros is lost in thought.)")
            return

# --- Handler Map ---
handler_map = {
    "Kagari": handle_kagari_story,
    "Eros": handle_eros_story,
    "Elysia": handle_elysia_story
}

# --- /serve 명령어 처리 함수 ---
async def handle_serve_command(bot, interaction, character, drink):
    """
    에로스 챕터1/2에서 /serve 명령 처리. 재료 입력/음료 이름 모두 지원, 리액션 및 다음 손님 안내 정상화.
    """
    from config import STORY_CHAPTERS, CHARACTER_INFO
    import re
    channel_id = interaction.channel.id
    user_id = interaction.user.id
    session = story_sessions.get(channel_id)
    if not session or session['character_name'] != 'Eros':
        await interaction.response.send_message("This command cannot be used in this channel.", ephemeral=True)
        return
    chapter_info = get_chapter_info('Eros', session['stage_num'])
    customers = chapter_info.get('customers', [])
    menu = chapter_info.get('menu', [])
    current_idx = session.get('current_customer', 0)
    if current_idx >= len(customers):
        await interaction.response.send_message("You have served all customers!", ephemeral=True)
        return
    customer = customers[current_idx]
    # --- 정답 레시피 추출 ---
    if isinstance(customer['order'], list):
        answer_recipe = [i.lower() for i in customer['order']]
    else:
        menu_item = next((m for m in menu if m['name'].lower() == customer['order'].lower()), None)
        answer_recipe = [i.lower() for i in menu_item['recipe']] if menu_item else [customer['order'].lower()]
    # --- 입력값 파싱 (음료 이름 or 재료) ---
    drink_item = next((m for m in menu if m['name'].lower() == drink.lower()), None)
    if drink_item:
        input_ingredients = [i.lower() for i in drink_item['recipe']]
    else:
        # 쉼표(,)만 기준으로 분리 (두 단어 이상 재료 지원)
        input_ingredients = [x.strip().lower() for x in drink.split(',') if x.strip()]
    # --- 정답 체크 ---
    is_correct = set(input_ingredients) == set(answer_recipe)
    # --- 리액션 임베드 ---
    reaction = EROS_CUSTOMER_REACTIONS[current_idx % len(EROS_CUSTOMER_REACTIONS)]
    reaction_text = reaction['success'] if is_correct else reaction['fail']
    reaction_color = discord.Color.green() if is_correct else discord.Color.red()
    reaction_embed = discord.Embed(
        title=f"{customer['name']}'s Reaction",
        description=reaction_text,
        color=reaction_color
    )
    image_url = CHARACTER_IMAGES["Eros"]
    if 'image_id' in customer:
        image_url = f"https://imagedelivery.net/ZQ-g2Ke3i84UnMdCSDAkmw/{customer['image_id']}/public"
    reaction_embed.set_thumbnail(url=image_url)
    # 성공 횟수 카운트
    if 'success_count' not in session:
        session['success_count'] = 0
    if is_correct:
        session['success_count'] += 1
    try:
        await interaction.response.send_message(embed=reaction_embed)
    except Exception:
        await interaction.followup.send(embed=reaction_embed)
    # --- 다음 손님 진행 ---
    session['current_customer'] = current_idx + 1
    story_sessions[channel_id] = session
    await asyncio.sleep(1)
    if session['current_customer'] < len(customers):
        next_customer = customers[session['current_customer']]
        next_embed = discord.Embed(
            title=f"👋 {next_customer['name']} Arrives!",
            description=next_customer['personality'],
            color=discord.Color.blue()
        )
        next_image_url = CHARACTER_IMAGES["Eros"]
        if 'image_id' in next_customer:
            next_image_url = f"https://imagedelivery.net/ZQ-g2Ke3i84UnMdCSDAkmw/{next_customer['image_id']}/public"
        next_embed.set_thumbnail(url=next_image_url)
        drink_name = next_customer['order'] if isinstance(next_customer['order'], str) else next_customer['order'][0]
        next_embed.add_field(name="📋 Order", value=f"**{drink_name}**", inline=False)
        next_embed.set_footer(text=f"Customer {session['current_customer']+1}/{len(customers)} • Use /serve to make the drink!")
        await interaction.followup.send(embed=next_embed)
    else:
        # 모든 손님 완료 후 성공/실패 결과 안내 및 리워드 지급
        if session['success_count'] >= 8:
            from gift_manager import GIFT_RARITY, get_gifts_by_rarity_v2, get_gift_details
            rarity_str = GIFT_RARITY['RARE']
            gift_ids = get_gifts_by_rarity_v2(rarity_str, 2)
            if gift_ids:
                for gift_id in gift_ids:
                    bot.db.add_user_gift(user_id, gift_id, 1)
                gift_names = [get_gift_details(g)['name'] for g in gift_ids if get_gift_details(g)]
                reward_text = f"You have received: **{', '.join(gift_names)}**\nUse the `/inventory` command to check your gifts!"
            else:
                reward_text = "You have received: **No gifts available for this rarity.**\nUse the `/inventory` command to check your gifts!"
            complete_embed = discord.Embed(
                title="☕ Mission Complete!",
                description=f"You have served {session['success_count']} out of {len(customers)} customers successfully!\n{reward_text}\nUse `/story` to continue to Chapter 2!\n\n⏰ This channel will be automatically deleted in 5 seconds.",
                color=discord.Color.gold()
            )
            await interaction.followup.send(embed=complete_embed)
            # --- 챕터1 클리어 기록 및 챕터2 오픈 안내 ---
            bot.db.complete_story_stage(user_id, 'Eros', 1)
            transition_embed = discord.Embed(
                title="🍯 Chapter 2 is now unlocked!",
                description="Congratulations! You have unlocked Chapter 2: Gifts for the Team.\nUse `/story` to start Chapter 2!",
                color=discord.Color.orange()
            )
            await interaction.followup.send(embed=transition_embed)
            session["is_active"] = False
            story_sessions[channel_id] = session
            
            # 5초 후 채널 삭제 (성공)
            import asyncio
            await asyncio.sleep(5)
            try:
                await interaction.channel.delete()
                print(f"[DEBUG][Eros] 챕터1 성공 후 채널 삭제 완료")
            except Exception as e:
                print(f"[DEBUG][Eros] 챕터1 성공 후 채널 삭제 실패: {e}")
        else:
            fail_embed = discord.Embed(
                title="😢 Mission Failed",
                description=f"You only served {session['success_count']} out of {len(customers)} customers successfully.\nTry again to clear Chapter 1!\n\n⏰ This channel will be automatically deleted in 5 seconds.",
                color=discord.Color.red()
            )
            await interaction.followup.send(embed=fail_embed)
            session["is_active"] = False
            story_sessions[channel_id] = session
            
            # 5초 후 채널 삭제 (실패)
            import asyncio
            await asyncio.sleep(5)
            try:
                await interaction.channel.delete()
                print(f"[DEBUG][Eros] 챕터1 실패 후 채널 삭제 완료")
            except Exception as e:
                print(f"[DEBUG][Eros] 챕터1 실패 후 채널 삭제 실패: {e}")