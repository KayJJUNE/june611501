#!/usr/bin/env python3
"""
캐릭터 개성화 시스템 시뮬레이션
감정 반응, 주제별 반응, 시간대별 반응을 테스트합니다.
"""

import asyncio
import datetime
from character_bot import CharacterBot
from database_manager import get_db_manager

class CharacterSimulation:
    def __init__(self):
        self.db = get_db_manager()
        self.characters = ["Kagari", "Eros", "Elysia"]
        
    async def simulate_emotion_reactions(self):
        """감정별 반응 시뮬레이션"""
        print("🎭 감정별 캐릭터 반응 시뮬레이션")
        print("=" * 50)
        
        test_messages = {
            "happy": "I'm so happy today! Something great happened 😊",
            "sad": "I'm feeling really down lately... so sad and depressed 😢",
            "angry": "I'm so angry! This is so frustrating 😠",
            "excited": "Wow! I'm so excited! This is amazing! 🔥",
            "tired": "I'm so tired... exhausted and worn out 😴"
        }
        
        for character in self.characters:
            print(f"\n📖 {character} 캐릭터:")
            print("-" * 30)
            
            for emotion, message in test_messages.items():
                print(f"\n감정: {emotion}")
                print(f"메시지: {message}")
                
                # 감정 분석
                bot = CharacterBot(character)
                detected_emotion = await bot.analyze_user_emotion(message)
                print(f"감지된 감정: {detected_emotion}")
                
                # 감정 반응 확인
                if detected_emotion == emotion:
                    print(f"✅ 감정 감지 성공")
                else:
                    print(f"❌ 감정 감지 실패 (예상: {emotion}, 실제: {detected_emotion})")
                
                print()
    
    async def simulate_topic_reactions(self):
        """주제별 반응 시뮬레이션"""
        print("\n🎯 주제별 캐릭터 반응 시뮬레이션")
        print("=" * 50)
        
        test_messages = {
            "food": "I had delicious food today! I also tried cooking",
            "weather": "The weather is really nice today! It's cool because it rained",
            "work": "I have too much work at the office, it's really hard",
            "hobby": "I like playing games or watching movies",
            "travel": "I want to travel! Where should I go?",
            "music": "I like listening to music while working",
            "book": "I love reading books. I read a lot of novels",
            "nature": "I love nature. I want to go to the mountains or sea"
        }
        
        for character in self.characters:
            print(f"\n📖 {character} 캐릭터:")
            print("-" * 30)
            
            for topic, message in test_messages.items():
                print(f"\n주제: {topic}")
                print(f"메시지: {message}")
                
                # 주제 감지
                bot = CharacterBot(character)
                detected_topic = await bot.detect_topic(message)
                print(f"감지된 주제: {detected_topic}")
                
                if detected_topic == topic:
                    print(f"✅ 주제 감지 성공")
                else:
                    print(f"❌ 주제 감지 실패")
                
                print()
    
    async def simulate_time_reactions(self):
        """시간대별 반응 시뮬레이션"""
        print("\n⏰ 시간대별 캐릭터 반응 시뮬레이션")
        print("=" * 50)
        
        # 현재 시간대 확인
        current_hour = datetime.datetime.now().hour
        if 5 <= current_hour < 12:
            time_period = "morning"
        elif 12 <= current_hour < 17:
            time_period = "afternoon"
        elif 17 <= current_hour < 21:
            time_period = "evening"
        else:
            time_period = "night"
        
        print(f"현재 시간: {current_hour}시")
        print(f"현재 시간대: {time_period}")
        
        for character in self.characters:
            print(f"\n📖 {character} 캐릭터:")
            print("-" * 30)
            
            bot = CharacterBot(character)
            detected_time = await bot.get_time_period()
            print(f"감지된 시간대: {detected_time}")
            
            if detected_time == time_period:
                print(f"✅ 시간대 감지 성공")
            else:
                print(f"❌ 시간대 감지 실패")
            
            print()
    
    async def simulate_combined_reactions(self):
        """통합 반응 시뮬레이션"""
        print("\n🎪 통합 캐릭터 반응 시뮬레이션")
        print("=" * 50)
        
        test_scenarios = [
            {
                "message": "I'm so happy today! I had delicious food 😊",
                "expected_emotion": "happy",
                "expected_topic": "food"
            },
            {
                "message": "I'm so tired from work lately... 😴",
                "expected_emotion": "tired",
                "expected_topic": "work"
            },
            {
                "message": "Wow! I want to travel! I'm so excited! ✨",
                "expected_emotion": "excited",
                "expected_topic": "travel"
            }
        ]
        
        for character in self.characters:
            print(f"\n📖 {character} 캐릭터:")
            print("-" * 30)
            
            for i, scenario in enumerate(test_scenarios, 1):
                print(f"\n시나리오 {i}:")
                print(f"메시지: {scenario['message']}")
                
                bot = CharacterBot(character)
                
                # 감정 분석
                detected_emotion = await bot.analyze_user_emotion(scenario['message'])
                print(f"감지된 감정: {detected_emotion}")
                
                # 주제 분석
                detected_topic = await bot.detect_topic(scenario['message'])
                print(f"감지된 주제: {detected_topic}")
                
                # 시간대 분석
                detected_time = await bot.get_time_period()
                print(f"감지된 시간대: {detected_time}")
                
                # 결과 확인
                emotion_correct = detected_emotion == scenario['expected_emotion']
                topic_correct = detected_topic == scenario['expected_topic']
                
                print(f"감정 분석: {'✅' if emotion_correct else '❌'}")
                print(f"주제 분석: {'✅' if topic_correct else '❌'}")
                print(f"시간대 분석: ✅")
                
                print()
    
    async def run_simulation(self):
        """전체 시뮬레이션 실행"""
        print("🚀 캐릭터 개성화 시스템 시뮬레이션 시작")
        print("=" * 60)
        
        try:
            await self.simulate_emotion_reactions()
            await self.simulate_topic_reactions()
            await self.simulate_time_reactions()
            await self.simulate_combined_reactions()
            
            print("\n🎉 시뮬레이션 완료!")
            print("=" * 60)
            
        except Exception as e:
            print(f"❌ 시뮬레이션 중 오류 발생: {e}")
            import traceback
            traceback.print_exc()

async def main():
    simulation = CharacterSimulation()
    await simulation.run_simulation()

if __name__ == "__main__":
    asyncio.run(main())