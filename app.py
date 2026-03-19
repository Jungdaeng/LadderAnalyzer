"""
app.py
PLC Ladder Code Analyzer - Streamlit 메인 앱
"""

import streamlit as st
import time

from ladder_parser import parse_csv, program_to_text, LadderProgram
from static_analyzer import analyze, AnalysisResult, Severity
from ai_analyzer import analyze_with_ai, format_ai_result, HAS_ANTHROPIC


# ============================================================
# 페이지 설정
# ============================================================

st.set_page_config(
    page_title="PLC Ladder Analyzer",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded"
)

# 커스텀 CSS
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;700&family=Noto+Sans+KR:wght@300;400;500;700&display=swap');

    .main-title {
        font-family: 'JetBrains Mono', monospace;
        font-size: 2.2rem;
        font-weight: 700;
        background: linear-gradient(135deg, #0ea5e9, #6366f1);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        margin-bottom: 0.5rem;
    }
    .subtitle {
        font-family: 'Noto Sans KR', sans-serif;
        font-size: 1rem;
        color: #64748b;
        margin-bottom: 2rem;
    }

    .score-card {
        padding: 1.5rem;
        border-radius: 12px;
        text-align: center;
        border: 1px solid rgba(100,100,100,0.15);
    }
    .score-card .score-value {
        font-family: 'JetBrains Mono', monospace;
        font-size: 2.5rem;
        font-weight: 700;
        line-height: 1;
    }
    .score-card .score-label {
        font-family: 'Noto Sans KR', sans-serif;
        font-size: 0.85rem;
        margin-top: 0.5rem;
        opacity: 0.8;
    }

    .grade-A { color: #22c55e; }
    .grade-B { color: #84cc16; }
    .grade-C { color: #eab308; }
    .grade-D { color: #f97316; }
    .grade-F { color: #ef4444; }

    .finding-critical {
        border-left: 4px solid #ef4444;
        padding: 0.8rem 1rem;
        margin: 0.5rem 0;
        border-radius: 0 8px 8px 0;
        background: rgba(239, 68, 68, 0.05);
    }
    .finding-warning {
        border-left: 4px solid #eab308;
        padding: 0.8rem 1rem;
        margin: 0.5rem 0;
        border-radius: 0 8px 8px 0;
        background: rgba(234, 179, 8, 0.05);
    }
    .finding-info {
        border-left: 4px solid #3b82f6;
        padding: 0.8rem 1rem;
        margin: 0.5rem 0;
        border-radius: 0 8px 8px 0;
        background: rgba(59, 130, 246, 0.05);
    }

    .device-table {
        font-family: 'JetBrains Mono', monospace;
        font-size: 0.85rem;
    }

    div[data-testid="stMetric"] {
        background: rgba(100,100,100,0.05);
        border-radius: 10px;
        padding: 0.8rem;
    }
</style>
""", unsafe_allow_html=True)


# ============================================================
# 사이드바
# ============================================================

with st.sidebar:
    st.markdown("## ⚙️ 설정")

    # AI 분석 토글
    use_ai = st.toggle("🤖 AI 분석 사용", value=False,
                        help="Claude API를 사용한 심층 분석. API 키가 필요합니다.")

    api_key = ""
    ai_model = "claude-sonnet-4-20250514"

    if use_ai:
        if not HAS_ANTHROPIC:
            st.error("⚠️ `anthropic` 패키지가 설치되지 않았습니다.\n`pip install anthropic`")
            use_ai = False
        else:
            api_key = st.text_input("Anthropic API Key", type="password",
                                    help="Claude API 키를 입력하세요")
            ai_model = st.selectbox("모델", [
                "claude-sonnet-4-20250514",
                "claude-haiku-4-5-20251001",
            ])

    st.markdown("---")
    st.markdown("## 📋 분석 규칙")
    st.markdown("""
    | ID | 검사 항목 |
    |---|---|
    | R001 | 이중 코일 |
    | R002 | END 명령 |
    | R003 | 미사용 코일 |
    | R004 | 코일 없는 접점 |
    | R005 | SET/RST 불일치 |
    | R006 | 타이머 중복 |
    | R007 | 자기유지 미적용 |
    | R008 | 비상정지 부재 |
    | R009 | Y 접점 사용 |
    | R010 | 빈 Rung |
    | R011 | 스캔 순서 |
    | R012 | 디바이스 범위 |
    | R013 | 프로그램 규모 |
    | R014 | Rung 복잡도 |
    """)


# ============================================================
# 메인 영역
# ============================================================

st.markdown('<div class="main-title">⚡ PLC Ladder Analyzer</div>', unsafe_allow_html=True)
st.markdown('<div class="subtitle">Mitsubishi GX Works3 래더 코드 취약점 분석 · 프로그램 평가 · 개선 제안</div>', unsafe_allow_html=True)

# 파일 업로드 + 설명 입력
col_upload, col_desc = st.columns([1, 1])

with col_upload:
    uploaded_file = st.file_uploader(
        "📂 GX Works3 CSV Export 파일 업로드",
        type=["csv"],
        help="GX Works3에서 Export한 래더 프로그램 CSV 파일"
    )

with col_desc:
    description = st.text_area(
        "📝 프로그램 설명",
        placeholder="이 프로그램이 무엇을 하는지 설명해주세요.\n예: M0을 켜면 Green→Yellow→Red 순서로 신호등이 자동 순환하는 프로그램",
        height=130
    )


# ============================================================
# 분석 실행
# ============================================================

if uploaded_file is not None:
    # 파일 파싱
    try:
        raw_data = uploaded_file.read()
        program = parse_csv(raw_data)
    except Exception as e:
        st.error(f"❌ CSV 파싱 실패: {e}")
        st.stop()

    # 분석 버튼
    analyze_btn = st.button("🔍 분석 시작", type="primary", use_container_width=True)

    if analyze_btn or st.session_state.get("analyzed"):
        st.session_state["analyzed"] = True

        # ---- 정적 분석 ----
        with st.spinner("정적 분석 수행 중..."):
            static_result = analyze(program)

        # ---- AI 분석 ----
        ai_result = None
        if use_ai and api_key and description:
            with st.spinner("🤖 AI 심층 분석 수행 중... (30초~1분 소요)"):
                ai_result = analyze_with_ai(program, description, static_result, api_key, ai_model)

        # ============================================================
        # 결과 표시
        # ============================================================

        st.markdown("---")

        # ---- 종합 점수 ----
        score = static_result.score
        grade = "A" if score >= 90 else "B" if score >= 75 else "C" if score >= 60 else "D" if score >= 40 else "F"
        grade_class = f"grade-{grade}"

        st.markdown("### 📊 종합 평가")

        score_cols = st.columns(5)

        with score_cols[0]:
            st.markdown(f"""
            <div class="score-card">
                <div class="score-value {grade_class}">{score}</div>
                <div class="score-label">종합 점수 ({grade})</div>
            </div>
            """, unsafe_allow_html=True)

        with score_cols[1]:
            s = static_result.safety_score
            st.markdown(f"""
            <div class="score-card">
                <div class="score-value {'grade-A' if s >= 90 else 'grade-C' if s >= 60 else 'grade-F'}">{s}</div>
                <div class="score-label">🛡️ 안전성</div>
            </div>
            """, unsafe_allow_html=True)

        with score_cols[2]:
            s = static_result.reliability_score
            st.markdown(f"""
            <div class="score-card">
                <div class="score-value {'grade-A' if s >= 90 else 'grade-C' if s >= 60 else 'grade-F'}">{s}</div>
                <div class="score-label">🔧 신뢰성</div>
            </div>
            """, unsafe_allow_html=True)

        with score_cols[3]:
            s = static_result.maintainability_score
            st.markdown(f"""
            <div class="score-card">
                <div class="score-value {'grade-A' if s >= 90 else 'grade-C' if s >= 60 else 'grade-F'}">{s}</div>
                <div class="score-label">🔩 유지보수성</div>
            </div>
            """, unsafe_allow_html=True)

        with score_cols[4]:
            s = static_result.efficiency_score
            st.markdown(f"""
            <div class="score-card">
                <div class="score-value {'grade-A' if s >= 90 else 'grade-C' if s >= 60 else 'grade-F'}">{s}</div>
                <div class="score-label">⚡ 효율성</div>
            </div>
            """, unsafe_allow_html=True)

        st.markdown("")

        # 이슈 카운트 메트릭
        met_cols = st.columns(4)
        met_cols[0].metric("전체 이슈", len(static_result.findings))
        met_cols[1].metric("🔴 Critical", static_result.critical_count)
        met_cols[2].metric("🟡 Warning", static_result.warning_count)
        met_cols[3].metric("🔵 Info", static_result.info_count)

        # ---- 탭 구성 ----
        tabs = st.tabs(["🔍 정적 분석 결과", "🤖 AI 분석", "📋 프로그램 정보", "💻 코드 뷰어"])

        # ==== 탭 1: 정적 분석 결과 ====
        with tabs[0]:
            if not static_result.findings:
                st.success("✅ 정적 분석에서 발견된 이슈가 없습니다!")
            else:
                # 심각도별 필터
                severity_filter = st.multiselect(
                    "심각도 필터",
                    ["CRITICAL", "WARNING", "INFO"],
                    default=["CRITICAL", "WARNING", "INFO"]
                )

                for f in static_result.findings:
                    if f.severity.value not in severity_filter:
                        continue

                    css_class = {
                        Severity.CRITICAL: "finding-critical",
                        Severity.WARNING: "finding-warning",
                        Severity.INFO: "finding-info",
                    }[f.severity]

                    icon = {
                        Severity.CRITICAL: "🔴",
                        Severity.WARNING: "🟡",
                        Severity.INFO: "🔵",
                    }[f.severity]

                    with st.container():
                        st.markdown(f"""
                        <div class="{css_class}">
                            <strong>{icon} [{f.rule_id}] {f.title}</strong><br>
                            {f.description}
                        </div>
                        """, unsafe_allow_html=True)

                        if f.suggestion:
                            st.markdown(f"  💡 **제안:** {f.suggestion}")

                        if f.affected_devices:
                            st.markdown(f"  📌 관련 디바이스: `{'`, `'.join(f.affected_devices)}`")

                # 이중 코일 상세 테이블
                st.markdown("### 코일 사용 맵")
                coil_data = []
                for dev, steps in sorted(program.coil_map.items()):
                    count = len(steps)
                    status = "✅ OK" if count == 1 else f"❌ 이중코일 ({count}회)"
                    coil_data.append({
                        "디바이스": dev,
                        "코일 수": count,
                        "Step": str(steps),
                        "상태": status
                    })
                if coil_data:
                    st.dataframe(coil_data, use_container_width=True, hide_index=True)

        # ==== 탭 2: AI 분석 ====
        with tabs[1]:
            if not use_ai:
                st.info("🤖 AI 분석을 사용하려면 사이드바에서 'AI 분석 사용'을 켜고 API 키를 입력하세요.")
            elif not api_key:
                st.warning("⚠️ API 키를 입력해주세요.")
            elif not description:
                st.warning("⚠️ 프로그램 설명을 입력해야 AI가 의도 대비 구현을 검증할 수 있습니다.")
            elif ai_result:
                if "error" in ai_result:
                    st.error(f"AI 분석 오류: {ai_result['error']}")
                    if "raw_response" in ai_result:
                        with st.expander("Raw Response"):
                            st.code(ai_result["raw_response"])
                else:
                    # AI 점수 표시
                    if "intent_match" in ai_result:
                        ai_scores = st.columns(4)
                        ai_scores[0].metric("의도 일치",
                                            f"{ai_result.get('intent_match', {}).get('score', 'N/A')}/100")
                        ai_scores[1].metric("안전성",
                                            f"{ai_result.get('safety_analysis', {}).get('score', 'N/A')}/100")
                        ai_scores[2].metric("최적화",
                                            f"{ai_result.get('optimization', {}).get('score', 'N/A')}/100")
                        ai_scores[3].metric("표준 준수",
                                            f"{ai_result.get('standards', {}).get('score', 'N/A')}/100")

                    # 포맷된 결과
                    st.markdown(format_ai_result(ai_result))

        # ==== 탭 3: 프로그램 정보 ====
        with tabs[2]:
            info_col1, info_col2 = st.columns(2)

            with info_col1:
                st.markdown("### 프로그램 개요")
                st.markdown(f"""
                | 항목 | 값 |
                |------|-----|
                | 프로젝트 | {program.project_name} |
                | 모듈 타입 | {program.module_type} |
                | 총 스텝 | {program.total_steps} |
                | 총 Rung | {len(program.rungs)} |
                """)

            with info_col2:
                st.markdown("### 디바이스 사용 현황")
                device_data = []
                if program.input_devices:
                    device_data.append({"유형": "입력 (X)", "디바이스": ", ".join(sorted(program.input_devices)), "개수": len(program.input_devices)})
                if program.output_devices:
                    device_data.append({"유형": "출력 (Y)", "디바이스": ", ".join(sorted(program.output_devices)), "개수": len(program.output_devices)})
                if program.internal_relays:
                    device_data.append({"유형": "내부릴레이 (M)", "디바이스": ", ".join(sorted(program.internal_relays)), "개수": len(program.internal_relays)})
                if program.timers:
                    device_data.append({"유형": "타이머 (T)", "디바이스": ", ".join(sorted(program.timers)), "개수": len(program.timers)})
                if program.counters:
                    device_data.append({"유형": "카운터 (C)", "디바이스": ", ".join(sorted(program.counters)), "개수": len(program.counters)})
                if device_data:
                    st.dataframe(device_data, use_container_width=True, hide_index=True)

            # Rung 구조 분석
            st.markdown("### Rung 구조")
            rung_data = []
            for rung in program.rungs:
                rung_data.append({
                    "Rung": rung.index,
                    "Step 범위": f"{rung.start_step}~{rung.end_step}",
                    "명령어 수": len(rung.steps),
                    "코일": rung.coil_device or "-",
                    "코일 명령": rung.coil_instruction or "-",
                    "접점": ", ".join(rung.contacts[:5]) + ("..." if len(rung.contacts) > 5 else "") if rung.contacts else "-",
                    "자기유지": "✅" if rung.has_self_hold else "-"
                })
            if rung_data:
                st.dataframe(rung_data, use_container_width=True, hide_index=True)

        # ==== 탭 4: 코드 뷰어 ====
        with tabs[3]:
            st.markdown("### IL 코드 리스팅")

            # 하이라이트 옵션
            highlight = st.multiselect(
                "하이라이트",
                ["코일 명령", "이중 코일 디바이스", "자기유지 Rung"],
                default=["코일 명령"]
            )

            # 이중 코일 디바이스 목록
            double_coil_devices = {d for d, s in program.coil_map.items() if len(s) > 1}

            code_lines = []
            for step in program.steps:
                prefix = ""
                suffix = ""

                if "코일 명령" in highlight and step.is_coil:
                    prefix = "→ "
                else:
                    prefix = "  "

                if "이중 코일 디바이스" in highlight:
                    base = f"{step.device_type}{step.device_number}" if step.device_type else ""
                    if base in double_coil_devices:
                        suffix = " ⚠️ DOUBLE COIL"

                if "자기유지 Rung" in highlight:
                    for rung in program.rungs:
                        if rung.has_self_hold and rung.start_step == step.step_no:
                            suffix += " 🔄 자기유지"

                line = f"{prefix}Step {step.step_no:>4}: {step.instruction:5} {step.device}{suffix}"
                code_lines.append(line)

            st.code("\n".join(code_lines), language="text")


else:
    # 파일 미업로드 시 안내
    st.markdown("---")

    st.markdown("""
    ### 사용 방법

    **1단계**: GX Works3에서 래더 프로그램을 CSV로 Export

    > Project → Export to CSV → 프로그램 선택 → 저장

    **2단계**: 위 파일 업로드 영역에 CSV 파일 업로드

    **3단계**: 프로그램 설명란에 이 프로그램이 무엇을 하는지 간단히 기술

    **4단계**: "분석 시작" 클릭

    ---

    ### 분석 항목

    **정적 분석 (무료, 즉시)** — 14개 규칙으로 자동 검출

    이중 코일, END 누락, 미사용 디바이스, SET/RST 불일치, 타이머 중복,
    자기유지 미적용, 비상정지 부재, 출력 접점 사용, 빈 Rung, 스캔 순서 등

    **AI 심층 분석 (API 키 필요)** — Claude가 로직 레벨에서 분석

    의도 대비 구현 검증, 안전성 심층 분석, 최적화 제안, IEC 61131-3 표준 준수,
    우선순위별 구체적 개선안 (변경 전/후 코드 포함)
    """)
