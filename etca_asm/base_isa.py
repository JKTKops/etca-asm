from bitarray import bitarray
from bitarray.util import int2ba

from etca_asm.core import Extension, reject, resolve_register_size

base = Extension(None, "base", "Base Instruction Set", True)


@base.set_init
def base_init(context):
    context.__dict__.setdefault('default_size', 'x')
    context.__dict__.setdefault('register_sizes', {})['x'] = 1


INSTRUCTIONS = {
    "add": 0x0,
    "sub": 0x1,
    "rsub": 0x2,
    "comp": 0x3,
    "cmp": 0x3,

    "or": 0x4,
    "xor": 0x5,
    "and": 0x6,
    "test": 0x7,

    "mov": 0x9,

    "load": 0xA, "ld": 0xA,
    "store": 0xB, "st": 0xB,

    "slo": 0xC,

    "port_read": 0xE,
    "port_write": 0xF,
}


def oneof(*names):
    names=sorted(names, key=len, reverse=True)
    return f"({'|'.join(names)})"


def build(*parts: tuple[int, int]):
    size = sum(w for v, w in parts)
    assert size % 8 == 0, "Instruction length must be multiple of a byte"
    data = bitarray(endian="big")
    i = 0
    for v, w in parts:
        data.extend(int2ba(v, w, endian="big"))
        i += w
    return data.tobytes()


def validate_registers(context, *registers, inst_size: str = None, register_range=range(8)) -> \
        tuple[str, tuple[int, ...]]:
    out_registers = []
    out_sizes = []
    for rs, r in registers:
        reject(r not in register_range, f"Register {r!r} out of valid range ({register_range})")
        out_registers.append(r)
        out_sizes.append(rs)
    size = resolve_register_size(context, inst_size, *out_sizes)
    return size, tuple(out_registers)


# TODO: This should be something like "directive", not an "instruction"
@base.inst(f'".syntax" /(no)?prefix/')
def syntax_prefix(context, new_value):
    if new_value == "noprefix":
        context.modes.difference_update({'prefix'})
    else:
        context.modes.add('prefix')
    context.reload_extensions()


# TODO: This should be something like "directive", not an "instruction"
@base.inst(f'".strict"')
def strict(context):
    context.modes.add('strict')
    context.reload_extensions()


# We need a negative lookbehind here to prevent "%r 7" from being valid.
@base.reg(fr'"%r" size_infix /(?!<\s)[0-9]+/', prefix=True)
@base.reg(fr'"r" size_infix /(?!<\s)[0-9]+/', prefix=False)
def base_registers(context, size, reg: str):
    return size, int(reg)


@base.register_syntax("size_postfix", r"/(?!<\s)x/")
@base.register_syntax("size_postfix", r"", strict=False)
def size_postfix_x(context, x=None):
    return 'x' if x else None


@base.register_syntax("size_infix", r"/(?!<\s)x(?!\s)/")
@base.register_syntax("size_infix", r"", strict=False)
def size_infix_x(context, x=None):
    return 'x' if x else None


@base.register_syntax("size_prefix", r"/x(?!\s)/")
@base.register_syntax("size_prefix", r"", strict=False)
def size_prefix_x(context, x=None):
    return 'x' if x else None


@base.inst(f'/{oneof(*INSTRUCTIONS)}/ size_postfix register "," register')
def base_computations_2reg(context, inst: str, inst_size, a: tuple[int | None, int], b: tuple[int | None, int]):
    size, (a, b) = validate_registers(context, a, b, inst_size=inst_size)

    op = INSTRUCTIONS[inst]
    reject(op >= 12, f"Opcode {op} doesn't have a 2 register form")
    return build((0b00, 2), (context.register_sizes[size], 2), (op, 4), (a, 3), (b, 3), (0, 2))


@base.inst(f'/{oneof(*INSTRUCTIONS)}/ size_postfix register "," immediate')
def base_computations_imm(context, inst: str, inst_size: str | None, reg: tuple[str | None, int], imm: int):
    size, (a,) = validate_registers(context, reg, inst_size=inst_size)

    op = INSTRUCTIONS[inst]

    if op < 12:
        reject(not isinstance(imm, int) or not (-16 <= imm < 16),
               f"Invalid immediate for base {imm} with opcode {inst}")
    else:
        reject(not isinstance(imm, int) or not (0 <= imm < 32), f"Invalid immediate for base {imm} with opcode {inst}")

    return build((0b01, 2), (context.register_sizes[size], 2), (op, 4), (a, 3), (imm & 0x1F, 5))


@base.inst('"inp" size_postfix register "," immediate')
def base_inp(context, inst_size, reg, port):
    size, (a,) = validate_registers(context, reg, inst_size=inst_size)
    reject(not isinstance(port, int) or not (0 <= port < 16), f"Invalid IO port for base {port}")
    return build((0b0101, 4), (0xE, 4), (a, 3), (port, 4), (1, 1))


@base.inst('"out" size_postfix register "," immediate', strict=False)
def base_out(context, inst_size, reg, port):
    size, (a,) = validate_registers(context, reg, inst_size=inst_size)
    reject(not isinstance(port, int) or not (0 <= port < 16), f"Invalid IO port for base {port}")
    return build((0b0101, 4), (0xF, 4), (a, 3), (port, 4), (1, 1))


@base.inst('"mfcr" size_postfix register "," immediate')
def base_mfcr(context, inst_size, reg, port):
    size, (a,) = validate_registers(context, reg, inst_size=inst_size)
    reject(not isinstance(port, int) or not (0 <= port < 16), f"Invalid control register for base {port}")
    return build((0b0101, 4), (0xE, 4), (a, 3), (port, 4), (0, 1))


@base.inst('"mtcr" size_postfix register "," immediate')
def base_mtcr(context, inst_size, reg, port):
    size, (a,) = validate_registers(context, reg, inst_size=inst_size)
    reject(not isinstance(port, int) or not (0 <= port < 16), f"Invalid control register for base {port}")
    return build((0b0101, 4), (0xF, 4), (a, 3), (port, 4), (0, 1))


@base.register_syntax("control_register", "/cr[0-9]+/", prefix=False)
@base.register_syntax("control_register", "/%cr[0-9]+/", prefix=True)
def cr_n(context, cr):
    return int(cr.removeprefix('%').removeprefix('cr'))


NAMED_CRS = {
    "cpuid": 0,
    "exten": 1
}


@base.register_syntax("control_register", f"/{oneof(*NAMED_CRS)}/", prefix=False)
@base.register_syntax("control_register", f"/%{oneof(*NAMED_CRS)}/", prefix=True)
def named_cr(context, name):
    return NAMED_CRS[name.removeprefix('%')]


@base.inst('"mov" size_postfix register_raw "," control_register')
def mov_from_cr(context, _, reg, cr):
    return context.macro(f"""
        mfcrx {reg}, {cr}
    """)


@base.inst('"mov" size_postfix control_register "," register_raw')
def mov_to_cr(context, _, cr, reg):
    return context.macro(f"""
        mtcrx {reg}, {cr}
    """)


@base.inst('"mov" size_postfix register_raw "," "[" (register_raw|immediate_raw) "]"')
def mov_from_mem(context, _, reg, arg):
    return context.macro(f"""
        ld {reg}, {arg}
    """)


@base.inst('"mov" size_postfix "[" register_raw "]" "," (register_raw|immediate_raw)')
def mov_to_mem(context, _, reg, arg):
    return context.macro(f"""
        st {reg}, {arg}
    """)


JUMP_NAMES = {
    "z": 0, "e": 0,
    "nz": 1, "ne": 1,
    "n": 2,
    "nn": 3,
    "c": 4, "b": 4,
    "nc": 5, "ae": 5,
    "v": 6,
    "nv": 7,
    "be": 8,
    "a": 9,
    "l": 10,
    "ge": 11,
    "le": 12,
    "g": 13,
    "mp": 14,
}

@base.inst(f'/j{oneof(*JUMP_NAMES)}/ label')
def base_jumps(context, inst: str, label: str):
    inst = inst.removeprefix('j')
    op = JUMP_NAMES[inst]
    target = context.resolve_label(label)
    if target is None:
        offset = 0
    else:
        offset = target - context.ip
    reject(not (-256 <= offset < 256))
    return build((0b100, 3), (offset & 100 >> 8, 1), (op, 4), (offset & 0xFF, 8))


@base.inst('"nop"')
def base_nop(context):
    return b"\x8f\x00"  # jump nowhere, never
