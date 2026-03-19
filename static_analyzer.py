"""
static_analyzer.py
룰 기반 정적 분석 엔진 - AI 없이 자동 검출 가능한 문제들
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional
from ladder_parser import LadderProgram, COIL_INSTRUCTIONS, CONTACT_INSTRUCTIONS


class Severity(Enum):
    CRITICAL = "CRITICAL"
    WARNING = "WARNING"
    INFO = "INFO"


@dataclass
class Finding:
    """분석에서 발견된 하나의 이슈"""
    rule_id: str
    severity: Severity
    title: str
    description: str
    affected_devices: list = field(default_factory=list)
    affected_steps: list = field(default_factory=list)
    suggestion: str = ""


@dataclass
class AnalysisResult:
    """전체 분석 결과"""
    findings: list = field(default_factory=list)
    score: int = 100  # 100점 만점
    summary: str = ""

    # 카테고리별 점수
    safety_score: int = 100
    reliability_score: int = 100
    maintainability_score: int = 100
    efficiency_score: int = 100

    @property
    def critical_count(self):
        return sum(1 for f in self.findings if f.severity == Severity.CRITICAL)

    @property
    def warning_count(self):
        return sum(1 for f in self.findings if f.severity == Severity.WARNING)

    @property
    def info_count(self):
        return sum(1 for f in self.findings if f.severity == Severity.INFO)


def analyze(program: LadderProgram) -> AnalysisResult:
    """프로그램 전체 정적 분석 수행"""
    result = AnalysisResult()

    # 모든 규칙 실행
    rules = [
        check_double_coil,
        check_end_instruction,
        check_unused_coils,
        check_unused_contacts,
        check_set_rst_mismatch,
        check_timer_duplicate,
        check_self_hold_missing,
        check_emergency_stop,
        check_output_as_contact,
        check_empty_rung,
        check_scan_order,
        check_device_range,
        check_program_size,
        check_nested_complexity,
    ]

    for rule in rules:
        findings = rule(program)
        result.findings.extend(findings)

    # 점수 계산
    _calculate_scores(result)

    # 요약 생성
    result.summary = _generate_summary(result, program)

    return result


# ============================================================
# 개별 분석 규칙
# ============================================================

def check_double_coil(program: LadderProgram) -> list:
    """R001: 이중 코일 검출"""
    findings = []
    for device, steps in program.coil_map.items():
        if len(steps) > 1:
            findings.append(Finding(
                rule_id="R001",
                severity=Severity.CRITICAL,
                title="이중 코일 (Double Coil)",
                description=(
                    f"디바이스 {device}가 {len(steps)}개의 코일 명령에서 사용됨 "
                    f"(Step {', '.join(map(str, steps))}). "
                    f"PLC 스캔 시 나중에 실행되는 코일이 앞의 결과를 덮어씀."
                ),
                affected_devices=[device],
                affected_steps=steps,
                suggestion=(
                    f"자기유지(Self-Hold) 패턴으로 {device}를 단일 OUT 코일로 통합하세요. "
                    f"SET/RST 대신 (시작조건 OR {device}) AND (해제조건 반전) → OUT {device} 구조를 사용하세요."
                )
            ))
    return findings


def check_end_instruction(program: LadderProgram) -> list:
    """R002: END 명령 존재 여부"""
    findings = []
    has_end = any(s.instruction == "END" for s in program.steps)
    if not has_end:
        findings.append(Finding(
            rule_id="R002",
            severity=Severity.CRITICAL,
            title="END 명령 누락",
            description="프로그램에 END 명령이 없습니다. PLC가 정상 실행되지 않을 수 있습니다.",
            suggestion="프로그램 마지막에 END 명령을 추가하세요."
        ))
    else:
        # END가 마지막이 아닌 경우
        end_steps = [s for s in program.steps if s.instruction == "END"]
        last_step = program.steps[-1] if program.steps else None
        if last_step and last_step.instruction != "END":
            findings.append(Finding(
                rule_id="R002b",
                severity=Severity.WARNING,
                title="END 이후 코드 존재",
                description=f"END 명령(Step {end_steps[0].step_no}) 뒤에 추가 코드가 있습니다.",
                suggestion="END 이후의 코드는 실행되지 않습니다. 의도한 것인지 확인하세요."
            ))
    return findings


def check_unused_coils(program: LadderProgram) -> list:
    """R003: 코일은 있지만 접점으로 사용되지 않는 디바이스"""
    findings = []
    for device in program.coil_map:
        if device not in program.contact_map:
            # Y(외부출력)는 접점으로 안 써도 정상
            if not device.startswith('Y') and not device.startswith('T'):
                findings.append(Finding(
                    rule_id="R003",
                    severity=Severity.WARNING,
                    title="미사용 코일 출력",
                    description=f"디바이스 {device}에 코일이 있지만, 프로그램 내에서 접점으로 참조되지 않습니다.",
                    affected_devices=[device],
                    suggestion=f"{device}가 실제로 필요한 디바이스인지 확인하세요. 불필요하면 제거하여 프로그램을 단순화하세요."
                ))
    return findings


def check_unused_contacts(program: LadderProgram) -> list:
    """R004: 접점으로 사용되지만 코일이 없는 내부 디바이스"""
    findings = []
    for device in program.contact_map:
        if device not in program.coil_map:
            # X(외부입력)는 코일이 없어도 정상
            if not device.startswith('X') and not device.startswith('SM'):
                findings.append(Finding(
                    rule_id="R004",
                    severity=Severity.INFO,
                    title="코일 없는 접점 참조",
                    description=(
                        f"디바이스 {device}가 접점으로 사용되지만 프로그램 내에서 코일로 구동되지 않습니다. "
                        f"외부 입력이거나 다른 프로그램 블록에서 제어될 수 있습니다."
                    ),
                    affected_devices=[device],
                    suggestion=f"{device}가 외부 입력(X)이 아니라면, 해당 디바이스를 구동하는 로직이 있는지 확인하세요."
                ))
    return findings


def check_set_rst_mismatch(program: LadderProgram) -> list:
    """R005: SET만 있고 RST가 없는 디바이스 (래치 해제 불가)"""
    findings = []
    set_devices = set()
    rst_devices = set()

    for step in program.steps:
        if step.instruction == "SET" and step.device_type:
            set_devices.add(f"{step.device_type}{step.device_number}")
        elif step.instruction == "RST" and step.device_type:
            rst_devices.add(f"{step.device_type}{step.device_number}")

    for dev in set_devices - rst_devices:
        findings.append(Finding(
            rule_id="R005",
            severity=Severity.WARNING,
            title="SET without RST (래치 해제 불가)",
            description=f"디바이스 {dev}에 SET 명령만 있고 RST가 없습니다. 한번 ON되면 해제할 수 없습니다.",
            affected_devices=[dev],
            suggestion=f"{dev}를 OFF할 수 있는 RST 조건을 추가하거나, 자기유지+OUT 패턴으로 변경하세요."
        ))

    return findings


def check_timer_duplicate(program: LadderProgram) -> list:
    """R006: 같은 타이머 번호를 여러 곳에서 OUT"""
    findings = []
    timer_outs = {}

    for step in program.steps:
        if step.instruction == "OUT" and step.device_type == "T":
            key = f"T{step.device_number}"
            timer_outs.setdefault(key, []).append(step.step_no)

    for timer, steps in timer_outs.items():
        if len(steps) > 1:
            findings.append(Finding(
                rule_id="R006",
                severity=Severity.CRITICAL,
                title="타이머 번호 중복 사용",
                description=f"타이머 {timer}가 {len(steps)}곳에서 OUT됨 (Step {', '.join(map(str, steps))}). 타이머 동작이 불안정해집니다.",
                affected_devices=[timer],
                affected_steps=steps,
                suggestion=f"각 용도에 서로 다른 타이머 번호를 할당하세요."
            ))
    return findings


def check_self_hold_missing(program: LadderProgram) -> list:
    """R007: OUT 코일인데 자기유지 패턴이 없는 내부 릴레이"""
    findings = []

    for rung in program.rungs:
        if not rung.coil_device:
            continue
        if rung.coil_instruction != "OUT":
            continue

        # 내부 릴레이(M)만 체크
        from ladder_parser import parse_device
        dt, dn, _ = parse_device(rung.coil_device)
        if dt != 'M':
            continue

        if not rung.has_self_hold:
            device = f"{dt}{dn}"
            findings.append(Finding(
                rule_id="R007",
                severity=Severity.INFO,
                title="자기유지 미적용",
                description=(
                    f"내부 릴레이 {device} (Rung {rung.index})에 자기유지 패턴이 없습니다. "
                    f"입력 조건이 해제되면 즉시 OFF됩니다."
                ),
                affected_devices=[device],
                suggestion=(
                    f"상태를 유지해야 한다면 자기유지 패턴을 적용하세요: "
                    f"(시작조건 OR {device}) AND (해제조건 반전) → OUT {device}"
                )
            ))
    return findings


def check_emergency_stop(program: LadderProgram) -> list:
    """R008: 비상정지 / 전체 OFF 조건 존재 여부"""
    findings = []

    # 모든 Y 출력을 OFF할 수 있는 공통 조건이 있는지 검사
    y_devices = [d for d in program.coil_map if d.startswith('Y')]
    if not y_devices:
        return findings

    # 각 Y 출력의 Rung에서 공통 접점 찾기
    y_rung_contacts = {}
    for rung in program.rungs:
        if rung.coil_device and rung.coil_device.startswith('Y'):
            y_rung_contacts[rung.coil_device] = set(rung.contacts)
        elif rung.coil_device:
            from ladder_parser import parse_device
            dt, dn, _ = parse_device(rung.coil_device)
            base = f"{dt}{dn}"
            # Y에 매핑되는 M도 추적
            for yrung in program.rungs:
                if yrung.coil_device and yrung.coil_device.startswith('Y'):
                    if base in yrung.contacts:
                        y_rung_contacts.setdefault(yrung.coil_device, set()).update(rung.contacts)

    if len(y_rung_contacts) < 2:
        return findings

    # 모든 Y 출력 Rung에 공통으로 존재하는 접점
    all_contact_sets = list(y_rung_contacts.values())
    if all_contact_sets:
        common = all_contact_sets[0]
        for s in all_contact_sets[1:]:
            common = common & s

        if not common:
            findings.append(Finding(
                rule_id="R008",
                severity=Severity.WARNING,
                title="비상정지 / 전체 정지 조건 미검출",
                description=(
                    f"모든 출력({', '.join(y_devices)})을 동시에 OFF할 수 있는 공통 조건이 발견되지 않았습니다. "
                    f"비상 상황에서 모든 출력을 즉시 차단할 수 있어야 합니다."
                ),
                suggestion="모든 출력 로직에 공통 비상정지 접점(예: X0 = 비상정지 버튼)을 AND 조건으로 추가하세요."
            ))
    return findings


def check_output_as_contact(program: LadderProgram) -> list:
    """R009: Y(외부출력)를 접점으로 사용"""
    findings = []
    for device, steps in program.contact_map.items():
        if device.startswith('Y'):
            findings.append(Finding(
                rule_id="R009",
                severity=Severity.INFO,
                title="외부 출력을 접점으로 사용",
                description=(
                    f"외부 출력 {device}가 접점(읽기)으로 사용됨 (Step {', '.join(map(str, steps))}). "
                    f"동작은 하지만, 출력 응답 지연으로 인해 비권장 패턴입니다."
                ),
                affected_devices=[device],
                affected_steps=steps,
                suggestion=f"내부 릴레이(M)를 중간 플래그로 사용하고, {device}는 최종 출력에서만 OUT하세요."
            ))
    return findings


def check_empty_rung(program: LadderProgram) -> list:
    """R010: 접점 없이 코일만 있는 Rung"""
    findings = []
    for rung in program.rungs:
        has_contact = any(s.is_contact for s in rung.steps)
        has_coil = any(s.is_coil for s in rung.steps)

        if has_coil and not has_contact:
            # END는 제외
            if rung.coil_instruction == "END" or rung.steps[0].instruction == "END":
                continue
            findings.append(Finding(
                rule_id="R010",
                severity=Severity.CRITICAL,
                title="접점 없는 코일",
                description=f"Rung {rung.index} (Step {rung.start_step})에 접점(입력 조건) 없이 코일만 존재합니다.",
                affected_steps=[rung.start_step],
                suggestion="코일 앞에 적절한 입력 조건(접점)을 추가하세요."
            ))
    return findings


def check_scan_order(program: LadderProgram) -> list:
    """R011: 스캔 순서 - 코일보다 접점이 뒤에 있는 경우"""
    findings = []

    # 각 디바이스의 첫 번째 코일 위치
    first_coil = {}
    for step in program.steps:
        if step.is_coil and step.device_type:
            base = f"{step.device_type}{step.device_number}"
            if base not in first_coil:
                first_coil[base] = step.step_no

    # 접점이 코일보다 앞에 있는 경우 (정상이 아닌, 코일 뒤에 접점이 있는 경우를 찾음)
    for step in program.steps:
        if step.is_contact and step.device_type:
            base = f"{step.device_type}{step.device_number}"
            if base in first_coil and step.step_no < first_coil[base]:
                # 내부 릴레이만 체크 (X, T는 정상적으로 코일 전에 참조 가능)
                if step.device_type == 'M':
                    findings.append(Finding(
                        rule_id="R011",
                        severity=Severity.INFO,
                        title="스캔 순서 참고",
                        description=(
                            f"내부 릴레이 {base}가 Step {step.step_no}에서 접점으로 사용되지만, "
                            f"코일은 Step {first_coil[base]}에서 정의됩니다. "
                            f"첫 스캔 시 이전 값을 사용하게 됩니다."
                        ),
                        affected_devices=[base],
                        suggestion="동작에 문제가 없다면 무시해도 되지만, 초기 1스캔 지연이 있을 수 있습니다."
                    ))
                    break  # 디바이스당 1회만 보고
    return findings


def check_device_range(program: LadderProgram) -> list:
    """R012: 시스템 예약 영역 디바이스 사용"""
    findings = []
    system_m_used = []

    for step in program.steps:
        if step.is_coil and step.device_type == 'M' and 0 <= step.device_number < 100:
            system_m_used.append(f"M{step.device_number}")

    if system_m_used:
        unique = list(set(system_m_used))
        findings.append(Finding(
            rule_id="R012",
            severity=Severity.INFO,
            title="낮은 번호 내부 릴레이 코일 사용",
            description=(
                f"M0~M99 영역의 디바이스({', '.join(unique)})를 코일로 사용 중입니다. "
                f"이 영역은 시스템에서 사용하거나, 외부 스위치 입력으로 쓰는 경우가 많습니다."
            ),
            affected_devices=unique,
            suggestion="상태 플래그는 M300 이상, 중간 연산용은 M400 이상 사용을 권장합니다."
        ))
    return findings


def check_program_size(program: LadderProgram) -> list:
    """R013: 프로그램 규모 분석"""
    findings = []

    if program.total_steps > 500:
        findings.append(Finding(
            rule_id="R013",
            severity=Severity.INFO,
            title="대규모 프로그램",
            description=f"프로그램이 {program.total_steps}스텝으로 비교적 큽니다. 모듈화를 고려하세요.",
            suggestion="기능별로 서브루틴(CALL)이나 별도 프로그램 블록으로 분리하면 유지보수성이 향상됩니다."
        ))

    if len(program.rungs) > 50:
        findings.append(Finding(
            rule_id="R013b",
            severity=Severity.INFO,
            title="Rung 수 과다",
            description=f"프로그램에 {len(program.rungs)}개의 Rung이 있습니다.",
            suggestion="관련 로직을 그룹화하고, 라벨/코멘트를 활용하여 가독성을 높이세요."
        ))
    return findings


def check_nested_complexity(program: LadderProgram) -> list:
    """R014: Rung 내 복잡도 (명령어 수)"""
    findings = []

    for rung in program.rungs:
        if len(rung.steps) > 15:
            findings.append(Finding(
                rule_id="R014",
                severity=Severity.WARNING,
                title="복잡한 Rung",
                description=(
                    f"Rung {rung.index} (Step {rung.start_step}~{rung.end_step})에 "
                    f"{len(rung.steps)}개의 명령어가 있습니다. 디버깅이 어려울 수 있습니다."
                ),
                suggestion="복잡한 조건은 중간 릴레이(M)로 분리하여 각 Rung을 단순화하세요."
            ))
    return findings


# ============================================================
# 점수 계산
# ============================================================

def _calculate_scores(result: AnalysisResult):
    """발견된 이슈를 기반으로 점수 계산"""
    deductions = {
        Severity.CRITICAL: 15,
        Severity.WARNING: 5,
        Severity.INFO: 1,
    }

    # 카테고리별 매핑
    safety_rules = {"R001", "R002", "R008", "R010"}
    reliability_rules = {"R001", "R005", "R006", "R011"}
    maintainability_rules = {"R003", "R004", "R007", "R009", "R012", "R013", "R013b", "R014"}
    efficiency_rules = {"R003", "R013", "R013b", "R014"}

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

    result.score = (
        result.safety_score * 0.35 +
        result.reliability_score * 0.30 +
        result.maintainability_score * 0.20 +
        result.efficiency_score * 0.15
    )
    result.score = round(result.score)


def _generate_summary(result: AnalysisResult, program: LadderProgram) -> str:
    """분석 결과 요약 텍스트 생성"""
    lines = []

    grade = "A" if result.score >= 90 else "B" if result.score >= 75 else "C" if result.score >= 60 else "D" if result.score >= 40 else "F"

    lines.append(f"종합 점수: {result.score}/100 (등급 {grade})")
    lines.append(f"  안전성: {result.safety_score}  신뢰성: {result.reliability_score}  유지보수성: {result.maintainability_score}  효율성: {result.efficiency_score}")
    lines.append(f"  발견 이슈: Critical {result.critical_count}건, Warning {result.warning_count}건, Info {result.info_count}건")
    lines.append(f"  프로그램 규모: {program.total_steps}스텝, {len(program.rungs)}Rung")
    lines.append(f"  디바이스: 입력 {len(program.input_devices)}개, 출력 {len(program.output_devices)}개, "
                 f"내부릴레이 {len(program.internal_relays)}개, 타이머 {len(program.timers)}개")

    return "\n".join(lines)
