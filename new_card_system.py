# 새로운 카드 시스템 - 각 캐릭터당 65장 (S 5장, A 10장, B 20장, C 30장)
# 총 195장의 카드

def generate_new_card_system():
    """새로운 카드 시스템 생성"""
    
    # 기본 이미지 URL 패턴
    base_url = "https://imagedelivery.net/ZQ-g2Ke3i84UnMdCSDAkmw"
    
    # 각 캐릭터별 카드 생성
    characters = ["Kagari", "Eros", "Elysia"]
    character_prefixes = {"Kagari": "kagari", "Eros": "eros", "Elysia": "elysia"}
    
    new_card_system = {}
    
    for char in characters:
        prefix = character_prefixes[char]
        char_cards = {}
        
        # S 티어 카드 (5장)
        for i in range(1, 6):
            card_id = f"{prefix}s{i}"
            char_cards[card_id] = {
                "image_path": f"{base_url}/{card_id}/public",
                "description": f"{char}'s S{i} Card",
                "tier": "S"
            }
        
        # A 티어 카드 (10장)
        for i in range(1, 11):
            card_id = f"{prefix}a{i}"
            char_cards[card_id] = {
                "image_path": f"{base_url}/{card_id}/public",
                "description": f"{char}'s A{i} Card",
                "tier": "A"
            }
        
        # B 티어 카드 (20장)
        for i in range(1, 21):
            card_id = f"{prefix}b{i}"
            char_cards[card_id] = {
                "image_path": f"{base_url}/{card_id}/public",
                "description": f"{char}'s B{i} Card",
                "tier": "B"
            }
        
        # C 티어 카드 (30장)
        for i in range(1, 31):
            card_id = f"{prefix}c{i}"
            char_cards[card_id] = {
                "image_path": f"{base_url}/{card_id}/public",
                "description": f"{char}'s C{i} Card",
                "tier": "C"
            }
        
        # 배너 이미지
        char_cards["banner_image"] = f"{base_url}/{prefix}_banner/public"
        
        new_card_system[char] = char_cards
    
    return new_card_system

# 새로운 카드 시스템 생성
NEW_CHARACTER_CARD_INFO = generate_new_card_system()

# 카드 개수 확인
def verify_card_counts():
    """카드 개수 검증"""
    for char, cards in NEW_CHARACTER_CARD_INFO.items():
        if char == "banner_image":
            continue
            
        s_count = len([c for c in cards.keys() if c.startswith(f"{char.lower()}s")])
        a_count = len([c for c in cards.keys() if c.startswith(f"{char.lower()}a")])
        b_count = len([c for c in cards.keys() if c.startswith(f"{char.lower()}b")])
        c_count = len([c for c in cards.keys() if c.startswith(f"{char.lower()}c")])
        total = s_count + a_count + b_count + c_count
        
        print(f"{char}: S={s_count}, A={a_count}, B={b_count}, C={c_count}, Total={total}")
    
    print(f"\n총 카드 수: {sum(len([c for c in cards.keys() if not c.startswith('banner')]) for char, cards in NEW_CHARACTER_CARD_INFO.items())}")

if __name__ == "__main__":
    verify_card_counts()
