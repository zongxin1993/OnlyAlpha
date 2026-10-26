"""Project the server's one WebSocket contract to JSON Schema and Web Zod."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.native_http_contract import exported, schema_document

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = ROOT / "contracts/product-api/v2/market-data-stream.schema.json"
WEB = ROOT / "packages/frontend/src/api/marketData/stream.generated.ts"


def _expression(schema: dict[str, Any]) -> str:
    if "allOf" in schema:
        parts = [_expression(part) for part in schema["allOf"]]
        if len(parts) == 1:
            return parts[0]
        result = parts[0]
        for part in parts[1:]:
            result = f"z.intersection({result}, {part})"
        return result
    kind = schema.get("type")
    if isinstance(kind, list):
        return _expression({"anyOf": [{**schema, "type": item} for item in kind]})
    if "$ref" in schema:
        return str(schema["$ref"]).split("/")[-1] + "Schema"
    if "anyOf" in schema:
        variants = schema["anyOf"]
        if len(variants) == 1:
            return _expression(variants[0])
        if (
            len(variants) == 2
            and all(isinstance(part.get("type"), str) for part in variants)
            and {part.get("type") for part in variants} == {"string", "null"}
        ):
            return _expression(next(part for part in variants if part.get("type") == "string")) + ".nullable()"
        return "z.union([" + ", ".join(_expression(part) for part in variants) + "])"
    if "oneOf" in schema:
        if len(schema["oneOf"]) == 1:
            return _expression(schema["oneOf"][0])
        return "z.union([" + ", ".join(_expression(part) for part in schema["oneOf"]) + "])"
    if "const" in schema:
        return f"z.literal({json.dumps(schema['const'])})"
    if "enum" in schema:
        values = schema["enum"]
        if len(values) == 1:
            return f"z.literal({json.dumps(values[0])})"
        if all(isinstance(value, str) for value in values):
            return "z.enum([" + ", ".join(json.dumps(item) for item in values) + "])"
        return "z.union([" + ", ".join(f"z.literal({json.dumps(item)})" for item in values) + "])"
    kind = schema.get("type")
    if kind == "string":
        result = "z.string()"
        if "minLength" in schema:
            result += f".min({schema['minLength']})"
        if "maxLength" in schema:
            result += f".max({schema['maxLength']})"
        if "pattern" in schema:
            result += f".regex(new RegExp({json.dumps(schema['pattern'])}))"
        return result
    if kind in {"integer", "number"}:
        result = "z.number().int()" if kind == "integer" else "z.number()"
        if "minimum" in schema:
            result += f".min({schema['minimum']})"
        if "maximum" in schema:
            result += f".max({schema['maximum']})"
        return result
    if kind == "boolean":
        return "z.boolean()"
    if kind == "array":
        result = f"z.array({_expression(schema['items'])})"
        if "minItems" in schema:
            result += f".min({schema['minItems']})"
        if "maxItems" in schema:
            result += f".max({schema['maxItems']})"
        if schema.get("uniqueItems"):
            if schema["items"].get("type") not in {"string", "integer", "boolean"}:
                raise ValueError("unique object/union array contract is unsupported")
            result += ".refine(value => new Set(value).size === value.length)"
        return result
    if kind == "null":
        return "z.null()"
    if kind == "object":
        additional = schema.get("additionalProperties", False)
        if isinstance(additional, dict) and "properties" not in schema:
            names = schema.get("propertyNames", {})
            if (
                not isinstance(names, dict)
                or names.get("type", "string") != "string"
                or set(names) - {"type", "minLength", "maxLength", "pattern", "title", "description"}
            ):
                raise ValueError("unsupported record key contract")
            key = {"type": "string", **names}
            result = f"z.record({_expression(key)}, {_expression(additional)})"
            if "minProperties" in schema:
                result += f".refine(value => Object.keys(value).length >= {schema['minProperties']})"
            if "maxProperties" in schema:
                result += f".refine(value => Object.keys(value).length <= {schema['maxProperties']})"
            return result
        if additional is not False:
            raise ValueError("open or mixed object contract is unsupported")
        required = set(schema.get("required", []))
        fields = [
            f"    {json.dumps(name)}: {_expression(value)}{'' if name in required else '.optional()'}"
            for name, value in schema.get("properties", {}).items()
        ]
        return "z.strictObject({\n" + ",\n".join(fields) + "\n})"
    if not (set(schema) - {"description", "title", "default", "example", "examples"}):
        return "z.json()"
    raise ValueError(f"unsupported stream contract schema: {schema}")


def _definitions(document: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    definitions = document["$defs"]
    result: list[tuple[str, dict[str, Any]]] = []
    pending = dict(definitions)
    while pending:
        ready = [
            name for name, schema in pending.items() if all(ref.split("/")[-1] not in pending for ref in _refs(schema))
        ]
        if not ready:
            raise ValueError("recursive stream contract is unsupported")
        for name in ready:
            result.append((name, pending.pop(name)))
    return result


def _refs(value: Any) -> list[str]:
    if isinstance(value, dict):
        return ([value["$ref"]] if "$ref" in value else []) + [ref for child in value.values() for ref in _refs(child)]
    if isinstance(value, list):
        return [ref for child in value for ref in _refs(child)]
    return []


def render() -> tuple[str, str]:
    native = exported("websocket")
    roots = {name: schema_document(native["contract"], target) for name, target in native["message_roots"].items()}
    definitions: dict[str, Any] = {}
    for root in roots.values():
        for name, schema in root.pop("$defs").items():
            if name in definitions and definitions[name] != schema:
                raise ValueError("Native WS definition collision")
            definitions[name] = schema
    subscribe, event = (roots[name] for name in ("subscribe", "event"))
    temporary_subscribe, temporary_event = (roots[name] for name in ("temporary_subscribe", "temporary_event"))
    document: dict[str, Any] = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "onlyalpha.product-api.v2.market-data-stream",
        "$defs": definitions,
        "anyOf": [
            {"$ref": "#/$defs/subscribe"},
            {"$ref": "#/$defs/event"},
            {"$ref": "#/$defs/temporary_subscribe"},
            {"$ref": "#/$defs/temporary_event"},
        ],
    }
    document["$defs"]["subscribe"] = subscribe
    document["$defs"]["subscribe"]["if"] = {"properties": {"resume_after_sequence": {"not": {"const": "0"}}}}
    document["$defs"]["subscribe"]["then"] = {
        "required": ["resume_plan_fingerprint"],
        "properties": {"resume_plan_fingerprint": {"type": "string"}},
    }
    document["$defs"]["event"] = event
    document["$defs"]["temporary_subscribe"] = temporary_subscribe
    document["$defs"]["temporary_event"] = temporary_event
    lines = ["// Generated by scripts/market_data_stream_contract.py; do not edit.", 'import { z } from "zod";', ""]
    for name, schema in _definitions(document):
        if name in {"subscribe", "event", "temporary_subscribe", "temporary_event"}:
            continue
        lines.append(f"const {name}Schema = {_expression(schema)};")
    lines += [
        f'export const marketDataStreamSubscribeSchema = {_expression(subscribe)}.refine(value => value.resume_after_sequence === "0" || value.resume_plan_fingerprint !== null && value.resume_plan_fingerprint !== undefined);',
        f"export const marketDataStreamEventSchema = {_expression(event)};",
        f"export const temporaryMarketDataStreamSubscribeSchema = {_expression(temporary_subscribe)};",
        f"export const temporaryMarketDataStreamEventSchema = {_expression(temporary_event)};",
        "export type TemporaryMarketDataStreamSubscribe = z.infer<typeof temporaryMarketDataStreamSubscribeSchema>;",
        "export type TemporaryMarketDataStreamEvent = z.infer<typeof temporaryMarketDataStreamEventSchema>;",
        "export type MarketDataStreamSubscribe = z.infer<typeof marketDataStreamSubscribeSchema>;",
        "export type MarketDataStreamEvent = z.infer<typeof marketDataStreamEventSchema>;",
        "",
    ]
    web = subprocess.run(
        [str(ROOT / "packages/frontend/node_modules/.bin/prettier"), "--stdin-filepath", str(WEB)],
        input="\n".join(lines),
        text=True,
        capture_output=True,
        check=True,
    ).stdout
    return json.dumps(document, indent=2, ensure_ascii=False) + "\n", web


def main() -> None:
    schema, web = render()
    if sys.argv[1:] == ["write"]:
        SCHEMA.write_text(schema, encoding="utf-8")
        WEB.write_text(web, encoding="utf-8")
    elif sys.argv[1:] == ["check"]:
        if SCHEMA.read_text(encoding="utf-8") != schema or WEB.read_text(encoding="utf-8") != web:
            raise SystemExit(
                "Market Data Stream contract projection is stale; run scripts/market_data_stream_contract.py write"
            )
    else:
        raise SystemExit("usage: market_data_stream_contract.py write|check")


if __name__ == "__main__":
    main()
