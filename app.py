"""
app.py
PLC Ladder Code Analyzer - Streamlit 메인 앱
Mitsubishi GX Works3 + Siemens TIA Portal 지원
"""

import streamlit as st

from ladder_parser import parse_csv, program_to_text
from static_analyzer import analyze, Severity
from siemens_parser import parse_scl, program_to_text_siemens
from siemens_analyzer import analyze_siemens
from ai_analyzer import analyze_with_ai, format_ai_result, HAS_ANTHROPIC


st.set_page_config(page_title="PLC Ladder Analyzer", page_icon="⚡", layout="wide", initial_sidebar_state="expanded")

st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;700&family=Noto+Sans+KR:wght@300;400;500;700&display=swap');
    .main-title { font-family: 'JetBrains Mono', monospace; font-size: 2.2rem; font-weight: 700; background: linear-gradient(135deg, #0ea5e9, #6366f1); -webkit-background-clip: text; -webkit-text-fill-color: transparent; margin-bottom: 0.5rem; }
    .subtitle { font-family: 'Noto Sans KR', sans-serif; font-size: 1rem; color: #64748b; margin-bottom: 1rem; }
    .score-card { padding: 1.5rem; border-radius: 12px; text-align: center; border: 1px solid rgba(100,100,100,0.15); }
    .score-card .score-value { font-family: 'JetBrains Mono', monospace; font-size: 2.5rem; font-weight: 700; line-height: 1; }
    .score-card .score-label { font-family: 'Noto Sans KR', sans-serif; font-size: 0.85rem; margin-top: 0.5rem; opacity: 0.8; }
    .grade-A { color: #22c55e; } .grade-B { color: #84cc16; } .grade-C { color: #eab308; } .grade-D { color: #f97316; } .grade-F { color: #ef4444; }
    .finding-critical { border-left: 4px solid #ef4444; padding: 0.8rem 1rem; margin: 0.5rem 0; border-radius: 0 8px 8px 0; background: rgba(239,68,68,0.05); }
    .finding-warning { border-left: 4px solid #eab308; padding: 0.8rem 1rem; margin: 0.5rem 0; border-radius: 0 8px 8px 0; background: rgba(234,179,8,0.05); }
    .finding-info { border-left: 4px solid #3b82f6; padding: 0.8rem 1rem; margin: 0.5rem 0; border-radius: 0 8px 8px 0; background: rgba(59,130,246,0.05); }
    div[data-testid="stMetric"] { background: rgba(100,100,100,0.05); border-radius: 10px; padding: 0.8rem; }
</style>
""", unsafe_allow_html=True)


# ---- Sidebar ----
with st.sidebar:
    st.markdown("## ⚙️ 설정")
    use_ai = st.toggle("🤖 AI 분석 사용", value=False)
    api_key, ai_model = "", "claude-sonnet-4-20250514"
    if use_ai:
        if not HAS_ANTHROPIC:
            st.error("⚠️ `pip install anthropic` 필요")
            use_ai = False
        else:
            api_key = st.text_input("Anthropic API Key", type="password")
            ai_model = st.selectbox("모델", ["claude-sonnet-4-20250514", "claude-haiku-4-5-20251001"])
    st.markdown("---")
    st.markdown("### 📋 분석 규칙")
    st.markdown("**Mitsubishi** R001~R014 (14개)\n\n**Siemens** S001~S014 (14개)")


# ---- Common renderers ----
def render_scores(result):
    score = result.score
    grade = "A" if score >= 90 else "B" if score >= 75 else "C" if score >= 60 else "D" if score >= 40 else "F"
    cols = st.columns(5)
    for col, (label, s, g) in zip(cols, [
        ("종합", score, grade), ("🛡️ 안전성", result.safety_score, None),
        ("🔧 신뢰성", result.reliability_score, None),
        ("🔩 유지보수성", result.maintainability_score, None),
        ("⚡ 효율성", result.efficiency_score, None),
    ]):
        gc = f"grade-{g}" if g else ("grade-A" if s >= 90 else "grade-C" if s >= 60 else "grade-F")
        sub = f" ({g})" if g else ""
        with col:
            st.markdown(f'<div class="score-card"><div class="score-value {gc}">{s}</div><div class="score-label">{label}{sub}</div></div>', unsafe_allow_html=True)
    st.markdown("")
    mc = st.columns(4)
    mc[0].metric("전체 이슈", len(result.findings))
    mc[1].metric("🔴 Critical", result.critical_count)
    mc[2].metric("🟡 Warning", result.warning_count)
    mc[3].metric("🔵 Info", result.info_count)


def render_findings(result, key_suffix=""):
    if not result.findings:
        st.success("✅ 발견된 이슈가 없습니다!")
        return
    sev = st.multiselect("심각도 필터", ["CRITICAL", "WARNING", "INFO"], default=["CRITICAL", "WARNING", "INFO"], key=f"sf_{key_suffix}")
    for f in result.findings:
        if f.severity.value not in sev:
            continue
        css = {"CRITICAL": "finding-critical", "WARNING": "finding-warning", "INFO": "finding-info"}[f.severity.value]
        icon = {"CRITICAL": "🔴", "WARNING": "🟡", "INFO": "🔵"}[f.severity.value]
        st.markdown(f'<div class="{css}"><strong>{icon} [{f.rule_id}] {f.title}</strong><br>{f.description}</div>', unsafe_allow_html=True)
        if f.suggestion:
            st.markdown(f"  💡 **제안:** {f.suggestion}")
        if f.affected_devices:
            st.markdown(f"  📌 관련: `{'`, `'.join(f.affected_devices)}`")


def render_coil_map(coil_map):
    st.markdown("### 코일/할당 맵")
    data = []
    for dev, steps in sorted(coil_map.items()):
        n = len(steps)
        data.append({"디바이스": dev, "코일 수": n, "위치": str(steps), "상태": "✅ OK" if n == 1 else f"❌ 이중코일 ({n}회)"})
    if data:
        st.dataframe(data, use_container_width=True, hide_index=True)


# ---- Main ----
st.markdown('<div class="main-title">⚡ PLC Ladder Analyzer</div>', unsafe_allow_html=True)
st.markdown('<div class="subtitle">Mitsubishi · Siemens 래더 코드 취약점 분석 · 프로그램 평가 · 개선 제안</div>', unsafe_allow_html=True)

tab_m, tab_s = st.tabs(["🔴 Mitsubishi (GX Works3 CSV)", "🟢 Siemens (TIA Portal SCL)"])


# ============== MITSUBISHI ==============
with tab_m:
    c1, c2 = st.columns(2)
    with c1:
        m_file = st.file_uploader("📂 GX Works3 CSV Export", type=["csv"], key="mf")
    with c2:
        m_desc = st.text_area("📝 프로그램 설명", key="md", height=130, placeholder="이 프로그램이 무엇을 하는지 설명")

    if m_file:
        try:
            m_prog = parse_csv(m_file.read())
        except Exception as e:
            st.error(f"❌ 파싱 실패: {e}"); st.stop()

        if st.button("🔍 분석 시작", type="primary", use_container_width=True, key="mb"):
            st.session_state["ma"] = True
            with st.spinner("분석 중..."):
                st.session_state["mr"] = analyze(m_prog)
            if use_ai and api_key and m_desc:
                with st.spinner("🤖 AI 분석 중..."):
                    st.session_state["mai"] = analyze_with_ai(m_prog, m_desc, st.session_state["mr"], api_key, ai_model)

        if st.session_state.get("ma") and "mr" in st.session_state:
            mr = st.session_state["mr"]
            st.markdown("---")
            render_scores(mr)

            t1, t2, t3, t4 = st.tabs(["🔍 정적 분석", "🤖 AI 분석", "📋 프로그램 정보", "💻 코드"])
            with t1:
                render_findings(mr, "m")
                render_coil_map(m_prog.coil_map)
            with t2:
                ai = st.session_state.get("mai")
                if ai and "error" not in ai:
                    st.markdown(format_ai_result(ai))
                elif ai:
                    st.error(ai.get("error", ""))
                else:
                    st.info("🤖 AI 분석을 사용하려면 사이드바에서 설정하세요.")
            with t3:
                st.markdown(f"**프로젝트:** {m_prog.project_name} | **모듈:** {m_prog.module_type} | **스텝:** {m_prog.total_steps} | **Rung:** {len(m_prog.rungs)}")
                dev_data = []
                for lbl, devs in [("입력(X)", m_prog.input_devices), ("출력(Y)", m_prog.output_devices), ("릴레이(M)", m_prog.internal_relays), ("타이머(T)", m_prog.timers)]:
                    if devs: dev_data.append({"유형": lbl, "디바이스": ", ".join(sorted(devs)), "수": len(devs)})
                if dev_data: st.dataframe(dev_data, use_container_width=True, hide_index=True)
                rung_data = [{"Rung": r.index, "Step": f"{r.start_step}~{r.end_step}", "코일": r.coil_device or "-", "자기유지": "✅" if r.has_self_hold else "-"} for r in m_prog.rungs]
                if rung_data: st.dataframe(rung_data, use_container_width=True, hide_index=True)
            with t4:
                dc = {d for d, s in m_prog.coil_map.items() if len(s) > 1}
                lines = []
                for s in m_prog.steps:
                    p = "→ " if s.is_coil else "  "
                    b = f"{s.device_type}{s.device_number}" if s.device_type else ""
                    x = " ⚠️ DOUBLE" if b in dc else ""
                    lines.append(f"{p}Step {s.step_no:>4}: {s.instruction:5} {s.device}{x}")
                st.code("\n".join(lines), language="text")
    else:
        st.markdown("**GX Works3:** Project → Export to CSV → 프로그램 선택 → 저장")


# ============== SIEMENS ==============
with tab_s:
    c1, c2 = st.columns(2)
    with c1:
        s_file = st.file_uploader("📂 TIA Portal SCL Export", type=["scl", "txt", "db", "udt"], key="sf",
                                   help="TIA Portal에서 Generate source from blocks로 내보낸 SCL 파일")
    with c2:
        s_desc = st.text_area("📝 프로그램 설명", key="sd", height=130, placeholder="이 프로그램이 무엇을 하는지 설명")

    if s_file:
        try:
            s_prog = parse_scl(s_file.read())
        except Exception as e:
            st.error(f"❌ SCL 파싱 실패: {e}"); st.stop()

        if st.button("🔍 분석 시작", type="primary", use_container_width=True, key="sb"):
            st.session_state["sa"] = True
            with st.spinner("분석 중..."):
                st.session_state["sr"] = analyze_siemens(s_prog)
            if use_ai and api_key and s_desc:
                with st.spinner("🤖 AI 분석 중..."):
                    try:
                        import anthropic, json
                        from ai_analyzer import SYSTEM_PROMPT
                        client = anthropic.Anthropic(api_key=api_key)
                        code = program_to_text_siemens(s_prog)
                        static_text = "\n".join(f"[{f.severity.value}] {f.rule_id}: {f.title}" for f in st.session_state["sr"].findings) or "없음"
                        sys_prompt = SYSTEM_PROMPT.replace("Mitsubishi iQ-R/iQ-F/Q 시리즈 PLC에 특화", "Siemens S7-1200/S7-1500 PLC의 SCL(Structured Control Language)에 특화").replace("래더", "SCL")
                        prompt = f"Siemens SCL 프로그램 분석:\n\n설명: {s_desc}\n\n블록: {s_prog.block_type} \"{s_prog.block_name}\"\n코드줄: {s_prog.code_lines}\n\n코드:\n{code}\n\n정적분석:\n{static_text}\n\nJSON 형식으로 응답."
                        resp = client.messages.create(model=ai_model, max_tokens=4096, system=sys_prompt, messages=[{"role": "user", "content": prompt}])
                        txt = "".join(b.text for b in resp.content if hasattr(b, 'text')).strip().strip("`").removeprefix("json").strip()
                        st.session_state["sai"] = json.loads(txt)
                    except Exception as e:
                        st.session_state["sai"] = {"error": str(e)}

        if st.session_state.get("sa") and "sr" in st.session_state:
            sr = st.session_state["sr"]
            st.markdown("---")
            render_scores(sr)

            t1, t2, t3, t4 = st.tabs(["🔍 정적 분석", "🤖 AI 분석", "📋 프로그램 정보", "💻 소스 코드"])
            with t1:
                render_findings(sr, "s")
                # 할당 맵 (SCL은 코일맵 대신 할당맵)
                st.markdown("### 변수 할당 맵")
                asgn_data = []
                for var, lines in sorted(s_prog.var_write_map.items()):
                    n = len(lines)
                    out_names = {v.name for v in s_prog.output_vars}
                    var_type = "OUTPUT" if var in out_names else "내부"
                    status = "✅ OK" if n == 1 else f"⚠️ {n}곳에서 할당"
                    asgn_data.append({"변수": var, "유형": var_type, "할당 횟수": n, "위치(Line)": str(lines), "상태": status})
                if asgn_data:
                    st.dataframe(asgn_data, use_container_width=True, hide_index=True)

            with t2:
                ai = st.session_state.get("sai")
                if ai and "error" not in ai:
                    st.markdown(format_ai_result(ai))
                elif ai:
                    st.error(ai.get("error", ""))
                else:
                    st.info("🤖 AI 분석을 사용하려면 사이드바에서 설정하세요.")

            with t3:
                ic1, ic2 = st.columns(2)
                with ic1:
                    st.markdown("### 프로그램 개요")
                    st.markdown(f"""
| 항목 | 값 |
|------|-----|
| 블록 타입 | {s_prog.block_type} |
| 블록 이름 | {s_prog.block_name} |
| 코드 줄수 | {s_prog.code_lines} |
| 주석 줄수 | {s_prog.comment_lines} |
| 중첩 최대 | {s_prog.max_nesting}단계 |
| 제어 구조 | {len(s_prog.control_blocks)}개 |
| 할당문 | {len(s_prog.assignments)}개 |
                    """)
                with ic2:
                    st.markdown("### 변수 선언")
                    var_data = []
                    for v in s_prog.variables:
                        var_data.append({"이름": v.name, "타입": v.data_type, "섹션": v.section, "초기값": v.initial_value or "-", "주석": v.comment or "-"})
                    if var_data:
                        st.dataframe(var_data, use_container_width=True, hide_index=True)

                # 제어 구조 분석
                st.markdown("### 제어 구조")
                cb_data = []
                for cb in s_prog.control_blocks:
                    extras = []
                    if cb.block_type == "IF" and not cb.has_else:
                        extras.append("⚠️ ELSE 없음")
                    if cb.nesting_depth > 3:
                        extras.append(f"⚠️ 깊이 {cb.nesting_depth}")
                    cb_data.append({
                        "유형": cb.block_type,
                        "Line": cb.line_no,
                        "조건": (cb.condition[:40] + "...") if len(cb.condition) > 40 else cb.condition or "-",
                        "깊이": cb.nesting_depth,
                        "줄수": cb.body_lines or "-",
                        "비고": " / ".join(extras) or "✅"
                    })
                if cb_data:
                    st.dataframe(cb_data, use_container_width=True, hide_index=True)

                # 타이머/카운터
                if s_prog.timer_counters:
                    st.markdown("### 타이머/카운터")
                    tc_data = [{"이름": tc.name, "타입": tc.tc_type, "프리셋": tc.preset or "-", "호출 횟수": len(tc.lines_used), "위치": str(tc.lines_used)} for tc in s_prog.timer_counters]
                    st.dataframe(tc_data, use_container_width=True, hide_index=True)

            with t4:
                # SCL 소스 코드 표시 (줄번호 포함)
                code_lines = []
                for i, line in enumerate(s_prog.raw_lines, 1):
                    code_lines.append(f"{i:>4}: {line}")
                st.code("\n".join(code_lines), language="pascal")

    else:
        st.markdown("""
**TIA Portal에서 SCL Export:**

1. 프로그램 블록(OB/FB/FC) 우클릭
2. **"Generate source from blocks"** 선택
3. SCL 소스 파일 저장 (`.scl` 또는 `.txt`)

지원 확장자: `.scl`, `.txt`, `.db`, `.udt`

**예시 SCL 코드:**
```
FUNCTION_BLOCK "TrafficLight"
VAR_INPUT
    Start : Bool;
END_VAR
VAR_OUTPUT
    GreenLamp : Bool;
    YellowLamp : Bool;
    RedLamp : Bool;
END_VAR
VAR
    State : Int;
    CycleTimer : TON;
END_VAR
BEGIN
    IF Start THEN
        CASE State OF
            0:  // Green
                GreenLamp := TRUE;
                YellowLamp := FALSE;
                RedLamp := FALSE;
                CycleTimer(IN := TRUE, PT := T#5S);
                IF CycleTimer.Q THEN
                    State := 1;
                    CycleTimer(IN := FALSE, PT := T#5S);
                END_IF;
            1:  // Yellow
                GreenLamp := FALSE;
                YellowLamp := TRUE;
                CycleTimer(IN := TRUE, PT := T#2S);
                IF CycleTimer.Q THEN
                    State := 2;
                    CycleTimer(IN := FALSE, PT := T#2S);
                END_IF;
            2:  // Red
                YellowLamp := FALSE;
                RedLamp := TRUE;
                CycleTimer(IN := TRUE, PT := T#5S);
                IF CycleTimer.Q THEN
                    State := 0;
                    CycleTimer(IN := FALSE, PT := T#5S);
                END_IF;
        END_CASE;
    ELSE
        GreenLamp := FALSE;
        YellowLamp := FALSE;
        RedLamp := FALSE;
        State := 0;
    END_IF;
END_FUNCTION_BLOCK
```
        """)
