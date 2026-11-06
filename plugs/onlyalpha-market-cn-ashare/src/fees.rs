use crate::*;
use onlyalpha_fee::{Binding, Catalog};

pub const PACK_ID: &str = "CN_A_SHARE_PRODUCTION_MARKET_FEES";
pub const PACK_VERSION: &str = "2025.06.30";

#[derive(Clone, Debug)]
pub struct FeePack {
    record: Value,
}
impl Default for FeePack {
    fn default() -> Self {
        Self::new()
    }
}
impl FeePack {
    pub fn new() -> Self {
        let sources: Value =
            serde_json::from_str(include_str!("fee_sources.json")).expect("frozen source manifest");
        let mut schedules = Vec::new();
        for (venue, name, source) in [
            ("XSHG", "SSE", "CSDC:SSE-FEE-TABLE:2025-06-30"),
            ("XSHE", "SZSE", "CSDC:SZSE-FEE-TABLE:2025-06-30"),
        ] {
            for (kind, version, start, end, source, rate, side, authority) in [
                (
                    "STAMP_DUTY",
                    "1",
                    20220701,
                    Some(20230828),
                    "PRC-NPC:STAMP-TAX-LAW:2021",
                    "0.001",
                    Some("SELL"),
                    "REGULATOR",
                ),
                (
                    "STAMP_DUTY",
                    "2",
                    20230828,
                    None,
                    "MOF-STA:ANNOUNCEMENT-2023-39:1",
                    "0.0005",
                    Some("SELL"),
                    "REGULATOR",
                ),
                (
                    "TRANSFER_FEE",
                    "1",
                    20250630,
                    None,
                    source,
                    "0.00001",
                    None,
                    "CLEARING",
                ),
            ] {
                let native = json!({"namespace":"MARKET","family":format!("CN_A_SHARE_{name}_{kind}"),"version":version,
                    "from":start,"to":end,"scope":{"market":"CN_A_SHARE","venue":venue,"instrument_class":"CASH","currency":"CNY"},
                    "rules":[{"id":format!("ordinary-cny-a-share-{kind}"),"type":kind,"authority":authority,"direction":"CHARGE",
                        "scope":"FILL","resolution":"FILL_EFFECTIVE","terms":[{"kind":"RATE","basis":"NOTIONAL","amount":rate}],
                        "minimum":null,"maximum":null,"quantum":"0.01","rounding":"HALF_UP","pipeline":"ROUND_THEN_BOUNDS",
                        "side":side,"offset":null,"liquidity":null}]});
                schedules.push(json!({"source_id":source,"schedule":native}));
            }
        }
        Self {
            record: json!({"schema_version":1,"pack_id":PACK_ID,"pack_version":PACK_VERSION,
            "compatible_market_products":[PRODUCT_ID],"coverage_from":"2025-06-30","sources":sources,"schedules":schedules}),
        }
    }
    pub fn record(&self) -> Value {
        self.record.clone()
    }
    pub fn fingerprint(&self) -> String {
        digest(&self.record)
    }
    /// Compose with a real explicit Broker contract. This plugin never supplies
    /// or assumes zero Broker commission. The caller retains its source record.
    pub fn compose(&self, venue: &str, broker: &Value) -> Result<FeeComposition, Error> {
        if !matches!(venue, "XSHG" | "XSHE") {
            return Err(bad("FEE_VENUE_UNSUPPORTED"));
        }
        fields(
            broker,
            &["contract", "schedules", "source"],
            &[],
            "BROKER_FEE_CONTRACT_REQUIRED",
        )?;
        let contract = &broker["contract"];
        let source = format!(
            "BROKER_CONTRACT:{}:{}",
            text(&contract["id"], "BROKER_FEE_CONTRACT_REQUIRED")?,
            text(&contract["version"], "BROKER_FEE_CONTRACT_REQUIRED")?
        );
        if broker["source"] != source {
            return Err(bad("BROKER_FEE_SOURCE_INVALID"));
        }
        let mut schedules = Vec::new();
        let mut families = std::collections::BTreeSet::new();
        for entry in self.record["schedules"]
            .as_array()
            .expect("fixed schedules")
        {
            let schedule = &entry["schedule"];
            if schedule["scope"]["venue"] == venue {
                families.insert(schedule["family"].as_str().expect("family").to_owned());
                schedules.push(schedule.clone());
            }
        }
        let broker_schedules = broker["schedules"]
            .as_array()
            .filter(|s| !s.is_empty())
            .ok_or_else(|| bad("BROKER_FEE_CONTRACT_REQUIRED"))?;
        for schedule in broker_schedules {
            if schedule["namespace"] != "BROKER" || schedule["scope"]["currency"] != "CNY" {
                return Err(bad("BROKER_FEE_SCOPE_INVALID"));
            }
            schedules.push(schedule.clone());
        }
        let catalog = boundary(Catalog::new(
            json!({"schema_version":1,"market_pack":{"id":PACK_ID,"version":PACK_VERSION,"families":families},
            "broker_contract":contract,"schedules":schedules}),
        ))?;
        // Catalog owns native normalization/selection/formulas. The enclosing
        // immutable composition additionally binds the exact source manifests.
        let record = json!({"schema_version":1,"market_fee_pack_fingerprint":self.fingerprint(),
            "market_fee_pack":self.record,"broker_source":broker["source"],"catalog":catalog.record()});
        Ok(FeeComposition { catalog, record })
    }
}
#[derive(Clone, Debug)]
pub struct FeeComposition {
    catalog: Catalog,
    record: Value,
}
impl FeeComposition {
    pub fn record(&self) -> Value {
        self.record.clone()
    }
    pub fn fingerprint(&self) -> String {
        digest(&self.record)
    }
    pub fn catalog(&self) -> &Catalog {
        &self.catalog
    }
    pub fn bind(&self, subject: Value, trading_day: OnlyTradingDay) -> Result<Binding, Error> {
        if day_text(trading_day).as_str() < "2025-06-30" {
            return Err(bad("FEE_SCHEDULE_NOT_FOUND"));
        }
        boundary(self.catalog.bind(subject, day_number(trading_day)?))
    }
}
