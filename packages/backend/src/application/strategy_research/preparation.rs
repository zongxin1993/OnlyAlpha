//! Exact Human-selected inputs for the bounded Strategy preparation profile.
//! This DTO does not grant a Run, Runtime, Source access or a frozen Strategy.
use crate::application::factor_studies::Source;
use serde::{Deserialize, Serialize};
use serde_json::Value;
use utoipa::ToSchema;

#[derive(Clone, Serialize, Deserialize, ToSchema)]
#[serde(deny_unknown_fields)]
pub struct StrategyPrepareInput {
    pub schema_version: u8,
    pub profile: String,
    pub strategy_id: String,
    pub strategy_revision_fingerprint: String,
    pub definition_fingerprint: String,
    /// Parsed by the existing Context1 value constructor before any effect.
    pub context: Value,
    pub source: Source,
    pub factor_proposal_fingerprint: String,
    pub release_manifest_fingerprint: String,
    pub expected_active_generation: Option<String>,
    pub initialize_fresh_runtime: bool,
    pub research_command_id: String,
}

impl StrategyPrepareInput {
    /// Validate the closed Product profile as a value; owning preparation still
    /// proves publication, Human lineage, Source access and Runtime history.
    pub fn validate(&self, command: &crate::application::command::CommandId) -> Result<super::Context, &'static str> {
        use crate::application::{command::CommandId, private_assets};
        const INVALID: &str = "RESEARCH_PREPARATION_INVALID";
        if self.schema_version != 1 || self.profile != "BTC_SPOT_STRATEGY_RESEARCH_V1"
            || self.research_command_id == command.value()
            || self.source.instrument_id != "BTCUSDT.BINANCE"
            || self.source.expected_type_id != "binance.spot.market_data"
            || [&self.strategy_revision_fingerprint,&self.definition_fingerprint,&self.factor_proposal_fingerprint,&self.release_manifest_fingerprint].iter().any(|s| !crate::is_sha256_hex(s))
            || self.expected_active_generation.as_deref().is_some_and(|s| !crate::is_sha256_hex(s))
            || serde_json::to_string(self).map_err(|_|INVALID)?.len()>65536
        { return Err(INVALID); }
        private_assets::id(&self.strategy_id,"STRATEGY").map_err(|_|INVALID)?;
        CommandId::new(&self.research_command_id).map_err(|_|INVALID)?;
        self.source.selection().map_err(|_|INVALID)?;
        let context=super::Context::new(self.context.clone()).map_err(|_|INVALID)?;
        let record=context.record();
        let targets=record["targets"].as_array().filter(|v|v.len()==1).ok_or(INVALID)?;
        let target=&targets[0];
        if record["start"]!="2025-01-02T12:00:00Z" || record["end"]!="2025-01-03T00:00:00Z"
            || target["type_reference"] != serde_json::json!({"kind":"TARGET","type_id":"onlyalpha.target.forward_return","semantic_version":"1"})
            || target["parameters"] != serde_json::json!({"exit_offset":{"kind":"FIXED","value":{"type":"INTEGER","value":5}}})
            || target["input_bindings"] != serde_json::json!([{"input_name":"entry_price","source":"bar.close"},{"input_name":"exit_price","source":"bar.close"}])
            || target["published_outputs"] != serde_json::json!(["target_value"])
            || !target["primary_output"].is_null()
        { return Err(INVALID); }
        Ok(context)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::application::command::CommandId;
    use serde_json::json;
    fn input() -> Value {
        json!({"schema_version":1,"profile":"BTC_SPOT_STRATEGY_RESEARCH_V1",
          "strategy_id":"private.strategy.use_test_btc","strategy_revision_fingerprint":"a".repeat(64),
          "definition_fingerprint":"b".repeat(64),"factor_proposal_fingerprint":"c".repeat(64),
          "context":{"schema_version":1,"start":"2025-01-02T12:00:00Z","end":"2025-01-03T00:00:00Z",
            "targets":[{"instance_key":"forward_return","type_reference":{"kind":"TARGET","type_id":"onlyalpha.target.forward_return","semantic_version":"1"},"parameters":{"exit_offset":{"kind":"FIXED","value":{"type":"INTEGER","value":5}}},"published_outputs":["target_value"],"primary_output":null,"input_bindings":[{"input_name":"entry_price","source":"bar.close"},{"input_name":"exit_price","source":"bar.close"}]}],
            "statistics":[{"variable":{"kind":"VARIABLE","instance_key":"momentum","output_name":"value"},"target_instance_key":"forward_return","definition":{"schema_version":1,"method":"IC","minimum_observations":2,"pairing_policy":"PAIRWISE_COMPLETE","universe_policy":"OBSERVED_PAIRWISE","rank_tie_method":"AVERAGE","weighting":"EQUAL","numeric":{"representation":"DECIMAL","precision":38,"output_quantum":"0.000000000001","rounding":"ROUND_HALF_EVEN"}}}],"display_metadata":{}},
          "source":{"integration_id":"00000000-0000-4000-8000-000000000101","integration_revision_fingerprint":"d".repeat(64),"expected_type_id":"binance.spot.market_data","source_id":"binance.spot","environment":"LIVE","instrument_id":"BTCUSDT.BINANCE"},
          "release_manifest_fingerprint":"e".repeat(64),"expected_active_generation":null,
          "initialize_fresh_runtime":false,"research_command_id":"00000000-0000-4000-8000-000000000102"})
    }
    #[test]
    fn exact_strategy_preparation_input_uses_public_context_and_a_separate_future_command() {
        let command=CommandId::new("00000000-0000-4000-8000-000000000103").unwrap();
        let original=input();
        let request:StrategyPrepareInput=serde_json::from_value(original.clone()).unwrap();
        let context=request.validate(&command).unwrap();
        assert_eq!(context.record(),&original["context"]);
        assert_eq!(serde_json::to_value(&request).unwrap(),original);
        let mut bad=original.clone();bad["research_command_id"]=json!(command.value());
        assert!(serde_json::from_value::<StrategyPrepareInput>(bad).unwrap().validate(&command).is_err());
        for (field,value) in [("profile",json!("BACKTEST")),("schema_version",json!(2)),("strategy_revision_fingerprint",json!("latest")),("factor_proposal_fingerprint",Value::Null),("expected_active_generation",json!("current"))] {
            let mut bad=original.clone();bad[field]=value;
            assert!(serde_json::from_value::<StrategyPrepareInput>(bad).map(|v|v.validate(&command).is_err()).unwrap_or(true),"{field}");
        }
    }
    #[test]
    fn preparation_rejects_hidden_contract_fields_and_profile_scope_changes() {
        let command=CommandId::new("00000000-0000-4000-8000-000000000103").unwrap();
        for field in ["study_proposal_fingerprint","binding","run_permit","backtest_capability"] {
            let mut bad=input();bad[field]=json!("not an authority");
            assert!(serde_json::from_value::<StrategyPrepareInput>(bad).is_err());
        }
        for path in ["context-extra","protected-period","target-horizon","wrong-instrument"] {
            let mut bad=input();
            match path {
                "context-extra"=>bad["context"]["runtime"]=json!("hidden"),
                "protected-period"=>bad["context"]["end"]=json!("2025-01-06T00:00:00Z"),
                "target-horizon"=>bad["context"]["targets"][0]["parameters"]["exit_offset"]["value"]["value"]=json!(6),
                _=>bad["source"]["instrument_id"]=json!("ETHUSDT.BINANCE"),
            }
            assert!(serde_json::from_value::<StrategyPrepareInput>(bad).unwrap().validate(&command).is_err(),"{path}");
        }
    }
    #[test]
    fn legacy_factor_preparation_wire_remains_byte_exact() {
        let record=json!({"schema_version":1,"study_proposal_fingerprint":"a".repeat(64),"release_manifest_fingerprint":"b".repeat(64),"expected_active_generation":null,"initialize_fresh_runtime":false,"research_command_id":"00000000-0000-4000-8000-000000000102"});
        let request:crate::application::factor_studies::PrepareInput=serde_json::from_value(record.clone()).unwrap();
        assert_eq!(serde_json::to_string(&request).unwrap(),"{\"schema_version\":1,\"study_proposal_fingerprint\":\"".to_owned()+&"a".repeat(64)+"\",\"release_manifest_fingerprint\":\""+&"b".repeat(64)+"\",\"expected_active_generation\":null,\"initialize_fresh_runtime\":false,\"research_command_id\":\"00000000-0000-4000-8000-000000000102\"}");
        assert!(serde_json::from_value::<StrategyPrepareInput>(record).is_err());
        assert!(serde_json::from_value::<crate::application::factor_studies::PrepareInput>(input()).is_err());
    }
}
