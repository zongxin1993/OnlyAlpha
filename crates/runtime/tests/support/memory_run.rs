use super::signal_support;
use onlyalpha_broker::Scope;
use onlyalpha_broker_virtual::VirtualBroker;
use onlyalpha_calculation_bridge::ProgramNodes;
use onlyalpha_domain::{
    base::OnlyDomainModel,
    fee::{
        OnlyOrderFeeApplicabilityScopeIdentity, OnlyOrderFeeApplicabilityScopeIdentityInput,
        OnlyOrderFeePolicyBinding, OnlyOrderFeePolicyBindingInput,
    },
    numeric::{only_multiply, only_quantize},
    time::OnlyTimestamp,
    value::{OnlyCurrency, OnlyMoney, OnlyPrice, OnlyQuantity},
};
use onlyalpha_execution::Error;
use onlyalpha_runtime::{
    OnlyAlphaRuntime, ResearchPanel,
    trading::backtest::{
        CompletedBacktest, ExecutionBinding, FrozenReplay, FrozenVenue, Inputs, MarketInput,
        MemoryRunSpec, NextOpenPolicy, Source,
    },
};
use onlyalpha_runtime::{RunBinding, RunConfiguration};
use onlyalpha_strategy::Executor;
use serde_json::{Value, json};
pub struct Policy {
    pub cfg: Value,
    pub denied: bool,
}
impl Policy {
    fn settlement_policy() -> Value {
        let settlement: Value = serde_json::from_str(include_str!(
            "../../../../test-data/settlement/common-v1.json"
        ))
        .unwrap();
        settlement["policy"].clone()
    }

    fn money(&self, price: &OnlyPrice, quantity: &OnlyQuantity) -> Value {
        let exact = only_multiply(price.value(), quantity.value()).unwrap();
        OnlyMoney::new(
            only_quantize(&exact, &"0.01".parse().unwrap()).unwrap(),
            OnlyCurrency::from_record(&self.cfg["currency"]).unwrap(),
        )
        .unwrap()
        .to_record()
    }
}
impl NextOpenPolicy for Policy {
    fn analytical_entry_quote(
        &self,
        price: &OnlyPrice,
        quantity: &OnlyQuantity,
        context: &Value,
    ) -> Result<Value, Error> {
        let currency = OnlyCurrency::from_record(&self.cfg["currency"]).unwrap();
        let charges = OnlyMoney::new("1.00".parse().unwrap(), currency.clone())
            .unwrap()
            .to_record();
        let rebates = OnlyMoney::new("0.00".parse().unwrap(), currency)
            .unwrap()
            .to_record();
        Ok(
            json!({"schema_version":1,"kind":"ANALYTICAL_ESTIMATE","reference_policy":"MODEL_NEXT_OPEN","venue_acceptance_proven":false,"policy_fingerprint":onlyalpha_execution::digest(self.binding().to_string().as_bytes()),"execution_price":price.to_record(),"quantity":quantity.to_record(),"context":context,"gross_notional":self.money(price,quantity),"charges":charges,"rebates":rebates}),
        )
    }
    fn binding(&self) -> Value {
        json!({"schema_version":1,"kind":"CONTROLLED_WHOLE_FILL_FIXED_FEE","configuration":onlyalpha_execution::digest(self.cfg.to_string().as_bytes()),"reference_policy":"MODEL_NEXT_OPEN","model_denied":self.denied,"settlement_policy":Self::settlement_policy()})
    }
    fn admission(&self, order: &Value, price: &OnlyPrice, context: &Value) -> Result<Value, Error> {
        if self.denied {
            return Ok(
                json!({"schema_version":1,"accepted":false,"reason":"CONTROLLED_MODEL_REJECTION","market_provenance":{"kind":"MODEL_RULE_DECISION","verdict":"MODEL_REJECT","reference_policy":"MODEL_NEXT_OPEN","venue_acceptance_proven":false}}),
            );
        }
        let fixture: Value = serde_json::from_str(include_str!(
            "../../../../test-data/execution/domain-inputs.json"
        ))
        .unwrap();
        let mut contract = if order["side"] == "BUY" {
            fixture["fee_contract"].clone()
        } else {
            fixture["second_fee_contract"].clone()
        };
        let original = OnlyOrderFeePolicyBinding::from_record(&contract["binding"]).unwrap();
        let scope = original.applicability_scope();
        let applicability = OnlyOrderFeeApplicabilityScopeIdentity::create(
            OnlyOrderFeeApplicabilityScopeIdentityInput {
                market_product_id: scope.market_product_id().clone(),
                market: scope.market().clone(),
                venue: scope.venue().clone(),
                instrument_class: scope.instrument_class().clone(),
                broker_id: scope.broker_id().clone(),
                account_id: scope.account_id().clone(),
                instrument_id: onlyalpha_domain::identifiers::OnlyInstrumentId::from_record(
                    &order["instrument_id"],
                )
                .unwrap(),
                charge_currency: scope.charge_currency().clone(),
                fingerprint: String::new(),
            },
        )
        .unwrap();
        let binding = OnlyOrderFeePolicyBinding::create(OnlyOrderFeePolicyBindingInput {
            runtime_id: original.runtime_id().clone(),
            account_id: original.account_id().clone(),
            cluster_id: original.cluster_id().clone(),
            order_id: onlyalpha_domain::identifiers::OnlyOrderId::from_record(&order["order_id"])
                .unwrap(),
            instrument_id: onlyalpha_domain::identifiers::OnlyInstrumentId::from_record(
                &order["instrument_id"],
            )
            .unwrap(),
            market_product_id: original.market_product_id().clone(),
            market_product_version: original.market_product_version().clone(),
            market_fee_pack: original.market_fee_pack().clone(),
            broker_fee_contract: original.broker_fee_contract().clone(),
            applicability_scope: applicability,
            order_fixed_schedules: original.order_fixed_schedules().clone(),
            fill_effective_families: original.fill_effective_families().clone(),
            charge_currency: original.charge_currency().clone(),
            bound_at: OnlyTimestamp::from_record(
                &json!({"schema_version":1,"unix_nanos":context["time"]}),
            )
            .unwrap(),
            fingerprint: String::new(),
        })
        .unwrap();
        contract["binding"] = binding.to_record();
        for kind in ["expected", "maximum"] {
            contract["estimate"][kind]["binding"] = binding.to_record();
            contract["estimate"][kind]["subject"]["order_id"] = order["order_id"].clone();
            contract["estimate"][kind]["subject"]["instrument_id"] = order["instrument_id"].clone();
        }
        contract["funding"]["binding_fingerprint"] = json!(binding.fingerprint());
        contract["funding"]["order_id"] = order["order_id"].clone();
        let notional = self.money(
            price,
            &OnlyQuantity::from_record(&order["quantity"]).unwrap(),
        );
        if order["side"] == "BUY" {
            contract["funding"]["principal_reservation"]["amount"] = notional["amount"].clone();
            contract["funding"]["total_reservation"]["amount"] = notional["amount"].clone();
        }
        Ok(
            json!({"schema_version":1,"accepted":true,"contract":contract,"fee_budget":"1.00","notional":notional,"settlement_policy":Self::settlement_policy(),"market_provenance":{"kind":"MODEL_RULE_DECISION","verdict":"MODEL_ACCEPT","reference_policy":"MODEL_NEXT_OPEN","venue_acceptance_proven":false}}),
        )
    }
    fn fill(
        &self,
        _: &Value,
        price: &OnlyPrice,
        quantity: &OnlyQuantity,
        _: &Value,
    ) -> Result<Value, Error> {
        Ok(
            json!({"schema_version":1,"charge_target":"1.00","rebate_target":"0.00","gross_notional":self.money(price,quantity),"settlement_policy":Self::settlement_policy()}),
        )
    }
}
pub struct Fixture {
    pub spec: MemoryRunSpec,
    pub inputs: Inputs,
    pub panel: ResearchPanel,
    pub venue: FrozenVenue,
    pub executor: Executor<ProgramNodes>,
    pub policy: Policy,
}

impl Fixture {
    pub fn run(self) -> Result<CompletedBacktest, Error> {
        let replay = FrozenReplay::new(
            &self.panel,
            self.panel.snapshot(),
            self.panel.content_digest(),
        )?;
        let runtime = OnlyAlphaRuntime::new()?;
        let mut task = runtime.backtest(
            replay,
            self.spec,
            &self.inputs,
            self.executor,
            Box::new(self.policy),
            self.venue,
        )?;
        task.run(|_, _| Ok(()))
            .map_err(|err| Error(err.to_string()))?;
        task.finish()
    }
}

pub fn run_prices(cash: &str, denied: bool, prices: &[&str]) -> CompletedBacktest {
    build_prices(cash, denied, prices, signal_support::executor()).unwrap()
}

pub fn build_prices(
    cash: &str,
    denied: bool,
    prices: &[&str],
    executor: Executor<ProgramNodes>,
) -> Result<CompletedBacktest, Error> {
    parts(cash, denied, prices, executor).run()
}

pub fn parts(
    cash: &str,
    denied: bool,
    prices: &[&str],
    executor: Executor<ProgramNodes>,
) -> Fixture {
    let instrument = signal_support::bar(1, "1.00").instrument_id().to_string();
    let cfg = json!({"schema_version":2,"account_checkpoint_version":5,"engine":"engine","runtime":"runtime","account":"account","gateway":"gateway","generation":"a".repeat(64),"runtime_kind":"BACKTEST","currency":{"schema_version":1,"code":"CNY","precision":2,"currency_type":"FIAT"},"initial_cash":cash,"capitals":{"cluster":cash},"profiles":{"cluster":{"schema_version":1,"revision":executor.program().revision().fingerprint(),"instruments":[instrument],"rules":[]}},"instruments":[{"schema_version":1,"id":instrument,"price_precision":2,"quantity_precision":0,"multiplier":"1"}]});
    let facts = prices
        .iter()
        .enumerate()
        .map(|(i, p)| {
            MarketInput::new(
                executor.program().source(),
                i as u64 + 1,
                "recorded",
                signal_support::bar(i as u64 + 1, p),
            )
            .unwrap()
        })
        .collect::<Vec<_>>();
    let start = OnlyTimestamp::from_datetime(*facts[1].bar().bar_start()).to_unix_nanos();
    let end = facts.last().unwrap().event_ns();
    let initial = OnlyTimestamp::from_datetime(*facts[0].bar().bar_start())
        .unix_nanos()
        .to_string()
        .parse()
        .unwrap();
    let snapshot = "1".repeat(64);
    let timestamps = facts
        .iter()
        .map(|input| OnlyTimestamp::from_unix_nanos(input.event_ns()))
        .collect();
    let closes = prices
        .iter()
        .map(|price| Some(price.parse().unwrap()))
        .collect();
    let panel = ResearchPanel::new(
        &snapshot,
        vec![(
            facts[0].bar().instrument_id().clone(),
            timestamps,
            [("close".into(), closes)].into(),
        )],
        1,
    )
    .unwrap();
    let source = Source::new(
        executor.program().source(),
        &snapshot,
        &"2".repeat(64),
        "recorded",
        0,
        facts.len() as u64,
    )
    .unwrap();
    let inputs = Inputs::new(vec![source], facts).unwrap();
    let config = RunConfiguration::from_record(cfg.clone()).unwrap();
    let mut calendar: Value = serde_json::from_str::<Value>(include_str!(
        "../../../../test-data/settlement/common-v1.json"
    ))
    .unwrap()["calendar"]
        .clone();
    calendar["calendar_id"]["value"] = json!("memory-golden-calendar-2025");
    calendar["venue_id"]["value"] = json!("X");
    calendar["effective_from"] = json!("2025-01-01");
    calendar["effective_to"] = json!("2026-01-01");
    calendar["holidays"] = json!([]);
    let settings = json!({"schema_version":2,"execution":cfg,"instrument":null,"calendar":calendar,"policy":{"schema_version":1,"kind":"NEXT_OPEN_LONG_ONLY_V1","quantity":{"schema_version":1,"value":"4","precision":0},"buy_multiplier":"1","sell_multiplier":"1","start_ns":start.to_string(),"end_ns":end.to_string()}});
    let scope = Scope::decode(&json!({"engine":cfg["engine"],"runtime":cfg["runtime"],"account":cfg["account"],"gateway":cfg["gateway"],"generation":cfg["generation"],"runtime_kind":cfg["runtime_kind"]})).unwrap();
    let balance = OnlyMoney::new(
        cash.parse().unwrap(),
        OnlyCurrency::from_record(&cfg["currency"]).unwrap(),
    )
    .unwrap();
    let artifact = "f".repeat(64);
    let matching = json!({"matching":{"type":"NEXT_OPEN_LONG_ONLY_V1", "buy_multiplier":"1", "sell_multiplier":"1"}});
    let broker = VirtualBroker::new(scope, &artifact, balance, &matching).unwrap();
    let venue = FrozenVenue {
        artifact,
        settings: matching,
        source: onlyalpha_broker::digest(broker.source_binding()),
    };
    let policy = Policy { cfg, denied };
    let execution = ExecutionBinding::new(
        &config,
        &settings,
        initial,
        "cluster",
        &policy.binding(),
        &venue,
        &panel,
    )
    .unwrap();
    let binding = RunBinding::new(
        &config,
        &"b".repeat(64),
        &inputs.fingerprint(),
        executor.program().fingerprint(),
    )
    .unwrap()
    .with_execution_fingerprint(execution.fingerprint())
    .unwrap();
    Fixture {
        spec: MemoryRunSpec {
            configuration: config,
            binding,
            policy_settings: settings,
            initial_ns: initial,
            cluster: "cluster".into(),
        },
        inputs,
        executor,
        policy,
        venue,
        panel,
    }
}
