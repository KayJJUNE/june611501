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
from vision_manager import VisionManager

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

        # Load cogs
        print("Loading inventory_commands cog...")
        await selector_bot.load_extension("inventory_commands")
        print("inventory_commands cog loaded.")

        # Sync command tree
        await selector_bot.tree.sync()
        print("Command tree synced.")

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

async def call_openai(prompt):
    # 실제 OpenAI API 연동 코드로 대체 필요
    return "0"  # 임시로 항상 0 반환

if __name__ == "__main__":
    asyncio.run(run_all_bots())