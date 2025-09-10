#!/usr/bin/env python3
"""
데이터베이스 마이그레이션 스크립트
기존 데이터베이스에 is_daily_message 컬럼을 추가합니다.
"""

import os
import sys
from init_db import migrate_database

def main():
    print("🔄 데이터베이스 마이그레이션을 시작합니다...")
    print("=" * 50)
    
    try:
        migrate_database()
        print("=" * 50)
        print("✅ 마이그레이션이 성공적으로 완료되었습니다!")
        print("이제 새로운 메시지 시스템을 사용할 수 있습니다.")
    except Exception as e:
        print("=" * 50)
        print(f"❌ 마이그레이션 중 오류가 발생했습니다: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
