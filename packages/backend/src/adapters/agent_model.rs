//! One explicitly configured OpenAI-compatible structured-output adapter. No retries/tools.
use crate::application::factor_chat::{INVALID, Result, hash};
use onlyalpha_integration_contract::{
    Category, Descriptor, Error,
    authoring::{PluginProjection, Registration},
};
use serde_json::{Value, json, value::RawValue};
use std::time::Duration;
pub const TYPE_ID: &str = "openai.compatible.agent_provider";
pub fn endpoint(raw: &str) -> Result<reqwest::Url> {
    let mut u = reqwest::Url::parse(raw).map_err(|_| INVALID)?;
    if !u.username().is_empty()
        || u.password().is_some()
        || u.query().is_some()
        || u.fragment().is_some()
        || !(u.scheme() == "https"
            || (u.scheme() == "http"
                && matches!(u.host_str(), Some("127.0.0.1" | "[::1]" | "localhost"))))
    {
        return Err(INVALID);
    }
    let path = format!("{}/chat/completions", u.path().trim_end_matches('/'));
    u.set_path(&path);
    Ok(u)
}
fn validate(raw: &RawValue, _: usize) -> std::result::Result<(), Error> {
    let v: Value = serde_json::from_str(raw.get()).map_err(|_| Error::Configuration)?;
    for (k, v) in v.as_object().ok_or(Error::Configuration)? {
        let s = v
            .as_str()
            .filter(|s| !s.trim().is_empty() && s.len() <= 2048 && !s.chars().any(char::is_control))
            .ok_or(Error::Configuration)?;
        match k.as_str() {
            "base_url" => {
                endpoint(s).map_err(|_| Error::Configuration)?;
            }
            "model_id" | "model_version" => {}
            _ => return Err(Error::Configuration),
        }
    }
    Ok(())
}
pub fn registration(work: usize) -> std::result::Result<Registration, Error> {
    let fields:Vec<Value>=[("api_credential","API 密钥",true),("base_url","服务地址",false),("model_id","模型名称",false),("model_version","模型版本说明",false)].into_iter().map(|(id,label,secret)|json!({"field_id":id,"display_name":label,"description":"","value_kind":"STRING","required":true,"secret":secret,"advanced":false,"default":null,"enum_values":[],"minimum":null,"maximum":null,"exclusive_minimum":false})).collect();
    let mut config = json!({"schema_version":1,"fields":fields});
    config["fingerprint"] = json!(hash(&config).map_err(|_| Error::Type)?);
    let doc = json!({"schema_version":1,"type_id":TYPE_ID,"category":"AGENT_PROVIDER","display_name":"OpenAI-compatible 模型","description":"仅用于聊天因子草稿；不授予 Research 或交易权限。","provider_id":"openai-compatible","implementation_id":"openai-compatible","implementation_version":"1.0.0","public_api_version":"1.1","capabilities":["CHAT","STRUCTURED_OUTPUT"],"configuration_contract":config,"probe_contract":null});
    Registration::new(
        PluginProjection::new(
            Category::AgentProvider,
            "openai-compatible",
            "1.0.0",
            "1.1",
            vec!["CHAT".into(), "STRUCTURED_OUTPUT".into()],
        )?,
        Descriptor::from_json(&doc.to_string(), work)?,
        validate,
    )
}
/// Every external response is bounded, recorded by the caller, and never retried here.
pub async fn invoke(config: &Value, secret: &str, body: &Value) -> Result<Value> {
    let url = endpoint(config["base_url"].as_str().ok_or(INVALID)?)?;
    if body["model"] != config["model_id"] {
        return Err("FACTOR_CHAT_MODEL_BINDING_UNAVAILABLE");
    }
    let client = reqwest::Client::builder()
        .no_proxy()
        .redirect(reqwest::redirect::Policy::none())
        .connect_timeout(Duration::from_secs(10))
        .timeout(Duration::from_secs(60))
        .build()
        .map_err(|_| "FACTOR_CHAT_MODEL_UNAVAILABLE")?;
    let mut r = client
        .post(url)
        .bearer_auth(secret)
        .header("content-type", "application/json")
        .body(body.to_string())
        .send()
        .await
        .map_err(|_| "FACTOR_CHAT_MODEL_OUTCOME_UNKNOWN")?;
    if !r.status().is_success() {
        return Err("FACTOR_CHAT_MODEL_FAILED");
    }
    let mut bytes = vec![];
    while let Some(chunk) = r
        .chunk()
        .await
        .map_err(|_| "FACTOR_CHAT_MODEL_OUTCOME_UNKNOWN")?
    {
        if bytes.len() + chunk.len() > 65536 {
            return Err("FACTOR_CHAT_MODEL_RESPONSE_INVALID");
        }
        bytes.extend_from_slice(&chunk);
    }
    let raw = std::str::from_utf8(&bytes).map_err(|_| "FACTOR_CHAT_MODEL_RESPONSE_INVALID")?;
    onlyalpha_metadata_json::canonical_json(raw, 8 * 1024 * 1024)
        .map_err(|_| "FACTOR_CHAT_MODEL_RESPONSE_INVALID")?;
    let r: Value = serde_json::from_str(raw).map_err(|_| "FACTOR_CHAT_MODEL_RESPONSE_INVALID")?;
    let content = r["choices"][0]["message"]["content"]
        .as_str()
        .ok_or("FACTOR_CHAT_MODEL_RESPONSE_INVALID")?;
    onlyalpha_metadata_json::canonical_json(content, 8 * 1024 * 1024)
        .map_err(|_| "FACTOR_CHAT_MODEL_RESPONSE_INVALID")?;
    let result: Value =
        serde_json::from_str(content).map_err(|_| "FACTOR_CHAT_MODEL_RESPONSE_INVALID")?;
    if result.as_object().is_none_or(|o| o.len() != 2)
        || result["message"]
            .as_str()
            .is_none_or(|s| s.is_empty() || s.len() > 8000)
        || result.get("candidate").is_none()
    {
        return Err("FACTOR_CHAT_MODEL_RESPONSE_INVALID");
    }
    Ok(
        json!({"response":result,"provider_response_id":r["id"],"returned_model":r["model"],"request_fingerprint":hash(body)?,"response_fingerprint":hash(&r)?}),
    )
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn configured_endpoints_do_not_allow_credentials_redirect_targets_or_cleartext_remote() {
        for s in [
            "http://example.com/v1",
            "https://user:pass@example.com/v1",
            "https://example.com/v1?key=foo",
            "file:///tmp/model",
        ] {
            assert!(endpoint(s).is_err());
        }
        assert!(endpoint("https://example.com/v1").is_ok());
        assert!(endpoint("http://127.0.0.1:9123/v1").is_ok());
        assert!(registration(8 * 1024 * 1024).is_ok());
    }
}
