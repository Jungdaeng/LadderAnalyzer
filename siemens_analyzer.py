"""
siemens_analyzer.py
Siemens SCL (Structured Control Language) 전용 정적 분석 엔진
래더와 완전히 다른 고급 언어 특화 규칙
"""

from dataclasses import dataclass, field
from static_analyzer import Finding, Severity, AnalysisResult
from siemens_parser import SCLProgram


def analyze_siemens(program: SCLProgram) -> AnalysisResult:
    """SCL 프로그램 정적 분석"""
    result = AnalysisResult()

    rules = [
        check_output_double_write,
        check_unused_variables,
        check_unread_outputs,
        check_missing_else,
        check_case_without_else,
        check_deep_nesting,
        check_magic_numbers,
        check_large_block,
        check_loop_safety,
        check_timer_reuse,
        check_comment_ratio,
        check_temp_var_abuse,
        check_direct_output_write,
        check_state_machine_pattern,
    ]

    for rule in rules:
        findings = rule(program)
        result.findings.extend(findings)

    _calculate_scores(result)
    result.summary = _generate_summary(result, program)
    return result


# ============================================================
# SCL 전용 분석 규칙
# ============================================================

def check_output_double_write(program: SCLProgram) -> list:
    """S001: 출력 변수에 여러 곳에서 할당 (분기 충돌 위험)"""
    findings = []
    output_names = {v.name for v in program.output_vars}

    for var_name, write_lines in program.var_write_map.items():
        if var_name in output_names and len(write_lines) > 1:
            # 같은 IF-ELSE 분기 내에서만 쓰는 건 OK — 다른 곳에서도 쓰면 Warning
            branches = set()
            for asgn in program.assignments:
                if asgn.target == var_name:
                    branches.add(asgn.in_branch)

            if len(branches) > 1 or "" in branches:
                findings.append(Finding(
                    rule_id="S001",
                    severity=Severity.WARNING,
                    title="출력 변수 다중 할당",
                    description=(
                        f"출력 '{var_name}'이 {len(write_lines)}곳에서 할당됨 "
                        f"(Line {', '.join(map(str, write_lines))}). "
                        f"실행 경로에 따라 의도치 않은 값이 출력될 수 있습니다."
                    ),
                    affected_devices=[var_name],
                    affected_steps=write_lines,
                    suggestion=(
                        f"IF/CASE 분기 구조를 명확히 하여 모든 경로에서 "
                        f"'{var_name}'이 정확히 한 번만 할당되도록 정리하세요."
                    )
                ))
    return findings


def check_unused_variables(program: SCLProgram) -> list:
    """S002: 선언만 되고 사용되지 않는 변수"""
    findings = []
    all_declared = {v.name for v in program.variables}
    all_written = set(program.var_write_map.keys())
    all_read = set(program.var_read_map.keys())
    all_used = all_written | all_read

    # 타이머/카운터 이름도 사용된 것으로 처리
    tc_names = {tc.name for tc in program.timer_counters}
    all_used |= tc_names

    unused = all_declared - all_used
    # 타이머/카운터 타입 변수는 인스턴스 호출로 사용되므로 제외
    tc_types = {"TON", "TOF", "TP", "CTU", "CTD", "CTUD", "R_TRIG", "F_TRIG"}
    for var in program.variables:
        if var.data_type.upper() in tc_types:
            unused.discard(var.name)

    if unused:
        for var_name in sorted(unused):
            var = next((v for v in program.variables if v.name == var_name), None)
            findings.append(Finding(
                rule_id="S002",
                severity=Severity.WARNING,
                title="미사용 변수",
                description=f"변수 '{var_name}' ({var.section}, {var.data_type})이 선언만 되고 코드에서 사용되지 않습니다.",
                affected_devices=[var_name],
                suggestion=f"불필요한 변수를 제거하여 코드를 정리하세요."
            ))
    return findings


def check_unread_outputs(program: SCLProgram) -> list:
    """S003: 할당은 되지만 읽히지 않는 내부 변수 (dead store)"""
    findings = []
    internal_names = {v.name for v in program.internal_vars + program.static_vars}

    for var_name in internal_names:
        if var_name in program.var_write_map and var_name not in program.var_read_map:
            findings.append(Finding(
                rule_id="S003",
                severity=Severity.INFO,
                title="쓰기만 하고 읽지 않는 변수 (Dead Store)",
                description=f"내부 변수 '{var_name}'에 값을 할당하지만, 다른 곳에서 참조되지 않습니다.",
                affected_devices=[var_name],
                suggestion=f"'{var_name}'이 디버깅용이 아니라면 제거를 검토하세요."
            ))
    return findings


def check_missing_else(program: SCLProgram) -> list:
    """S004: 출력을 제어하는 IF문에 ELSE가 없음"""
    findings = []
    output_names = {v.name for v in program.output_vars}

    for cb in program.control_blocks:
        if cb.block_type != "IF":
            continue
        if cb.has_else:
            continue

        # 이 IF 블록 안에서 출력 변수에 할당하는지 확인
        affected_outputs = []
        for asgn in program.assignments:
            if cb.line_no <= asgn.line_no <= cb.end_line:
                if asgn.target in output_names:
                    affected_outputs.append(asgn.target)

        if affected_outputs:
            findings.append(Finding(
                rule_id="S004",
                severity=Severity.WARNING,
                title="ELSE 없는 출력 제어 IF문",
                description=(
                    f"Line {cb.line_no}의 IF문에서 출력({', '.join(set(affected_outputs))})을 "
                    f"제어하지만 ELSE 분기가 없습니다. 조건 미충족 시 출력이 이전 값을 유지합니다."
                ),
                affected_devices=list(set(affected_outputs)),
                affected_steps=[cb.line_no],
                suggestion="ELSE 분기에서 출력의 기본값(보통 FALSE 또는 0)을 명시적으로 할당하세요."
            ))
    return findings


def check_case_without_else(program: SCLProgram) -> list:
    """S005: CASE문에 ELSE(기본값) 없음"""
    findings = []

    for cb in program.control_blocks:
        if cb.block_type != "CASE":
            continue
        if cb.end_line == 0:
            continue

        # CASE ~ END_CASE 사이에 ELSE가 있는지 확인
        has_else = False
        for i, line in enumerate(program.raw_lines):
            line_no = i + 1
            if cb.line_no < line_no < cb.end_line:
                if line.strip().upper() == "ELSE":
                    has_else = True
                    break

        if not has_else:
            findings.append(Finding(
                rule_id="S005",
                severity=Severity.WARNING,
                title="CASE문에 ELSE(기본 분기) 없음",
                description=(
                    f"Line {cb.line_no}의 CASE문에 ELSE 기본 분기가 없습니다. "
                    f"정의되지 않은 값이 들어오면 아무 동작도 하지 않습니다."
                ),
                affected_steps=[cb.line_no],
                suggestion=(
                    f"CASE문 끝에 ELSE 분기를 추가하여 예상치 못한 값을 처리하세요. "
                    f"상태 머신이라면 ELSE에서 안전 상태로 복귀하는 것이 좋습니다."
                )
            ))
    return findings


def check_deep_nesting(program: SCLProgram) -> list:
    """S006: 과도한 중첩 깊이"""
    findings = []

    if program.max_nesting > 4:
        deep_blocks = [cb for cb in program.control_blocks if cb.nesting_depth > 4]
        lines = [cb.line_no for cb in deep_blocks[:5]]
        findings.append(Finding(
            rule_id="S006",
            severity=Severity.WARNING,
            title=f"과도한 중첩 (깊이 {program.max_nesting})",
            description=(
                f"제어 구조 중첩이 {program.max_nesting}단계까지 들어갑니다 "
                f"(Line {', '.join(map(str, lines))}). 가독성과 디버깅이 어려워집니다."
            ),
            affected_steps=lines,
            suggestion=(
                "Early return 패턴이나 조건 반전으로 중첩을 줄이세요. "
                "복잡한 로직은 별도 FC/FB로 분리하세요."
            )
        ))
    elif program.max_nesting > 3:
        findings.append(Finding(
            rule_id="S006",
            severity=Severity.INFO,
            title=f"중첩 깊이 참고 ({program.max_nesting}단계)",
            description=f"제어 구조 중첩이 {program.max_nesting}단계입니다. 3단계 이내를 권장합니다.",
            suggestion="가능하면 중첩을 줄여 가독성을 높이세요."
        ))
    return findings


def check_magic_numbers(program: SCLProgram) -> list:
    """S007: 매직 넘버 (하드코딩된 상수)"""
    findings = []

    if len(program.magic_numbers) > 3:
        samples = program.magic_numbers[:5]
        sample_text = ", ".join(f"Line {ln}: {val}" for ln, val in samples)
        findings.append(Finding(
            rule_id="S007",
            severity=Severity.INFO,
            title=f"매직 넘버 {len(program.magic_numbers)}개",
            description=(
                f"하드코딩된 숫자값이 {len(program.magic_numbers)}곳에서 발견됨 ({sample_text}). "
                f"의미를 파악하기 어렵고, 값 변경 시 여러 곳을 수정해야 합니다."
            ),
            suggestion="상수(CONSTANT)를 선언하여 의미 있는 이름을 붙이세요. 예: MAX_SPEED := 1500;"
        ))
    return findings


def check_large_block(program: SCLProgram) -> list:
    """S008: 대규모 코드 블록"""
    findings = []

    if program.code_lines > 200:
        findings.append(Finding(
            rule_id="S008",
            severity=Severity.WARNING,
            title=f"대규모 코드 블록 ({program.code_lines}줄)",
            description=f"코드가 {program.code_lines}줄로 한 블록에 너무 많은 로직이 있습니다.",
            suggestion="기능별로 FC(Function) 또는 FB(Function Block)로 분리하세요. 100줄 이내를 권장합니다."
        ))
    elif program.code_lines > 100:
        findings.append(Finding(
            rule_id="S008",
            severity=Severity.INFO,
            title=f"코드 블록 규모 참고 ({program.code_lines}줄)",
            description=f"코드가 {program.code_lines}줄입니다. 기능이 많다면 분리를 검토하세요.",
            suggestion="관련 로직을 REGION ~ END_REGION으로 그룹화하여 가독성을 높이세요."
        ))
    return findings


def check_loop_safety(program: SCLProgram) -> list:
    """S009: WHILE/REPEAT 루프 안전성"""
    findings = []

    for cb in program.control_blocks:
        if cb.block_type in ("WHILE", "REPEAT"):
            # 루프 조건에 타임아웃이나 카운터가 포함되어 있는지 간이 검사
            cond_lower = cb.condition.lower() if cb.condition else ""
            has_counter = any(kw in cond_lower for kw in ["count", "cnt", "iter", "loop", "max", "limit"])
            has_timer = any(kw in cond_lower for kw in ["timer", "time", "timeout"])

            if not has_counter and not has_timer and cb.condition:
                findings.append(Finding(
                    rule_id="S009",
                    severity=Severity.WARNING,
                    title="루프 안전장치 미검출",
                    description=(
                        f"Line {cb.line_no}의 {cb.block_type} 루프에서 "
                        f"카운터/타임아웃 기반 탈출 조건이 명확하지 않습니다. "
                        f"무한 루프로 PLC 스캔 타임 초과(Watchdog) 가능성이 있습니다."
                    ),
                    affected_steps=[cb.line_no],
                    suggestion=(
                        "반복 횟수 상한을 두거나, PLC 스캔 타임 내에 "
                        "반드시 종료되는 조건을 확인하세요. FOR 루프로 대체도 검토하세요."
                    )
                ))
    return findings


def check_timer_reuse(program: SCLProgram) -> list:
    """S010: 타이머 인스턴스 다중 호출"""
    findings = []

    for tc in program.timer_counters:
        if len(tc.lines_used) > 1:
            findings.append(Finding(
                rule_id="S010",
                severity=Severity.CRITICAL,
                title="타이머/카운터 다중 호출",
                description=(
                    f"타이머 '{tc.name}' ({tc.tc_type})이 {len(tc.lines_used)}곳에서 호출됨 "
                    f"(Line {', '.join(map(str, tc.lines_used))}). "
                    f"마지막 호출만 유효하며 타이밍이 꼬일 수 있습니다."
                ),
                affected_devices=[tc.name],
                affected_steps=tc.lines_used,
                suggestion="각 용도에 별도의 타이머 인스턴스를 선언하세요."
            ))
    return findings


def check_comment_ratio(program: SCLProgram) -> list:
    """S011: 주석 비율"""
    findings = []

    if program.code_lines > 20:
        ratio = program.comment_lines / max(1, program.code_lines) * 100
        if ratio < 5:
            findings.append(Finding(
                rule_id="S011",
                severity=Severity.INFO,
                title=f"주석 부족 (코드 대비 {ratio:.0f}%)",
                description=(
                    f"코드 {program.code_lines}줄에 주석이 {program.comment_lines}줄 ({ratio:.0f}%)입니다. "
                    f"유지보수를 위해 핵심 로직에 주석을 추가하세요."
                ),
                suggestion="REGION 블록, 상태 전환 조건, 계산식에 주석을 달아주세요."
            ))
    return findings


def check_temp_var_abuse(program: SCLProgram) -> list:
    """S012: VAR_TEMP에 상태를 저장하는 패턴"""
    findings = []

    temp_names = {v.name for v in program.temp_vars}

    for var_name in temp_names:
        # TEMP 변수가 읽히는데 같은 스캔에서 먼저 쓰이지 않는 경우
        read_lines = program.var_read_map.get(var_name, [])
        write_lines = program.var_write_map.get(var_name, [])

        if read_lines and (not write_lines or min(read_lines) < min(write_lines)):
            findings.append(Finding(
                rule_id="S012",
                severity=Severity.WARNING,
                title="TEMP 변수 초기화 전 참조",
                description=(
                    f"VAR_TEMP 변수 '{var_name}'이 할당 전에 참조됨 (Line {min(read_lines)}). "
                    f"TEMP 변수는 매 스캔마다 초기화되지 않으므로 불확정 값을 읽을 수 있습니다."
                ),
                affected_devices=[var_name],
                suggestion=f"'{var_name}'을 사용 전에 명시적으로 초기화하거나, VAR/VAR_STAT으로 옮기세요."
            ))
    return findings


def check_direct_output_write(program: SCLProgram) -> list:
    """S013: %Q 직접 주소 출력 (절대 주소 접근)"""
    findings = []

    for asgn in program.assignments:
        if re.match(r'^%[QI]', asgn.target):
            findings.append(Finding(
                rule_id="S013",
                severity=Severity.INFO,
                title="절대 주소 직접 접근",
                description=(
                    f"Line {asgn.line_no}에서 절대 주소 '{asgn.target}'에 직접 할당합니다. "
                    f"심볼릭 변수(VAR_OUTPUT)를 통한 접근이 가독성과 유지보수에 유리합니다."
                ),
                affected_steps=[asgn.line_no],
                suggestion="PLC Tag Table에서 심볼릭 이름을 정의하고, VAR_OUTPUT으로 매핑하세요."
            ))
            break  # 하나만 보고

    return findings


def check_state_machine_pattern(program: SCLProgram) -> list:
    """S014: 상태 머신 패턴 감지 및 개선 제안"""
    findings = []

    # CASE문이 있고, 상태 변수가 있는 패턴
    state_vars = set()
    for cb in program.control_blocks:
        if cb.block_type == "CASE" and cb.condition:
            # CASE condition OF
            cond = cb.condition.strip().strip('"#')
            state_vars.add(cond)

            # CASE 내부에서 ELSE가 있는지는 check_case_without_else에서 처리
            # 여기서는 상태 전환 누락 검사

            # 상태 변수에 할당하는 곳 추적
            if cond in program.var_write_map:
                write_lines = program.var_write_map[cond]
                # 상태 전환이 CASE 블록 밖에서도 일어나는지
                outside_writes = [
                    ln for ln in write_lines
                    if not (cb.line_no <= ln <= cb.end_line)
                ]
                if outside_writes:
                    findings.append(Finding(
                        rule_id="S014",
                        severity=Severity.INFO,
                        title="상태 머신 외부 전환",
                        description=(
                            f"상태 변수 '{cond}'가 CASE 블록(Line {cb.line_no}) 밖에서도 "
                            f"변경됨 (Line {', '.join(map(str, outside_writes))}). "
                            f"상태 전환 추적이 어려울 수 있습니다."
                        ),
                        affected_devices=[cond],
                        suggestion="모든 상태 전환은 CASE 블록 내부에서만 수행하면 흐름을 파악하기 쉽습니다."
                    ))

    return findings


# ============================================================
# 점수 계산
# ============================================================

import re

def _calculate_scores(result: AnalysisResult):
    deductions = {Severity.CRITICAL: 15, Severity.WARNING: 5, Severity.INFO: 1}

    safety_rules = {"S001", "S004", "S005", "S009", "S010"}
    reliability_rules = {"S001", "S004", "S009", "S010", "S012"}
    maintainability_rules = {"S002", "S003", "S006", "S007", "S008", "S011", "S013"}
    efficiency_rules = {"S002", "S003", "S008"}

    for f in result.findings:
        d = deductions.get(f.severity, 0)
        if f.rule_id in safety_rules:
            result.safety_score = max(0, result.safety_score - d)
        if f.rule_id in reliability_rules:
            result.reliability_score = max(0, result.reliability_score - d)
        if f.rule_id in maintainability_rules:
            result.maintainability_score = max(0, result.maintainability_score - d)
        if f.rule_id in efficiency_rules:
            result.efficiency_score = max(0, result.efficiency_score - d)

    result.score = round(
        result.safety_score * 0.35 +
        result.reliability_score * 0.30 +
        result.maintainability_score * 0.20 +
        result.efficiency_score * 0.15
    )


def _generate_summary(result: AnalysisResult, program: SCLProgram) -> str:
    grade = "A" if result.score >= 90 else "B" if result.score >= 75 else "C" if result.score >= 60 else "D" if result.score >= 40 else "F"
    return "\n".join([
        f"종합 점수: {result.score}/100 (등급 {grade})",
        f"  안전성: {result.safety_score}  신뢰성: {result.reliability_score}  유지보수성: {result.maintainability_score}  효율성: {result.efficiency_score}",
        f"  발견 이슈: Critical {result.critical_count}건, Warning {result.warning_count}건, Info {result.info_count}건",
        f"  코드 규모: {program.code_lines}줄 (주석 {program.comment_lines}줄), 중첩 최대 {program.max_nesting}단계",
        f"  변수: IN {len(program.input_vars)}개, OUT {len(program.output_vars)}개, 내부 {len(program.internal_vars)}개, TEMP {len(program.temp_vars)}개",
    ])
