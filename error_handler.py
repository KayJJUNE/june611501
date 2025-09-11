import logging
import traceback
import asyncio
from datetime import datetime
import discord
from discord.ext import commands
import os

# 로깅 설정
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('bot_errors.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

class ErrorHandler:
    def __init__(self, bot):
        self.bot = bot
        self.error_count = {}
        self.critical_errors = []
        
    async def log_error(self, error, context=""):
        """에러를 로그에 기록합니다."""
        error_msg = f"Error in {context}: {str(error)}"
        logger.error(error_msg)
        logger.error(traceback.format_exc())
        
        # 에러 카운트 증가
        error_type = type(error).__name__
        self.error_count[error_type] = self.error_count.get(error_type, 0) + 1
        
        # 크리티컬 에러인지 확인
        if self.is_critical_error(error):
            self.critical_errors.append({
                'timestamp': datetime.now(),
                'error': str(error),
                'context': context,
                'traceback': traceback.format_exc()
            })
            
            # 관리자에게 알림
            await self.notify_admin_critical_error(error, context)
    
    def is_critical_error(self, error):
        """크리티컬 에러인지 판단합니다."""
        critical_errors = [
            'ConnectionError',
            'DatabaseError',
            'MemoryError',
            'TimeoutError',
            'DiscordException',
            'HTTPException'
        ]
        return type(error).__name__ in critical_errors
    
    async def notify_admin_critical_error(self, error, context):
        """관리자에게 크리티컬 에러 알림을 보냅니다."""
        try:
            # 관리자 ID (실제 관리자 ID로 변경)
            admin_id = 534941503345262613
            
            admin = self.bot.get_user(admin_id)
            if admin:
                embed = discord.Embed(
                    title="🚨 Critical Error Alert",
                    description=f"**Error Type:** {type(error).__name__}\n**Context:** {context}\n**Time:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
                    color=discord.Color.red()
                )
                embed.add_field(
                    name="Error Details",
                    value=f"```{str(error)[:1000]}```",
                    inline=False
                )
                
                await admin.send(embed=embed)
        except Exception as e:
            logger.error(f"Failed to notify admin: {e}")
    
    def get_error_stats(self):
        """에러 통계를 반환합니다."""
        return {
            'total_errors': sum(self.error_count.values()),
            'error_types': self.error_count,
            'critical_errors_count': len(self.critical_errors),
            'recent_critical_errors': self.critical_errors[-5:] if self.critical_errors else []
        }
    
    def get_detailed_error_analysis(self):
        """상세한 에러 분석을 반환합니다."""
        # 에러 로그 파일에서 최근 에러들 분석
        try:
            if os.path.exists('bot_errors.log'):
                with open('bot_errors.log', 'r', encoding='utf-8') as f:
                    lines = f.readlines()
                    recent_errors = lines[-50:] if len(lines) > 50 else lines
                    
                # 에러 패턴 분석
                error_patterns = {}
                for line in recent_errors:
                    if 'ERROR' in line:
                        # 에러 타입 추출
                        if 'ConnectionError' in line:
                            error_patterns['ConnectionError'] = error_patterns.get('ConnectionError', 0) + 1
                        elif 'DatabaseError' in line:
                            error_patterns['DatabaseError'] = error_patterns.get('DatabaseError', 0) + 1
                        elif 'TimeoutError' in line:
                            error_patterns['TimeoutError'] = error_patterns.get('TimeoutError', 0) + 1
                        elif 'DiscordException' in line:
                            error_patterns['DiscordException'] = error_patterns.get('DiscordException', 0) + 1
                        else:
                            error_patterns['Other'] = error_patterns.get('Other', 0) + 1
                
                return {
                    'recent_error_patterns': error_patterns,
                    'total_recent_errors': len([line for line in recent_errors if 'ERROR' in line]),
                    'log_file_exists': True
                }
        except Exception as e:
            return {
                'recent_error_patterns': {},
                'total_recent_errors': 0,
                'log_file_exists': False,
                'log_error': str(e)
            }
    
    async def health_check(self):
        """봇의 상태를 확인합니다."""
        try:
            # 데이터베이스 연결 확인
            # 메모리 사용량 확인
            # 디스코드 연결 상태 확인
            
            health_status = {
                'bot_latency': self.bot.latency,
                'guild_count': len(self.bot.guilds),
                'user_count': len(self.bot.users),
                'error_count': sum(self.error_count.values()),
                'uptime': datetime.now() - self.bot.start_time if hasattr(self.bot, 'start_time') else None
            }
            
            return health_status
        except Exception as e:
            logger.error(f"Health check failed: {e}")
            return {'status': 'unhealthy', 'error': str(e)}

# 전역 에러 핸들러 데코레이터
def handle_errors(func):
    """함수 실행 중 에러를 처리하는 데코레이터"""
    async def wrapper(*args, **kwargs):
        try:
            return await func(*args, **kwargs)
        except Exception as e:
            # 에러 핸들러가 있다면 사용
            if hasattr(wrapper, 'error_handler'):
                await wrapper.error_handler.log_error(e, func.__name__)
            else:
                logger.error(f"Unhandled error in {func.__name__}: {e}")
            raise
    return wrapper
