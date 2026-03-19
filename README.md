# ⚡ PLC Ladder Analyzer

Mitsubishi GX Works3 래더 코드 **취약점 분석 · 프로그램 평가 · 개선 제안** 도구

## 설치 및 실행

```bash
# 의존성 설치
pip install -r requirements.txt

# 앱 실행
streamlit run app.py
```

브라우저에서 `http://localhost:8501` 접속

## 사용법

1. GX Works3에서 래더 프로그램을 CSV로 Export
2. 앱에 CSV 파일 업로드
3. 프로그램 설명 입력 (AI 분석 시 필요)
4. "분석 시작" 클릭

## 분석 기능

### 정적 분석 (14개 규칙, 즉시 실행)

| ID | 검사 항목 | 심각도 |
|----|----------|--------|
| R001 | 이중 코일 (Double Coil) | Critical |
| R002 | END 명령 누락 | Critical |
| R003 | 미사용 코일 출력 | Warning |
| R004 | 코일 없는 접점 참조 | Info |
| R005 | SET without RST | Warning |
| R006 | 타이머 번호 중복 | Critical |
| R007 | 자기유지 미적용 | Info |
| R008 | 비상정지 조건 미검출 | Warning |
| R009 | 외부 출력을 접점으로 사용 | Info |
| R010 | 접점 없는 코일 | Critical |
| R011 | 스캔 순서 참고 | Info |
| R012 | 시스템 영역 디바이스 사용 | Info |
| R013 | 프로그램 규모 분석 | Info |
| R014 | Rung 복잡도 | Warning |

### AI 심층 분석 (Claude API, 선택 사항)

- 의도 대비 구현 검증
- 안전성 심층 분석 (비상정지, 인터록)
- 로직 최적화 제안
- IEC 61131-3 표준 준수 확인
- 우선순위별 구체적 개선안

## 점수 체계

| 카테고리 | 가중치 | 평가 항목 |
|---------|--------|----------|
| 안전성 | 35% | 이중코일, END, 비상정지, 빈 Rung |
| 신뢰성 | 30% | 이중코일, SET/RST, 타이머, 스캔순서 |
| 유지보수성 | 20% | 미사용디바이스, 자기유지, Y접점, 디바이스범위 |
| 효율성 | 15% | 미사용디바이스, 프로그램규모, Rung복잡도 |

## 프로젝트 구조

```
ladder-analyzer/
├── app.py              # Streamlit 메인 앱
├── ladder_parser.py    # GX Works3 CSV 파서
├── static_analyzer.py  # 룰 기반 정적 분석 엔진
├── ai_analyzer.py      # Claude API AI 분석
├── requirements.txt
└── README.md
```
