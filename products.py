import json
import os
from typing import Dict, Any, Optional
from datetime import datetime, timedelta

class ProductManager:
    def __init__(self):
        self.products_file = "products.json"
        self.products = self.load_products()
    
    def load_products(self) -> Dict[str, Any]:
        """상품 정보를 로드합니다."""
        try:
            if os.path.exists(self.products_file):
                with open(self.products_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    return data.get('products', {})
            return {}
        except Exception as e:
            print(f"Error loading products: {e}")
            return {}
    
    def get_product(self, product_id: str) -> Optional[Dict[str, Any]]:
        """Look up product information by product ID.."""
        return self.products.get(product_id)
    
    def get_all_products(self) -> Dict[str, Any]:
        """Returns all product information.."""
        return self.products
    
    def process_product_delivery(self, user_id: int, product_id: str, db) -> bool:
        """상품 지급을 처리합니다."""
        product = self.get_product(product_id)
        if not product:
            print(f"Product {product_id} not found")
            return False
        
        try:
            rewards = product.get('rewards', {})
            product_type = product.get('type')
            
            # 일회성 상품의 메시지 지급
            if product_type == 'one_time' and 'messages' in rewards:
                message_count = rewards['messages']
                if message_count > 0:
                    db.add_user_messages(user_id, message_count)
                    print(f"Added {message_count} messages to user {user_id}")
            
            # 구독 상품의 기프트 지급 (일회성)
            if product_type == 'subscription' and 'gifts' in rewards:
                gift_count = rewards['gifts']
                for _ in range(gift_count):
                    # 랜덤 기프트 지급 (모든 캐릭터에서)
                    gift_name = db.add_random_gift_to_user(user_id, "Kagari")
                    if not gift_name:
                        gift_name = db.add_random_gift_to_user(user_id, "Eros")
                    if not gift_name:
                        gift_name = db.add_random_gift_to_user(user_id, "Elysia")
                    print(f"Added subscription gift to user {user_id}")
            
            # 일회성 상품의 기프트 지급
            if product_type == 'one_time' and 'gifts' in rewards:
                gift_count = rewards['gifts']
                for _ in range(gift_count):
                    # 랜덤 기프트 지급 (모든 캐릭터에서)
                    gift_name = db.add_random_gift_to_user(user_id, "Kagari")
                    if not gift_name:
                        gift_name = db.add_random_gift_to_user(user_id, "Eros")
                    if not gift_name:
                        gift_name = db.add_random_gift_to_user(user_id, "Elysia")
                    print(f"Added random gift to user {user_id}")
            
            # 구독 처리
            if product_type == 'subscription':
                duration_days = product.get('duration_days', 30)
                db.add_user_subscription(user_id, product_id, duration_days)
                print(f"Added subscription {product_id} for {duration_days} days to user {user_id}")
                
                # 구독 시작 시 즉시 일일 보상 지급
                db.process_daily_subscription_rewards(user_id)
                print(f"Processed initial daily subscription rewards for user {user_id}")
            
            return True
            
        except Exception as e:
            print(f"Error processing product delivery: {e}")
            return False

# 전역 인스턴스
product_manager = ProductManager()
