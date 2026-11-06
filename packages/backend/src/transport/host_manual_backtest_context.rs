//! Human authoring observations only. GET never prepares, freezes, binds work or starts SDKs.
use crate::{
    application::{
        backtest_preparation::BacktestOrigin,
        manual_backtest_context::{btc_definition, choose_draft},
        private_assets,
    },
    persistence::{
        private_strategy_postgres::Strategies,
        research_preparation::{Operation, Preparations},
        research_runtime::Registry,
    },
    security::{
        human_access,
        ingress::{self, Release},
    },
    transport::{
        host::{Failure, Host, invalid, parameters, required},
        host_factor_studies::failed,
    },
};
use axum::{
    Json,
    body::Body,
    response::{IntoResponse, Response},
};
use http::{Method, Request};
use serde_json::{Value, json};
use std::{collections::BTreeMap, os::fd::AsFd, sync::Arc, time::Instant};
const UNAVAILABLE: &str = "BACKTEST_CONTEXT_UNAVAILABLE";
fn strategy_id(id: &str) -> Result<(), Failure> {
    if id.len() > 4096 {
        return Err(invalid());
    }
    private_assets::id(id, "STRATEGY").map_err(|_| invalid())
}
fn origin(query: &BTreeMap<String, String>) -> Result<BacktestOrigin, Failure> {
    if query.len() == 2
        && query.contains_key("strategy_id")
        && query.contains_key("strategy_revision_fingerprint")
    {
        let id = required(query, "strategy_id")?;
        strategy_id(id)?;
        let pin = required(query, "strategy_revision_fingerprint")?;
        if !crate::is_sha256_hex(pin) {
            return Err(invalid());
        }
        return Ok(BacktestOrigin::ManualStrategy {
            strategy_id: id.into(),
            strategy_revision_fingerprint: pin.into(),
        });
    }
    let names = [
        "strategy_fingerprint",
        "freeze_relation_fingerprint",
        "qualification_decision_fingerprint",
        "promotion_fingerprint",
    ];
    if query.len() != 4
        || query.keys().any(|key| !names.contains(&key.as_str()))
        || names.iter().any(|key| {
            query
                .get(*key)
                .is_none_or(|value| !crate::is_sha256_hex(value))
        })
    {
        return Err(invalid());
    }
    Ok(BacktestOrigin::FrozenStrategy {
        strategy_fingerprint: required(query, names[0])?.into(),
        freeze_relation_fingerprint: required(query, names[1])?.into(),
        qualification_decision_fingerprint: required(query, names[2])?.into(),
        promotion_fingerprint: required(query, names[3])?.into(),
    })
}
fn name(revision: &Value, fallback: &str) -> String {
    revision["description"]
        .as_str()
        .filter(|value| !value.trim().is_empty())
        .unwrap_or(fallback)
        .into()
}
impl Host {
    async fn backtest_context_generation(&self) -> Result<Option<String>, Failure> {
        let root = self.research_preparation_config.runtime_root.clone();
        let value = tokio::task::spawn_blocking(move || Registry::inspect(&root))
            .await
            .map_err(|_| failed(UNAVAILABLE))?
            .map_err(failed)?;
        if value["active_for_new_work"].is_null() {
            return Ok(None);
        }
        let pin = value["active_for_new_work"]
            .as_str()
            .filter(|value| crate::is_sha256_hex(value))
            .ok_or_else(|| failed(UNAVAILABLE))?;
        Ok(Some(pin.into()))
    }
    async fn backtest_context_preparations(
        &self,
        operations: Vec<Operation>,
        selected: &BacktestOrigin,
        human: &human_access::Session,
        deadline: Instant,
    ) -> Result<Vec<Value>, Failure> {
        let expected = serde_json::to_value(selected).map_err(|_| failed(UNAVAILABLE))?;
        let mut values = Vec::with_capacity(operations.len());
        let mut bytes = 0_usize;
        for operation in operations {
            if Instant::now() >= deadline {
                return Err(failed("REQUEST_DEADLINE_EXPIRED"));
            }
            let original = operation.request.backtest().map_err(failed)?;
            if serde_json::to_value(&original.origin).map_err(|_| failed(UNAVAILABLE))? != expected
            {
                return Err(failed("BACKTEST_CONTEXT_STRATEGY_MISMATCH"));
            }
            let value = self
                .preparation_view(&operation, human)
                .await
                .map_err(|error| failed(error.code()))?;
            bytes = bytes
                .checked_add(value.to_string().len())
                .filter(|size| *size <= 8 * 1024 * 1024)
                .ok_or_else(|| failed(UNAVAILABLE))?;
            values.push(value);
        }
        Ok(values)
    }
    pub(crate) async fn manual_backtest_strategy_context(
        self: &Arc<Self>,
        request: Request<Body>,
        human: &human_access::Session,
        deadline: Instant,
    ) -> Result<Response, Failure> {
        self.human_access.check_session(human)?;
        if Instant::now() >= deadline {
            return Err(failed("REQUEST_DEADLINE_EXPIRED"));
        }
        if request.method() != Method::GET {
            return Err(invalid());
        }
        let owner = human.subject_id()?.to_owned();
        let query = parameters(request.uri())?;
        let names = [
            "factor_id",
            "factor_revision_fingerprint",
            "factor_content_fingerprint",
            "strategy_id",
        ];
        if !(3..=4).contains(&query.len()) || query.keys().any(|key| !names.contains(&key.as_str()))
        {
            return Err(invalid());
        }
        let id = required(&query, "factor_id")?;
        if id.len() > 4096 || private_assets::authoring::validate_id(id).is_err() {
            return Err(invalid());
        }
        let revision = required(&query, "factor_revision_fingerprint")?;
        let content = required(&query, "factor_content_fingerprint")?;
        if !crate::is_sha256_hex(revision) || !crate::is_sha256_hex(content) {
            return Err(invalid());
        }
        if let Some(id) = query.get("strategy_id") {
            strategy_id(id)?;
        }
        let locator = json!({"private_asset_kind":"FACTOR","private_asset_id":id,"revision_fingerprint":revision,"content_fingerprint":content});
        let (factor, label, state, operations) = {
            let mut reader = self.reader.lock().await;
            let client = reader
                .as_mut()
                .ok_or_else(|| failed("PRODUCT_READ_DRIVER_UNAVAILABLE"))?;
            let tx = client
                .build_transaction()
                .isolation_level(tokio_postgres::IsolationLevel::RepeatableRead)
                .read_only(true)
                .start()
                .await
                .map_err(|_| failed(UNAVAILABLE))?;
            crate::persistence::postgres::bounds(&tx)
                .await
                .map_err(|_| failed(UNAVAILABLE))?;
            let factor = private_assets::factor_revision_in_transaction(&tx, id, revision)
                .await
                .map_err(|error| failed(error.code()))?;
            if factor["factor_id"] != id
                || factor["revision_fingerprint"] != revision
                || factor["source_sha256"] != content
            {
                return Err(failed("PRIVATE_ASSET_EXACT_READ_MISMATCH"));
            }
            let label = crate::persistence::private_factor_postgres::catalog_presentation(
                &tx, id, &locator,
            )
            .await
            .map_err(|error| failed(error.code()))?;
            tx.commit().await.map_err(|_| failed(UNAVAILABLE))?;
            let state = if let Some(id) = query.get("strategy_id") {
                match Strategies::new(client).read(id).await {
                    Ok(value) => Some(value),
                    Err("PRIVATE_STRATEGY_NOT_FOUND") => None,
                    Err(code) => return Err(failed(code)),
                }
            } else {
                None
            };
            let operations = if let Some(state) = state.as_ref() {
                if let Some(pin) = state["current_revision_fingerprint"].as_str() {
                    let original = BacktestOrigin::ManualStrategy {
                        strategy_id: query.get("strategy_id").cloned().ok_or_else(invalid)?,
                        strategy_revision_fingerprint: pin.into(),
                    };
                    Preparations::new(client)
                        .for_backtest_origin(&original, &owner)
                        .await
                        .map_err(failed)?
                } else {
                    Vec::new()
                }
            } else {
                Vec::new()
            };
            (factor, label, state, operations)
        };
        let selected_id = if let Some(id) = query.get("strategy_id") {
            id.clone()
        } else {
            let mut entropy = [0_u8; 16];
            getrandom::fill(&mut entropy).map_err(|_| failed(UNAVAILABLE))?;
            format!(
                "private.strategy.btc_momentum_{}",
                entropy
                    .iter()
                    .map(|byte| format!("{byte:02x}"))
                    .collect::<String>()
            )
        };
        let draft = choose_draft(
            &btc_definition(&factor).map_err(failed)?,
            &selected_id,
            state.as_ref(),
        )
        .map_err(failed)?;
        let existing = if let Some(pin) = state
            .as_ref()
            .and_then(|value| value["current_revision_fingerprint"].as_str())
        {
            self.backtest_context_preparations(
                operations,
                &BacktestOrigin::ManualStrategy {
                    strategy_id: selected_id,
                    strategy_revision_fingerprint: pin.into(),
                },
                human,
                deadline,
            )
            .await?
        } else {
            Vec::new()
        };
        let generation = self.backtest_context_generation().await?;
        if Instant::now() >= deadline {
            return Err(failed("REQUEST_DEADLINE_EXPIRED"));
        }
        self.human_access.check_session(human)?;
        let value = json!({"schema_version":1,"factor_locator":locator,"factor_name":label["display"]["display_name"],"formula":null,
            "draft":draft,"release_manifest_fingerprint":self.research_preparation_config.release_manifest_fingerprint,"expected_active_generation":generation,"initialize_fresh_runtime":false,"existing_preparations":existing});
        Ok(ingress::attach(
            Json(value).into_response(),
            Release::Generation(human.metadata_session()),
        ))
    }
    pub(crate) async fn backtest_creation_context_v2(
        self: &Arc<Self>,
        request: Request<Body>,
        human: human_access::Session,
        deadline: Instant,
    ) -> Result<Response, Failure> {
        self.human_access.check_session(&human)?;
        if Instant::now() >= deadline {
            return Err(failed("REQUEST_DEADLINE_EXPIRED"));
        }
        if request.method() != Method::GET {
            return Err(invalid());
        }
        let owner = human.subject_id()?.to_owned();
        let selected = origin(&parameters(request.uri())?)?;
        let (strategy_name, existing) = {
            let mut reader = self.reader.lock().await;
            let client = reader
                .as_mut()
                .ok_or_else(|| failed("PRODUCT_READ_DRIVER_UNAVAILABLE"))?;
            let strategy_name = match &selected {
                BacktestOrigin::ManualStrategy {
                    strategy_id,
                    strategy_revision_fingerprint,
                } => {
                    let tx = client
                        .build_transaction()
                        .isolation_level(tokio_postgres::IsolationLevel::RepeatableRead)
                        .read_only(true)
                        .start()
                        .await
                        .map_err(|_| failed(UNAVAILABLE))?;
                    crate::persistence::postgres::bounds(&tx)
                        .await
                        .map_err(|_| failed(UNAVAILABLE))?;
                    let revision = private_assets::strategy_revision_in_transaction(
                        &tx,
                        strategy_id,
                        strategy_revision_fingerprint,
                    )
                    .await
                    .map_err(|error| failed(error.code()))?;
                    tx.commit().await.map_err(|_| failed(UNAVAILABLE))?;
                    name(&revision, "已保存策略")
                }
                BacktestOrigin::FrozenStrategy {
                    strategy_fingerprint,
                    freeze_relation_fingerprint,
                    ..
                } => {
                    let root = crate::security::protected_files::open_directory(
                        &self.research_preparation_config.research_root,
                    )
                    .map_err(|_| failed(UNAVAILABLE))?;
                    let frozen =
                        crate::application::frozen_strategy::FrozenStore::open(root.as_fd())
                            .map_err(|error| failed(error.code()))?;
                    let revision = frozen
                        .load_verified(strategy_fingerprint, 8 * 1024 * 1024)
                        .map_err(|error| failed(error.code()))?;
                    let relation = frozen
                        .load_relation_verified(freeze_relation_fingerprint, 8 * 1024 * 1024)
                        .map_err(|error| failed(error.code()))?;
                    if relation.strategy_fingerprint() != revision.fingerprint() {
                        return Err(failed("BACKTEST_CONTEXT_STRATEGY_MISMATCH"));
                    }
                    let record = relation.to_record();
                    if record["origin"]["kind"] == "MANUAL_BACKTEST" {
                        let id = record["origin"]["private_strategy_id"]
                            .as_str()
                            .ok_or_else(|| failed(UNAVAILABLE))?;
                        let pin = record["origin"]["private_strategy_revision_fingerprint"]
                            .as_str()
                            .ok_or_else(|| failed(UNAVAILABLE))?;
                        let tx = client
                            .build_transaction()
                            .isolation_level(tokio_postgres::IsolationLevel::RepeatableRead)
                            .read_only(true)
                            .start()
                            .await
                            .map_err(|_| failed(UNAVAILABLE))?;
                        crate::persistence::postgres::bounds(&tx)
                            .await
                            .map_err(|_| failed(UNAVAILABLE))?;
                        let authored =
                            private_assets::strategy_revision_in_transaction(&tx, id, pin)
                                .await
                                .map_err(|error| failed(error.code()))?;
                        tx.commit().await.map_err(|_| failed(UNAVAILABLE))?;
                        name(&authored, "已冻结策略")
                    } else {
                        name(&revision.to_record(), "已冻结策略")
                    }
                }
            };
            let existing = Preparations::new(client)
                .for_backtest_origin(&selected, &owner)
                .await
                .map_err(failed)?;
            (strategy_name, existing)
        };
        let preparations = self
            .backtest_context_preparations(existing, &selected, &human, deadline)
            .await?;
        let generation = self.backtest_context_generation().await?;
        if Instant::now() >= deadline {
            return Err(failed("REQUEST_DEADLINE_EXPIRED"));
        }
        self.human_access.check_session(&human)?;
        let value = json!({"schema_version":2,"strategy_name":strategy_name,"input_defaults":{"schema_version":2,"profile":"BTC_SPOT_NEXT_OPEN_BACKTEST_V1","origin":selected,
            "release_manifest_fingerprint":self.research_preparation_config.release_manifest_fingerprint,"expected_active_generation":generation,"initialize_fresh_runtime":false},
            "sample_start_at":"2025-01-03T00:00:00Z","sample_end_at":"2025-01-03T12:00:00Z","initial_cash":"10000","quantity":"0.01","fee_bps":10,"slippage_bps":2,
            "limitations":["仅限现货多头；不加仓、不借币、不使用杠杆。","收盘后形成信号，最早按下一分钟开盘价成交。","使用当前交易规则建模；短样本结果仅作探索。"],"existing_preparations":preparations});
        Ok(ingress::attach(
            Json(value).into_response(),
            Release::Generation(human.metadata_session()),
        ))
    }
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn normal_context_requires_exact_private_revision_and_never_research_or_latest() {
        let query = BTreeMap::from([
            ("strategy_id".into(), "private.strategy.btc_momentum".into()),
            ("strategy_revision_fingerprint".into(), "a".repeat(64)),
        ]);
        assert!(matches!(
            origin(&query).unwrap(),
            BacktestOrigin::ManualStrategy { .. }
        ));
        for (key, value) in [
            ("strategy_revision_fingerprint", "latest"),
            ("strategy_id", "private.factor.other"),
        ] {
            let mut bad = query.clone();
            bad.insert(key.into(), value.into());
            assert!(origin(&bad).is_err());
        }
        let mut additional = query.clone();
        additional.insert(
            "research_run_id".into(),
            "00000000-0000-4000-8000-000000009403".into(),
        );
        assert!(origin(&additional).is_err());
    }
    #[test]
    fn frozen_context_requires_all_four_exact_pins() {
        let query = [
            "strategy_fingerprint",
            "freeze_relation_fingerprint",
            "qualification_decision_fingerprint",
            "promotion_fingerprint",
        ]
        .into_iter()
        .map(|key| (key.into(), "a".repeat(64)))
        .collect::<BTreeMap<_, _>>();
        assert!(matches!(
            origin(&query).unwrap(),
            BacktestOrigin::FrozenStrategy { .. }
        ));
        for key in query.keys() {
            let mut missing = query.clone();
            missing.remove(key);
            assert!(origin(&missing).is_err());
        }
    }
    #[test]
    fn empty_exact_revision_description_uses_a_natural_name_without_ids_or_mutable_head() {
        assert_eq!(
            name(&json!({"description":"旧版本策略"}), "已保存策略"),
            "旧版本策略"
        );
        assert_eq!(
            name(&json!({"description":" "}), "已保存策略"),
            "已保存策略"
        );
    }
}
