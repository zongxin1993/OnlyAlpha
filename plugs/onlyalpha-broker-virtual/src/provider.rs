use crate::config::Config;
use onlyalpha_broker::Error;
use serde_json::{Value, json};

pub const VIRTUAL_BROKER_TYPE_ID: &str = "onlyalpha.virtual_broker";

pub const CAPABILITIES: &[&str] = &[
    "AUTHENTICATE",
    "CANCEL_ORDER",
    "CONNECT",
    "LIMIT_ORDER",
    "MARKET_ORDER",
    "PARTIAL_FILL",
    "PUSH_ORDER_UPDATES",
    "PUSH_TRADE_UPDATES",
    "QUERY_ACCOUNT",
    "QUERY_BALANCES",
    "QUERY_FEE_EVIDENCE",
    "QUERY_OPEN_ORDERS",
    "QUERY_ORDERS",
    "QUERY_POSITIONS",
    "QUERY_TRADES",
    "SUBMIT_ORDER",
];

pub fn descriptor() -> Value {
    let configuration = json!({
        "fingerprint": "2d0a6aff884e5e0c1bf301bfe4a949775534e9808842a24ba26e61b4d56e9273",
        "fields": [
            {
                "advanced": true, "default": null, "description": "各场所操作的非负纳秒延迟",
                "display_name": "模拟延迟", "enum_values": [], "exclusive_minimum": false,
                "field_id": "latency", "maximum": null, "minimum": null, "required": false,
                "secret": false, "value_kind": "STRING_INTEGER_MAP"
            },
            {
                "advanced": false, "default": null, "description": "每根行情柱可成交的最大数量，以精确十进制字符串表示",
                "display_name": "单柱最大成交量", "enum_values": [], "exclusive_minimum": false,
                "field_id": "maximum_fill_quantity", "maximum": null, "minimum": null,
                "required": false, "secret": false, "value_kind": "STRING"
            }
        ],
        "schema_version": 1
    });
    json!({
        "schema_version": 1,
        "type_id": VIRTUAL_BROKER_TYPE_ID,
        "category": "BROKER",
        "display_name": "OnlyAlpha 模拟券商",
        "description": "按绑定的配置和有序行情推进模拟订单与成交。",
        "provider_id": "virtual",
        "implementation_id": "virtual",
        "implementation_version": crate::IMPLEMENTATION_VERSION,
        "public_api_version": "1.0",
        "capabilities": CAPABILITIES,
        "configuration_contract": configuration,
        "probe_contract": null
    })
}

/// 返回运行绑定中的规范配置，创建场所时仍传入原始配置。
pub fn normalize_configuration(extensions: &Value) -> Result<Value, Error> {
    Ok(Config::parse(extensions)?.record)
}
