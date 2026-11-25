use crate::{
    application::integration_configuration::IntegrationId,
    bootstrap::deployment::{SemanticStoreId, read_binding},
    persistence::{
        integration_postgres::VIRTUAL_BROKER_TYPE_ID,
        sim_account::{
            Error, InstrumentPolicy, SIM_CLUSTER_ID, SIM_ENGINE_ID, TradingPolicy,
            encode_canonical_document_for_test, publish_sim_account_revision as publish,
            read_sim_account_revision as read, verify_document_for_test,
        },
    },
};
use onlyalpha_domain::{
    base::OnlyDomainModel,
    enums::OnlyCurrencyType,
    identifiers::{OnlyAccountId, OnlyInstrumentId},
    value::{OnlyCurrency, OnlyMoney},
};
use onlyalpha_runtime::durability::RecoveryFacts;
use std::str::FromStr;
use serde_json::{Value, json};

fn cash(amount: &str) -> OnlyMoney {
    let currency = OnlyCurrency::new("USD", 2, OnlyCurrencyType::Fiat).unwrap();
    OnlyMoney::new(amount.parse().unwrap(), currency).unwrap()
}

fn instrument(id: &str, price_precision: u8, quantity_precision: u8) -> InstrumentPolicy {
    InstrumentPolicy::new(id.parse::<OnlyInstrumentId>().unwrap(), price_precision, quantity_precision, "1").unwrap()
}

fn rule(id: &str, scope: &str, order: u64, mode: &str, kind: &str, limit: &str) -> Value {
    json!({
        "schema_version": 1,
        "id": id,
        "scope": scope,
        "order": order,
        "mode": mode,
        "kind": kind,
        "limit": limit,
    })
}

fn standard_policy() -> TradingPolicy {
    TradingPolicy::new(
        vec![
            instrument("ETHUSDT.BINANCE", 2, 4),
            instrument("BTCUSDT.BINANCE", 2, 5),
        ],
        vec![
            rule("observe-orders", "CLUSTER", 20, "OBSERVING", "MAX_ACTIVE_ORDERS", "8"),
            rule("limit-notional", "ACCOUNT", 10, "ENFORCING", "MAX_ORDER_NOTIONAL", "500.00"),
        ],
    )
    .unwrap()
}

const FIXTURE: &str = include_str!("../../../../../test-data/execution/domain-inputs.json");
const SETTLEMENT_FIXTURE: &str = include_str!("../../../../../test-data/settlement/common-v1.json");
#[path = "../../../../../crates/execution/tests/support/mod.rs"]
mod economics;

#[test]
fn same_order_is_subject_to_the_frozen_instruments_and_account_rule() {
    use onlyalpha_domain::{
        enums::OnlyCurrencyType,
        fee::*,
        identifiers::{OnlyClusterId, OnlyInstrumentId, OnlyOrderId, OnlyRuntimeId},
        numeric::{only_multiply, only_quantize},
        time::OnlyTimestamp,
        value::{OnlyCurrency, OnlyPrice, OnlyQuantity},
    };
    let deployment = SemanticStoreId::new("00a90000-0000-4000-8000-000000000020").unwrap();
    let account = OnlyAccountId::new("account").unwrap();
    let broker = IntegrationId::new("00a90000-0000-4000-8000-000000000021").unwrap();
    let cash = OnlyMoney::from_record(&json!({"schema_version":1,"amount":"1000.00","currency":economics::config()["currency"]})).unwrap();
    let run = "00900000-0000-4000-8000-000000000099";
    let genesis = |limit: &str, symbol: &str| {
        let policy = TradingPolicy::new(vec![instrument("600000.XSHG", 2, 0), instrument("600001.XSHG", 2, 0)],
            vec![rule("limit-notional", "ACCOUNT", 10, "ENFORCING", "MAX_ORDER_NOTIONAL", limit)]).unwrap();
        let (fp, raw) = encode_canonical_document_for_test(&deployment, &account, &cash, &broker, &policy).unwrap();
        let revision = verify_document_for_test(&deployment, &account, broker.clone(), &fp, &raw).unwrap();
        let binding = revision.trading_binding(run, &"a".repeat(64), &"b".repeat(64), &"c".repeat(64), &[symbol.into()]).unwrap();
        RecoveryFacts::from_records(&binding, binding.fingerprint(), 0, vec![]).unwrap()
    };
    let permitted = genesis("40", "600000.XSHG");
    let cfg = permitted.binding().configuration().record();
    let mut input = economics::open(1, "BUY");
    for field in ["engine", "runtime", "gateway", "account", "generation", "runtime_kind"] {
        input[field] = cfg[field].clone();
    }
    input["cluster"] = json!(SIM_CLUSTER_ID);
    input["revision"] = cfg["profiles"][SIM_CLUSTER_ID]["revision"].clone();
    // 使用领域费用 owner 为原 Run、Cluster 和原生订单身份生成测试零费用契约。
    let runtime = OnlyRuntimeId::new(run).unwrap();
    let cluster = OnlyClusterId::new(SIM_CLUSTER_ID).unwrap();
    let instrument_id = OnlyInstrumentId::from_str("600000.XSHG").unwrap();
    let order_id = OnlyOrderId::new(&format!("{run}-ORDER-000001")).unwrap();
    let price = OnlyPrice::new("10.00".parse().unwrap(), 2).unwrap();
    let quantity = OnlyQuantity::new("4".parse().unwrap(), 0).unwrap();
    let currency = OnlyCurrency::new("CNY", 2, OnlyCurrencyType::Fiat).unwrap();
    let digest = "0".repeat(64);
    let scope = OnlyOrderFeeApplicabilityScopeIdentity::create(OnlyOrderFeeApplicabilityScopeIdentityInput {
        market_product_id: "TEST_ZERO_FEE".into(), market: "TEST".into(), venue: "TEST".into(), instrument_class: "CASH".into(),
        broker_id: "TEST_BROKER".into(), account_id: account.clone(), instrument_id: instrument_id.clone(),
        charge_currency: currency.clone(), fingerprint: String::new(),
    }).unwrap();
    let binding = OnlyOrderFeePolicyBinding::create(OnlyOrderFeePolicyBindingInput {
        runtime_id: runtime.clone(), account_id: account.clone(), cluster_id: cluster.clone(), order_id: order_id.clone(),
        instrument_id: instrument_id.clone(), market_product_id: "TEST_ZERO_FEE".into(), market_product_version: "1".into(),
        market_fee_pack: OnlyMarketFeePackIdentity::new(OnlyMarketFeePackIdentityInput {
            pack_id: "TEST_ZERO_MARKET_FEES".into(), pack_version: "1".into(), fingerprint: digest.clone(),
        }).unwrap(), broker_fee_contract: OnlyBrokerFeeContractIdentity::new(OnlyBrokerFeeContractIdentityInput {
            contract_id: "TEST_ZERO_BROKER_FEES".into(), contract_version: "1".into(), broker_id: "TEST_BROKER".into(),
            account_scope: OnlyBrokerFeeAccountScope::new(OnlyBrokerFeeAccountScopeInput {
                scope_type: OnlyBrokerFeeAccountScopeType::ExactAccount, account_id: Some(account.clone()),
            }).unwrap(), fingerprint: digest.clone(),
        }).unwrap(), applicability_scope: scope, order_fixed_schedules: vec![], fill_effective_families: vec![],
        charge_currency: currency.clone(), bound_at: OnlyTimestamp::from_unix_nanos(1.into()), fingerprint: String::new(),
    }).unwrap();
    let zero = OnlyMoney::new("0".parse().unwrap(), currency.clone()).unwrap();
    let assessment = OnlyFeeAssessment::new(OnlyFeeAssessmentInput {
        assessment_id: "test-zero-fee".into(), subject: OnlyFeeSubject::new(OnlyFeeSubjectInput {
            runtime_id: runtime, account_id: account.clone(), cluster_id: cluster, order_id: order_id.clone(), instrument_id: instrument_id.clone(),
        }).unwrap(), trade_id: None, components: vec![], total_charges: zero.clone(), total_rebates: zero.clone(),
        policy_fingerprint: digest.clone(), resolution_fingerprint: digest.clone(), local_finality: OnlyLocalFeeFinality::ModelConfirmed, binding: binding.clone(),
    }).unwrap();
    let estimate = OnlyOrderFeeEstimate::new(OnlyOrderFeeEstimateInput {
        expected: assessment.clone(), maximum: assessment, reservation_charge: zero.clone(), estimated_rebate: zero.clone(), assumptions_fingerprint: digest.clone(),
    }).unwrap();
    let amount = only_multiply(price.value(), quantity.value()).unwrap();
    let principal = OnlyMoney::new(only_quantize(&amount, &"0.01".parse().unwrap()).unwrap(), currency).unwrap();
    let funding = OnlyOrderFundingPlan::new(OnlyOrderFundingPlanInput {
        order_id: order_id.clone(), principal_reservation: principal.clone(), fee_reservation: zero, total_reservation: principal,
        binding_fingerprint: binding.fingerprint().clone(), estimate_fingerprint: digest,
    }).unwrap();
    input["payload"]["order"] = json!(order_id.value());
    input["payload"]["fee_contract"] = json!({"binding":binding.to_record(),"estimate":estimate.to_record(),"funding":funding.to_record()});
    assert_eq!(permitted.prepare(&input).unwrap().prepared().input(), &input);
    assert_eq!(genesis("39.99", "600000.XSHG").prepare(&input).unwrap_err().to_string(), "EXECUTION_RISK_DENIED");
    assert_eq!(genesis("40", "600001.XSHG").prepare(&input).unwrap_err().to_string(), "EXECUTION_INSTRUMENT");
}

#[test]
fn usd_opening_cash_requires_exact_cent_precision() {
    let currency = OnlyCurrency::new("USD", 2, OnlyCurrencyType::Fiat).unwrap();
    for invalid in ["1.239", "0.001", "1e-999999999999999999"] {
        assert!(OnlyMoney::new(invalid.parse().unwrap(), currency.clone()).is_err());
    }
}

#[test]
fn trading_policy_rejects_missing_empty_or_invalid_operator_configuration() {
    let deployment = SemanticStoreId::new("00a90000-0000-4000-8000-000000000010").unwrap();
    let account = OnlyAccountId::new("sim-policy-unit-test").unwrap();
    let broker = IntegrationId::new("00a90000-0000-4000-8000-000000000011").unwrap();
    let btc: OnlyInstrumentId = "BTCUSDT.BINANCE".parse().unwrap();

    // 显式 multiplier 与精度校验（禁止错误 multiplier 或超界精度）
    for bad_multiplier in ["", "0", "-1", "2", "1.0", "1e0", "invalid"] {
        assert_eq!(InstrumentPolicy::new(btc.clone(), 2, 5, bad_multiplier), Err(Error::Invalid));
    }
    assert_eq!(InstrumentPolicy::new(btc.clone(), 19, 5, "1"), Err(Error::Invalid));
    assert_eq!(InstrumentPolicy::new(btc.clone(), 2, 19, "1"), Err(Error::Invalid));

    let valid_inst = vec![instrument("BTCUSDT.BINANCE", 2, 5)];
    let valid_rule = vec![rule("max-orders", "ACCOUNT", 10, "ENFORCING", "MAX_ACTIVE_ORDERS", "4")];

    // 禁止空标的、重复标的、超过 32 个标的
    assert_eq!(TradingPolicy::new(vec![], valid_rule.clone()), Err(Error::Invalid));
    assert_eq!(
        TradingPolicy::new(
            vec![instrument("BTCUSDT.BINANCE", 2, 5), instrument("BTCUSDT.BINANCE", 2, 5)],
            valid_rule.clone()
        ),
        Err(Error::Invalid)
    );
    let too_many_instruments: Vec<_> = (0..33)
        .map(|i| instrument(&format!("SYM{i}.BINANCE"), 2, 5))
        .collect();
    assert_eq!(TradingPolicy::new(too_many_instruments, valid_rule), Err(Error::Invalid));

    // 禁止空风控（不默认空风控）、仅 OBSERVING 无 ENFORCING 规则、超过 64 条规则
    assert_eq!(TradingPolicy::new(valid_inst.clone(), vec![]), Err(Error::Invalid));
    assert_eq!(
        TradingPolicy::new(
            valid_inst.clone(),
            vec![rule("obs-only", "ACCOUNT", 10, "OBSERVING", "MAX_ACTIVE_ORDERS", "4")]
        ),
        Err(Error::Invalid)
    );
    let too_many_rules: Vec<_> = (0..65)
        .map(|i| rule(&format!("rule-{i}"), "ACCOUNT", i, "ENFORCING", "MAX_ACTIVE_ORDERS", "4"))
        .collect();
    assert_eq!(TradingPolicy::new(valid_inst.clone(), too_many_rules), Err(Error::Invalid));

    // 交由风险 owner 校验的错配置负例：SYSTEM/system.* 越权、重复 ID、未知 kind/mode/scope、精度超界、负数/指数攻击
    let invalid_rule_sets = vec![
        vec![rule("sys-scope", "SYSTEM", 1, "ENFORCING", "MAX_ACTIVE_ORDERS", "4")],
        vec![rule("system.override", "ACCOUNT", 1, "ENFORCING", "MAX_ACTIVE_ORDERS", "4")],
        vec![
            rule("dup-id", "ACCOUNT", 1, "ENFORCING", "MAX_ACTIVE_ORDERS", "4"),
            rule("dup-id", "CLUSTER", 2, "ENFORCING", "MAX_ORDER_NOTIONAL", "100"),
        ],
        vec![rule("bad-kind", "ACCOUNT", 1, "ENFORCING", "UNKNOWN_RULE", "4")],
        vec![rule("bad-scope", "GLOBAL", 1, "ENFORCING", "MAX_ACTIVE_ORDERS", "4")],
        vec![rule("bad-int", "ACCOUNT", 1, "ENFORCING", "MAX_ACTIVE_ORDERS", "1.5")],
        vec![rule("bad-scale", "ACCOUNT", 1, "ENFORCING", "MAX_ORDER_NOTIONAL", "10.001")],
        vec![rule("neg-limit", "ACCOUNT", 1, "ENFORCING", "MAX_ORDER_NOTIONAL", "-1")],
        vec![rule("huge-exp", "ACCOUNT", 1, "ENFORCING", "MAX_ORDER_NOTIONAL", "1e999999999999999999")],
    ];
    for rules in invalid_rule_sets {
        let result = TradingPolicy::new(valid_inst.clone(), rules).and_then(|policy| {
            encode_canonical_document_for_test(&deployment, &account, &cash("1000"), &broker, &policy)
        });
        assert_eq!(result, Err(Error::Invalid));
    }

    // 规则带额外字段或错误 schema_version 被拒绝
    let mut extra_field = rule("extra", "ACCOUNT", 1, "ENFORCING", "MAX_ACTIVE_ORDERS", "4");
    extra_field["unexpected"] = json!(true);
    assert_eq!(TradingPolicy::new(valid_inst.clone(), vec![extra_field]), Err(Error::Invalid));
    let mut wrong_version = rule("ver", "ACCOUNT", 1, "ENFORCING", "MAX_ACTIVE_ORDERS", "4");
    wrong_version["schema_version"] = json!(2);
    assert_eq!(TradingPolicy::new(valid_inst, vec![wrong_version]), Err(Error::Invalid));
}

#[test]
fn trading_binding_verifies_frozen_universe_scopes_profile_and_enforces_risk_owner() {
    let deployment = SemanticStoreId::new("00a90000-0000-4000-8000-000000000020").unwrap();
    let account = OnlyAccountId::new("sim-account-binding-test").unwrap();
    let broker = IntegrationId::new("00a90000-0000-4000-8000-000000000021").unwrap();
    let run_id = "00900000-0000-4000-8000-000000000099";
    let generation = "a".repeat(64);
    let kernel = "b".repeat(64);
    let strategy = "c".repeat(64);

    let policy = standard_policy();
    let (fp_a, raw_a) =
        encode_canonical_document_for_test(&deployment, &account, &cash("1000"), &broker, &policy).unwrap();

    // 不同输入顺序与等价精度（1000.0 / 500）规范化为同一不可变账户修订
    let reordered = TradingPolicy::new(
        vec![
            instrument("BTCUSDT.BINANCE", 2, 5),
            instrument("ETHUSDT.BINANCE", 2, 4),
        ],
        vec![
            rule("limit-notional", "ACCOUNT", 10, "ENFORCING", "MAX_ORDER_NOTIONAL", "500"),
            rule("observe-orders", "CLUSTER", 20, "OBSERVING", "MAX_ACTIVE_ORDERS", "8"),
        ],
    )
    .unwrap();
    let (fp_b, raw_b) =
        encode_canonical_document_for_test(&deployment, &account, &cash("1000.0"), &broker, &reordered).unwrap();
    assert_eq!(fp_a, fp_b);
    assert_eq!(raw_a, raw_b);

    let revision = verify_document_for_test(&deployment, &account, broker.clone(), &fp_a, &raw_a).unwrap();
    assert_eq!(revision.instruments().len(), 2);
    assert_eq!(revision.instruments()[0].id().to_string(), "BTCUSDT.BINANCE");
    assert_eq!(revision.instruments()[1].id().to_string(), "ETHUSDT.BINANCE");
    // 风险 owner 按 (scope, order, id) 排序并规范化 limit（500.00 -> 500）
    assert_eq!(revision.risk_rules()[0]["id"], "limit-notional");
    assert_eq!(revision.risk_rules()[0]["limit"], "500");
    assert_eq!(revision.risk_rules()[1]["id"], "observe-orders");

    // 账户允许 BTC+ETH，但冻结策略仅声明 BTC：profile 与 instruments 只能包含 BTC
    let binding = revision
        .trading_binding(run_id, &generation, &kernel, &strategy, &["BTCUSDT.BINANCE".into()])
        .unwrap();
    let cfg = binding.configuration().record();
    assert_eq!(binding.kernel_artifact(), kernel);
    assert_eq!(cfg["schema_version"], 1);
    assert_eq!(cfg["engine"], SIM_ENGINE_ID);
    assert_eq!(cfg["runtime"], run_id);
    assert_eq!(cfg["account"], account.value());
    assert_eq!(cfg["gateway"], broker.value());
    assert_eq!(cfg["generation"], generation);
    assert_eq!(cfg["runtime_kind"], "SIM");
    assert_eq!(cfg["initial_cash"], "1000.00");
    assert_eq!(cfg["capitals"], json!({ SIM_CLUSTER_ID: "1000.00" }));
    assert_eq!(cfg["profiles"].as_object().unwrap().len(), 1);
    assert_eq!(cfg["profiles"][SIM_CLUSTER_ID]["revision"], strategy);
    assert_eq!(cfg["profiles"][SIM_CLUSTER_ID]["instruments"], json!(["BTCUSDT.BINANCE"]));
    assert_eq!(
        cfg["instruments"],
        json!([{"schema_version": 1, "id": "BTCUSDT.BINANCE", "price_precision": 2, "quantity_precision": 5, "multiplier": "1"}])
    );
    assert_eq!(cfg["profiles"][SIM_CLUSTER_ID]["rules"], json!(revision.risk_rules()));

    // 多标的策略 universe 顺序无关，确定性生成同一 TradingBinding
    let both_a = revision
        .trading_binding(
            run_id,
            &generation,
            &kernel,
            &strategy,
            &["ETHUSDT.BINANCE".into(), "BTCUSDT.BINANCE".into()],
        )
        .unwrap();
    let both_b = revision
        .trading_binding(
            run_id,
            &generation,
            &kernel,
            &strategy,
            &["BTCUSDT.BINANCE".into(), "ETHUSDT.BINANCE".into()],
        )
        .unwrap();
    assert_eq!(both_a.fingerprint(), both_b.fingerprint());
    assert_eq!(
        both_a.configuration().record()["profiles"][SIM_CLUSTER_ID]["instruments"],
        json!(["BTCUSDT.BINANCE", "ETHUSDT.BINANCE"])
    );

    // 18 位小数极小资金（1e-18）以定点明文形式进入 RunConfiguration 并构造有效 TradingBinding
    let precise = OnlyCurrency::new("TOKEN", 18, OnlyCurrencyType::Crypto).unwrap();
    let tiny = OnlyMoney::new("1e-18".parse().unwrap(), precise).unwrap();
    let tiny_policy = TradingPolicy::new(
        vec![instrument("BTCUSDT.BINANCE", 2, 5)],
        vec![rule("max-orders", "ACCOUNT", 1, "ENFORCING", "MAX_ACTIVE_ORDERS", "2")],
    )
    .unwrap();
    let (tiny_fp, tiny_raw) =
        encode_canonical_document_for_test(&deployment, &account, &tiny, &broker, &tiny_policy).unwrap();
    let tiny_rev = verify_document_for_test(&deployment, &account, broker, &tiny_fp, &tiny_raw).unwrap();
    let tiny_binding = tiny_rev
        .trading_binding(run_id, &generation, &kernel, &strategy, &["BTCUSDT.BINANCE".into()])
        .unwrap();
    assert_eq!(tiny_binding.configuration().record()["initial_cash"], "0.000000000000000001");
}

#[test]
fn trading_binding_and_document_verification_reject_unauthorized_or_forged_inputs() {
    let deployment = SemanticStoreId::new("00a90000-0000-4000-8000-000000000030").unwrap();
    let other_deployment = SemanticStoreId::new("00a90000-0000-4000-8000-000000000039").unwrap();
    let account = OnlyAccountId::new("sim-account-negative-test").unwrap();
    let other_account = OnlyAccountId::new("sim-account-other").unwrap();
    let broker = IntegrationId::new("00a90000-0000-4000-8000-000000000031").unwrap();
    let other_broker = IntegrationId::new("00a90000-0000-4000-8000-000000000032").unwrap();
    let run_id = "00900000-0000-4000-8000-000000000088";
    let generation = "a".repeat(64);
    let kernel = "b".repeat(64);
    let strategy = "c".repeat(64);

    let (fp, raw) = encode_canonical_document_for_test(
        &deployment,
        &account,
        &cash("1000"),
        &broker,
        &standard_policy(),
    )
    .unwrap();
    let revision = verify_document_for_test(&deployment, &account, broker.clone(), &fp, &raw).unwrap();

    // 错标的 / 未获准标的负例
    assert_eq!(
        revision
            .trading_binding(run_id, &generation, &kernel, &strategy, &["SOLUSDT.BINANCE".into()])
            .unwrap_err(),
        Error::Mismatch
    );
    assert_eq!(
        revision
            .trading_binding(
                run_id,
                &generation,
                &kernel,
                &strategy,
                &["BTCUSDT.BINANCE".into(), "SOLUSDT.BINANCE".into()],
            )
            .unwrap_err(),
        Error::Mismatch
    );

    // 非法 universe 与参数负例
    assert_eq!(
        revision
            .trading_binding(run_id, &generation, &kernel, &strategy, &[])
            .unwrap_err(),
        Error::Invalid
    );
    assert_eq!(
        revision
            .trading_binding(
                run_id,
                &generation,
                &kernel,
                &strategy,
                &["BTCUSDT.BINANCE".into(), "BTCUSDT.BINANCE".into()],
            )
            .unwrap_err(),
        Error::Invalid
    );
    for bad_symbol in ["BTCUSDT", " BTCUSDT.BINANCE", "BTCUSDT.BINANCE\0", ""] {
        assert_eq!(
            revision
                .trading_binding(run_id, &generation, &kernel, &strategy, &[bad_symbol.into()])
                .unwrap_err(),
            Error::Invalid
        );
    }
    assert_eq!(
        revision
            .trading_binding("not-a-uuid", &generation, &kernel, &strategy, &["BTCUSDT.BINANCE".into()])
            .unwrap_err(),
        Error::Invalid
    );
    assert_eq!(
        revision
            .trading_binding(run_id, "bad-gen", &kernel, &strategy, &["BTCUSDT.BINANCE".into()])
            .unwrap_err(),
        Error::Invalid
    );
    assert_eq!(
        revision
            .trading_binding(run_id, &generation, "bad-kernel", &strategy, &["BTCUSDT.BINANCE".into()])
            .unwrap_err(),
        Error::Invalid
    );
    assert_eq!(
        revision
            .trading_binding(run_id, &generation, &kernel, "bad-strategy", &["BTCUSDT.BINANCE".into()])
            .unwrap_err(),
        Error::Invalid
    );

    // 归属错配与篡改文档负例
    assert_eq!(verify_document_for_test(&other_deployment, &account, broker.clone(), &fp, &raw), Err(Error::Mismatch));
    assert_eq!(verify_document_for_test(&deployment, &other_account, broker.clone(), &fp, &raw), Err(Error::Mismatch));
    assert_eq!(verify_document_for_test(&deployment, &account, other_broker, &fp, &raw), Err(Error::Mismatch));
    assert_eq!(verify_document_for_test(&deployment, &account, broker.clone(), "bad-fp", &raw), Err(Error::Invalid));

    let mutate_and_verify = |mutate: &dyn Fn(&mut Value)| {
        let mut forged: Value = serde_json::from_str(&raw).unwrap();
        mutate(&mut forged);
        let forged_raw = forged.to_string();
        let forged_fp = onlyalpha_execution::digest(forged_raw.as_bytes());
        assert_eq!(
            verify_document_for_test(&deployment, &account, broker.clone(), &forged_fp, &forged_raw),
            Err(Error::Mismatch)
        );
    };
    mutate_and_verify(&|v| { v["risk_rules"] = json!([]); });
    mutate_and_verify(&|v| { v["risk_rules"][0]["mode"] = json!("OBSERVING"); });
    mutate_and_verify(&|v| { v["risk_rules"][0]["scope"] = json!("SYSTEM"); });
    mutate_and_verify(&|v| { v["risk_rules"][0]["id"] = json!("system.bypass"); });
    mutate_and_verify(&|v| { v["risk_rules"][0]["limit"] = json!("500.00"); });
    mutate_and_verify(&|v| { v["risk_rules"].as_array_mut().unwrap().reverse(); });
    mutate_and_verify(&|v| { v["instruments"][0]["multiplier"] = json!("2"); });
    mutate_and_verify(&|v| { v["instruments"][0]["price_precision"] = json!(19); });
    mutate_and_verify(&|v| { v["instruments"].as_array_mut().unwrap().reverse(); });
    mutate_and_verify(&|v| { v["unexpected"] = json!("field"); });
}

#[tokio::test]
async fn sim_account_revision_publishes_and_recovers_the_original_binding() {
    let mut connection = crate::tests::database().await;
    let mut other = crate::tests::database().await;
    let mut tx = connection.client.transaction().await.unwrap();
    let deployment = read_binding(&tx).await.unwrap();
    let account = OnlyAccountId::new("sim-account-revision-test").unwrap();
    let broker = IntegrationId::new("00a90000-0000-4000-8000-000000000001").unwrap();
    let source = IntegrationId::new("00a90000-0000-4000-8000-000000000002").unwrap();
    let policy = standard_policy();
    let tiny_policy = TradingPolicy::new(
        vec![instrument("BTCUSDT.BINANCE", 2, 5)],
        vec![rule("max-orders", "ACCOUNT", 10, "ENFORCING", "MAX_ACTIVE_ORDERS", "4")],
    )
    .unwrap();
    tx.batch_execute("SET LOCAL ROLE onlyalpha_node_control").await.unwrap();
    for (id, type_id) in [(&broker, VIRTUAL_BROKER_TYPE_ID), (&source, "test.data_source")] {
        tx.execute("INSERT INTO public.integration (integration_id,type_id,display_name,lifecycle_state,created_at,updated_at)
            VALUES ($1::text::uuid,$2,'test','ACTIVE',now(),now())", &[&id.value(), &type_id]).await.unwrap();
    }
    // 权限负例：未持节点写锁拒绝发布
    assert_eq!(publish(&tx, &deployment, &account, &cash("1"), &broker, &policy).await, Err(Error::Unavailable));
    tx.query_one("SELECT pg_advisory_xact_lock(1329199301,5)", &[]).await.unwrap();
    // 错券商类型 / 错资金负例
    assert_eq!(publish(&tx, &deployment, &account, &cash("1"), &source, &policy).await, Err(Error::Mismatch));
    assert_eq!(publish(&tx, &deployment, &account, &cash("-1"), &broker, &policy).await, Err(Error::Invalid));
    for too_large in ["1e126", "1e1000000000", "1e999999999999999999"] {
        assert_eq!(publish(&tx, &deployment, &account, &cash(too_large), &broker, &policy).await, Err(Error::Invalid));
    }
    let largest = cash(&format!("{}.99", "9".repeat(126)));
    let upper_bound = publish(&tx, &deployment, &account, &largest, &broker, &policy).await.unwrap();
    assert_eq!(upper_bound.opening_cash(), &largest);
    let precise = OnlyCurrency::new("TOKEN", 18, OnlyCurrencyType::Crypto).unwrap();
    let tiny = OnlyMoney::new("1e-18".parse().unwrap(), precise).unwrap();
    let tiny_revision = publish(&tx, &deployment, &account, &tiny, &broker, &tiny_policy).await.unwrap();
    assert_eq!(tiny_revision.opening_cash(), &tiny);
    let original = publish(&tx, &deployment, &account, &cash("1e2"), &broker, &policy).await.unwrap();
    assert_eq!(original.opening_cash().amount().to_string(), "100.00");
    assert_eq!(original.deployment_id(), &deployment);
    assert_eq!(original.account_id(), &account);
    assert_eq!(original.broker_integration_id(), &broker);
    assert_eq!(original.instruments().len(), 2);
    assert_eq!(original.risk_rules().len(), 2);
    assert_eq!(publish(&tx, &deployment, &account, &cash("100.0"), &broker, &policy).await.unwrap(), original);
    let original_raw: String = tx.query_one("SELECT document FROM public.sim_account_revision WHERE revision_fingerprint=$1",
        &[&original.revision_fingerprint()]).await.unwrap().get(0);

    // 数据库 CHECK 约束直接拒绝空标的、空风控及无 ENFORCING 规则
    for bad_policy in [
        ("instruments", json!([])),
        ("risk_rules", json!([])),
        ("risk_rules", json!([rule("obs-only", "ACCOUNT", 1, "OBSERVING", "MAX_ACTIVE_ORDERS", "4")])),
    ] {
        let sp = tx.savepoint("bad_policy_check").await.unwrap();
        let mut forged: Value = serde_json::from_str(&original_raw).unwrap();
        forged[bad_policy.0] = bad_policy.1;
        let raw = forged.to_string();
        let fingerprint = onlyalpha_execution::digest(raw.as_bytes());
        let err = sp.execute("INSERT INTO public.sim_account_revision (revision_fingerprint,document) VALUES ($1,$2)",
            &[&fingerprint, &raw]).await.unwrap_err();
        assert_eq!(err.as_db_error().unwrap().constraint(), Some("sim_account_revision_trading_policy_check"));
        sp.rollback().await.unwrap();
    }

    // 绕过 publish 写入的篡改行（能过粗粒度 JSONB 约束但违反领域/风控 owner 规则）在 read 时被拒绝
    for (field, value) in [
        ("broker_integration_id", json!(source.value())),
        ("unexpected", json!("field")),
        ("amount", json!("1.239")),
        ("amount", json!("1e9223372036854775807")),
        ("amount", json!("1e-9223372036854775808")),
        ("amount", json!("-1.00")),
        ("amount", json!("-0.00")),
        ("multiplier", json!("2")),
        ("rule_scope", json!("SYSTEM")),
        ("rule_id", json!("system.override")),
        ("rule_limit", json!("500.00")),
    ] {
        let mut forged: Value = serde_json::from_str(&original_raw).unwrap();
        match field {
            "amount" => forged["opening_cash"]["amount"] = value,
            "multiplier" => forged["instruments"][0]["multiplier"] = value,
            "rule_scope" => forged["risk_rules"][0]["scope"] = value,
            "rule_id" => forged["risk_rules"][0]["id"] = value,
            "rule_limit" => forged["risk_rules"][0]["limit"] = value,
            _ => forged[field] = value,
        }
        let raw = forged.to_string();
        let fingerprint = onlyalpha_execution::digest(raw.as_bytes());
        tx.execute("INSERT INTO public.sim_account_revision (revision_fingerprint,document) VALUES ($1,$2)",
            &[&fingerprint, &raw]).await.unwrap();
        assert_eq!(read(&tx, &deployment, &account, &fingerprint).await, Err(Error::Mismatch));
    }
    let changed = publish(&tx, &deployment, &account, &cash("101"), &broker, &policy).await.unwrap();
    assert_ne!(original.revision_fingerprint(), changed.revision_fingerprint());
    let savepoint = tx.savepoint("discard_revision").await.unwrap();
    let zero = publish(&savepoint, &deployment, &account, &cash("-0"), &broker, &policy).await.unwrap();
    assert_eq!(publish(&savepoint, &deployment, &account, &cash("0.00"), &broker, &policy).await.unwrap(), zero);
    savepoint.rollback().await.unwrap();
    assert_eq!(read(&tx, &deployment, &account, zero.revision_fingerprint()).await, Err(Error::Missing));
    let observe = other.client.transaction().await.unwrap();
    assert_eq!(read(&observe, &deployment, &account, original.revision_fingerprint()).await, Err(Error::Missing));
    observe.commit().await.unwrap();
    tx.commit().await.unwrap();

    let mut tx = other.client.transaction().await.unwrap();
    tx.batch_execute("SET LOCAL ROLE onlyalpha_node_control").await.unwrap();
    let recovered = read(&tx, &deployment, &account, original.revision_fingerprint()).await.unwrap();
    assert_eq!(recovered, original);
    let binding = recovered
        .trading_binding(
            "00900000-0000-4000-8000-000000000077",
            &"a".repeat(64),
            &"b".repeat(64),
            &"c".repeat(64),
            &["BTCUSDT.BINANCE".into()],
        )
        .unwrap();
    assert_eq!(binding.configuration().record()["engine"], SIM_ENGINE_ID);
    assert_eq!(
        binding.configuration().record()["profiles"][SIM_CLUSTER_ID]["instruments"],
        json!(["BTCUSDT.BINANCE"])
    );
    assert_eq!(
        recovered
            .trading_binding(
                "00900000-0000-4000-8000-000000000077",
                &"a".repeat(64),
                &"b".repeat(64),
                &"c".repeat(64),
                &["SOLUSDT.BINANCE".into()],
            )
            .unwrap_err(),
        Error::Mismatch
    );
    assert_eq!(read(&tx, &deployment, &account, changed.revision_fingerprint()).await.unwrap(), changed);
    let wrong_account = OnlyAccountId::new("other").unwrap();
    assert_eq!(read(&tx, &deployment, &wrong_account, original.revision_fingerprint()).await, Err(Error::Mismatch));
    let wrong_deployment = SemanticStoreId::new("00a90000-0000-4000-8000-000000000003").unwrap();
    assert_eq!(read(&tx, &wrong_deployment, &account, original.revision_fingerprint()).await, Err(Error::Mismatch));
    assert_eq!(read(&tx, &deployment, &account, "invalid").await, Err(Error::Invalid));
    // 权限负例：onlyalpha_node_control 禁止 UPDATE/DELETE，未持锁禁止 INSERT
    let sp = tx.savepoint("deny_update").await.unwrap();
    assert!(sp.execute("UPDATE public.sim_account_revision SET document=document", &[]).await.is_err());
    sp.rollback().await.unwrap();
    let sp = tx.savepoint("deny_delete").await.unwrap();
    assert!(sp.execute("DELETE FROM public.sim_account_revision", &[]).await.is_err());
    sp.rollback().await.unwrap();
    let error = tx.execute("INSERT INTO public.sim_account_revision (revision_fingerprint,document)
        SELECT revision_fingerprint,document FROM public.sim_account_revision WHERE revision_fingerprint=$1 ON CONFLICT DO NOTHING",
        &[&original.revision_fingerprint()]).await.unwrap_err();
    assert_eq!(error.as_db_error().unwrap().message(), "TRADING_AUTHORITY_REQUIRED");
    assert_eq!(read(&tx, &deployment, &account, original.revision_fingerprint()).await, Err(Error::Unavailable));
    tx.rollback().await.unwrap();
}
