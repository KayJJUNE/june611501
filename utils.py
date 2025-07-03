from config import AFFINITY_THRESHOLDS

def get_affinity_grade(emotion_score: int) -> str:
    """친밀도 점수에 따라 등급을 반환합니다."""
    # 내림차순으로 정렬된 등급 임계값 순회
    for threshold, grade_info in sorted(AFFINITY_THRESHOLDS.items(), key=lambda item: item[1]['threshold'], reverse=True):
        if emotion_score >= grade_info['threshold']:
            return grade_info['name']
    
    # 기본값 (가장 낮은 등급)
    lowest_grade = min(AFFINITY_THRESHOLDS.values(), key=lambda x: x['threshold'])
    return lowest_grade['name'] 