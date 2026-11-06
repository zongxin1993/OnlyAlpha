use crate::{Components, model::*};
use serde_json::{Value, json};
use std::sync::Arc;
#[cfg(test)]
std::thread_local! {
    pub(crate) static FULL_LEDGER_STATE_CAPTURES: std::cell::Cell<u64> = const { std::cell::Cell::new(0) };
}
#[cfg(test)]
std::thread_local! {
    static VALUATION_HISTORY_ACCOUNT_CAPTURES: std::cell::Cell<usize> = const { std::cell::Cell::new(0) };
}
impl Components {
    pub(crate) fn valuation(&mut self, input: &Value) -> Result<(), Error> {
        let p = &input["payload"];
        row(
            p,
            &[
                "valuation",
                "version",
                "economic_version",
                "position_evidence",
                "marks",
            ],
        )?;
        let mut intent = p.clone();
        intent["time"] = input["time"].clone();
        let effect = boundary(self.position.value(&intent))?;
        let n = uint(&input["runtime_sequence"])?;
        let mut seen = std::collections::BTreeSet::new();
        for m in p["marks"]
            .as_array()
            .ok_or_else(|| err("EXECUTION_VALUATION_MARKS"))?
        {
            let i = text(&m["instrument"])?;
            if uint(&m["as_of_sequence"])? > n || !seen.insert(text(&m["source_ref"])?) {
                return Err(err("EXECUTION_VALUATION_MARK_WATERMARK"));
            }
            let old = &self.meta["valuation_marks"][i];
            if old == m {
                continue;
            } // Reuse only the exact immutable fact, never a modified alias.
            if !old.is_null()
                && (uint(&m["version"])? <= uint(&old["version"])?
                    || uint(&m["as_of_sequence"])? <= uint(&old["as_of_sequence"])?
                    || dec(&json!(m["time"].to_string()))? < dec(&json!(old["time"].to_string()))?)
            {
                return Err(err("EXECUTION_VALUATION_STALE"));
            }
            if self.meta["valuation_sources"]
                .get(text(&m["source_ref"])?)
                .is_some()
            {
                return Err(err("EXECUTION_VALUATION_SOURCE_ALIAS"));
            }
        }
        let position = self.position.current_exposure();
        let ledger = self.ledger.valuation_view();
        let clusters: Vec<_> = self.config["profiles"]
            .as_object()
            .expect("profiles")
            .keys()
            .cloned()
            .collect();
        for (ordinal, cluster) in clusters.iter().enumerate() {
            let rows = &ledger[cluster]["lines"];
            let mut lines = vec![];
            for b in position["allocations"].as_array().expect("allocations") {
                if b["cluster"] != *cluster {
                    continue;
                }
                let i = text(&b["instrument"])?;
                let snapshot = &b["snapshot"];
                let line = &rows[i];
                let witness = super::planning::allocation_witness(snapshot, self.precision)?;
                if line["allocation"] != witness {
                    return Err(err("EXECUTION_VALUATION_ALLOCATION_RELATION"));
                }
                let mark = p["marks"]
                    .as_array()
                    .expect("validated marks")
                    .iter()
                    .find(|m| m["instrument"] == i)
                    .ok_or_else(|| err("EXECUTION_VALUATION_MARK_REQUIRED"))?;
                lines.push(json!({"schema_version":1,"instrument":i,"allocation_version":snapshot["version"],"allocation_evidence":line["allocation_evidence"],"mark":mark["mark"],"multiplier":line["multiplier"]}));
            }
            if rows.as_object().map_or(0, |m| m.len()) != lines.len() {
                return Err(err("EXECUTION_VALUATION_ALLOCATION_COMPLETENESS"));
            }
            let mut c=self.ledger_command(input,"VALUATION",json!({"schema_version":1,"valuation":format!("VAL-{}",hash(&json!([input["engine"],input["runtime"],input["account"],input["generation"],p["valuation"],cluster]))),"economic_version":ledger[cluster]["economic_version"],"version":p["version"],"lines":lines}),ordinal as u64+1);
            c["cluster"] = json!(cluster);
            self.ledger_apply(&c)?;
        }
        let c = self.command(input, "VALUATION", Value::Null, 0);
        if boundary(Arc::make_mut(&mut self.account).apply_valuation(&c, &effect))?.status
            != onlyalpha_account::Status::Applied
        {
            return Err(err("EXECUTION_VALUATION_NOT_APPLIED"));
        }
        for m in p["marks"].as_array().expect("validated marks") {
            let i = text(&m["instrument"])?;
            Arc::make_mut(&mut self.meta)["valuation_marks"][i] = m.clone();
            Arc::make_mut(&mut self.meta)["valuation_sources"][text(&m["source_ref"])?] =
                json!(hash(m));
            // Keep fill consumers' cached marks aligned with this account-wide valuation.
            for cluster in &clusters {
                if !self.meta["marks"][cluster][i].is_null() {
                    Arc::make_mut(&mut self.meta)["marks"][cluster][i] = m["mark"].clone();
                }
            }
        }
        Ok(())
    }
}

impl Components {
    pub(crate) fn validate_valuation_metadata(&self, meta: &Value) -> Result<(), Error> {
        let mut marks = json!({});
        let mut sources = json!({});
        for intent in self.account.valuation_intents() {
            for m in intent["marks"]
                .as_array()
                .ok_or_else(|| err("EXECUTION_VALUATION_HISTORY"))?
            {
                let i = text(&m["instrument"])?;
                let source = text(&m["source_ref"])?;
                let old = &marks[i];
                if old == m {
                    continue;
                }
                if !old.is_null()
                    && (uint(&m["version"])? <= uint(&old["version"])?
                        || uint(&m["as_of_sequence"])? <= uint(&old["as_of_sequence"])?
                        || dec(&json!(m["time"].to_string()))?
                            < dec(&json!(old["time"].to_string()))?)
                {
                    return Err(err("EXECUTION_VALUATION_HISTORY_WATERMARK"));
                }
                if sources.get(source).is_some() {
                    return Err(err("EXECUTION_VALUATION_HISTORY_ALIAS"));
                }
                marks[i] = m.clone();
                sources[source] = json!(hash(m));
            }
        }
        if meta["valuation_marks"] != marks || meta["valuation_sources"] != sources {
            return Err(err("EXECUTION_VALUATION_HISTORY_MISMATCH"));
        }
        Ok(())
    }
}

#[cfg(test)]
#[path = "valuation_history_tests.rs"]
mod valuation_history_tests;
