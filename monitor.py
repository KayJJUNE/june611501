import asyncio
import psutil
import time
from datetime import datetime, timedelta
import discord
from collections import defaultdict
import logging

logger = logging.getLogger(__name__)

class BotMonitor:
    def __init__(self, bot):
        self.bot = bot
        self.start_time = datetime.now()
        self.metrics = {
            'messages_processed': 0,
            'commands_executed': 0,
            'errors_occurred': 0,
            'users_active': set(),
            'guilds_active': set()
        }
        self.alert_thresholds = {
            'memory_usage': 80,  # 80% 이상
            'cpu_usage': 90,     # 90% 이상
            'error_rate': 10,    # 10% 이상
            'response_time': 5.0  # 5초 이상
        }
        self.alerts_sent = defaultdict(bool)
        
    async def start_monitoring(self):
        """모니터링을 시작합니다."""
        while True:
            try:
                await self.check_system_health()
                await self.check_bot_health()
                await asyncio.sleep(60)  # 1분마다 체크
            except Exception as e:
                logger.error(f"Monitoring error: {e}")
                await asyncio.sleep(60)
    
    async def check_system_health(self):
        """시스템 상태를 확인합니다."""
        try:
            # 메모리 사용량
            memory_percent = psutil.virtual_memory().percent
            if memory_percent > self.alert_thresholds['memory_usage']:
                await self.send_alert("High Memory Usage", f"Memory usage: {memory_percent}%")
            
            # CPU 사용량
            cpu_percent = psutil.cpu_percent(interval=1)
            if cpu_percent > self.alert_thresholds['cpu_usage']:
                await self.send_alert("High CPU Usage", f"CPU usage: {cpu_percent}%")
                
        except Exception as e:
            logger.error(f"System health check failed: {e}")
    
    async def check_bot_health(self):
        """봇 상태를 확인합니다."""
        try:
            # 봇 지연시간
            latency = self.bot.latency
            if latency > self.alert_thresholds['response_time']:
                await self.send_alert("High Bot Latency", f"Latency: {latency:.2f}s")
            
            # 에러율 계산
            total_operations = self.metrics['messages_processed'] + self.metrics['commands_executed']
            if total_operations > 0:
                error_rate = (self.metrics['errors_occurred'] / total_operations) * 100
                if error_rate > self.alert_thresholds['error_rate']:
                    await self.send_alert("High Error Rate", f"Error rate: {error_rate:.2f}%")
                    
        except Exception as e:
            logger.error(f"Bot health check failed: {e}")
    
    async def send_alert(self, title: str, message: str):
        """관리자에게 알림을 보냅니다."""
        try:
            # 중복 알림 방지 (1시간 내 같은 알림은 1번만)
            alert_key = f"{title}_{datetime.now().hour}"
            if self.alerts_sent[alert_key]:
                return
                
            admin_id = 534941503345262613  # 실제 관리자 ID로 변경
            admin = self.bot.get_user(admin_id)
            
            if admin:
                embed = discord.Embed(
                    title=f"⚠️ {title}",
                    description=message,
                    color=discord.Color.orange(),
                    timestamp=datetime.now()
                )
                embed.add_field(
                    name="Bot Status",
                    value=f"Uptime: {datetime.now() - self.start_time}",
                    inline=False
                )
                
                await admin.send(embed=embed)
                self.alerts_sent[alert_key] = True
                
        except Exception as e:
            logger.error(f"Failed to send alert: {e}")
    
    def record_message(self, user_id: int, guild_id: int):
        """메시지 처리를 기록합니다."""
        self.metrics['messages_processed'] += 1
        self.metrics['users_active'].add(user_id)
        self.metrics['guilds_active'].add(guild_id)
    
    def record_command(self, command_name: str):
        """명령어 실행을 기록합니다."""
        self.metrics['commands_executed'] += 1
    
    def record_error(self, error_type: str):
        """에러 발생을 기록합니다."""
        self.metrics['errors_occurred'] += 1
    
    def get_status_report(self) -> dict:
        """상태 리포트를 반환합니다."""
        uptime = datetime.now() - self.start_time
        
        return {
            'uptime': str(uptime),
            'messages_processed': self.metrics['messages_processed'],
            'commands_executed': self.metrics['commands_executed'],
            'errors_occurred': self.metrics['errors_occurred'],
            'active_users': len(self.metrics['users_active']),
            'active_guilds': len(self.metrics['guilds_active']),
            'error_rate': (self.metrics['errors_occurred'] / max(1, self.metrics['messages_processed'] + self.metrics['commands_executed'])) * 100,
            'memory_usage': psutil.virtual_memory().percent,
            'cpu_usage': psutil.cpu_percent(),
            'bot_latency': self.bot.latency
        }
    
    async def reset_daily_metrics(self):
        """일일 메트릭을 리셋합니다."""
        # 매일 자정에 실행
        self.metrics['messages_processed'] = 0
        self.metrics['commands_executed'] = 0
        self.metrics['errors_occurred'] = 0
        self.metrics['users_active'].clear()
        self.metrics['guilds_active'].clear()
        self.alerts_sent.clear()
