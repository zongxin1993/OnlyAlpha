use crate::{Components, Store, model::*};
use onlyalpha_domain::time::OnlyTimestamp;
use serde_json::{Value, json};
/// Source-bound Runtime Account performance; no execution or Result-seal authority.
/// ```compile_fail
/// use onlyalpha_execution::RuntimePerformance;
/// let forged=RuntimePerformance { value:serde_json::json!({}) };
/// ```
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct RuntimePerformance {
    value: Value,
}
impl RuntimePerformance {
    pub fn record(&self) -> Value {
        self.value.clone()
    }
    pub fn encode(&self) -> Result<Vec<u8>, Error> {
        Ok(serde_json::to_vec(&self.value)?)
    }
}
impl Components {
    pub fn performance<S: Store>(
        &self,
        store: &S,
        initial_time: &OnlyTimestamp,
    ) -> Result<RuntimePerformance, Error> {
        let source = self.verified_source(store, |_| Ok(()))?;
        let performance = boundary(self.account.performance(initial_time))?.record();
        let mut value = json!({"schema_version":1,"semantic_version":"RUNTIME_PORTFOLIO_PERFORMANCE@1","scope":self.config,"source":source,"performance":performance});
        value["id"] = json!(format!("RPP-{}", hash(&value)));
        Ok(RuntimePerformance { value })
    }
}
