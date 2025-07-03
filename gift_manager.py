# gift_manager.py
from typing import Dict, Any, List
import random

# Gift Rarity Definition
GIFT_RARITY = {
    "COMMON": "Common",
    "RARE": "Rare",
    "EPIC": "Epic",
}

# Detailed information for all gifts
ALL_GIFTS: Dict[str, Dict[str, Any]] = {
    # Elysia's Gifts
    "yarn_ball": {"name": "Ball of Yarn", "rarity": GIFT_RARITY["COMMON"], "description": "Roll, roll... it stimulates Elysia's instincts."},
    "bottle_cap": {"name": "Bottle Cap", "rarity": GIFT_RARITY["COMMON"], "description": "The best toy for a cat who loves shiny things."},
    "plastic_bag": {"name": "Plastic Bag", "rarity": GIFT_RARITY["COMMON"], "description": "The crinkling sound is irresistible!"},
    "fur_pom_pom": {"name": "Fur Pom-Pom", "rarity": GIFT_RARITY["RARE"], "description": "A fluffy ball of fur with a pleasant, soft touch."},
    "doll": {"name": "Cute Doll", "rarity": GIFT_RARITY["RARE"], "description": "Sleeping with it might bring sweet dreams."},
    "salmon_treat": {"name": "Salmon Treat", "rarity": GIFT_RARITY["EPIC"], "description": "A special treat that Elysia absolutely loves."},
    "shaped_sugar_cube": {"name": "Noah Island Sugar Cube", "rarity": GIFT_RARITY["COMMON"], "description": "A heart-shaped sugar cube to sweeten her coffee. A small but delightful gesture."},
    "golden_honey_pendant": {"name": "Golden Honey Pendant", "rarity": GIFT_RARITY["EPIC"], "description": "A beautiful pendant shaped like a drop of golden honey. It shines with a warm, inviting light."},

    # Eros's Gifts
    "honey_jar": {"name": "Honey Jar", "rarity": GIFT_RARITY["COMMON"], "description": "Sweet honey is a source of vitality for Eros."},
    "rose": {"name": "Single Rose", "rarity": GIFT_RARITY["COMMON"], "description": "A fragrant flower that brings joy to the heart."},
    "mini_espresso_cup": {"name": "Mini Espresso Cup", "rarity": GIFT_RARITY["RARE"], "description": "Drinking coffee from a small, cute cup doubles the joy."},
    "honeycomb_chocolate": {"name": "Honeycomb Chocolate", "rarity": GIFT_RARITY["RARE"], "description": "A special chocolate that combines sweetness and crunch."},
    "bee_brooch": {"name": "Bee Brooch", "rarity": GIFT_RARITY["EPIC"], "description": "A cute brooch that represents Eros's identity."},
    "pocket_watch": {"name": "Pocket Watch", "rarity": GIFT_RARITY["EPIC"], "description": "An elegant watch that lets you feel the flow of time."},
    "pressed_flower_bookmark": {"name": "Pressed Flower Bookmark", "rarity": GIFT_RARITY["COMMON"], "description": "A delicate bookmark made from carefully pressed flowers. It's perfect for marking a page in her favorite book."},
    "writing_brush": {"name": "Ink Wash Brush", "rarity": GIFT_RARITY["COMMON"], "description": "A simple but elegant brush for calligraphy or ink wash painting. It encourages a moment of focus and artistry."},

    # Kagari's Gifts
    "tea_bag_collection": {"name": "Tea Bag Collection", "rarity": GIFT_RARITY["COMMON"], "description": "Contains various types of tea for a serene tea time."},
    "antique_teacup": {"name": "Antique Teacup", "rarity": GIFT_RARITY["RARE"], "description": "A beautiful teacup that seems to hold stories from ages past."},
    "hand_knit_scraf": {"name": "Hand-Knit Scarf", "rarity": GIFT_RARITY["RARE"], "description": "A cozy scarf filled with a warm heart."},
    "incense_burner": {"name": "Ceramic Incense Burner", "rarity": GIFT_RARITY["EPIC"], "description": "Emits a gentle fragrance that calms the mind."}
}

# Character-specific gift data and reactions
CHARACTER_GIFT_REACTIONS: Dict[str, Dict[str, Any]] = {
    "Elysia": {
        "preferred_gifts": ["yarn_ball", "bottle_cap", "plastic_bag", "fur_pom_pom", "doll", "salmon_treat"],
        "reactions": {
            "yarn_ball": "Oh, a ball of yarn! *purr* You know me so well—I can't wait to chase it all around!",
            "bottle_cap": "A bottle cap? Haha, it's the perfect size for batting under the sofa. Thank you—I'll treasure it!",
            "plastic_bag": "A crinkly plastic bag! The rustle is so fun… Let's play hide-and-seek inside together!",
            "fur_pom_pom": "A soft fur pom-pom! *kneads* Your gift feels like a cozy nap in the sun—just purr-fect.",
            "doll": "Such a cute doll… I'll curl up next to it and pretend it's my tiny companion. Thank you!",
            "salmon_treat": "Salmon! My favorite snack—your timing is impeccable. *licks lips* Let's enjoy this together!",
        },
        "mismatch_response": "Nya....?? Thank you for the gift… , I'm not sure why you gave this to me. But, well… thanks, I guess!"
    },
    "Eros": {
        "preferred_gifts": ["honey_jar", "rose", "mini_espresso_cup", "honeycomb_chocolate", "bee_brooch", "shaped_sugar_cube", "golden_honey_pendant"],
        "reactions": {
            "honey_jar": "Pure honey! *eyes sparkle* This will make my drinks extra sweet—thank you for the thoughtful treat!",
            "rose": "A single rose… Its scent is heavenly. You've brightened my day just like a perfect latte art.",
            "mini_espresso_cup": "These tiny cups are adorable! I can't wait to brew a mini espresso just for us—cheers to you!",
            "honeycomb_chocolate": "Honeycomb chocolate?! This crunchy sweetness is divine… You always know how to spoil me.",
            "bee_brooch": "A bee brooch! How cute and fitting. I'll pin it on my apron with pride—thank you for this sweet accessory.",
            "shaped_sugar_cube": "A heart-shaped sugar cube! It's almost too cute to dissolve. I'll save it for a special cup of coffee.",
            "golden_honey_pendant": "Oh, it's beautiful... It glows just like a drop of morning honey. I'll wear it close to my heart, thank you!"
        },
        "mismatch_response": "Thanks for the gift… I'm a bit puzzled why you picked this for me. Either way, thank you."
    },
    "Kagari": {
        "preferred_gifts": ["tea_bag_collection", "antique_teacup", "hand_knit_scraf", "incense_burner", "pocket_watch", "pressed_flower_bookmark", "writing_brush"],
        "reactions": {
            "tea_bag_collection": "Noah Island tea… The aromas bring back memories of home. Thank you for such a thoughtful selection.",
            "antique_teacup": "An antique teacup set—its craftsmanship is exquisite. I'll treasure each cup as I savor my tea.",
            "hand_knit_scraf": "This scarf is so warm and soft… I can feel the care in every stitch. Thank you for wrapping me in comfort.",
            "incense_burner": "A delicate incense burner… The rising smoke and scent create such tranquility. You've given me serenity.",
            "pocket_watch": "A vintage pocket watch—its ticking reminds me of timeless memories. I'll keep it close, always.",
            "pressed_flower_bookmark": "A pressed flower... It's lovely. I'll use it to mark the pages of the story we're reading together.",
            "writing_brush": "An ink brush... How thoughtful. Perhaps I can use it to write down a poem that reminds me of this moment."
        },
        "mismatch_response": "I appreciate the gift… though I don't quite understand why you chose it. In any case, thank you."
    }
}

def get_gift_details(gift_id: str) -> Dict[str, Any]:
    """Retrieves detailed information for a gift by its ID."""
    return ALL_GIFTS.get(gift_id)

def get_random_gift_for_character(character_name: str) -> tuple[str, str]:
    """Selects and returns the ID and name of a random gift from a character's preferred list."""
    preferred = CHARACTER_GIFT_REACTIONS.get(character_name, {}).get("preferred_gifts")
    if preferred:
        gift_id = random.choice(preferred)
        gift_details = get_gift_details(gift_id)
        gift_name = gift_details.get("name", "Unknown Gift") if gift_details else "Unknown Gift"
        return gift_id, gift_name
    return None, None

def get_random_gift_from_all() -> str:
    """Selects and returns the ID of a random gift from the entire gift list."""
    all_gift_ids = list(ALL_GIFTS.keys())
    if all_gift_ids:
        return random.choice(all_gift_ids)
    return None

def check_gift_preference(character_name: str, gift_id: str) -> bool:
    """Checks if a gift is on the character's preferred list."""
    return gift_id in CHARACTER_GIFT_REACTIONS.get(character_name, {}).get("preferred_gifts", [])

def get_gift_reaction(character_name: str, gift_id: str) -> str:
    """
    Fetches the character's reaction for a gift.
    Returns the mismatch response if the gift is not preferred.
    """
    char_data = CHARACTER_GIFT_REACTIONS.get(character_name)
    if not char_data:
        return "..."

    if check_gift_preference(character_name, gift_id):
        return char_data["reactions"].get(gift_id, "Thank you.")
    else:
        return char_data["mismatch_response"]

def get_gift_emoji(gift_id: str) -> str:
    """Returns an emoji corresponding to the gift ID."""
    # This is a simple mapping. It would be better to add an 'emoji' field to ALL_GIFTS.
    emoji_map = {
        "yarn_ball": "🧶", "bottle_cap": "🍾", "plastic_bag": "🛍️", "fur_pom_pom": "🐾", "doll": "🧸", "salmon_treat": "🍣",
        "honey_jar": "🍯", "rose": "🌹", "mini_espresso_cup": "☕", "honeycomb_chocolate": "🍫", "bee_brooch": "🐝", "shaped_sugar_cube": "🍬", "golden_honey_pendant": "💖",
        "tea_bag_collection": "🫖", "antique_teacup": "🍵", "hand_knit_scraf": "🧣", "incense_burner": "♨️", "pocket_watch": "⏱️", "pressed_flower_bookmark": "🔖", "writing_brush": "🖌️"
    }
    return emoji_map.get(gift_id, "🎁")

def get_random_gift_by_rarity(rarity: str) -> str:
    """특정 등급의 랜덤 아이템을 반환합니다."""
    matching_gifts = [gift_id for gift_id, details in ALL_GIFTS.items() 
                     if details.get('rarity') == rarity]
    return random.choice(matching_gifts) if matching_gifts else None

def get_gifts_by_rarity_v2(rarity: str, count: int = 1) -> list[str]:
    """특정 등급의 랜덤 아이템들을 반환합니다."""
    matching_gifts = [gift_id for gift_id, details in ALL_GIFTS.items() 
                     if details.get('rarity') == rarity]
    return random.sample(matching_gifts, min(count, len(matching_gifts))) if matching_gifts else [] 