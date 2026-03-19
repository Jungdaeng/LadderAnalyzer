"""
ai_analyzer.py
Claude API를 활용한 AI 기반 래더 코드 심층 분석
"""

import json
from typing import Optional

try:
    import anthropic
    HAS_ANTHROPIC = True
except ImportError:
    HAS_ANTHROPIC = False

from ladder_parser import LadderProgram, program_to_text
from static_analyzer import AnalysisResult, Severity


SYSTEM_PROMPT = """너는 산업용 PLC 래더 프로그래밍 전문가야. Mitsubishi iQ-R/iQ-F/Q 시리즈 PLC에 특화되어 있으며, IEC 61131-3, ISA-88, PackML 표준에 정통하다.

사용자가 래더 코드와 프로그램 설명을 제공하면, 아래 관점에서 심층 분석을 수행한다:

## 분석 관점

### 1. 의도 대비 구현 검증
- 사용자의 설명과 실제 코드 로직이 일치하는가?
- 빠진 기능이나 잘못 구현된 부분이 있는가?

### 2. 안전성 분석
- 비상정지 로직이 적절한가?
- 인터록(Interlock) 조건이 충분한가?
- 동시 동작 방지가 되어 있는가?
- 출력 충돌 가능성은 없는가?

### 3. 로직 최적화
- 더 효율적인 구현 방법이 있는가?
- 불필요한 중간 릴레이가 있는가?
- 타이머/카운터 사용이 적절한가?

### 4. 표준 준수
- IEC 61131-3 권장사항을 따르고 있는가?
- 디바이스 네이밍 규칙이 일관적인가?
- 코멘트/라벨이 충분한가?

### 5. 개선 제안
- 구체적이고 실행 가능한 개선안을 제시
- 변경 전/후 코드를 비교하여 보여줌
- 우선순위를 매겨서 가장 중요한 것부터 제안

## 응답 형식

반드시 아래 JSON 형식으로만 응답하라. JSON 외의 텍스트를 포함하지 마라.

```json
{
  "intent_match": {
    "score": 0-100,
    "matches": ["일치하는 부분들"],
    "mismatches": ["불일치 또는 누락된 부분들"]
  },
  "safety_analysis": {
    "score": 0-100,
    "findings": [
      {"issue": "문제 설명", "severity": "CRITICAL|WARNING|INFO", "suggestion": "개선 방안"}
    ]
  },
  "optimization": {
    "score": 0-100,
    "suggestions": [
      {"current": "현재 방식", "proposed": "제안 방식", "benefit": "기대 효과"}
    ]
  },
  "standards": {
    "score": 0-100,
    "observations": ["표준 관련 관찰사항"]
  },
  "improvements": [
    {"priority": 1, "title": "제목", "description": "설명", "code_before": "변경전", "code_after": "변경후"}
  ],
  "overall_assessment": "전체 평가 요약 (2-3문장)"
}
```"""


def build_analysis_prompt(program: LadderProgram, description: str, static_result: AnalysisResult) -> str:
    """AI 분석용 프롬프트 구성"""

    # 프로그램 코드
    code_text = program_to_text(program)

    # 정적 분석 결과 요약
    static_findings = []
    for f in static_result.findings:
        static_findings.append(f"[{f.severity.value}] {f.rule_id}: {f.title} - {f.description}")
    static_text = "\n".join(static_findings) if static_findings else "정적 분석에서 발견된 이슈 없음"

    # 디바이스 맵
    device_info = []
    device_info.append(f"입력(X): {sorted(program.input_devices) if program.input_devices else '없음'}")
    device_info.append(f"출력(Y): {sorted(program.output_devices) if program.output_devices else '없음'}")
    device_info.append(f"내부릴레이(M): {sorted(program.internal_relays) if program.internal_relays else '없음'}")
    device_info.append(f"타이머(T): {sorted(program.timers) if program.timers else '없음'}")
    device_info.append(f"카운터(C): {sorted(program.counters) if program.counters else '없음'}")
    device_map = "\n".join(device_info)

    # 코일 맵
    coil_info = []
    for dev, steps in sorted(program.coil_map.items()):
        count = len(steps)
        status = "OK" if count == 1 else f"⚠️ 이중코일 ({count}회)"
        coil_info.append(f"  {dev}: Step {steps} {status}")
    coil_text = "\n".join(coil_info)

    prompt = f"""아래 Mitsubishi PLC 래더 프로그램을 분석해줘.

## 프로그램 설명 (사용자 제공)
{description}

## 프로그램 정보
- 프로젝트: {program.project_name}
- 모듈: {program.module_type}
- 총 스텝: {program.total_steps}
- 총 Rung: {len(program.rungs)}

## 디바이스 사용 현황
{device_map}

## 코일 사용 맵
{coil_text}

## 프로그램 코드
{code_text}

## 자동 정적 분석 결과
{static_text}

위 정보를 바탕으로 심층 분석을 수행하고, 지정된 JSON 형식으로 응답해줘."""

    return prompt


def analyze_with_ai(
    program: LadderProgram,
    description: str,
    static_result: AnalysisResult,
    api_key: str,
    model: str = "claude-sonnet-4-20250514"
) -> Optional[dict]:
    """Claude API를 사용하여 AI 분석 수행"""

    if not HAS_ANTHROPIC:
        return None

    client = anthropic.Anthropic(api_key=api_key)

    prompt = build_analysis_prompt(program, description, static_result)

    try:
        response = client.messages.create(
            model=model,
            max_tokens=4096,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}]
        )

        # 응답 텍스트 추출
        text = ""
        for block in response.content:
            if hasattr(block, 'text'):
                text += block.text

        # JSON 파싱
        text = text.strip()
        if text.startswith("```json"):
            text = text[7:]
        if text.startswith("```"):
            text = text[3:]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()

        result = json.loads(text)
        return result

    except json.JSONDecodeError as e:
        return {"error": f"AI 응답 JSON 파싱 실패: {e}", "raw_response": text}
    except Exception as e:
        return {"error": f"AI 분석 실패: {e}"}


def format_ai_result(ai_result: dict) -> str:
    """AI 분석 결과를 읽기 쉬운 텍스트로 변환"""
    if not ai_result:
        return "AI 분석을 수행하지 않았습니다."

    if "error" in ai_result:
        return f"AI 분석 오류: {ai_result['error']}"

    lines = []

    # 전체 평가
    if "overall_assessment" in ai_result:
        lines.append("## 전체 평가")
        lines.append(ai_result["overall_assessment"])
        lines.append("")

    # 의도 대비 구현
    if "intent_match" in ai_result:
        im = ai_result["intent_match"]
        lines.append(f"## 의도 대비 구현 (점수: {im.get('score', 'N/A')})")
        if im.get("matches"):
            lines.append("**일치:**")
            for m in im["matches"]:
                lines.append(f"  ✅ {m}")
        if im.get("mismatches"):
            lines.append("**불일치/누락:**")
            for m in im["mismatches"]:
                lines.append(f"  ❌ {m}")
        lines.append("")

    # 안전성
    if "safety_analysis" in ai_result:
        sa = ai_result["safety_analysis"]
        lines.append(f"## 안전성 분석 (점수: {sa.get('score', 'N/A')})")
        for f in sa.get("findings", []):
            icon = "🔴" if f.get("severity") == "CRITICAL" else "🟡" if f.get("severity") == "WARNING" else "🔵"
            lines.append(f"  {icon} {f.get('issue', '')}")
            lines.append(f"     → {f.get('suggestion', '')}")
        lines.append("")

    # 최적화
    if "optimization" in ai_result:
        opt = ai_result["optimization"]
        lines.append(f"## 최적화 제안 (점수: {opt.get('score', 'N/A')})")
        for s in opt.get("suggestions", []):
            lines.append(f"  현재: {s.get('current', '')}")
            lines.append(f"  제안: {s.get('proposed', '')}")
            lines.append(f"  효과: {s.get('benefit', '')}")
            lines.append("")

    # 개선 제안
    if "improvements" in ai_result:
        lines.append("## 우선순위별 개선 제안")
        for imp in ai_result["improvements"]:
            lines.append(f"### [{imp.get('priority', '?')}] {imp.get('title', '')}")
            lines.append(imp.get("description", ""))
            if imp.get("code_before"):
                lines.append(f"  변경 전: {imp['code_before']}")
            if imp.get("code_after"):
                lines.append(f"  변경 후: {imp['code_after']}")
            lines.append("")

    return "\n".join(lines)
