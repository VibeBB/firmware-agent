"""mruby/c device API: contract schema and generated C bindings.

The ``*.mruby-api.json`` spec (authored by ux-creator-agent) declares
device-specific classes, methods, symbols and the handler functions the
bindings delegate to. ``firmware mrubyc`` regenerates, per contract
``mrubyc.device_api``:

- ``fw_api_<class>.c`` / ``fw_api_<class>.h`` — argument decoders
  (``c_<class>_<method>``) plus the ``fw_api_<class>_define()``
  registration entry point, one file pair per class.
- ``fw_api_symbols.c`` / ``fw_api_symbols.h`` — the symbol registry
  (mirrors OpenBlink ``src/api/symbol.c``): names registered with
  ``mrbc_symbol_new`` at define time, symid -> handler-constant dispatch.
- ``fw_api.c`` / ``fw_api.h`` — ``fw_api_init_all`` / ``fw_api_define_all``
  aggregators plus the system-task gate helper.

Generated code follows the OpenBlink idioms: ``MRBC_KW_ARG`` keyword
extraction inside ``do { ... } while (0)`` guard blocks, ``SET_*_RETURN``
return marshalling, ``system_task`` per-VM gating and ``expert`` methods
that only exist under a compile-time define.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .contract import FirmwareContract, MrubyDeviceApi, resolve
from .interchange import sha256_file

_SCHEMA = ConfigDict(extra="forbid")

_RUBY_CLASS = r"^[A-Z][A-Za-z0-9]*$"
_RUBY_METHOD = r"^[a-z_][a-z0-9_]*[?!]?$"
_RUBY_PARAM = r"^[a-z_][a-z0-9_]*$"
_RUBY_SYMBOL = r"^[a-z_][a-z0-9_]*$"
_C_IDENT = r"^[A-Za-z_][A-Za-z0-9_]*$"

_SEP = "\t// =============================="


class ApiSymbol(BaseModel):
    model_config = _SCHEMA

    name: str = Field(pattern=_RUBY_SYMBOL)
    const: str = Field(min_length=1, description="C constant the handler receives")


class ApiParam(BaseModel):
    model_config = _SCHEMA

    name: str = Field(pattern=_RUBY_PARAM)
    type: str = Field(pattern=r"^(int|float|bool|symbol|string|array<int>)$")
    required: bool = True
    default: int | float | bool | str | None = None
    enum: list[str] = Field(default_factory=list[str])
    max_len: int = 0

    @property
    def c_type(self) -> str:
        """Handler ABI C type: mruby/c typedefs follow the VM int/float width."""
        return {
            "int": "mrbc_int_t",
            "float": "mrbc_float_t",
            "bool": "int",
            "symbol": "int32_t",
            "string": "const char *",
            "array<int>": "mrbc_int_t",
        }[self.type]

    @model_validator(mode="after")
    def _shape(self) -> ApiParam:
        if self.type == "symbol" and not self.enum:
            raise ValueError(f"{self.name}: symbol params need an enum of spec symbols")
        if self.type != "symbol" and self.enum:
            raise ValueError(f"{self.name}: enum only applies to symbol params")
        if self.type == "array<int>":
            if self.max_len < 1 or self.max_len > 1024:
                raise ValueError(f"{self.name}: array<int> needs 1 <= max_len <= 1024")
        elif self.max_len:
            raise ValueError(f"{self.name}: max_len only applies to array<int> params")
        if not self.required and self.default is None:
            raise ValueError(f"{self.name}: optional params need a default")
        if self.default is not None and self.required:
            raise ValueError(f"{self.name}: default only applies to optional params")
        if self.type == "symbol" and self.default is not None and self.default not in self.enum:
            raise ValueError(f"{self.name}: default {self.default} not in enum")
        return self


class ApiReturn(BaseModel):
    model_config = _SCHEMA

    type: str = Field(pattern=r"^(nil|bool|int|float|string|array<int>|array<float>)$")
    cap: int = 0

    @model_validator(mode="after")
    def _shape(self) -> ApiReturn:
        if self.type in ("string", "array<int>", "array<float>"):
            if self.cap < 1 or self.cap > 1024:
                raise ValueError(f"{self.type} returns need 1 <= cap <= 1024")
        elif self.cap:
            raise ValueError(f"{self.type} returns do not take cap")
        return self


class ApiMethod(BaseModel):
    model_config = _SCHEMA

    name: str = Field(pattern=_RUBY_METHOD)
    doc: str = ""
    params: list[ApiParam] = Field(default_factory=list[ApiParam])
    kwargs: list[ApiParam] = Field(default_factory=list[ApiParam])
    rest_kwargs: bool = False
    block: str = Field(default="none", pattern=r"^(none|required|optional)$")
    returns: ApiReturn = Field(default_factory=lambda: ApiReturn(type="nil"))
    access: str = Field(default="any", pattern=r"^(any|system_task|expert)$")
    arg_errors: str = Field(default="raise", pattern=r"^(raise|silent)$")
    handler: str = Field(pattern=_C_IDENT)

    @model_validator(mode="after")
    def _shape(self) -> ApiMethod:
        seen = [p.name for p in self.params + self.kwargs]
        if len(set(seen)) != len(seen):
            raise ValueError(f"{self.name}: duplicate argument name")
        if "rest" in seen or "blk" in seen:
            raise ValueError(f"{self.name}: 'rest'/'blk' are reserved argument names")
        return self


class ApiInstance(BaseModel):
    model_config = _SCHEMA

    data_size: int = Field(ge=1, le=4096)
    constructor: str | None = Field(default=None, pattern=_C_IDENT)
    destructor: str | None = Field(default=None, pattern=_C_IDENT)


class ApiConst(BaseModel):
    model_config = _SCHEMA

    name: str = Field(pattern=r"^[A-Z][A-Z0-9_]*$")
    value: int | float | bool | str


class ApiClass(BaseModel):
    model_config = _SCHEMA

    name: str = Field(pattern=_RUBY_CLASS)
    kind: str = Field(default="class", pattern=r"^(class|module)$")
    outer: str | None = Field(default=None, pattern=_RUBY_CLASS)
    super: str = Field(default="Object", pattern=_RUBY_CLASS)
    doc: str = ""
    constants: list[ApiConst] = Field(default_factory=list[ApiConst])
    methods: list[ApiMethod] = Field(default_factory=list[ApiMethod])
    init: str | None = Field(default=None, pattern=_C_IDENT)
    instance: ApiInstance | None = None

    @model_validator(mode="after")
    def _shape(self) -> ApiClass:
        if self.kind == "module" and (self.super != "Object" or self.instance is not None):
            raise ValueError(f"{self.name}: modules take no super/instance data")
        names = [m.name for m in self.methods]
        if len(set(names)) != len(names):
            raise ValueError(f"{self.name}: duplicate method name")
        fnames = [_func_name(self.name, m.name) for m in self.methods]
        if len(set(fnames)) != len(fnames):
            raise ValueError(f"{self.name}: method names collide after C translation")
        cnames = [c.name for c in self.constants]
        if len(set(cnames)) != len(cnames):
            raise ValueError(f"{self.name}: duplicate constant name")
        return self


class ApiSystemTask(BaseModel):
    model_config = _SCHEMA

    vm_id: int = Field(ge=1, le=255)


class MrubyApiDoc(BaseModel):
    """The ``*.mruby-api.json`` document shared by ux, firmware, sim, dashboard."""

    model_config = _SCHEMA

    schema_version: int = 1
    artifact_kind: str = "mruby_api"
    product: str = Field(min_length=1)
    symbols: list[ApiSymbol] = Field(default_factory=list[ApiSymbol])
    classes: list[ApiClass] = Field(min_length=1)
    system_task: ApiSystemTask | None = None
    expert_define: str | None = Field(default=None, pattern=_C_IDENT)

    @model_validator(mode="after")
    def _shape(self) -> MrubyApiDoc:
        names = [c.name for c in self.classes]
        if len(set(names)) != len(names):
            raise ValueError("duplicate class name")
        sym_names = {s.name for s in self.symbols}
        if len(sym_names) != len(self.symbols):
            raise ValueError("duplicate symbol name")
        needs_system = needs_expert = False
        for cls in self.classes:
            if cls.outer is not None and cls.outer not in names:
                raise ValueError(f"{cls.name}: outer {cls.outer} not a spec class")
            if cls.super != "Object" and cls.super not in names:
                raise ValueError(f"{cls.name}: super {cls.super} not a spec class")
            for method in cls.methods:
                needs_system |= method.access == "system_task"
                needs_expert |= method.access == "expert"
                for param in method.params + method.kwargs:
                    missing = [v for v in param.enum if v not in sym_names]
                    if missing:
                        raise ValueError(
                            f"{cls.name}.{method.name}: enum {missing} not in spec symbols"
                        )
        if needs_system and self.system_task is None:
            raise ValueError("access=system_task requires a system_task block")
        if needs_expert and self.expert_define is None:
            raise ValueError("access=expert requires expert_define")
        return self


# ---------------------------------------------------------------- naming


def _stem(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


def _cname(cls: ApiClass) -> str:
    return _stem(cls.name)


def _func_name(class_name: str, method_name: str) -> str:
    return f"c_{_stem(class_name)}_{method_name.replace('?', '_p').replace('!', '_b')}"


def _cname_by_name(spec: MrubyApiDoc, name: str) -> str:
    for cls in spec.classes:
        if cls.name == name:
            return _cname(cls)
    raise KeyError(name)


def _camel(name: str) -> str:
    return "".join(part.capitalize() for part in re.split(r"[_\-]", name))


def _comment(contract_name: str, spec_rel: str) -> str:
    return (
        "/* Auto-generated by `firmware mrubyc`; do not edit by hand.\n"
        f" * contract: {contract_name}   api spec: {spec_rel}\n"
        " * Regenerate: `firmware mrubyc <name>.fw.json`\n"
        " */\n"
    )


def _symbol_const(spec: MrubyApiDoc, name: str) -> str:
    for sym in spec.symbols:
        if sym.name == name:
            return sym.const
    raise KeyError(name)


# ---------------------------------------------------------------- decode


def _param_decls(param: ApiParam, spec: MrubyApiDoc) -> list[str]:
    """Local variable declarations for one decoded argument."""
    n = param.name
    if param.type == "symbol":
        if param.default is None:
            return [f"\tint32_t a_{n} = -1;"]
        return [f"\tint32_t a_{n} = {_symbol_const(spec, str(param.default))};"]
    if param.type == "string":
        return [f'\tconst char *a_{n} = "{param.default}";', f"\tsize_t a_{n}_n = 0U;"]
    if param.type == "array<int>":
        return [f"\tmrbc_int_t a_{n}[{param.max_len}] = {{0}};", f"\tsize_t a_{n}_n = 0U;"]
    if param.type == "bool":
        lit = "1" if param.default else "0"
        return [f"\tint a_{n} = {lit};"]
    if param.type == "float":
        lit = str(param.default) if param.default is not None else "0.0"
        return [f"\tmrbc_float_t a_{n} = {lit};"]
    lit = param.default if param.default is not None else 0
    return [f"\tmrbc_int_t a_{n} = {lit};"]


def _array_copy(val: str, param: ApiParam, indent: str, fail: str = "break") -> list[str]:
    """Bounded copy of an mrbc array argument into the stack buffer."""
    n = param.name
    return [
        f"{indent}{{",
        f"{indent}\tsize_t dec = 0U;",
        f"{indent}\tfor (dec = 0U; dec < (size_t){val}.array->n_stored; dec++) {{",
        f"{indent}\t\tif (MRBC_TT_INTEGER != {val}.array->data[dec].tt) {{ {fail}; }}",
        f"{indent}\t\ta_{n}[dec] = {val}.array->data[dec].i;",
        f"{indent}\t}}",
        f"{indent}\tif (dec != (size_t){val}.array->n_stored) {{ {fail}; }}",
        f"{indent}\ta_{n}_n = dec;",
        f"{indent}}}",
    ]


def _decode_slot(val: str, param: ApiParam, indent: str, fail: str = "break") -> list[str]:
    """Type check + store lines for one argument slot (v[i] or kw name)."""
    n = param.name
    out: list[str] = []
    if param.type == "int":
        out += [
            f"{indent}if (!MRBC_ISNUMERIC({val})) {{ {fail}; }}",
            f"{indent}a_{n} = mrbc_integer({val});",
        ]
    elif param.type == "float":
        out += [
            f"{indent}if (!MRBC_ISNUMERIC({val})) {{ {fail}; }}",
            f"{indent}a_{n} = mrbc_float({val});",
        ]
    elif param.type == "bool":
        out += [
            f"{indent}if (MRBC_TT_TRUE != {val}.tt && MRBC_TT_FALSE != {val}.tt) {{ {fail}; }}",
            f"{indent}a_{n} = (MRBC_TT_TRUE == {val}.tt) ? 1 : 0;",
        ]
    elif param.type == "symbol":
        out += [
            f"{indent}if (MRBC_TT_SYMBOL != {val}.tt) {{ {fail}; }}",
            f"{indent}a_{n} = fw_api_symbol_const({val}.sym_id);",
            f"{indent}if (a_{n} < 0) {{ {fail}; }}",
        ]
    elif param.type == "string":
        out += [
            f"{indent}if (MRBC_TT_STRING != {val}.tt) {{ {fail}; }}",
            f"{indent}a_{n} = (const char *){val}.string->data;",
            f"{indent}a_{n}_n = (size_t){val}.string->size;",
        ]
    else:  # array<int>
        out += [
            f"{indent}if (MRBC_TT_ARRAY != {val}.tt) {{ {fail}; }}",
            f"{indent}if ({val}.array->n_stored > {param.max_len}u) {{ {fail}; }}",
            *_array_copy(val, param, indent, fail),
        ]
    return out


def _call_args(method: ApiMethod, cls: ApiClass) -> list[str]:
    args: list[str] = ["data"] if cls.instance is not None else []
    for param in method.params + method.kwargs:
        args.append(f"a_{param.name}")
        if param.type in ("string", "array<int>"):
            args.append(f"a_{param.name}_n")
    if method.rest_kwargs:
        args.append("&rest")
    if method.block != "none":
        args.append("blk")
    return args


def _neutral_return(ret: ApiReturn) -> str:
    return {
        "nil": "SET_NIL_RETURN();",
        "bool": "SET_FALSE_RETURN();",
        "int": "SET_INT_RETURN(-1);",
        "float": "SET_FLOAT_RETURN(-1.0f);",
        "string": "SET_NIL_RETURN();",
        "array<int>": "SET_NIL_RETURN();",
        "array<float>": "SET_NIL_RETURN();",
    }[ret.type]


def _emit_return(method: ApiMethod, cls: ApiClass, out: list[str]) -> None:
    """Handler invocation plus ``SET_*_RETURN`` marshalling."""
    ret = method.returns
    args = _call_args(method, cls)
    call = f"{method.handler}({', '.join(args)})"
    if ret.type == "nil":
        out += [f"\t(void){call};", "\tSET_NIL_RETURN();"]
    elif ret.type == "bool":
        out.append(f"\tSET_BOOL_RETURN({call} != 0);")
    elif ret.type == "int":
        out.append(f"\tSET_INT_RETURN({call});")
    elif ret.type == "float":
        out.append(f"\tSET_FLOAT_RETURN({call});")
    elif ret.type == "string":
        out += [
            "\tdo {",
            f"\t\tchar ret_buf[{ret.cap}u];",
            f"\t\tint ret_n = {method.handler}("
            f"{', '.join([*args, 'ret_buf', 'sizeof(ret_buf)'])});",
            "\t\tif (ret_n < 0) break;",
            f"\t\tif (ret_n > (int){ret.cap}u) ret_n = (int){ret.cap}u;",
            "\t\tmrb_value ret = mrbc_string_new(vm, ret_buf, ret_n);",
            "\t\tSET_RETURN(ret);",
            "\t} while (0);",
        ]
    else:
        c_type = "mrbc_int_t" if ret.type == "array<int>" else "mrbc_float_t"
        out += [
            "\tdo {",
            f"\t\t{c_type} ret_buf[{ret.cap}u];",
            f"\t\tint ret_n = {method.handler}("
            f"{', '.join([*args, 'ret_buf', f'(size_t){ret.cap}u'])});",
            "\t\tif (ret_n < 0) break;",
            f"\t\tif (ret_n > (int){ret.cap}u) ret_n = (int){ret.cap}u;",
            "\t\tmrb_value ret = mrbc_array_new(vm, ret_n);",
            "\t\tfor (int i = 0; i < ret_n; i++) {",
        ]
        if ret.type == "array<int>":
            out.append("\t\t\tmrb_value e = mrbc_integer_value(ret_buf[i]);")
        else:
            out.append("\t\t\tmrb_value e = mrbc_float_value(vm, ret_buf[i]);")
        out += [
            "\t\t\tmrbc_array_set(&ret, i, &e);",
            "\t\t}",
            "\t\tSET_RETURN(ret);",
            "\t} while (0);",
        ]


def _fail_lines(method: ApiMethod, cls: ApiClass, where: str) -> list[str]:
    """Decode-failure epilogue: raise ArgumentError or silently return."""
    if method.arg_errors == "raise":
        return [
            f'\t\tmrbc_raise(vm, MRBC_CLASS(ArgumentError), "{cls.name}.{method.name}: {where}");',
            "\t\treturn;",
        ]
    return ["\t\treturn;"]


def _emit_method(method: ApiMethod, cls: ApiClass, spec: MrubyApiDoc) -> list[str]:
    """One ``c_<cls>_<name>`` function, OpenBlink decoder idiom throughout."""
    fname = _func_name(cls.name, method.name)
    uses_vm = (
        method.access == "system_task"
        or method.arg_errors == "raise"
        or method.rest_kwargs
        or method.returns.type in ("string", "array<int>", "array<float>")
    )
    uses_argc = bool(method.params or method.kwargs or method.rest_kwargs or method.block != "none")
    out = [
        "/**",
        f" * @brief {method.doc or f'Binding for {cls.name}.{method.name}'}",
        " *",
        " * @param vm The mruby/c VM instance",
        " * @param v The value array",
        " * @param argc The argument count",
        " */",
        f"static void {fname}(mrb_vm *vm, mrb_value *v, int argc) {{",
    ]
    for param in method.params + method.kwargs:
        out += _param_decls(param, spec)
    if cls.instance is not None:
        out.append("\tvoid *data = v[0].instance->data;")
    if method.block != "none":
        out.append("\tmrb_value *blk = 0;")
    if not uses_vm:
        out.append("\t(void)vm;")
    if not uses_argc:
        out.append("\t(void)argc;")
    out.append(f"\t{_neutral_return(method.returns)}")
    if method.access == "system_task":
        out += [
            "",
            "\t/* access gate: system task only */",
            "\tif (!fw_api_is_system_task(vm->vm_id)) {",
            "\t\treturn;",
            "\t}",
        ]
    if method.params:
        out += ["", _SEP, "\tint ok = 0;", "\tdo {"]
        for i, param in enumerate(method.params, start=1):
            if param.required:
                out.append(f"\t\tif (argc < {i}) break;")
                out += _decode_slot(f"v[{i}]", param, "\t\t")
            else:
                out.append(f"\t\tif (argc >= {i}) {{")
                out += _decode_slot(f"v[{i}]", param, "\t\t\t")
                out.append("\t\t}")
        out += [
            "\t\tok = 1;",
            "\t} while (0);",
            "\tif (!ok) {",
            *_fail_lines(method, cls, "invalid argument"),
            "\t}",
            _SEP,
        ]
    if method.kwargs:
        names = ", ".join(p.name for p in method.kwargs)
        required = [p.name for p in method.kwargs if p.required]
        kw_fail = "kw_bad = 1; break" if method.arg_errors == "raise" else "break"
        out += ["", _SEP, f"\tMRBC_KW_ARG({names});"]
        if method.arg_errors == "raise":
            out.append("\tint kw_bad = 0;")
        if method.rest_kwargs:
            out.append("\tMRBC_KW_DICT(rest);")
        out += ["\tdo {"]
        if required:
            out.append(f"\t\tif (!MRBC_KW_MANDATORY({', '.join(required)})) break;")
        if not method.rest_kwargs:
            out.append("\t\tif (!MRBC_KW_END()) break;")
        out += [""]
        for param in method.kwargs:
            out.append(f"\t\tif (MRBC_KW_ISVALID({param.name})) {{")
            out += _decode_slot(param.name, param, "\t\t\t", kw_fail)
            out.append("\t\t}")
        out += ["\t} while (0);", f"\tMRBC_KW_DELETE({names});"]
        out += [
            "\t/* MRBC_KW_MANDATORY/MRBC_KW_END raise in place; stop before",
            "\t * calling the handler when the VM already carries the error. */",
            "\tif (mrbc_israised(vm)) {",
            "\t\treturn;",
            "\t}",
        ]
        if method.arg_errors == "raise":
            out += ["\tif (kw_bad) {"]
            out += _fail_lines(method, cls, "invalid keyword argument")
            out += ["\t}"]
        out.append(_SEP)
    if method.rest_kwargs and not method.kwargs:
        out += [
            "",
            _SEP,
            "\t/* trailing **rest keyword hash */",
            "\tMRBC_KW_DICT(rest);",
            _SEP,
        ]
    if method.block != "none":
        out += [
            "",
            _SEP,
            "\t/* optional trailing block: v[argc+1], or v[argc+2] after a kw-hash */",
            "\tif (MRBC_TT_PROC == v[argc + 1].tt) {",
            "\t\tblk = &v[argc + 1];",
            "\t} else if (MRBC_TT_HASH == v[argc + 1].tt &&",
            "\t\t\tMRBC_TT_PROC == v[argc + 2].tt) {",
            "\t\tblk = &v[argc + 2];",
            "\t}",
        ]
        if method.block == "required":
            out += [
                "\tif (0 == blk) {",
                *_fail_lines(method, cls, "block required"),
                "\t}",
            ]
        out.append(_SEP)
    out.append("")
    _emit_return(method, cls, out)
    out.append("}")
    return out


# ---------------------------------------------------------------- emit


def _emit_class(
    cls: ApiClass, spec: MrubyApiDoc, contract_name: str, spec_rel: str
) -> tuple[str, str]:
    """Return (header, source) text for ``fw_api_<cls>``."""
    cname = _cname(cls)
    guard = f"FW_API_{cname.upper()}_H"
    header = [
        _comment(contract_name, spec_rel),
        f"#ifndef {guard}",
        f"#define {guard}",
        "",
        '#include "mrubyc.h"',
        "",
        "/** Register the class and its methods with the mruby/c VM. */",
        f"int fw_api_{cname}_define(void);",
    ]
    if cls.init is not None:
        header += ["", "/** Driver/hardware init for this API (pre-VM). */"]
        header.append(f"int fw_api_{cname}_init(void);")
    header += ["", f"extern mrb_class *fw_api_{cname}_class;", "", f"#endif /* {guard} */", ""]

    source = [_comment(contract_name, spec_rel)]
    source += [
        f'#include "fw_api_{cname}.h"',
        "",
        "#include <stddef.h>",
        "#include <stdint.h>",
        "",
        '#include "fw_api.h"',
        '#include "fw_api_handlers.h"',
    ]
    if spec.symbols:
        source.append('#include "fw_api_symbols.h"')
    source += [""]
    if any(m.arg_errors == "raise" for m in cls.methods):
        source += [
            "/* Exception class globals live in _autogen_class_exception.h on the",
            " * mruby/c build side; declare them for MRBC_CLASS() resolution. */",
            "extern struct RBuiltinNoMethodClass mrbc_class_ArgumentError;",
            "",
        ]
    for dep in (cls.outer, cls.super if cls.super != "Object" else None):
        if dep is not None and dep != cls.name:
            source.append(f"extern mrb_class *fw_api_{_cname_by_name(spec, dep)}_class;")
    if cls.outer is not None or cls.super != "Object":
        source.append("")
    source += [
        f"mrb_class *fw_api_{cname}_class = 0;",
        "",
        "/* ---- forward declarations ---- */",
    ]
    for method in cls.methods:
        source.append(
            f"static void {_func_name(cls.name, method.name)}(mrb_vm *vm, mrb_value *v, int argc);"
        )
    if cls.instance is not None:
        source.append(f"static void c_{cname}_new(mrb_vm *vm, mrb_value *v, int argc);")
        if cls.instance.destructor is not None:
            source.append(f"static void c_{cname}_dtor(mrbc_value *v);")
    source += [
        "",
        "/* ---- class definition ---- */",
        "/**",
        " * @brief Defines the class and methods for mruby/c",
        " *",
        " * @return 0 on success, -1 on failure",
        " */",
        f"int fw_api_{cname}_define(void) {{",
    ]
    if cls.kind == "module":
        if cls.outer is not None:
            source.append(
                f"\tfw_api_{cname}_class = mrbc_define_module_under(0, "
                f'fw_api_{_cname_by_name(spec, cls.outer)}_class, "{cls.name}");'
            )
        else:
            source.append(f'\tfw_api_{cname}_class = mrbc_define_module(0, "{cls.name}");')
    elif cls.outer is not None:
        outer_ref = f"fw_api_{_cname_by_name(spec, cls.outer)}_class"
        source.append(
            f"\tfw_api_{cname}_class = mrbc_define_class_under(0, "
            f'{outer_ref}, "{cls.name}", {_super_ref(cls, spec)});'
        )
    else:
        source.append(
            f'\tfw_api_{cname}_class = mrbc_define_class(0, "{cls.name}", {_super_ref(cls, spec)});'
        )
    for method in cls.methods:
        fname = _func_name(cls.name, method.name)
        if method.access == "expert":
            source += [
                f"#if defined({spec.expert_define})",
                f'\tmrbc_define_method(0, fw_api_{cname}_class, "{method.name}", {fname});',
                f"#endif /* defined({spec.expert_define}) */",
            ]
        else:
            source.append(
                f'\tmrbc_define_method(0, fw_api_{cname}_class, "{method.name}", {fname});'
            )
    if cls.constants:
        source += ["", "\t/* class constants */", "\t{", "\t\tmrb_value k;"]
        for const in cls.constants:
            if isinstance(const.value, bool):
                lit = f"mrbc_bool_value({1 if const.value else 0})"
            elif isinstance(const.value, int):
                lit = f"mrbc_integer_value({const.value})"
            elif isinstance(const.value, float):
                lit = f"mrbc_float_value(0, {const.value})"
            else:
                esc = const.value.replace('"', '\\"')
                lit = f'mrbc_string_new_cstr(0, "{esc}")'
            source += [
                f"\t\tk = {lit};",
                f"\t\t(void)mrbc_set_class_const(fw_api_{cname}_class, "
                f'mrbc_str_to_symid("{const.name}"), &k);',
            ]
        source.append("\t}")
    if cls.instance is not None:
        source.append(f'\tmrbc_define_method(0, fw_api_{cname}_class, "new", c_{cname}_new);')
        if cls.instance.destructor is not None:
            source.append(f"\tmrbc_define_destructor(fw_api_{cname}_class, c_{cname}_dtor);")
    source += ["\treturn 0;", "}"]
    if cls.init is not None:
        source += [
            "",
            "/* ---- driver init ---- */",
            "/**",
            " * @brief Initializes the driver side of this API (pre-VM)",
            " *",
            " * @return 0 on success, -1 on failure",
            " */",
            f"int fw_api_{cname}_init(void) {{",
            f"\treturn {cls.init}();",
            "}",
        ]
    source += ["", "/* ---- method bindings ---- */"]
    for method in cls.methods:
        source += ["", *_emit_method(method, cls, spec)]
    if cls.instance is not None:
        source += ["", "/**", " * @brief Instance constructor (mrbc_instance_new + init)", " */"]
        source += [
            f"static void c_{cname}_new(mrb_vm *vm, mrb_value *v, int argc) {{",
            "\t(void)argc;",
            f"\tmrb_value obj = mrbc_instance_new(vm, v[0].cls, {cls.instance.data_size}u);",
        ]
        if cls.instance.constructor is not None:
            source += [
                f"\tif (0 != {cls.instance.constructor}((void *)obj.instance->data)) {{",
                "\t\tmrbc_instance_delete(&obj);",
                "\t\tSET_NIL_RETURN();",
                "\t\treturn;",
                "\t}",
            ]
        source += ["\tv[0] = obj;", "\tSET_RETURN(v[0]);", "}"]
        if cls.instance.destructor is not None:
            source += [
                "",
                "/**",
                " * @brief Releases instance data (registered via mrbc_define_destructor)",
                " *",
                " * @param v The instance value being collected",
                " */",
                f"static void c_{cname}_dtor(mrbc_value *v) {{",
                f"\t{cls.instance.destructor}((void *)v->instance->data);",
                "}",
            ]
    source.append("")
    return "\n".join(header), "\n".join(source)


def _super_ref(cls: ApiClass, spec: MrubyApiDoc) -> str:
    if cls.super == "Object":
        return "mrbc_class_object"
    return f"fw_api_{_cname_by_name(spec, cls.super)}_class"


def _sorted_classes(spec: MrubyApiDoc) -> list[ApiClass]:
    """Topological order so outer/super classes define first."""
    by_name = {c.name: c for c in spec.classes}
    ordered: list[ApiClass] = []
    seen: set[str] = set()

    def visit(cls: ApiClass) -> None:
        if cls.name in seen:
            return
        seen.add(cls.name)
        for dep in (cls.outer, cls.super if cls.super != "Object" else None):
            if dep is not None and dep in by_name:
                visit(by_name[dep])
        ordered.append(cls)

    for cls in spec.classes:
        visit(cls)
    return ordered


def _emit_symbols(spec: MrubyApiDoc, contract_name: str, spec_rel: str) -> tuple[str, str]:
    comment = _comment(contract_name, spec_rel)
    guard = "FW_API_SYMBOLS_H"
    header = [
        comment,
        f"#ifndef {guard}",
        f"#define {guard}",
        "",
        "#include <stdint.h>",
        '#include "mrubyc.h"',
        "",
        "/** Symbol slots registered with the VM at define time. */",
        "typedef enum {",
    ]
    for i, sym in enumerate(spec.symbols):
        header.append(f"\tkFwApiSym{_camel(sym.name)} = {i},")
    header += [
        "\tkFwApiSymCount,",
        "} fw_api_symbol_t;",
        "",
        "int fw_api_symbols_init(void);",
        "int fw_api_symbols_define(void);",
        "mrbc_sym fw_api_symbol_id(fw_api_symbol_t sym);",
        "/** Map a live symid to its handler constant, -1 when unknown. */",
        "int32_t fw_api_symbol_const(mrbc_sym sym_id);",
        "",
        f"#endif /* {guard} */",
        "",
    ]
    source = [
        comment,
        '#include "fw_api_symbols.h"',
        "",
        "#include <stddef.h>",
        "",
        '#include "fw_api_handlers.h"',
        "",
        "/* Symbol names registered with mrbc_symbol_new at define time. */",
        "static const char *const symbol_name_table[kFwApiSymCount] = {",
    ]
    for sym in spec.symbols:
        source.append(f'\t"{sym.name}",')
    source += [
        "};",
        "",
        "/* Handler constant each symbol maps to (declared in fw_api_handlers.h). */",
        "static const int32_t symbol_const_table[kFwApiSymCount] = {",
    ]
    for sym in spec.symbols:
        source.append(f"\t{sym.const},")
    source += [
        "};",
        "",
        "/* Live symid for each registered symbol, -1 until defined. */",
        "static mrbc_sym symbol_id_table[kFwApiSymCount];",
        "",
        "/**",
        " * @brief Clears the symid table (call before mrbc_init_class)",
        " *",
        " * @return 0 always",
        " */",
        "int fw_api_symbols_init(void) {",
        "\tfor (size_t i = 0; i < (size_t)kFwApiSymCount; i++) {",
        "\t\tsymbol_id_table[i] = -1;",
        "\t}",
        "\treturn 0;",
        "}",
        "",
        "/**",
        " * @brief Registers every declared symbol with the mruby/c symbol table",
        " *",
        " * @return 0 on success, -1 when a symbol fails to register",
        " */",
        "int fw_api_symbols_define(void) {",
        "\tfor (size_t i = 0; i < (size_t)kFwApiSymCount; i++) {",
        "\t\tmrbc_symbol_new(0, symbol_name_table[i]);",
        "\t\tsymbol_id_table[i] = mrbc_search_symid(symbol_name_table[i]);",
        "\t\tif (symbol_id_table[i] < 0) {",
        "\t\t\treturn -1;",
        "\t\t}",
        "\t}",
        "\treturn 0;",
        "}",
        "",
        "/**",
        " * @brief Returns the live symid for a declared symbol slot",
        " *",
        " * @param sym The declared symbol slot",
        " * @return mrbc_sym The symid, or -1 when not yet defined",
        " */",
        "mrbc_sym fw_api_symbol_id(const fw_api_symbol_t sym) {",
        "\tif (sym < 0 || sym >= kFwApiSymCount) {",
        "\t\treturn -1;",
        "\t}",
        "\treturn symbol_id_table[sym];",
        "}",
        "",
        "/**",
        " * @brief Maps a live symid to its handler constant",
        " *",
        " * @param sym_id The symid carried by a MRBC_TT_SYMBOL argument",
        " * @return int32_t The declared constant, or -1 when unknown",
        " */",
        "int32_t fw_api_symbol_const(const mrbc_sym sym_id) {",
        "\tfor (size_t i = 0; i < (size_t)kFwApiSymCount; i++) {",
        "\t\tif (symbol_id_table[i] == sym_id) {",
        "\t\t\treturn symbol_const_table[i];",
        "\t\t}",
        "\t}",
        "\treturn -1;",
        "}",
        "",
    ]
    return "\n".join(header), "\n".join(source)


def _emit_aggregate(spec: MrubyApiDoc, contract_name: str, spec_rel: str) -> tuple[str, str]:
    comment = _comment(contract_name, spec_rel)
    guard = "FW_API_H"
    ordered = _sorted_classes(spec)
    header = [
        comment,
        f"#ifndef {guard}",
        f"#define {guard}",
        "",
        "#include <stdint.h>",
        "",
        "/** Driver/hardware init for every API (call before mrbc_init). */",
        "int fw_api_init_all(void);",
        "/** Register every declared class/method/symbol (post mrbc_init_class). */",
        "int fw_api_define_all(void);",
    ]
    if spec.system_task is not None:
        header += [
            "/** True when the running VM id is the declared system task. */",
            "int fw_api_is_system_task(uint8_t vm_id);",
        ]
    header += ["", f"#endif /* {guard} */", ""]
    source = [comment, '#include "fw_api.h"', "", '#include "mrubyc.h"']
    for cls in ordered:
        source.append(f'#include "fw_api_{_cname(cls)}.h"')
    if spec.symbols:
        source.append('#include "fw_api_symbols.h"')
    source += [
        "",
        "/**",
        " * @brief Runs every declared driver init (mirrors OpenBlink init.c)",
        " *",
        " * @return 0 when every init handler succeeded",
        " */",
        "int fw_api_init_all(void) {",
        "\tint rc = 0;",
    ]
    if spec.symbols:
        source.append("\trc |= fw_api_symbols_init();")
    for cls in ordered:
        if cls.init is not None:
            source.append(f"\trc |= fw_api_{_cname(cls)}_init();")
    source += [
        "\treturn rc;",
        "}",
        "",
        "/**",
        " * @brief Registers every declared class/method/symbol with the VM",
        " *",
        " * @details Mirrors the OpenBlink mrubyc_vm.c define sequence:",
        " *          symbols first, then classes in dependency order.",
        " * @return 0 when every define succeeded",
        " */",
        "int fw_api_define_all(void) {",
        "\tint rc = 0;",
    ]
    if spec.symbols:
        source.append("\trc |= fw_api_symbols_define();")
    for cls in ordered:
        source.append(f"\trc |= fw_api_{_cname(cls)}_define();")
    source += ["\treturn rc;", "}"]
    if spec.system_task is not None:
        source += [
            "",
            "/**",
            " * @brief Checks whether the running VM is the declared system task",
            " *",
            " * @details Mirrors api_api_check_systemtask in OpenBlink api.c:",
            " *          system-task-only methods bail out for other VMs.",
            " * @param vm_id The running VM id (vm->vm_id)",
            " * @return int non-zero when this VM is the system task",
            " */",
            "int fw_api_is_system_task(const uint8_t vm_id) {",
            f"\treturn vm_id == {spec.system_task.vm_id}u;",
            "}",
        ]
    source.append("")
    return "\n".join(header), "\n".join(source)


def render_api(spec: MrubyApiDoc, contract_name: str, spec_rel: str) -> dict[str, str]:
    """Render every generated artifact as an in-memory name -> text map."""
    files: dict[str, str] = {}
    header, source = _emit_aggregate(spec, contract_name, spec_rel)
    files["fw_api.h"], files["fw_api.c"] = header, source
    if spec.symbols:
        header, source = _emit_symbols(spec, contract_name, spec_rel)
        files["fw_api_symbols.h"], files["fw_api_symbols.c"] = header, source
    for cls in spec.classes:
        header, source = _emit_class(cls, spec, contract_name, spec_rel)
        files[f"fw_api_{_cname(cls)}.h"] = header
        files[f"fw_api_{_cname(cls)}.c"] = source
    return files


def generate_api(spec: MrubyApiDoc, contract_name: str, spec_rel: str, out_dir: Path) -> list[Path]:
    """Write every generated C artifact under ``out_dir``."""
    files = render_api(spec, contract_name, spec_rel)
    written: list[Path] = []
    out_dir.mkdir(parents=True, exist_ok=True)
    for name, text in files.items():
        path = out_dir / name
        path.write_text(text, encoding="utf-8")
        written.append(path)
    return written


# ---------------------------------------------------------------- gate


def _handler_names(spec: MrubyApiDoc) -> list[str]:
    """Every handler symbol a generated binding calls."""
    names: list[str] = []
    for cls in spec.classes:
        if cls.init is not None:
            names.append(cls.init)
        if cls.instance is not None:
            names += [
                n for n in (cls.instance.constructor, cls.instance.destructor) if n is not None
            ]
        names += [m.handler for m in cls.methods]
    return names


def uses_feature(spec: MrubyApiDoc) -> dict[str, bool]:
    """VM features the generated bindings need (drives flag cross-checks)."""
    needs = {"float": False, "string": False}
    for cls in spec.classes:
        for const in cls.constants:
            needs["float"] |= isinstance(const.value, float)
            needs["string"] |= isinstance(const.value, str)
        for method in cls.methods:
            for param in method.params + method.kwargs:
                needs["float"] |= param.type == "float"
                needs["string"] |= param.type == "string"
            needs["float"] |= method.returns.type in ("float", "array<float>")
            needs["string"] |= method.returns.type == "string"
    return needs


def consumed_symbols(spec: MrubyApiDoc) -> int:
    """Distinct symids the generated code registers into the app symbol table.

    mruby/c keeps user symbols in ``sym_index[MAX_SYMBOLS_COUNT]`` (builtins
    live in a separate ROM table), so the spec's declared symbols plus every
    class/method/constant/keyword name must fit the configured budget.
    """
    names: set[str] = set()
    for cls in spec.classes:
        names.add(cls.name)
        names.update(c.name for c in cls.constants)
        for method in cls.methods:
            names.add(method.name)
            names.update(p.name for p in method.kwargs)
        if cls.instance is not None:
            names.add("new")
    return len(spec.symbols) + len(names)


def api_problems(
    contract: FirmwareContract, link: MrubyDeviceApi, contract_path: Path
) -> tuple[list[str], list[str]]:
    """Validate the pinned spec plus generated freshness for ``fw.mrubyc``."""
    problems: list[str] = []
    evidence: list[str] = []
    assert contract.mrubyc is not None  # guaranteed by the mrubyc config link
    cfg = contract.mrubyc
    spec_path = resolve(contract_path, link.spec)
    if not spec_path.is_file():
        return [f"device api spec {link.spec} missing"], evidence
    sha = sha256_file(spec_path)
    if sha != link.sha256:
        problems.append(
            f"device api spec sha256 {sha} differs from pinned {link.sha256}; review and re-pin"
        )
        return problems, evidence
    try:
        spec = MrubyApiDoc.model_validate(json.loads(spec_path.read_text(encoding="utf-8")))
    except Exception as exc:
        problems.append(f"device api spec invalid: {exc}")
        return problems, evidence
    evidence.append(f"classes={len(spec.classes)} symbols={len(spec.symbols)}")

    if spec.system_task is not None and spec.system_task.vm_id > cfg.max_vm_count:
        problems.append(
            f"system_task.vm_id {spec.system_task.vm_id} exceeds max_vm_count {cfg.max_vm_count}"
        )
    needs = uses_feature(spec)
    if needs["float"] and cfg.use_float == 0:
        problems.append("device api uses float but mrubyc.use_float=0")
    if needs["string"] and not cfg.use_string:
        problems.append("device api uses string but mrubyc.use_string is false")
    consumed = consumed_symbols(spec)
    evidence.append(f"symbols={consumed}/{cfg.max_symbols}")
    if consumed > cfg.max_symbols:
        problems.append(
            f"device api consumes {consumed} app symbols; "
            f"max_symbols {cfg.max_symbols} would overflow at runtime"
        )

    header_path = resolve(contract_path, link.handlers_header)
    if not header_path.is_file():
        problems.append(f"handlers header {link.handlers_header} missing")
    else:
        text = header_path.read_text(encoding="utf-8")
        for name in _handler_names(spec):
            if not re.search(rf"\b{re.escape(name)}\b", text):
                problems.append(f"handler {name} not declared in {header_path.name}")

    out_dir = resolve(contract_path, cfg.generated_dir)
    rendered = render_api(spec, contract.name, link.spec)
    for name, text in rendered.items():
        target = out_dir / name
        if not target.is_file():
            problems.append(f"{name} missing; run `firmware mrubyc`")
        elif target.read_text(encoding="utf-8") != text:
            problems.append(f"{name} stale; run `firmware mrubyc`")
    if cfg.ux_manifest is not None:
        ux_path = resolve(contract_path, cfg.ux_manifest.manifest)
        if ux_path.is_file():
            try:
                ux = json.loads(ux_path.read_text(encoding="utf-8"))
                ux_classes = set(ux.get("classes", []))
                overlap = ux_classes & {c.name for c in spec.classes}
                if overlap:
                    problems.append(
                        "classes declared by the device api and the ux manifest: "
                        + ", ".join(sorted(overlap))
                    )
            except (OSError, json.JSONDecodeError):
                pass
    return problems, evidence
