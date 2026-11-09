//! 公开及显式提供的账户响应只作为离线输入；保留原字节与捕获身份。
use onlyalpha_domain::time::OnlyUtcDateTime;
use onlyalpha_market_crypto::reference::{
    Reference, Result, fingerprint, iso, raw_sha256, read_json,
};
use serde_json::{Value, json};
use std::collections::{BTreeMap, BTreeSet};
pub(crate) const SPOT_ENDPOINTS: [&str; 2] = ["/api/v3/exchangeInfo", "/api/v3/executionRules"];
const USDM_ENDPOINTS: [&str; 4] = [
    "/fapi/v1/exchangeInfo",
    "/fapi/v1/fundingInfo",
    "/fapi/v1/leverageBracket",
    "ONLYALPHA_BINANCE_USDM_ACCOUNT_PROFILE@1",
];
#[derive(Clone, Debug)]
pub struct ReferenceCapture {
    authorities: Vec<Reference>,
    fingerprint: String,
    pub(crate) manifest: Value,
    pub(crate) evidence: Vec<Vec<u8>>,
}
pub(crate) fn ascii_json(v: &Value) -> Result<String> {
    let canonical = onlyalpha_metadata_json::python_json(&v.to_string(), 64 * 1024 * 1024)
        .map_err(|e| e.code())?;
    // 原 Python 协议使用 json.dumps 的 ensure_ascii=True，包括非 BMP 的代理对。
    let mut s = String::new();
    for c in canonical.chars() {
        if c.is_ascii() && c != '\u{7f}' {
            s.push(c);
        } else {
            use std::fmt::Write;
            for code in c.encode_utf16(&mut [0; 2]) {
                write!(s, "\\u{code:04x}").map_err(|_| "BINANCE_REFERENCE_ENCODE")?;
            }
        }
    }
    Ok(s)
}
pub(crate) fn text(v: &Value) -> Result<&str> {
    v.as_str()
        .filter(|s| !s.is_empty() && s.len() <= 1024)
        .ok_or("BINANCE_REFERENCE_TEXT")
}
pub(crate) fn rows(v: &Value) -> Result<&Vec<Value>> {
    v.as_array()
        .filter(|a| a.len() <= 65536)
        .ok_or("BINANCE_REFERENCE_ROWS")
}
pub(crate) fn keyed<'a>(v: &'a Value, field: &str) -> Result<BTreeMap<&'a str, &'a Value>> {
    let mut result = BTreeMap::new();
    for r in rows(v)? {
        if result.insert(text(&r[field])?, r).is_some() {
            return Err("BINANCE_REFERENCE_DUPLICATE");
        }
    }
    Ok(result)
}
impl ReferenceCapture {
    pub fn fingerprint(&self) -> &str {
        &self.fingerprint
    }
    pub fn authorities(&self) -> &[Reference] {
        &self.authorities
    }
    pub fn raw_evidence(&self) -> &[Vec<u8>] {
        &self.evidence
    }
    pub fn manifest(&self) -> &Value {
        &self.manifest
    }
    pub fn spot(
        exchange: &[u8],
        rules: &[u8],
        captured: OnlyUtcDateTime,
        environment: &str,
        requested: &[&str],
    ) -> Result<Self> {
        if !matches!(environment, "LIVE" | "SPOT_TESTNET") {
            return Err("BINANCE_ENVIRONMENT");
        }
        let e = read_json(exchange)?;
        let authority = crate::spot_reference::normalize(&e, &read_json(rules)?, captured)?;
        let actual: Vec<_> = rows(&authority.payload()["authority"]["references"])?
            .iter()
            .map(|r| text(&r["raw_symbol"]))
            .collect::<Result<_>>()?;
        let wanted: BTreeSet<_> = if requested.is_empty() {
            actual.iter().copied().collect()
        } else {
            requested.iter().copied().collect()
        };
        if wanted.iter().copied().ne(actual.iter().copied()) {
            return Err("BINANCE_REFERENCE_SYMBOL_SCOPE");
        }
        let params = json!([["symbols", ascii_json(&json!(wanted))?]]);
        let server_time = &e["serverTime"];
        if !(server_time.is_null() || server_time.is_i64() || server_time.is_u64()) {
            return Err("BINANCE_REFERENCE_SERVER_TIME");
        }
        let version = "BINANCE_SPOT_REFERENCE_NORMALIZER@2";
        let mut proof = Vec::new();
        let mut descriptions = Vec::new();
        for (i, bytes) in [exchange, rules].into_iter().enumerate() {
            let hash = raw_sha256(bytes);
            proof.push(json!([SPOT_ENDPOINTS[i], params, hash]));
            let filename = ["exchangeInfo.json", "executionRules.json"][i];
            descriptions.push(json!({"endpoint_id":SPOT_ENDPOINTS[i],"filename":filename,"request_parameters":params,"raw_sha256":hash}));
        }
        let id = fingerprint(&json!([
            1,
            "BINANCE",
            "SPOT",
            environment,
            captured.to_string(),
            version,
            wanted,
            proof
        ]))?;
        let manifest = json!({"schema_version":1,"capture_fingerprint":id,"semantic_reference_fingerprint":authority.fingerprint(),"provenance":{"schema_version":1,"provider":"BINANCE","product":"SPOT","environment":environment,"captured_at_utc":iso(captured),"parser_contract_version":version,"requested_symbols":wanted,"server_time":server_time},"evidence":descriptions});
        Ok(Self {
            authorities: vec![authority],
            fingerprint: id,
            manifest,
            evidence: vec![exchange.to_vec(), rules.to_vec()],
        })
    }
    pub fn usdm(
        raw: [&[u8]; 4],
        captured: OnlyUtcDateTime,
        start: OnlyUtcDateTime,
        end: Option<OnlyUtcDateTime>,
    ) -> Result<Self> {
        if end.is_some_and(|e| e <= start) {
            return Err("BINANCE_USDM_REFERENCE_COVERAGE");
        }
        let hashes = raw.map(raw_sha256);
        let [exchange, funding, brackets, account] = raw.map(read_json);
        let (public, account) = crate::usdm_reference::normalize(
            [&exchange?, &funding?, &brackets?, &account?],
            &hashes,
            captured,
            start,
            end,
        )?;
        let evidence: Vec<_> = USDM_ENDPOINTS
            .iter()
            .zip(&hashes)
            .map(|(endpoint, hash)| json!([endpoint, [], hash]))
            .collect();
        let authority = |kind: &str, name: &str, r: &Reference| json!({"authority_kind":kind,"authority_id":name,"authority_version":"2","authority_fingerprint":r.fingerprint()});
        let id = fingerprint(&json!([
            "BINANCE_USDM_REFERENCE_CAPTURE@2",
            captured.to_string(),
            start.to_string(),
            end.map(|t| t.to_string()),
            evidence,
            authority("REFERENCE", "BINANCE_USDM_PUBLIC", &public),
            authority("ACCOUNT_REFERENCE", "BINANCE_USDM", &account)
        ]))?;
        let manifest = json!({"capture_fingerprint":id,"captured_at":iso(captured),"coverage_start":iso(start),"coverage_end":end.map(iso),"evidence":evidence,"public":public.fingerprint(),"account":account.fingerprint()});
        Ok(Self {
            authorities: vec![public, account],
            fingerprint: id,
            manifest,
            evidence: raw.iter().map(|v| v.to_vec()).collect(),
        })
    }
}
