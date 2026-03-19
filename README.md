# ⚡ PLC Ladder Analyzer

Mitsubishi + Siemens PLC 래더 코드 **취약점 분석 · 프로그램 평가 · 개선 제안** 도구

## 설치 및 실행

```bash
pip install -r requirements.txt
streamlit run app.py
```

## 지원 PLC

| PLC | Export 포맷 | 확장자 |
|-----|-----------|--------|
| **Mitsubishi** GX Works3 | CSV Export | `.csv` |
| **Siemens** TIA Portal / STEP 7 | AWL/STL Export | `.awl`, `.stl`, `.txt` |

## 분석 규칙

### Mitsubishi (R001~R014)

| ID | 검사 항목 | 심각도 |
|----|----------|--------|
| R001 | 이중 코일 | Critical |
| R002 | END 명령 누락 | Critical |
| R003 | 미사용 코일 | Warning |
| R004 | 코일 없는 접점 | Info |
| R005 | SET/RST 불일치 | Warning |
| R006 | 타이머 중복 | Critical |
| R007 | 자기유지 미적용 | Info |
| R008 | 비상정지 부재 | Warning |
| R009 | Y 접점 사용 | Info |
| R010 | 빈 Rung | Critical |
| R011 | 스캔 순서 | Info |
| R012 | 디바이스 범위 | Info |
| R013 | 프로그램 규모 | Info |
| R014 | Rung 복잡도 | Warning |

### Siemens (S001~S014)

| ID | 검사 항목 | 심각도 |
|----|----------|--------|
| S001 | 이중 할당 | Critical |
| S002 | 미참조 할당 | Warning |
| S003 | 할당 없는 접점 | Info |
| S004 | Set without Reset | Warning |
| S005 | 타이머 중복 기동 | Critical |
| S006 | 자기유지 미적용 | Info |
| S007 | 비상정지 부재 | Warning |
| S008 | Q 접점 사용 | Info |
| S009 | 조건 없는 할당 | Critical |
| S010 | Network 복잡도 | Warning |
| S011 | 주소 방식 혼용 | Info |
| S012 | 심볼릭 미사용 | Info |
| S013 | 괄호 불일치 | Critical |
| S014 | 프로그램 규모 | Info |

## 프로젝트 구조

```
ladder-analyzer/
├── app.py                # Streamlit 메인 앱 (Mitsubishi + Siemens 탭)
├── ladder_parser.py      # Mitsubishi GX Works3 CSV 파서
├── static_analyzer.py    # Mitsubishi 정적 분석 (14규칙)
├── siemens_parser.py     # Siemens TIA Portal AWL/STL 파서
├── siemens_analyzer.py   # Siemens 정적 분석 (14규칙)
├── ai_analyzer.py        # Claude API AI 분석 (공용)
├── requirements.txt
└── README.md
```
