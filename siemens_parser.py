"""
siemens_parser.py
Siemens TIA Portal SCL (Structured Control Language) Export 파일 파싱
SCL = IEC 61131-3 Structured Text (ST) 기반 고급 언어
"""

import re
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Variable:
    """변수 정의"""
    name: str
    data_type: str
    section: str = ""       # VAR_INPUT, VAR_OUTPUT, VAR, VAR_TEMP, VAR_STAT
    initial_value: str = ""
    comment: str = ""
    line_no: int = 0


@dataclass
class Assignment:
    """할당문 (:=)"""
    target: str             # 할당 대상
    expression: str         # 우변 표현식
    line_no: int = 0
    in_branch: str = ""     # IF/CASE 분기 내부인지
    nesting_depth: int = 0


@dataclass
class ControlBlock:
    """제어 구조 (IF/CASE/FOR/WHILE/REPEAT)"""
    block_type: str         # IF, CASE, FOR, WHILE, REPEAT
    condition: str = ""
    line_no: int = 0
    end_line: int = 0
    has_else: bool = False
    nesting_depth: int = 0
    body_lines: int = 0


@dataclass
class TimerCounter:
    """타이머/카운터 인스턴스 사용"""
    name: str
    tc_type: str            # TON, TOF, TP, CTU, CTD, CTUD
    preset: str = ""        # T#5S 등
    lines_used: list = field(default_factory=list)


@dataclass
class FunctionCall:
    """함수/FB 호출"""
    name: str
    line_no: int = 0
    arguments: str = ""


@dataclass
class SCLProgram:
    """파싱된 SCL 프로그램"""
    block_type: str = ""        # FUNCTION_BLOCK, FUNCTION, ORGANIZATION_BLOCK, DATA_BLOCK
    block_name: str = ""
    title: str = ""
    raw_lines: list = field(default_factory=list)
    total_lines: int = 0
    code_lines: int = 0         # 실제 코드 줄 수 (빈줄/주석 제외)
    comment_lines: int = 0

    # 파싱 결과
    variables: list = field(default_factory=list)
    assignments: list = field(default_factory=list)
    control_blocks: list = field(default_factory=list)
    timer_counters: list = field(default_factory=list)
    function_calls: list = field(default_factory=list)

    # 분류
    input_vars: list = field(default_factory=list)
    output_vars: list = field(default_factory=list)
    internal_vars: list = field(default_factory=list)
    temp_vars: list = field(default_factory=list)
    static_vars: list = field(default_factory=list)

    # 사용 맵
    var_write_map: dict = field(default_factory=dict)   # {변수: [할당 줄 번호]}
    var_read_map: dict = field(default_factory=dict)    # {변수: [참조 줄 번호]}

    # 메트릭
    max_nesting: int = 0
    magic_numbers: list = field(default_factory=list)   # [(줄번호, 값)]


def parse_scl(file_data: bytes) -> SCLProgram:
    """SCL 파일 파싱"""
    program = SCLProgram()

    # 인코딩 감지
    text = ""
    for enc in ['utf-8-sig', 'utf-8', 'utf-16', 'iso-8859-1', 'cp1252', 'cp949']:
        try:
            text = file_data.decode(enc)
            break
        except (UnicodeDecodeError, Exception):
            continue

    if not text:
        raise ValueError("파일 인코딩을 감지할 수 없습니다.")

    lines = text.splitlines()
    program.raw_lines = lines
    program.total_lines = len(lines)

    # 1단계: 블록 헤더 파싱
    _parse_block_header(program, lines)

    # 2단계: 변수 선언 파싱
    _parse_variable_declarations(program, lines)

    # 3단계: 코드 본문 파싱
    _parse_code_body(program, lines)

    return program


def _parse_block_header(program: SCLProgram, lines: list):
    """블록 타입, 이름, 타이틀 파싱"""
    for line in lines:
        stripped = line.strip()

        block_match = re.match(
            r'^(FUNCTION_BLOCK|FUNCTION|ORGANIZATION_BLOCK|DATA_BLOCK|TYPE)\s+"?([^"]*)"?',
            stripped, re.IGNORECASE
        )
        if block_match:
            program.block_type = block_match.group(1).upper()
            program.block_name = block_match.group(2)
            continue

        title_match = re.match(r'^\{\s*S7_Optimized_Access\s*:=', stripped)
        if not title_match:
            title_match2 = re.match(r'^TITLE\s*=\s*(.*)', stripped, re.IGNORECASE)
            if title_match2 and not program.title:
                program.title = title_match2.group(1).strip()


def _parse_variable_declarations(program: SCLProgram, lines: list):
    """VAR 섹션 파싱"""
    current_section = ""
    var_sections = {"VAR_INPUT", "VAR_OUTPUT", "VAR_IN_OUT", "VAR", "VAR_TEMP", "VAR_STAT"}

    for line_no, line in enumerate(lines, 1):
        stripped = line.strip()
        upper = stripped.upper()

        # 섹션 시작/종료
        if upper in var_sections:
            current_section = upper
            continue
        if upper == "END_VAR":
            current_section = ""
            continue

        if not current_section:
            continue

        # 변수 선언: name : Type := initial; // comment
        var_match = re.match(
            r'^"?([^":]+)"?\s*:\s*([^;:=]+?)(?:\s*:=\s*([^;]*))?\s*;?\s*(?://\s*(.*))?$',
            stripped
        )
        if var_match:
            name = var_match.group(1).strip().strip('"')
            dtype = var_match.group(2).strip()
            init_val = (var_match.group(3) or "").strip()
            comment = (var_match.group(4) or "").strip()

            var = Variable(
                name=name,
                data_type=dtype,
                section=current_section,
                initial_value=init_val,
                comment=comment,
                line_no=line_no
            )
            program.variables.append(var)

            # 섹션별 분류
            if current_section == "VAR_INPUT":
                program.input_vars.append(var)
            elif current_section == "VAR_OUTPUT":
                program.output_vars.append(var)
            elif current_section == "VAR_TEMP":
                program.temp_vars.append(var)
            elif current_section == "VAR_STAT":
                program.static_vars.append(var)
            else:
                program.internal_vars.append(var)


def _parse_code_body(program: SCLProgram, lines: list):
    """BEGIN ~ END 사이 코드 본문 파싱"""
    in_code = False
    nesting_depth = 0
    current_branch = ""

    for line_no, line in enumerate(lines, 1):
        stripped = line.strip()
        upper = stripped.upper()

        # 코드 영역 시작/종료
        if upper == "BEGIN":
            in_code = True
            continue
        if re.match(r'^END_(FUNCTION_BLOCK|FUNCTION|ORGANIZATION_BLOCK|DATA_BLOCK|TYPE)', upper):
            break

        if not in_code:
            continue

        # 줄 분류
        if not stripped:
            continue
        if stripped.startswith("//"):
            program.comment_lines += 1
            continue

        # 인라인 주석 제거 (문자열 내부 제외 - 간이 처리)
        code_part = stripped
        if "//" in code_part:
            # 문자열 밖의 // 찾기
            in_str = False
            for i, c in enumerate(code_part):
                if c == "'":
                    in_str = not in_str
                if not in_str and code_part[i:i+2] == "//":
                    code_part = code_part[:i].strip()
                    program.comment_lines += 1
                    break

        program.code_lines += 1

        # 제어 구조 감지
        if re.match(r'^IF\b', code_part, re.IGNORECASE):
            cond = re.match(r'^IF\s+(.+?)\s+THEN', code_part, re.IGNORECASE)
            nesting_depth += 1
            program.max_nesting = max(program.max_nesting, nesting_depth)
            cb = ControlBlock(
                block_type="IF",
                condition=cond.group(1) if cond else "",
                line_no=line_no,
                nesting_depth=nesting_depth
            )
            program.control_blocks.append(cb)
            current_branch = f"IF@{line_no}"

        elif re.match(r'^ELSIF\b', code_part, re.IGNORECASE):
            current_branch = f"ELSIF@{line_no}"

        elif re.match(r'^ELSE\b', code_part, re.IGNORECASE):
            # 가장 최근 IF에 has_else 표시
            for cb in reversed(program.control_blocks):
                if cb.block_type == "IF" and not cb.has_else:
                    cb.has_else = True
                    break
            current_branch = f"ELSE@{line_no}"

        elif re.match(r'^END_IF', code_part, re.IGNORECASE):
            nesting_depth = max(0, nesting_depth - 1)
            for cb in reversed(program.control_blocks):
                if cb.block_type == "IF" and cb.end_line == 0:
                    cb.end_line = line_no
                    cb.body_lines = line_no - cb.line_no
                    break
            current_branch = ""

        elif re.match(r'^CASE\b', code_part, re.IGNORECASE):
            cond = re.match(r'^CASE\s+(.+?)\s+OF', code_part, re.IGNORECASE)
            nesting_depth += 1
            program.max_nesting = max(program.max_nesting, nesting_depth)
            cb = ControlBlock(
                block_type="CASE",
                condition=cond.group(1) if cond else "",
                line_no=line_no,
                nesting_depth=nesting_depth
            )
            program.control_blocks.append(cb)

        elif re.match(r'^END_CASE', code_part, re.IGNORECASE):
            nesting_depth = max(0, nesting_depth - 1)
            for cb in reversed(program.control_blocks):
                if cb.block_type == "CASE" and cb.end_line == 0:
                    cb.end_line = line_no
                    cb.body_lines = line_no - cb.line_no
                    break

        elif re.match(r'^FOR\b', code_part, re.IGNORECASE):
            nesting_depth += 1
            program.max_nesting = max(program.max_nesting, nesting_depth)
            program.control_blocks.append(ControlBlock(
                block_type="FOR", line_no=line_no, nesting_depth=nesting_depth))

        elif re.match(r'^END_FOR', code_part, re.IGNORECASE):
            nesting_depth = max(0, nesting_depth - 1)

        elif re.match(r'^WHILE\b', code_part, re.IGNORECASE):
            cond = re.match(r'^WHILE\s+(.+?)\s+DO', code_part, re.IGNORECASE)
            nesting_depth += 1
            program.max_nesting = max(program.max_nesting, nesting_depth)
            program.control_blocks.append(ControlBlock(
                block_type="WHILE",
                condition=cond.group(1) if cond else "",
                line_no=line_no,
                nesting_depth=nesting_depth
            ))

        elif re.match(r'^END_WHILE', code_part, re.IGNORECASE):
            nesting_depth = max(0, nesting_depth - 1)

        elif re.match(r'^REPEAT\b', code_part, re.IGNORECASE):
            nesting_depth += 1
            program.max_nesting = max(program.max_nesting, nesting_depth)
            program.control_blocks.append(ControlBlock(
                block_type="REPEAT", line_no=line_no, nesting_depth=nesting_depth))

        elif re.match(r'^UNTIL\b', code_part, re.IGNORECASE):
            nesting_depth = max(0, nesting_depth - 1)

        # 할당문 감지: target := expression;
        assign_match = re.match(r'^"?([^":=]+?)"?\s*:=\s*(.+?)(?:;|$)', code_part)
        if assign_match:
            target = assign_match.group(1).strip().strip('"')
            expr = assign_match.group(2).strip().rstrip(';')

            program.assignments.append(Assignment(
                target=target,
                expression=expr,
                line_no=line_no,
                in_branch=current_branch,
                nesting_depth=nesting_depth
            ))

            # 쓰기 맵 업데이트
            program.var_write_map.setdefault(target, []).append(line_no)

            # 읽기 맵 - 우변에서 참조되는 변수들
            _extract_references(program, expr, line_no)

        # 타이머/카운터 호출 감지
        tc_match = re.match(
            r'^"?([^"(]+)"?\s*\(\s*IN\s*:=\s*(.+?)\s*,\s*PT\s*:=\s*(.+?)\s*\)',
            code_part, re.IGNORECASE
        )
        if tc_match:
            tc_name = tc_match.group(1).strip().strip('"')
            tc_preset = tc_match.group(3).strip()
            # 타이머 타입은 변수 선언에서 찾기
            tc_type = ""
            for v in program.variables:
                if v.name == tc_name:
                    tc_type = v.data_type
                    break

            existing = None
            for tc in program.timer_counters:
                if tc.name == tc_name:
                    existing = tc
                    break

            if existing:
                existing.lines_used.append(line_no)
            else:
                program.timer_counters.append(TimerCounter(
                    name=tc_name, tc_type=tc_type, preset=tc_preset,
                    lines_used=[line_no]
                ))

        # 함수 호출 감지 (할당의 우변이 아닌 독립 호출)
        func_match = re.match(r'^"?([A-Za-z_][^"(]*)"?\s*\(', code_part)
        if func_match and not assign_match and not tc_match:
            fname = func_match.group(1).strip().strip('"')
            if fname.upper() not in ('IF', 'CASE', 'FOR', 'WHILE', 'REPEAT'):
                program.function_calls.append(FunctionCall(
                    name=fname, line_no=line_no
                ))

        # 매직 넘버 감지 (할당문에서 리터럴 숫자)
        if assign_match:
            expr = assign_match.group(2)
            numbers = re.findall(r'(?<![A-Za-z_#])(\d+\.?\d*)(?![A-Za-z_])', expr)
            for num_str in numbers:
                try:
                    num = float(num_str)
                    if num not in (0, 1, -1, 0.0, 1.0, True, False):
                        program.magic_numbers.append((line_no, num_str))
                except ValueError:
                    pass

        # 변수 읽기 참조 (접점 역할) - IF/WHILE 조건에서
        for cb in program.control_blocks:
            if cb.line_no == line_no and cb.condition:
                _extract_references(program, cb.condition, line_no)


def _extract_references(program: SCLProgram, expression: str, line_no: int):
    """표현식에서 변수 참조 추출"""
    # 간이 토크나이저: 따옴표로 감싼 이름이나 식별자 추출
    identifiers = re.findall(r'"([^"]+)"', expression)
    identifiers += re.findall(r'\b([A-Za-z_]\w*)\b', expression)

    # 키워드 제외
    keywords = {'TRUE', 'FALSE', 'AND', 'OR', 'NOT', 'XOR', 'MOD',
                'INT', 'REAL', 'BOOL', 'DINT', 'TIME', 'STRING',
                'TO_INT', 'TO_REAL', 'TO_BOOL', 'ABS', 'MAX', 'MIN',
                'IN', 'PT', 'Q', 'ET', 'THEN', 'DO', 'OF', 'T'}

    for ident in identifiers:
        if ident.upper() not in keywords and not ident.isdigit():
            program.var_read_map.setdefault(ident, []).append(line_no)


def program_to_text_siemens(program: SCLProgram) -> str:
    """프로그램 요약 텍스트"""
    lines = []
    lines.append(f"Block: {program.block_type} \"{program.block_name}\"")
    if program.title:
        lines.append(f"Title: {program.title}")
    lines.append(f"Lines: {program.total_lines} total, {program.code_lines} code, {program.comment_lines} comment")
    lines.append(f"Variables: {len(program.variables)} ({len(program.input_vars)} IN, {len(program.output_vars)} OUT, {len(program.internal_vars)} internal)")
    lines.append(f"Control Blocks: {len(program.control_blocks)} (max nesting: {program.max_nesting})")
    lines.append(f"Assignments: {len(program.assignments)}")
    lines.append(f"Timers/Counters: {len(program.timer_counters)}")
    lines.append("")
    lines.append("=== Source Code ===")

    for i, line in enumerate(program.raw_lines, 1):
        lines.append(f"  {i:>4}: {line}")

    return "\n".join(lines)
