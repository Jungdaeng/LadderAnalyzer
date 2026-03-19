"""
ladder_parser.py
GX Works3 CSV Export 파일을 파싱하여 구조화된 데이터로 변환
"""

import io
import re
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class LadderStep:
    """래더 프로그램의 단일 스텝"""
    step_no: int
    instruction: str
    device: str
    line_statement: str = ""
    note: str = ""
    # 파싱된 정보
    device_type: str = ""       # M, Y, X, T, C, D
    device_number: int = -1
    timer_value: Optional[int] = None   # K값 (타이머/카운터)
    is_contact: bool = False    # 접점 명령 여부
    is_coil: bool = False       # 코일 명령 여부
    rung_index: int = -1        # 소속 Rung 번호


@dataclass
class Rung:
    """래더 프로그램의 하나의 Rung (회로)"""
    index: int
    steps: list = field(default_factory=list)
    start_step: int = 0
    end_step: int = 0
    coil_device: str = ""
    coil_instruction: str = ""
    contacts: list = field(default_factory=list)
    has_self_hold: bool = False


@dataclass
class LadderProgram:
    """파싱된 래더 프로그램 전체"""
    project_name: str = ""
    module_type: str = ""
    steps: list = field(default_factory=list)
    rungs: list = field(default_factory=list)
    total_steps: int = 0

    # 디바이스 사용 통계
    input_devices: set = field(default_factory=set)     # X
    output_devices: set = field(default_factory=set)     # Y
    internal_relays: set = field(default_factory=set)    # M
    timers: set = field(default_factory=set)             # T
    counters: set = field(default_factory=set)           # C
    data_registers: set = field(default_factory=set)     # D

    # 코일 사용 맵: {디바이스: [사용된 step 번호들]}
    coil_map: dict = field(default_factory=dict)
    # 접점 사용 맵: {디바이스: [사용된 step 번호들]}
    contact_map: dict = field(default_factory=dict)


# 접점(읽기) 명령어
CONTACT_INSTRUCTIONS = {"LD", "LDI", "AND", "ANI", "OR", "ORI", "LDP", "LDF", "ANDP", "ANDF", "ORP", "ORF"}

# 코일(쓰기) 명령어
COIL_INSTRUCTIONS = {"OUT", "SET", "RST"}

# 블록 연산 명령어
BLOCK_INSTRUCTIONS = {"ANB", "ORB", "MPS", "MRD", "MPP"}

# 프로그램 제어 명령어
CONTROL_INSTRUCTIONS = {"END", "NOP", "FEND", "RET"}

# Rung 시작 명령어
RUNG_START_INSTRUCTIONS = {"LD", "LDI", "LDP", "LDF"}


def parse_device(device_str: str) -> tuple:
    """디바이스 문자열에서 타입, 번호, 타이머값 추출"""
    device_str = device_str.strip()
    if not device_str:
        return "", -1, None

    # 타이머/카운터: "T0 K50" 형태
    timer_match = re.match(r'^([TCSD])(\d+)\s+K(\d+)$', device_str)
    if timer_match:
        dtype = timer_match.group(1)
        dnum = int(timer_match.group(2))
        kval = int(timer_match.group(3))
        return dtype, dnum, kval

    # 일반 디바이스: "M300", "Y20", "X0" 등
    dev_match = re.match(r'^([MXYZTCD])(\d+)$', device_str)
    if dev_match:
        dtype = dev_match.group(1)
        dnum = int(dev_match.group(2))
        return dtype, dnum, None

    # 특수 디바이스 (SM, SD 등)
    special_match = re.match(r'^(SM|SD|SW)(\d+)$', device_str)
    if special_match:
        dtype = special_match.group(1)
        dnum = int(special_match.group(2))
        return dtype, dnum, None

    return "", -1, None


def detect_encoding(raw_data: bytes) -> str:
    """파일 인코딩 자동 감지"""
    if raw_data[:2] == b'\xff\xfe':
        return 'utf-16-le'
    elif raw_data[:2] == b'\xfe\xff':
        return 'utf-16-be'
    elif raw_data[:3] == b'\xef\xbb\xbf':
        return 'utf-8-sig'
    else:
        # 시도: utf-8 → shift-jis → cp949
        for enc in ['utf-8', 'shift-jis', 'cp949']:
            try:
                raw_data.decode(enc)
                return enc
            except (UnicodeDecodeError, Exception):
                continue
        return 'utf-8'


def parse_csv(file_data: bytes) -> LadderProgram:
    """GX Works3 CSV Export 파일을 파싱"""
    program = LadderProgram()

    # 인코딩 감지 및 디코딩
    encoding = detect_encoding(file_data)
    if encoding == 'utf-16-le':
        text = file_data[2:].decode('utf-16-le')
    elif encoding == 'utf-16-be':
        text = file_data[2:].decode('utf-16-be')
    elif encoding == 'utf-8-sig':
        text = file_data[3:].decode('utf-8')
    else:
        text = file_data.decode(encoding)

    lines = [l for l in text.split('\r\n') if l.strip()]
    if not lines and '\n' in text:
        lines = [l for l in text.split('\n') if l.strip()]

    if len(lines) < 3:
        raise ValueError(f"CSV 파일이 너무 짧습니다 (헤더 3줄 필요, {len(lines)}줄 발견)")

    # 헤더 파싱
    program.project_name = lines[0].replace('"', '').strip('()')
    module_parts = lines[1].split('\t')
    if len(module_parts) >= 2:
        program.module_type = module_parts[1].replace('"', '').strip()

    # 데이터 행 파싱
    rung_index = -1
    current_rung_steps = []

    for line in lines[3:]:
        fields = [f.strip('"') for f in line.split('\t')]
        if len(fields) < 4:
            continue

        try:
            step_no = int(fields[0])
        except ValueError:
            continue

        instruction = fields[2].strip()
        device_raw = fields[3].strip()
        line_stmt = fields[1].strip() if len(fields) > 1 else ""
        note = fields[6].strip() if len(fields) > 6 else ""

        # 디바이스 파싱
        device_type, device_number, timer_value = parse_device(device_raw)

        # Rung 시작 감지
        if instruction in RUNG_START_INSTRUCTIONS:
            if current_rung_steps:
                _finalize_rung(program, rung_index, current_rung_steps)
            rung_index += 1
            current_rung_steps = []

        step = LadderStep(
            step_no=step_no,
            instruction=instruction,
            device=device_raw,
            line_statement=line_stmt,
            note=note,
            device_type=device_type,
            device_number=device_number,
            timer_value=timer_value,
            is_contact=instruction in CONTACT_INSTRUCTIONS,
            is_coil=instruction in COIL_INSTRUCTIONS,
            rung_index=rung_index
        )

        program.steps.append(step)
        current_rung_steps.append(step)

        # 디바이스 분류
        base_device = f"{device_type}{device_number}" if device_type and device_number >= 0 else ""
        if base_device:
            if device_type == 'X':
                program.input_devices.add(base_device)
            elif device_type == 'Y':
                program.output_devices.add(base_device)
            elif device_type == 'M':
                program.internal_relays.add(base_device)
            elif device_type == 'T':
                program.timers.add(base_device)
            elif device_type == 'C':
                program.counters.add(base_device)
            elif device_type == 'D':
                program.data_registers.add(base_device)

            # 접점/코일 맵 업데이트
            if step.is_contact:
                program.contact_map.setdefault(base_device, []).append(step_no)
            if step.is_coil:
                program.coil_map.setdefault(base_device, []).append(step_no)

    # 마지막 Rung 마무리
    if current_rung_steps:
        _finalize_rung(program, rung_index, current_rung_steps)

    program.total_steps = len(program.steps)
    return program


def _finalize_rung(program: LadderProgram, rung_index: int, steps: list):
    """Rung 객체 생성 및 분석"""
    rung = Rung(
        index=rung_index,
        steps=list(steps),
        start_step=steps[0].step_no,
        end_step=steps[-1].step_no
    )

    # 코일/접점 분류
    for s in steps:
        if s.is_coil:
            rung.coil_device = s.device
            rung.coil_instruction = s.instruction
        if s.is_contact:
            base = f"{s.device_type}{s.device_number}" if s.device_type else s.device
            rung.contacts.append(base)

    # 자기유지 검출: 코일 디바이스가 같은 Rung에서 접점으로도 사용
    coil_base = ""
    if rung.coil_device:
        dt, dn, _ = parse_device(rung.coil_device)
        coil_base = f"{dt}{dn}" if dt else rung.coil_device

    if coil_base and coil_base in rung.contacts:
        for s in steps:
            if s.is_contact and f"{s.device_type}{s.device_number}" == coil_base and s.instruction == "OR":
                rung.has_self_hold = True
                break

    program.rungs.append(rung)


def program_to_text(program: LadderProgram) -> str:
    """프로그램을 읽기 쉬운 텍스트로 변환"""
    lines = []
    lines.append(f"Project: {program.project_name}")
    lines.append(f"Module: {program.module_type}")
    lines.append(f"Total Steps: {program.total_steps}")
    lines.append(f"Total Rungs: {len(program.rungs)}")
    lines.append("")
    lines.append("=== Program Listing ===")

    for step in program.steps:
        prefix = "→ " if step.is_coil else "  "
        lines.append(f"{prefix}Step {step.step_no:>4}: {step.instruction:5} {step.device}")

    return "\n".join(lines)
