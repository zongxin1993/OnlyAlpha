"""Generate the frozen Alpha158 fixture from the public formulas and independent Decimal arithmetic."""

import ast
import json
import operator
import sys
from decimal import Decimal as D, ROUND_HALF_EVEN, getcontext, localcontext
from pathlib import Path
from statistics import mean, pstdev


PERIODS = 69
SCALE = D("1e-12")


def market(instrument):
    columns = {key: [] for key in ("open", "high", "low", "close", "vwap", "volume")}
    for t in range(PERIODS):
        close = 35 + ((t * t + 3 * t) % 17) if instrument == 0 else 51 + (t // 3) % 5
        opening = close + (t + instrument) % 5 - 2
        high, low = max(opening, close) + t % 3, min(opening, close) - t % 2
        if instrument == 1 and 8 <= t <= 14:
            opening = high = low = close = 52
        volume = 3 + (t * 11 + t // 4 + instrument * 9) % 23
        if instrument == 1 and (t == 2 or 8 <= t <= 14):
            volume = 0
        for key, value in zip(columns, (opening, high, low, close, D(high + low) / 2, volume)):
            columns[key].append(D(value))
    if instrument == 1:
        columns["low"][3] = None
        columns["volume"][64] = None
        columns["close"][65] = None
    return columns


def public_value(x):
    if x is None:
        return None
    with localcontext() as ctx:
        ctx.prec = 28
        return (+x).quantize(SCALE, rounding=ROUND_HALF_EVEN)


def rolling(name, x, y, q):
    n = len(x)
    if name == "Sum":
        return sum(x)
    if name == "Mean":
        return mean(x)
    if name == "Std":
        return pstdev(x)
    if name == "Max":
        return max(x)
    if name == "Min":
        return min(x)
    if name in ("IdxMax", "IdxMin"):
        return D(1 + x.index((max if name == "IdxMax" else min)(x)))
    if name == "Rank":
        ranks = [i for i, value in enumerate(sorted(x)) if value == x[-1]]
        return D(sum(ranks)) / (len(ranks) * (n - 1)) if n > 1 else D("0.5")
    if name == "Quantile":
        ordered = sorted(x)
        position = (n - 1) * q
        lo = int(position)
        weight = position - lo
        return ordered[lo] * (1 - weight) + ordered[min(lo + 1, n - 1)] * weight
    if name == "Corr":
        ax, ay = mean(x), mean(y)
        xx = sum((v - ax) ** 2 for v in x)
        yy = sum((v - ay) ** 2 for v in y)
        xy = sum((v - ax) * (w - ay) for v, w in zip(x, y))
        return xy / (xx * yy).sqrt() if xx and yy else None
    if name in ("Slope", "Rsquare", "Resi"):
        if n == 1:
            return None
        center = D(n - 1) / 2
        offsets = [i - center for i in range(n)]
        slope = sum(v * u for v, u in zip(x, offsets)) / sum(u * u for u in offsets)
        if name == "Slope":
            return slope
        avg = mean(x)
        residuals = [v - (avg + slope * u) for v, u in zip(x, offsets)]
        if name == "Resi":
            return residuals[-1]
        total = sum((v - avg) ** 2 for v in x)
        return 1 - sum(e * e for e in residuals) / total if total else None
    raise ValueError(name)


BINARY = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
          ast.Div: lambda a, b: a / b if b else None,
          ast.Lt: lambda a, b: D(a < b), ast.Gt: lambda a, b: D(a > b)}
POINTWISE = {"Greater": max, "Less": min, "Abs": abs, "Log": lambda x: x.ln() if x > 0 else None}


def apply(function, columns):
    return [None if None in row else public_value(function(*row)) for row in zip(*columns)]


def evaluate(node, source, fields):
    def child(expr):
        return evaluate(expr, source, fields)

    if isinstance(node, ast.Name):
        return fields[node.id]
    if isinstance(node, ast.Constant):
        return [D(ast.get_source_segment(source, node))] * PERIODS
    if isinstance(node, ast.BinOp):
        return apply(BINARY[type(node.op)], [child(node.left), child(node.right)])
    if isinstance(node, ast.Compare):
        return apply(BINARY[type(node.ops[0])], [child(node.left), child(node.comparators[0])])
    if not isinstance(node, ast.Call):
        raise ValueError(ast.dump(node))
    name = node.func.id
    if name in POINTWISE:
        return apply(POINTWISE[name], [child(a) for a in node.args])
    x = child(node.args[0])
    if name == "Ref":
        lag = node.args[1].value
        return [None] * lag + x[:PERIODS-lag]
    paired = name == "Corr"
    y = child(node.args[1]) if paired else []
    window = node.args[2 if paired else 1].value
    q = D(ast.get_source_segment(source, node.args[2])) if name == "Quantile" else None
    result = [None] * (window - 1)
    for end in range(window, len(x) + 1):
        xs, ys = x[end-window:end], y[end-window:end]
        value = None if None in xs or None in ys else rolling(name, xs, ys, q)
        result.append(public_value(value))
    return result


def encode(x):
    if not isinstance(x, D):
        raise TypeError(x)
    return str(x.normalize()) if x else "0"


def emit(record):
    print(json.dumps(record, default=encode, separators=(",", ":")))


if __name__ == "__main__":
    getcontext().prec = 70
    root = Path(sys.argv[1])
    panel = [market(0), market(1)]
    emit({"panel": panel})
    for item in json.loads((root / "manifest.json").read_text())["features"]:
        factor = json.loads((root / item["file"]).read_text())
        source = factor["expression"].replace("$", "")
        tree = ast.parse(source, mode="eval").body
        emit({"name": factor["name"], "values": [evaluate(tree, source, fields) for fields in panel]})
