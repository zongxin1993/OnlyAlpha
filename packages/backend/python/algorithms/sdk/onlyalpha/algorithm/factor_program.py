"""Compile the closed authoring language to data, never execute supplied Python.

The Rust calculation owner validates types/budgets and executes the resulting
program. Compiling source does not confer readiness, permission or certification.
"""

from __future__ import annotations

import ast
from decimal import Decimal, InvalidOperation, localcontext
from typing import Any, cast

_NUMERIC = {"add", "sub", "mul", "div", "abs", "sign", "log", "negate", "min", "max"}
_LOGICAL = {"eq", "ne", "lt", "le", "gt", "ge", "not_", "and_", "or_", "is_missing", "where", "coalesce"}
_WINDOWS = {
    "delay",
    "delta",
    "rolling_mean",
    "rolling_sum",
    "rolling_min",
    "rolling_max",
    "rolling_std",
    "rolling_var",
    "ts_rank",
    "decay_linear",
}


def _name(value: object) -> str:
    if (
        type(value) is not str
        or not value
        or len(value) > 64
        or not value.isascii()
        or not all(c.isalnum() or c == "_" for c in value)
    ):
        raise ValueError("FACTOR_PROGRAM_NAME")
    return value


def _scalar(kind: str, value: object) -> dict[str, object]:
    if kind == "BOOLEAN":
        if type(value) is not bool:
            raise ValueError("FACTOR_PROGRAM_BOOLEAN")
    elif kind == "INTEGER":
        if type(value) is not int or len(str(value)) > 256:
            raise ValueError("FACTOR_PROGRAM_INTEGER")
    elif kind == "DECIMAL":
        if type(value) not in (str, int) or len(str(value)) > 512:
            raise ValueError("FACTOR_PROGRAM_DECIMAL")
        try:
            d = Decimal(cast(str | int, value))
        except InvalidOperation as exc:
            raise ValueError("FACTOR_PROGRAM_DECIMAL") from exc
        if not d.is_finite() or len(d.as_tuple().digits) > 256 or abs(int(d.as_tuple().exponent)) > 1024:
            raise ValueError("FACTOR_PROGRAM_DECIMAL_BUDGET")
        with localcontext() as ctx:
            ctx.prec = 512
            value = "0" if d.is_zero() else format(d.normalize(), "f")
    else:
        raise ValueError("FACTOR_PROGRAM_TYPE")
    return {"type": kind, "value": value}


def compile_factor_source(
    source: str,
    interface_version: int,
    *,
    input_contract: dict[str, Any],
    parameter_contract: dict[str, Any],
    output_contract: dict[str, Any],
) -> dict[str, Any]:
    if (
        type(source) is not str
        or len(source.encode()) > 65536
        or type(interface_version) is not int
        or interface_version != 1
    ):
        raise ValueError("FACTOR_PROGRAM_SOURCE_BUDGET")
    for contract in (input_contract, parameter_contract, output_contract):
        if type(contract) is not dict or len(contract) > 128:
            raise ValueError("FACTOR_PROGRAM_CONTRACT_BUDGET")
        for name in contract:
            _name(name)
    if not output_contract:
        raise ValueError("FACTOR_PROGRAM_OUTPUT_REQUIRED")
    try:
        tree = ast.parse(source, mode="exec")
    except (SyntaxError, RecursionError) as exc:
        raise ValueError("FACTOR_PROGRAM_SYNTAX") from exc
    if sum(1 for _ in ast.walk(tree)) > 4096 or len(tree.body) != 1 or not isinstance(tree.body[0], ast.FunctionDef):
        raise ValueError("FACTOR_PROGRAM_ENTRYPOINT")
    fn = tree.body[0]
    args = fn.args
    if (
        fn.name != "calculate"
        or [a.arg for a in args.args] != ["api", "inputs", "parameters"]
        or args.posonlyargs
        or args.kwonlyargs
        or args.vararg
        or args.kwarg
        or args.defaults
        or args.kw_defaults
        or fn.decorator_list
        or fn.returns
        or fn.type_params
        or any(a.annotation for a in args.args)
    ):
        raise ValueError("FACTOR_PROGRAM_SIGNATURE")
    schema = []
    for name, p in sorted(parameter_contract.items()):
        if type(p) is not dict or set(p) - {
            "type",
            "required",
            "default",
            "minimum",
            "maximum",
            "enum_values",
            "uppercase",
        }:
            raise ValueError("FACTOR_PROGRAM_PARAMETER_SCHEMA")
        kind = p.get("type")
        if not isinstance(kind, str):
            raise ValueError("FACTOR_PROGRAM_PARAMETER_TYPE")
        required = p.get("required", "default" not in p)
        if (
            type(required) is not bool
            or type(p.get("uppercase", False)) is not bool
            or p.get("uppercase", False)
            or type(p.get("enum_values", [])) is not list
            or (required and "default" in p)
        ):
            raise ValueError("FACTOR_PROGRAM_PARAMETER_SCHEMA")
        schema.append(
            {
                "name": name,
                "parameter_type": kind,
                "required": required,
                "default": None if required else _scalar(kind, p.get("default")),
                "minimum": None if p.get("minimum") is None else _scalar(kind, p["minimum"]),
                "maximum": None if p.get("maximum") is None else _scalar(kind, p["maximum"]),
                "enum_values": [_scalar(kind, v) for v in p.get("enum_values", [])],
                "uppercase": False,
            }
        )
    for contract in (input_contract, output_contract):
        for spec in contract.values():
            if type(spec) is not dict or spec.get("type") not in ("DECIMAL", "INTEGER", "BOOLEAN"):
                raise ValueError("FACTOR_PROGRAM_VALUE_CONTRACT")
            if any(type(spec[key]) is not bool for key in ("nullable", "missing") if key in spec):
                raise ValueError("FACTOR_PROGRAM_NULLABILITY")
            if "nullable" in spec and "missing" in spec and spec["nullable"] != spec["missing"]:
                raise ValueError("FACTOR_PROGRAM_NULLABILITY")
    inputs = {}
    for name, p in sorted(input_contract.items()):
        if (
            type(p) is not dict
            or p.get("type") not in ("DECIMAL", "INTEGER", "BOOLEAN")
            or p.get("role", "MARKET") not in ("MARKET", "FACTOR")
        ):
            raise ValueError("FACTOR_PROGRAM_INPUT")
        inputs[name] = {"type": p["type"], "role": p.get("role", "MARKET")}
    nodes: list[dict[str, Any]] = []
    locals_: dict[str, int] = {}

    def emit(node: dict[str, Any]) -> int:
        if len(nodes) >= 1024:
            raise ValueError("FACTOR_PROGRAM_NODE_BUDGET")
        nodes.append(node)
        return len(nodes) - 1

    def reference(e: ast.AST, root: str) -> str:
        if (
            not isinstance(e, ast.Subscript)
            or not isinstance(e.value, ast.Name)
            or e.value.id != root
            or not isinstance(e.slice, ast.Constant)
            or type(e.slice.value) is not str
        ):
            raise ValueError("FACTOR_PROGRAM_REFERENCE")
        key = e.slice.value
        if key not in (input_contract if root == "inputs" else parameter_contract):
            raise ValueError("FACTOR_PROGRAM_UNKNOWN_REFERENCE")
        return key

    def expression(e: ast.AST, depth: int = 0) -> int:
        if depth > 64:
            raise ValueError("FACTOR_PROGRAM_DEPTH")
        if isinstance(e, ast.Name) and e.id in locals_:
            return locals_[e.id]
        if isinstance(e, ast.Subscript):
            if isinstance(e.value, ast.Name) and e.value.id in ("inputs", "parameters"):
                root = e.value.id
                key = reference(e, root)
                return emit({"op": "input" if root == "inputs" else "parameter", "name": key})
        if isinstance(e, ast.Constant):
            v = e.value
            if v is None:
                return emit({"op": "literal", "type": "DECIMAL", "value": None})
            if type(v) is bool:
                return emit({"op": "literal", "type": "BOOLEAN", "value": v})
            if type(v) is int:
                return emit({"op": "literal", "type": "INTEGER", "value": str(v)})
        if (
            isinstance(e, ast.Call)
            and isinstance(e.func, ast.Attribute)
            and isinstance(e.func.value, ast.Name)
            and e.func.value.id == "api"
            and not e.keywords
        ):
            op = e.func.attr
            if (
                op == "decimal"
                and len(e.args) == 1
                and isinstance(e.args[0], ast.Constant)
                and type(e.args[0].value) is str
            ):
                return emit({"op": "literal", **_scalar("DECIMAL", e.args[0].value)})
            if op in _WINDOWS and len(e.args) == 2:
                value = expression(e.args[0], depth + 1)
                period = e.args[1]
                if isinstance(period, ast.Constant) and type(period.value) is int and 0 < period.value <= 100000:
                    p: int | dict[str, str] = period.value
                else:
                    name = reference(period, "parameters")
                    if parameter_contract[name]["type"] != "INTEGER":
                        raise ValueError("FACTOR_PROGRAM_PERIOD_TYPE")
                    p = {"parameter": name}
                return emit({"op": op, "args": [value], "period": p})
            if op in _NUMERIC | _LOGICAL:
                arity = 1 if op in {"abs", "sign", "log", "negate", "not_", "is_missing"} else 3 if op == "where" else 2
                if len(e.args) != arity:
                    raise ValueError("FACTOR_PROGRAM_ARITY")
                a = [expression(arg, depth + 1) for arg in e.args]
                return emit({"op": op, "args": a})
        raise ValueError("FACTOR_PROGRAM_FORBIDDEN_EXPRESSION")

    outputs: dict[str, int] | None = None
    for statement in fn.body:
        if outputs is not None:
            raise ValueError("FACTOR_PROGRAM_UNREACHABLE")
        if (
            isinstance(statement, ast.Assign)
            and len(statement.targets) == 1
            and isinstance(statement.targets[0], ast.Name)
        ):
            name = _name(statement.targets[0].id)
            if name in ("api", "inputs", "parameters") or name.startswith("__"):
                raise ValueError("FACTOR_PROGRAM_RESERVED_NAME")
            locals_[name] = expression(statement.value)
        elif isinstance(statement, ast.Return) and isinstance(statement.value, ast.Dict):
            out = statement.value
            if any(not isinstance(k, ast.Constant) or type(k.value) is not str for k in out.keys):
                raise ValueError("FACTOR_PROGRAM_OUTPUT_KEYS")
            keys = [cast(str, cast(ast.Constant, k).value) for k in out.keys]
            if len(set(keys)) != len(keys) or set(keys) != set(output_contract):
                raise ValueError("FACTOR_PROGRAM_OUTPUT_MEMBERS")
            outputs = {k: expression(v) for k, v in zip(keys, out.values, strict=True)}
        else:
            raise ValueError("FACTOR_PROGRAM_FORBIDDEN_STATEMENT")
    if outputs is None:
        raise ValueError("FACTOR_PROGRAM_RETURN_REQUIRED")
    # The declared output owns promotion. Never silently narrow Decimal to
    # Integer; native type checking rejects that mismatch. Promotion itself
    # does not round: the native output boundary applies NumericPolicy once.
    for name, index in outputs.items():
        if output_contract[name]["type"] == "DECIMAL":
            outputs[name] = emit({"op": "to_decimal", "args": [index]})
    return {
        "schema_version": 1,
        "numeric_policy": "DECIMAL28_HALF_EVEN_Q12_V1",
        "inputs": inputs,
        "parameters": schema,
        "nodes": nodes,
        "outputs": outputs,
    }
