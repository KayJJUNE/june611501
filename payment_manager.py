#!/usr/bin/env python3
"""
Payment Manager for Discord Bot
Discord DM으로 결제 성공 메시지를 보내는 기능을 제공합니다.
"""

import discord
from datetime import datetime
from typing import Optional, Dict, Any
import asyncio

class PaymentManager:
    def __init__(self, bot):
        self.bot = bot
        self.db = None  # 데이터베이스 매니저 참조
        
    def set_database(self, db_manager):
        """데이터베이스 매니저를 설정합니다."""
        self.db = db_manager
    
    async def send_payment_success_dm(self, user_id: int, payment_data: Dict[str, Any]) -> bool:
        """
        결제 성공 시 사용자에게 DM을 보냅니다.
        
        Args:
            user_id (int): 사용자 Discord ID
            payment_data (dict): 결제 정보
                - product_name: 상품명
                - amount: 결제 금액
                - currency: 통화
                - transaction_id: 거래 ID
                - subscription_type: 구독 타입 (예: "Premium", "Starter")
                - duration: 구독 기간
                - features: 제공되는 기능들
        
        Returns:
            bool: DM 전송 성공 여부
        """
        try:
            # 사용자 객체 가져오기
            user = self.bot.get_user(user_id)
            if not user:
                print(f"❌ 사용자를 찾을 수 없습니다: {user_id}")
                return False
            
            # DM 채널 생성 또는 가져오기
            try:
                dm_channel = await user.create_dm()
            except discord.Forbidden:
                print(f"❌ 사용자 {user_id}의 DM을 생성할 수 없습니다 (DM 비활성화)")
                return False
            
            # 결제 성공 임베드 생성
            embed = self._create_payment_success_embed(payment_data)
            
            # DM 전송
            await dm_channel.send(embed=embed)
            
            # 데이터베이스에 결제 기록 저장
            if self.db:
                await self._save_payment_record(user_id, payment_data)
            
            print(f"✅ 결제 성공 DM 전송 완료: {user_id}")
            return True
            
        except Exception as e:
            print(f"❌ 결제 성공 DM 전송 실패: {e}")
            return False
    
    def _create_payment_success_embed(self, payment_data: Dict[str, Any]) -> discord.Embed:
        """결제 성공 임베드를 생성합니다."""
        
        # 기본 정보
        product_name = payment_data.get('product_name', 'Premium Subscription')
        amount = payment_data.get('amount', 0)
        currency = payment_data.get('currency', 'USD')
        subscription_type = payment_data.get('subscription_type', 'Premium')
        duration = payment_data.get('duration', '1 month')
        features = payment_data.get('features', [])
        
        # 임베드 생성
        embed = discord.Embed(
            title="🎉 Welcome to Engage Premium!",
            description=f"**{subscription_type} Access Purchased**",
            color=discord.Color.green(),
            timestamp=datetime.now()
        )
        
        # 상품 정보 추가
        embed.add_field(
            name="📦 Product Details",
            value=f"**{product_name}**\n"
                  f"💰 Amount: ${amount} {currency}\n"
                  f"⏰ Duration: {duration}",
            inline=False
        )
        
        # 제공되는 기능들
        if features:
            features_text = "\n".join([f"• {feature}" for feature in features])
            embed.add_field(
                name="✨ Premium Features",
                value=features_text,
                inline=False
            )
        
        # 추가 안내사항
        embed.add_field(
            name="📋 Next Steps",
            value="• Your premium access has been activated\n"
                  "• Please connect your Discord on Whop to receive role on Engage Discord Server\n"
                  "• Enjoy your premium experience!",
            inline=False
        )
        
        # 푸터
        embed.set_footer(
            text="Thank you for choosing Engage Premium!",
            icon_url=self.bot.user.avatar.url if self.bot.user and self.bot.user.avatar else None
        )
        
        # 썸네일 (선택사항)
        embed.set_thumbnail(url="https://imagedelivery.net/ZQ-g2Ke3i84UnMdCSDAkmw/premium-icon/public")
        
        return embed
    
    async def _save_payment_record(self, user_id: int, payment_data: Dict[str, Any]):
        """결제 기록을 데이터베이스에 저장합니다."""
        try:
            if not self.db:
                return
            
            # 결제 기록 저장
            transaction_id = payment_data.get('transaction_id', f"txn_{user_id}_{int(datetime.now().timestamp())}")
            
            # 데이터베이스에 결제 기록 저장 (실제 구현은 데이터베이스 구조에 따라 달라질 수 있음)
            # 예시: self.db.add_payment_transaction(user_id, transaction_id, payment_data)
            
            print(f"✅ 결제 기록 저장 완료: {user_id} - {transaction_id}")
            
        except Exception as e:
            print(f"❌ 결제 기록 저장 실패: {e}")
    
    async def send_payment_failure_dm(self, user_id: int, error_message: str) -> bool:
        """결제 실패 시 사용자에게 DM을 보냅니다."""
        try:
            user = self.bot.get_user(user_id)
            if not user:
                return False
            
            dm_channel = await user.create_dm()
            
            embed = discord.Embed(
                title="❌ Payment Failed",
                description="We encountered an issue processing your payment.",
                color=discord.Color.red(),
                timestamp=datetime.now()
            )
            
            embed.add_field(
                name="Error Details",
                value=error_message,
                inline=False
            )
            
            embed.add_field(
                name="Need Help?",
                value="Please contact our support team for assistance.",
                inline=False
            )
            
            await dm_channel.send(embed=embed)
            return True
            
        except Exception as e:
            print(f"❌ 결제 실패 DM 전송 실패: {e}")
            return False
    
    async def send_subscription_expiry_warning(self, user_id: int, days_remaining: int) -> bool:
        """구독 만료 경고 DM을 보냅니다."""
        try:
            user = self.bot.get_user(user_id)
            if not user:
                return False
            
            dm_channel = await user.create_dm()
            
            embed = discord.Embed(
                title="⚠️ Subscription Expiring Soon",
                description=f"Your premium subscription will expire in {days_remaining} days.",
                color=discord.Color.orange(),
                timestamp=datetime.now()
            )
            
            embed.add_field(
                name="Renew Now",
                value="Visit our website to renew your subscription and continue enjoying premium features.",
                inline=False
            )
            
            await dm_channel.send(embed=embed)
            return True
            
        except Exception as e:
            print(f"❌ 구독 만료 경고 DM 전송 실패: {e}")
            return False

# 결제 웹훅 처리 클래스
class PaymentWebhookHandler:
    def __init__(self, payment_manager: PaymentManager):
        self.payment_manager = payment_manager
    
    async def handle_payment_webhook(self, webhook_data: Dict[str, Any]) -> bool:
        """
        결제 웹훅을 처리합니다.
        
        Args:
            webhook_data: 웹훅 데이터
                - user_id: 사용자 Discord ID
                - status: 결제 상태 (success, failed, cancelled)
                - payment_data: 결제 정보
        """
        try:
            user_id = webhook_data.get('user_id')
            status = webhook_data.get('status')
            payment_data = webhook_data.get('payment_data', {})
            
            if not user_id:
                print("❌ 웹훅에 user_id가 없습니다.")
                return False
            
            if status == 'success':
                return await self.payment_manager.send_payment_success_dm(user_id, payment_data)
            elif status == 'failed':
                error_message = webhook_data.get('error_message', 'Unknown error')
                return await self.payment_manager.send_payment_failure_dm(user_id, error_message)
            else:
                print(f"❌ 알 수 없는 결제 상태: {status}")
                return False
                
        except Exception as e:
            print(f"❌ 웹훅 처리 실패: {e}")
            return False

# 사용 예시 함수들
async def example_payment_success(bot, user_id: int):
    """결제 성공 예시"""
    payment_manager = PaymentManager(bot)
    
    payment_data = {
        'product_name': 'Engage Starter',
        'amount': 9.99,
        'currency': 'USD',
        'subscription_type': 'Starter',
        'duration': '1 month',
        'transaction_id': f'txn_{user_id}_{int(datetime.now().timestamp())}',
        'features': [
            'Unlimited messages',
            'Premium characters access',
            'Priority support',
            'Exclusive content'
        ]
    }
    
    success = await payment_manager.send_payment_success_dm(user_id, payment_data)
    return success

async def example_payment_failure(bot, user_id: int):
    """결제 실패 예시"""
    payment_manager = PaymentManager(bot)
    
    error_message = "Insufficient funds. Please check your payment method."
    success = await payment_manager.send_payment_failure_dm(user_id, error_message)
    return success
