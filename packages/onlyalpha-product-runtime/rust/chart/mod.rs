//! Disposable chart Product composition. Storage/Source own input truth; the
//! selected installed Python factory owns mathematics, never business authority.
use crate::{
    market_data::Storage,
    market_product::{
        self, Application, Authorized, HistoryContext, PreviewSource, Resolved, SendFence,
        WindowRequest,
    },
    source_access::{Permission, Session},
};
use onlyalpha_calculation::product::{Definition, TypeDeclaration};
use onlyalpha_calculation_worker::{Cancellation, ChartInstallation, ProcessState, Worker};
use onlyalpha_domain::{base::OnlyDomainModel, market::OnlyBarSemantic};
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use std::{
    collections::{BTreeMap, BTreeSet},
    sync::{Arc, Mutex},
    time::{Duration, Instant},
};
const WORK: usize = 8 * 1024 * 1024;
#[derive(Debug)]
pub enum Error {
    Invalid,
    Unavailable,
    Changed,
    InputChanged,
    Capacity,
    Market(market_product::Error),
    Worker(onlyalpha_calculation_worker::WorkerError),
}
impl Error {
    pub fn code(&self) -> &'static str {
        match self {
            Self::Invalid => "CHART_STUDY_REQUEST_INVALID",
            Self::Unavailable => "CHART_STUDY_CAPABILITY_UNAVAILABLE",
            Self::Changed => "CHART_STUDY_REGISTRATION_CHANGED",
            Self::InputChanged => "CHART_STUDY_INPUT_CHANGED",
            Self::Capacity => "CHART_STUDY_CAPACITY_UNAVAILABLE",
            Self::Market(e) => e.code(),
            Self::Worker(_) => "CHART_STUDY_QUERY_UNAVAILABLE",
        }
    }
}
impl std::fmt::Display for Error {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(self.code())
    }
}
impl std::error::Error for Error {}
impl From<market_product::Error> for Error {
    fn from(e: market_product::Error) -> Self {
        Self::Market(e)
    }
}
impl From<crate::source_access::Error> for Error {
    fn from(_: crate::source_access::Error) -> Self {
        Self::Market(market_product::Error::Forbidden)
    }
}
impl From<onlyalpha_calculation_worker::WorkerError> for Error {
    fn from(e: onlyalpha_calculation_worker::WorkerError) -> Self {
        Self::Worker(e)
    }
}
type Result<T> = std::result::Result<T, Error>;
fn hash(b: &[u8]) -> String {
    Sha256::digest(b)
        .iter()
        .map(|v| format!("{v:02x}"))
        .collect()
}
fn fp(v: &Value) -> Result<String> {
    Ok(hash(
        onlyalpha_metadata_json::canonical_json(&v.to_string(), WORK)
            .map_err(|_| Error::Unavailable)?
            .as_bytes(),
    ))
}
fn text(v: &Value) -> Result<&str> {
    v.as_str()
        .filter(|s| !s.is_empty() && s.len() <= 4096)
        .ok_or(Error::Invalid)
}
fn sha(v: &Value) -> Result<&str> {
    let s = text(v)?;
    if s.len() != 64
        || !s
            .bytes()
            .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
    {
        return Err(Error::Invalid);
    }
    Ok(s)
}
fn exact(v: &Value, fields: &[&str]) -> Result<()> {
    let o = v.as_object().ok_or(Error::Invalid)?;
    if o.len() != fields.len() || fields.iter().any(|f| !o.contains_key(*f)) {
        return Err(Error::Invalid);
    }
    Ok(())
}
fn ns(v: &Value) -> Result<i64> {
    let s = text(v)?;
    let n = s.parse::<i64>().map_err(|_| Error::Invalid)?;
    if n < 0 || n.to_string() != s {
        return Err(Error::Invalid);
    }
    Ok(n)
}
fn remaining(end: Instant) -> Result<Duration> {
    end.checked_duration_since(Instant::now())
        .filter(|d| !d.is_zero())
        .ok_or(Error::Unavailable)
}
fn manifest(
    reference: Value,
    resources: Value,
    dependencies: Value,
    entrypoint: &str,
) -> Result<Value> {
    let bundle = fp(
        &json!({"domain":"onlyalpha.calculation.implementation-bundle","schema_version":1,"resources":resources}),
    )?;
    let identity = json!({"domain":"onlyalpha.calculation.implementation","schema_version":1,"calculation_type_reference":reference,"backend_kind":"RESEARCH","entrypoint_identity":entrypoint,"implementation_bundle_fingerprint":bundle,"semantic_dependencies":dependencies});
    Ok(
        json!({"schema_version":1,"calculation_type_reference":reference,"backend_kind":"RESEARCH","entrypoint_identity":entrypoint,"resources":resources,"semantic_dependencies":dependencies,"implementation_bundle_fingerprint":bundle,"implementation_fingerprint":fp(&identity)?}),
    )
}
struct Entry {
    declaration: TypeDeclaration,
    capability: Value,
}
struct Composition {
    worker: Worker,
    algorithm_artifact: Value,
    entries: BTreeMap<(String, String), Entry>,
}
enum CatalogProjection {
    Empty,
    Fixed { invocation: Value, catalog: Value },
    Rejected,
}
pub enum ChartSource<'a> {
    Current(&'a Resolved),
    History(&'a HistoryContext),
}
impl<'a> From<&'a Resolved> for ChartSource<'a> {
    fn from(v: &'a Resolved) -> Self {
        Self::Current(v)
    }
}
impl<'a> From<&'a HistoryContext> for ChartSource<'a> {
    fn from(v: &'a HistoryContext) -> Self {
        Self::History(v)
    }
}
impl ChartSource<'_> {
    fn selection(&self) -> &crate::source_access::Selection {
        match self {
            Self::Current(r) => r.selection(),
            Self::History(h) => h.selection(),
        }
    }
}
pub struct ChartQuery {
    installation: Arc<ChartInstallation>,
    invocation: Value,
    slot: Arc<tokio::sync::Semaphore>,
    active: Mutex<Vec<Cancellation>>,
    catalog: Mutex<CatalogProjection>,
}
impl ChartQuery {
    pub const MAX_CONCURRENT_INVOCATIONS: usize = 2;
    pub fn new(installation: ChartInstallation) -> Result<Self> {
        let executable = std::fs::read(std::env::current_exe().map_err(|_| Error::Unavailable)?)
            .map_err(|_| Error::Unavailable)?;
        let invocation = manifest(
            json!({"kind":"INDICATOR","type_id":"onlyalpha.chart-study.invocation","semantic_version":"3"}),
            json!([{"relative_path":"native-product-executable","byte_sha256":hash(&executable)}]),
            json!([{"dependency_id":"onlyalpha.algorithm-installation","semantic_version":"1","artifact_fingerprint":installation.artifact_fingerprint()}]),
            "onlyalpha_product_runtime.chart:ChartQuery",
        )?;
        Ok(Self {
            installation: Arc::new(installation),
            invocation,
            slot: Arc::new(tokio::sync::Semaphore::new(
                Self::MAX_CONCURRENT_INVOCATIONS,
            )),
            active: Mutex::new(Vec::new()),
            catalog: Mutex::new(CatalogProjection::Empty),
        })
    }
    pub fn process_state(&self) -> ProcessState {
        match self.active.lock() {
            Ok(active) => active.iter().map(Cancellation::state).fold(
                ProcessState::Joined,
                |observed, next| match (observed, next) {
                    (ProcessState::Uncertain, _) | (_, ProcessState::Uncertain) => {
                        ProcessState::Uncertain
                    }
                    (ProcessState::Running, _) | (_, ProcessState::Running) => {
                        ProcessState::Running
                    }
                    _ => ProcessState::Joined,
                },
            ),
            Err(_) => ProcessState::Uncertain,
        }
    }
    pub fn is_closed(&self) -> bool {
        self.slot.is_closed()
    }
    /// Close new admission, then explicitly drain the same retained lifecycle owner.
    pub fn close(&self) -> Result<()> {
        self.slot.close();
        self.drain()
    }
    pub fn drain(&self) -> Result<()> {
        let active = self.active.lock().unwrap_or_else(|p| p.into_inner());
        let mut outcome = Ok(());
        for control in active.iter() {
            let drained = control.drain();
            if outcome.is_ok() {
                outcome = drained;
            }
        }
        outcome?;
        self.active.clear_poison();
        Ok(())
    }
    /// A declaration is pinned only after successful worker shutdown. Conflicting
    /// declarations cannot replace the fixed installation's original identity.
    fn check_catalog(&self, observed: &Value, publish: bool) -> Result<()> {
        let mut catalog = self.catalog.lock().map_err(|_| Error::Unavailable)?;
        match &*catalog {
            CatalogProjection::Empty => {
                if publish {
                    *catalog = CatalogProjection::Fixed {
                        invocation: self.invocation.clone(),
                        catalog: observed.clone(),
                    };
                }
                Ok(())
            }
            CatalogProjection::Fixed {
                invocation,
                catalog: fixed,
            } if *invocation == self.invocation && fixed == observed => Ok(()),
            _ => {
                *catalog = CatalogProjection::Rejected;
                Err(Error::Changed)
            }
        }
    }
    fn compose(&self, end: Instant) -> Result<(Composition, Value)> {
        remaining(end)?;
        let permit = self
            .slot
            .clone()
            .try_acquire_owned()
            .map_err(|_| Error::Capacity)?;
        let mut active = self.active.lock().map_err(|_| Error::Unavailable)?;
        if self.is_closed() || active.iter().any(|c| c.state() == ProcessState::Uncertain) {
            return Err(Error::Unavailable);
        }
        active.retain(|c| c.state() != ProcessState::Joined);
        remaining(end)?;
        let mut worker = self.installation.spawn(Box::new(permit))?;
        active.push(worker.cancellation()?);
        drop(active);
        worker.handshake_chart(remaining(end)?)?;
        let observed = worker.exchange_chart(json!({"op":"CATALOG"}), remaining(end)?)?;
        let entries = self.admit_catalog(&observed)?;
        self.check_catalog(&observed, false)?;
        Ok((
            Composition {
                worker,
                algorithm_artifact: observed["artifact_fingerprint"].clone(),
                entries,
            },
            observed,
        ))
    }
    fn admit_catalog(&self, observed: &Value) -> Result<BTreeMap<(String, String), Entry>> {
        exact(observed, &["artifact_fingerprint", "entries"])?;
        sha(&observed["artifact_fingerprint"])?;
        let rows = observed["entries"]
            .as_array()
            .filter(|r| !r.is_empty() && r.len() <= 64)
            .ok_or(Error::Unavailable)?;
        let provider = json!({"schema_version":1,"provider_id":"onlyalpha.indicator.library","provider_version":"17","kind":"INDICATOR","source":{"kind":"DISTRIBUTION","distribution_name":"onlyalpha-plugin-indicators","distribution_version":self.installation.distribution_version()?}});
        let content = fp(
            &json!({"provider_manifest":provider,"installed_algorithm_artifact":observed["artifact_fingerprint"],"installation":self.installation.artifact_fingerprint(),"registrations":rows}),
        )?;
        let generation =
            fp(&json!({"domain":"onlyalpha.chart.installed-catalog","provider":content}))?;
        let mut entries = BTreeMap::new();
        let mut required_resources = BTreeSet::new();
        for row in rows {
            exact(
                row,
                &[
                    "schema_version",
                    "descriptor",
                    "parameter_values",
                    "implementation_fingerprint",
                    "implementation",
                    "artifact_fingerprint",
                    "support",
                    "numeric_binding",
                ],
            )?;
            if row["artifact_fingerprint"] != observed["artifact_fingerprint"] {
                return Err(Error::Unavailable);
            }
            let d = &row["descriptor"];
            let declaration=TypeDeclaration::from_record(&json!({"schema_version":row["schema_version"],"descriptor":d,"parameter_values":row["parameter_values"]}),WORK).map_err(|_|Error::Unavailable)?;
            if d["kind"] != "INDICATOR" || d["execution_shape"] != "TIME_SERIES" {
                return Err(Error::Unavailable);
            }
            let m = &row["implementation"];
            let expected = manifest(
                json!({"kind":d["kind"],"type_id":d["type_id"],"semantic_version":d["semantic_version"]}),
                m["resources"].clone(),
                m["semantic_dependencies"].clone(),
                text(&m["entrypoint_identity"])?,
            )?;
            if *m != expected
                || m["implementation_fingerprint"] != row["implementation_fingerprint"]
            {
                return Err(Error::Unavailable);
            }
            for resource in m["resources"].as_array().ok_or(Error::Unavailable)? {
                required_resources.insert((
                    text(&resource["relative_path"])?.to_owned(),
                    sha(&resource["byte_sha256"])?.to_owned(),
                ));
            }
            let numeric = &row["numeric_binding"];
            if numeric["declared_rounding"] != d["numeric"]["rounding"]
                || numeric["effective_rounding"] != "ROUND_HALF_EVEN"
                || numeric["representation"] != "DECIMAL"
                || numeric["precision"] != 28
                || numeric["output_quantum"] != "0.000000000001"
                || numeric["resolution_policy"] != "CONTEXT_HALF_EVEN_V1"
                || fp(&numeric["core_policy"])? != sha(&numeric["core_policy_fingerprint"])?
            {
                return Err(Error::Unavailable);
            }
            let members = row["support"]["series"]
                .as_array()
                .filter(|a| !a.is_empty() && a.len() <= 8)
                .ok_or(Error::Unavailable)?
                .iter()
                .map(|s| text(&s["output_name"]).map(str::to_owned))
                .collect::<Result<Vec<_>>>()?;
            let declared = d["outputs"].as_array().ok_or(Error::Unavailable)?;
            if members.iter().collect::<BTreeSet<_>>().len() != members.len()
                || members.iter().any(|name| {
                    !declared
                        .iter()
                        .any(|p| p["name"] == *name && p["data_type"] == "DECIMAL")
                })
            {
                return Err(Error::Unavailable);
            }
            let projection = json!({"domain":"onlyalpha.chart-study.capability-projection","schema_version":2,"source_kind":"CHART_STUDY_TRANSIENT","authority":"DISPLAY_ONLY","publication_status":"NOT_A_RESEARCH_RESULT","descriptor":d,"backend":"RESEARCH","implementation":m,"invocation":self.invocation,"provider_manifest":provider,"provider_content_fingerprint":content,"catalog_generation_fingerprint":generation,"readiness_contract_versions":[1],"output_members":members,"supported_shape":"TIME_SERIES/BAR_FIELDS","input_support":{"instrument_policy":"EXACT_SOURCE_CATALOG","resolution_mode":"VERIFIED_NATIVE_OR_DERIVED","bar_formation":"FIXED_DURATION","alignment":"UTC_24X7","closed_only":false,"preview_mode":"OWNING_STREAM_SNAPSHOT","coverage_policy":"COMPLETE_VERIFIED_WINDOW"},"finite_initialization":"PARTIAL_WINDOW_AT_EXPLICIT_FINITE_START","limits":{"max_input_rows":2000,"max_period":10000,"max_concurrent_invocations":Self::MAX_CONCURRENT_INVOCATIONS},"numeric_binding":row["numeric_binding"],"presentation":row["support"]});
            let capability = json!({"kind":"INDICATOR","type_id":d["type_id"],"semantic_version":d["semantic_version"],"descriptor":d,"descriptor_fingerprint":fp(d)?,"backend":"RESEARCH","implementation_fingerprint":row["implementation_fingerprint"],"provider_id":provider["provider_id"],"provider_version":provider["provider_version"],"provider_content_fingerprint":content,"catalog_generation_fingerprint":generation,"readiness_contract_version":1,"execution_shape":"TIME_SERIES","output_members":members,"limits":projection["limits"],"numeric_execution_binding":row["numeric_binding"],"invocation_implementation_fingerprint":self.invocation["implementation_fingerprint"],"presentation":row["support"],"capability_projection":projection,"capability_projection_fingerprint":fp(&projection)?});
            let key = (
                text(&d["type_id"])?.into(),
                text(&d["semantic_version"])?.into(),
            );
            if entries
                .insert(
                    key,
                    Entry {
                        declaration,
                        capability,
                    },
                )
                .is_some()
            {
                return Err(Error::Unavailable);
            }
        }
        self.installation.require_resources(&required_resources)?;
        Ok(entries)
    }
    pub fn capabilities(&self, session: &Session) -> Result<Value> {
        self.capabilities_before(session, Instant::now() + Duration::from_secs(10))
    }
    pub fn capabilities_before(&self, session: &Session, deadline: Instant) -> Result<Value> {
        session.require_permission(Permission::ClosedHistory)?;
        let value = self.registered_capabilities_before(deadline)?;
        session.check_active()?;
        Ok(value)
    }
    /// Public implementation metadata only; the Host separately admits Human reads.
    /// This method grants no Source, computation or execution capability.
    pub fn registered_capabilities_before(&self, deadline: Instant) -> Result<Value> {
        let deadline = deadline.min(Instant::now() + Duration::from_secs(10));
        remaining(deadline)?;
        let observed = {
            let catalog = self.catalog.lock().map_err(|_| Error::Unavailable)?;
            match &*catalog {
                CatalogProjection::Empty => None,
                CatalogProjection::Fixed {
                    invocation,
                    catalog,
                } if *invocation == self.invocation => Some(catalog.clone()),
                _ => return Err(Error::Changed),
            }
        };
        if let Some(observed) = observed {
            let _permit = self
                .slot
                .clone()
                .try_acquire_owned()
                .map_err(|_| Error::Capacity)?;
            let active = self.active.lock().map_err(|_| Error::Unavailable)?;
            if active.iter().any(|c| c.state() == ProcessState::Uncertain) {
                return Err(Error::Unavailable);
            }
            // No retained freshness or worker-availability proof: re-read the
            // complete sealed installation and every exact resource binding.
            self.installation.verify()?;
            let entries = self.admit_catalog(&observed)?;
            self.check_catalog(&observed, false)?;
            remaining(deadline)?;
            if self.is_closed() {
                return Err(Error::Unavailable);
            }
            drop(active);
            return Ok(
                json!({"schema_version":2,"capabilities":entries.values().map(|e|e.capability.clone()).collect::<Vec<_>>()}),
            );
        }
        let (composition, observed) = self.compose(deadline)?;
        let value = json!({"schema_version":2,"capabilities":composition.entries.values().map(|e|e.capability.clone()).collect::<Vec<_>>()});
        composition.worker.terminate()?;
        remaining(deadline)?;
        if self.is_closed() {
            return Err(Error::Unavailable);
        }
        self.check_catalog(&observed, true)?;
        Ok(value)
    }
    pub fn catalog(&self, session: &Session) -> Result<Value> {
        self.catalog_before(session, Instant::now() + Duration::from_secs(10))
    }
    pub fn catalog_before(&self, session: &Session, deadline: Instant) -> Result<Value> {
        session.require_permission(Permission::ClosedHistory)?;
        let value = self.registered_catalog_before(deadline)?;
        session.check_active()?;
        Ok(value)
    }
    pub fn registered_catalog_before(&self, deadline: Instant) -> Result<Value> {
        let caps = self.registered_capabilities_before(deadline)?;
        let rows = caps["capabilities"].as_array().ok_or(Error::Unavailable)?;
        let mut calculations = vec![];
        for row in rows {
            let d = &row["descriptor"];
            let parameters=d["parameters"].as_array().ok_or(Error::Unavailable)?.iter().map(|p|{
    let scalar=|v:&Value|json!({"type":if v.is_null(){"NULL"}else{p["parameter_type"].as_str().unwrap_or("")},"value":v});
    json!({"name":p["name"],"type":p["parameter_type"],"required":p["required"],"default":scalar(&p["default"]),"minimum":if p["minimum"].is_null(){Value::Null}else{scalar(&p["minimum"])},"maximum":if p["maximum"].is_null(){Value::Null}else{scalar(&p["maximum"])},"enum_values":p["enum_values"].as_array().map(|a|a.iter().map(scalar).collect::<Vec<_>>()).unwrap_or_default(),"uppercase":p["uppercase"]})
   }).collect::<Vec<_>>();
            calculations.push(json!({"kind":d["kind"],"type_reference":{"kind":d["kind"],"type_id":d["type_id"],"semantic_version":d["semantic_version"]},"parameters":parameters,"inputs":d["inputs"],"outputs":d["outputs"],"parameter_sweep_allowed":true}));
        }
        Ok(json!({"schema_version":2,"calculations":calculations}))
    }
    pub async fn prepare<'a>(
        &self,
        app: &Application,
        source: impl Into<ChartSource<'a>>,
        session: &Session,
        store: &mut Storage<'_>,
        input: ChartInput<'_>,
    ) -> Result<PreparedChart> {
        self.prepare_before(
            app,
            source,
            session,
            store,
            input,
            Instant::now() + Duration::from_secs(10),
        )
        .await
    }
    pub async fn prepare_before<'a>(
        &self,
        app: &Application,
        source: impl Into<ChartSource<'a>>,
        session: &Session,
        store: &mut Storage<'_>,
        input: ChartInput<'_>,
        deadline: Instant,
    ) -> Result<PreparedChart> {
        let source = source.into();
        let ChartInput {
            raw,
            preview_stream,
            clock_ns,
        } = input;
        if raw.len() > 65536 {
            return Err(Error::Invalid);
        }
        let canonical =
            onlyalpha_metadata_json::canonical_json(raw, WORK).map_err(|_| Error::Invalid)?;
        let request: Value = serde_json::from_str(&canonical).map_err(|_| Error::Invalid)?;
        exact(
            &request,
            &[
                "schema_version",
                "source_reference",
                "instrument_id",
                "bar_semantic",
                "window",
                "expected_history_projection_fingerprint",
                "calculation",
                "include_unclosed_preview",
                "preview_stream_id",
            ],
        )?;
        if request["schema_version"] != 2 {
            return Err(Error::Invalid);
        }
        let r = &request["source_reference"];
        exact(
            r,
            &[
                "integration_id",
                "integration_revision_fingerprint",
                "expected_type_id",
            ],
        )?;
        let reference = source.selection().reference();
        if r["integration_id"] != reference.integration_id()
            || r["integration_revision_fingerprint"] != reference.revision()
            || r["expected_type_id"].as_str() != reference.expected_type_id()
        {
            return Err(Error::InputChanged);
        }
        session.require_selection(source.selection(), Permission::ClosedHistory)?;
        let w = &request["window"];
        exact(w, &["anchor_kind", "before_ns", "target_bar_count"])?;
        let before = ns(&w["before_ns"])?;
        let count = w["target_bar_count"]
            .as_u64()
            .filter(|n| (1..=2000).contains(n))
            .ok_or(Error::Invalid)? as usize;
        if w["anchor_kind"] != "BEFORE_TIME" {
            return Err(Error::Invalid);
        }
        let semantic =
            OnlyBarSemantic::from_record(&request["bar_semantic"]).map_err(|_| Error::Invalid)?;
        if request["bar_semantic"]["formation"]["kind"] != "FIXED_DURATION" {
            return Err(Error::Invalid);
        }
        let stride = semantic
            .stride_minutes()
            .map_err(|_| Error::Invalid)?
            .to_string()
            .parse::<i64>()
            .map_err(|_| Error::Invalid)?
            .checked_mul(60_000_000_000)
            .ok_or(Error::Invalid)?;
        if before <= 0
            || before % stride != 0
            || before <= stride.checked_mul(count as i64).ok_or(Error::Invalid)?
        {
            return Err(Error::Invalid);
        }
        sha(&request["expected_history_projection_fingerprint"])?;
        let include = request["include_unclosed_preview"]
            .as_bool()
            .ok_or(Error::Invalid)?;
        if include != request["preview_stream_id"].is_string()
            || (!include && !request["preview_stream_id"].is_null())
        {
            return Err(Error::Invalid);
        }
        if include && !crate::command::uuid4(text(&request["preview_stream_id"])?) {
            return Err(Error::Invalid);
        }
        let end = deadline.min(Instant::now() + Duration::from_secs(10));
        let (composition, calculation) = self.prepare_calculation(&request["calculation"], end)?;
        let window_request = WindowRequest {
            instrument_id: text(&request["instrument_id"])?.into(),
            semantic,
            before_ns: Some(before),
            bar_count: count,
            clock_ns,
        };
        let history = match source {
            ChartSource::Current(current) => {
                let reference = app
                    .reference(current, session, text(&request["instrument_id"])?, end)
                    .await?;
                reference.parts()?.1.check()?;
                app.window(current, session, store, &window_request).await?
            }
            ChartSource::History(history) => {
                app.history_window(history, session, store, &window_request)
                    .await?
            }
        };
        let (window, history_fence) = history.parts()?;
        let calendar = history_fence.calendar()?.to_record();
        if fp(&calendar)? != sha(&window["calendar_fingerprint"])?
            || !utc_continuous_calendar(&calendar)
        {
            return Err(Error::Unavailable);
        }

        if !matches!(
            window["resolution_mode"].as_str(),
            Some("PROVIDER_NATIVE" | "DERIVED")
        ) || (window["resolution_mode"] == "PROVIDER_NATIVE"
            && window["derived_projection_fingerprint"] != Value::Null)
            || (window["resolution_mode"] == "DERIVED"
                && !window["derived_projection_fingerprint"]
                    .as_str()
                    .is_some_and(|v| v.len() == 64))
            || window["closed_only"] != true
            || window["resolved_end_ns"] != w["before_ns"]
        {
            return Err(Error::Unavailable);
        }
        sha(&window["resolution_plan_fingerprint"])?;
        sha(&window["calendar_fingerprint"])?;
        let complete = window["coverage"]["status"] == "COMPLETE";
        if complete
            && window["history_projection_fingerprint"]
                != request["expected_history_projection_fingerprint"]
        {
            return Err(Error::InputChanged);
        }
        let preview = if include && complete {
            match preview_stream {
                Some(stream) => {
                    stream.retained_preview(&history, text(&request["preview_stream_id"])?)?
                }
                None => None,
            }
        } else {
            None
        };
        Ok(PreparedChart {
            input_kind: ChartInputKind::SealedHistory,
            composition,
            history,
            preview,
            calculation,
            complete,
            end,
        })
    }
}
struct Calculation {
    definition: Definition,
    declaration: Value,
    capability: Value,
    base: Value,
    selected: Vec<String>,
}
impl ChartQuery {
    // Both explicit input owners use the same registration, parameter validation,
    // installed factory and definition admission. No input authority crosses here.
    fn prepare_calculation(&self, c: &Value, end: Instant) -> Result<(Composition, Calculation)> {
        let (mut composition, _) = self.compose(end)?;
        let calculation = self.resolve_calculation(c, &mut composition, end)?;
        Ok((composition, calculation))
    }
    fn resolve_calculation(
        &self,
        c: &Value,
        composition: &mut Composition,
        end: Instant,
    ) -> Result<Calculation> {
        exact(
            c,
            &[
                "kind",
                "type_id",
                "semantic_version",
                "typed_parameters",
                "output_members",
                "expected_descriptor_fingerprint",
                "expected_implementation_fingerprint",
                "expected_capability_projection_fingerprint",
            ],
        )?;
        if c["kind"] != "INDICATOR" {
            return Err(Error::Invalid);
        }
        let key = (
            text(&c["type_id"])?.into(),
            text(&c["semantic_version"])?.into(),
        );
        let selected = c["output_members"]
            .as_array()
            .filter(|a| !a.is_empty() && a.len() <= 8)
            .ok_or(Error::Invalid)?
            .iter()
            .map(|v| text(v).map(str::to_owned))
            .collect::<Result<Vec<_>>>()?;
        if selected.iter().collect::<BTreeSet<_>>().len() != selected.len() {
            return Err(Error::Invalid);
        }
        for field in [
            "expected_descriptor_fingerprint",
            "expected_implementation_fingerprint",
            "expected_capability_projection_fingerprint",
        ] {
            sha(&c[field])?;
        }
        let entry = composition.entries.get(&key).ok_or(Error::Unavailable)?;
        for (expected, actual) in [
            ("expected_descriptor_fingerprint", "descriptor_fingerprint"),
            (
                "expected_implementation_fingerprint",
                "implementation_fingerprint",
            ),
            (
                "expected_capability_projection_fingerprint",
                "capability_projection_fingerprint",
            ),
        ] {
            if c[expected] != entry.capability[actual] {
                return Err(Error::Changed);
            }
        }
        if selected.iter().any(|s| {
            !entry.capability["output_members"]
                .as_array()
                .is_some_and(|a| a.contains(&json!(s)))
        }) {
            return Err(Error::Invalid);
        }
        let parameters = parameters(&entry.declaration, &c["typed_parameters"])?;
        let base = json!({"type_id":key.0,"semantic_version":key.1,"parameters":parameters,"implementation_fingerprint":entry.capability["implementation_fingerprint"]});
        let mut resolve = base.clone();
        resolve["op"] = json!("RESOLVE");
        let resolved = composition
            .worker
            .exchange_chart(resolve, remaining(end)?)?;
        let definition = resolved_definition(entry, &resolved)?;
        let capability = entry.capability.clone();
        let declaration = entry.declaration.to_record();
        Ok(Calculation {
            definition,
            declaration,
            capability,
            base,
            selected,
        })
    }
}

fn resolved_definition(entry: &Entry, resolved: &Value) -> Result<Definition> {
    exact(resolved, &["definition", "definition_fingerprint"]).map_err(|_| Error::Unavailable)?;
    let definition = entry
        .declaration
        .validate_candidate(&resolved["definition"], WORK)
        .map_err(|_| Error::Unavailable)?;
    let record = definition.to_record();
    let descriptor = entry.declaration.descriptor();
    for field in [
        "inputs",
        "outputs",
        "numeric",
        "timestamp",
        "missing_values",
        "factor_kind",
    ] {
        if record[field] != descriptor[field] {
            return Err(Error::Unavailable);
        }
    }
    for binding in record["input_bindings"]
        .as_object()
        .ok_or(Error::Unavailable)?
        .values()
    {
        if !binding["node_fingerprint"].is_null()
            || !matches!(
                binding["source"].as_str(),
                Some(
                    "bar.open"
                        | "bar.high"
                        | "bar.low"
                        | "bar.close"
                        | "bar.volume"
                        | "bar.start_ns"
                )
            )
        {
            return Err(Error::Unavailable);
        }
    }
    if !definition.to_record()["warmup"]["minimum_observations"]
        .as_u64()
        .is_some_and(|n| (1..=10000).contains(&n))
    {
        return Err(Error::Unavailable);
    }
    if definition.fingerprint()
        != text(&resolved["definition_fingerprint"]).map_err(|_| Error::Unavailable)?
    {
        return Err(Error::Unavailable);
    }
    Ok(definition)
}
fn utc_continuous_calendar(calendar: &Value) -> bool {
    let Some(sessions) = calendar["sessions"].as_array() else {
        return false;
    };
    if sessions.len() != 1 {
        return false;
    }
    let session = &sessions[0];
    calendar["timezone"]["name"] == "UTC"
        && ["holidays", "weekend_days", "special_schedules"]
            .iter()
            .all(|key| calendar[*key].as_array().is_some_and(Vec::is_empty))
        && calendar["effective_from"].is_null()
        && calendar["effective_to"].is_null()
        && session["opens_at"] == "00:00:00"
        && session["closes_at"] == "00:00:00"
        && session["session_type"] == "CONTINUOUS"
        && session["belongs_to_trading_day_offset"] == 0
        && session["allows_market_data"] == true
}
fn request_decimal(s: &str) -> bool {
    if s.is_empty() || s.len() > 64 {
        return false;
    }
    let negative = s.starts_with('-');
    let magnitude = s.strip_prefix('-').unwrap_or(s);
    let (whole, fraction) = magnitude
        .split_once('.')
        .map_or((magnitude, None), |(a, b)| (a, Some(b)));
    if whole.is_empty()
        || !whole.bytes().all(|b| b.is_ascii_digit())
        || (whole.len() > 1 && whole.starts_with('0'))
        || fraction.is_some_and(|f| f.is_empty() || !f.bytes().all(|b| b.is_ascii_digit()))
    {
        return false;
    }
    !negative || magnitude.bytes().any(|b| b.is_ascii_digit() && b != b'0')
}
fn parameters(declaration: &TypeDeclaration, typed: &Value) -> Result<Value> {
    let values = typed
        .as_object()
        .filter(|p| p.len() <= 16)
        .ok_or(Error::Invalid)?;
    let d = declaration.descriptor();
    let specs = d["parameters"].as_array().ok_or(Error::Unavailable)?;
    let mut out = serde_json::Map::new();
    for (name, p) in values {
        exact(p, &["type", "value"])?;
        let spec = specs
            .iter()
            .find(|s| s["name"] == *name)
            .ok_or(Error::Invalid)?;
        if p["type"] != spec["parameter_type"] {
            return Err(Error::Invalid);
        }
        let valid = match p["type"].as_str() {
            Some("INTEGER") => p["value"]
                .as_u64()
                .is_some_and(|n| (1..=10000).contains(&n)),
            Some("BOOLEAN") => p["value"].is_boolean(),
            Some("STRING") => p["value"]
                .as_str()
                .is_some_and(|s| !s.is_empty() && s.len() <= 256),
            Some("DECIMAL") => p["value"].as_str().is_some_and(request_decimal),
            _ => false,
        };
        if !valid {
            return Err(Error::Invalid);
        }
        out.insert(name.clone(), p["value"].clone());
    }
    Ok(Value::Object(out))
}
/// One observed Chart request and its optional retained stream occurrence.
pub struct ChartInput<'a> {
    pub raw: &'a str,
    pub preview_stream: Option<&'a PreviewSource>,
    pub clock_ns: i64,
}
impl Drop for ChartQuery {
    fn drop(&mut self) {
        self.slot.close();
        if let Ok(active) = self.active.lock() {
            for control in active.iter() {
                let _ = control.cancel();
            }
        }
    }
}
#[derive(Clone, Copy)]
enum ChartInputKind {
    SealedHistory,
    Temporary,
}
pub struct PreparedChart {
    input_kind: ChartInputKind,
    composition: Composition,
    history: Authorized<Value>,
    preview: Option<Authorized<Value>>,
    calculation: Calculation,
    complete: bool,
    end: Instant,
}
pub struct ChartResult {
    payload: Value,
    history: SendFence,
    preview: Option<SendFence>,
}
impl ChartResult {
    pub fn into_parts(mut self) -> Result<(Value, ChartFence)> {
        self.history.check()?;
        if let Some(fence) = &self.preview {
            match fence.check() {
                Ok(()) => (),
                Err(market_product::Error::Source(
                    onlyalpha_integration_contract::source::SourceError::Stopped,
                )) => {
                    self.payload["preview"] = Value::Null;
                    self.preview = None;
                }
                Err(error) => return Err(error.into()),
            }
        }
        let fence = ChartFence {
            history: self.history,
            preview: self.preview,
        };
        fence.check()?;
        Ok((self.payload, fence))
    }
}
pub struct ChartFence {
    history: SendFence,
    preview: Option<SendFence>,
}
impl ChartFence {
    pub fn prepare_send(&mut self, payload: &mut Value) -> Result<()> {
        self.history.check()?;
        if let Some(preview) = &self.preview {
            match preview.check() {
                Ok(()) => (),
                Err(market_product::Error::Source(
                    onlyalpha_integration_contract::source::SourceError::Stopped,
                )) => {
                    payload["preview"] = Value::Null;
                    self.preview = None
                }
                Err(error) => return Err(error.into()),
            }
        }
        self.check()
    }
    pub fn check(&self) -> Result<()> {
        self.history.check()?;
        if let Some(p) = &self.preview {
            p.check()?;
        }
        Ok(())
    }
}
impl PreparedChart {
    /// Move into an owned blocking task. Dropping an HTTP future cannot release its
    /// capacity while the actual child remains unjoined; Drop is only best effort.
    pub fn cancellation(&self) -> Result<onlyalpha_calculation_worker::Cancellation> {
        Ok(self.composition.worker.cancellation()?)
    }
    pub fn execute(mut self) -> Result<ChartResult> {
        let (window, history) = self.history.into_parts()?;
        let preview = match self.preview {
            Some(p) => match p.into_parts() {
                Ok(parts) => Some(parts),
                Err(market_product::Error::Source(
                    onlyalpha_integration_contract::source::SourceError::Stopped,
                )) => None,
                Err(error) => return Err(error.into()),
            },
            None => None,
        };
        history.check()?;
        let mut payload = self.calculation.evaluate(
            &mut self.composition,
            self.input_kind,
            &window,
            preview.as_ref().map(|p| &p.0),
            self.complete,
            self.end,
        )?;
        // Capacity remains owned until positive worker join.
        self.composition.worker.terminate()?;
        history.check()?;
        let mut preview = preview.map(|p| p.1);
        if let Some(fence) = &preview {
            match fence.check() {
                Ok(()) => (),
                Err(market_product::Error::Source(
                    onlyalpha_integration_contract::source::SourceError::Stopped,
                )) => {
                    payload["preview"] = Value::Null;
                    preview = None;
                }
                Err(error) => return Err(error.into()),
            }
        }
        Ok(ChartResult {
            payload,
            history,
            preview,
        })
    }
}
impl Calculation {
    fn evaluate(
        &self,
        composition: &mut Composition,
        input_kind: ChartInputKind,
        window: &Value,
        preview: Option<&Value>,
        complete: bool,
        end: Instant,
    ) -> Result<Value> {
        remaining(end)?;
        let definition = self.definition.to_record();
        let normalized = self.definition.semantic_payload();
        let mut series = vec![];
        let mut preview_output = Value::Null;
        if complete {
            let mut bars = window["bars"].as_array().ok_or(Error::Unavailable)?.clone();
            let closed_count = bars.len();
            if closed_count
                != window["requested_bar_count"]
                    .as_u64()
                    .ok_or(Error::Unavailable)? as usize
            {
                return Err(Error::Unavailable);
            }
            if let Some(p) = preview {
                bars.push(p["bar"].clone());
            }
            let mut columns = serde_json::Map::new();
            for (name, binding) in definition["input_bindings"]
                .as_object()
                .ok_or(Error::Unavailable)?
            {
                let field = match binding["source"].as_str() {
                    Some("bar.open") => "open",
                    Some("bar.high") => "high",
                    Some("bar.low") => "low",
                    Some("bar.close") => "close",
                    Some("bar.volume") => "volume",
                    Some("bar.start_ns") => "bar_start_ns",
                    _ => return Err(Error::Unavailable),
                };
                if !binding["node_fingerprint"].is_null() {
                    return Err(Error::Unavailable);
                }
                let values = bars
                    .iter()
                    .map(|bar| {
                        if field == "bar_start_ns" {
                            ns(&bar[field]).map(|v| json!(v))
                        } else {
                            Ok(bar[field].clone())
                        }
                    })
                    .collect::<Result<Vec<_>>>()?;
                columns.insert(name.clone(), json!(values));
            }
            let input = fp(
                &json!({"window":window,"preview":preview,"definition":definition,"inputs":columns}),
            )?;
            let mut call = self.base.clone();
            call["op"] = json!("EXECUTE");
            call["inputs"] = json!(columns);
            call["input_fingerprint"] = json!(input);
            let value = composition.worker.exchange_chart(call, remaining(end)?)?;
            execution_result(
                &value,
                &self.declaration,
                &composition.algorithm_artifact,
                &input,
                &self.definition,
                &self.capability,
                bars.len(),
            )?;
            for name in &self.selected {
                let points = (0..closed_count)
                    .map(|index| {
                        point(
                            &value["outputs"][name],
                            index,
                            &bars[index]["bar_start_ns"],
                            false,
                        )
                    })
                    .collect::<Result<Vec<_>>>()?;
                series.push(json!({"output_name":name,"points":points}));
            }
            if let Some(p) = preview {
                preview_output = json!({"source_kind":"PREVIEW_UNCLOSED","stream_id":p["stream_id"],"revision_fingerprint":p["revision_fingerprint"],"bar_start_ns":p["bar"]["bar_start_ns"],"bar_end_ns":p["bar"]["bar_end_ns"],"series":self.selected.iter().map(|name|Ok(json!({"output_name":name,"point":point(&value["outputs"][name],closed_count,&bars[closed_count]["bar_start_ns"],true)?}))).collect::<Result<Vec<_>>>()?});
            }
        }
        let mut calculation = self.capability.clone();
        let object = calculation.as_object_mut().ok_or(Error::Unavailable)?;
        for field in [
            "descriptor",
            "readiness_contract_version",
            "execution_shape",
            "output_members",
            "limits",
            "presentation",
            "capability_projection",
        ] {
            object.remove(field);
        }
        object.insert(
            "normalized_typed_parameters".into(),
            definition["parameters"].clone(),
        );
        object.insert(
            "definition_fingerprint".into(),
            json!(self.definition.fingerprint()),
        );
        object.insert("normalized_definition".into(), normalized);
        object.insert("numeric".into(), definition["numeric"].clone());
        object.insert("output_members".into(),json!(self.selected.iter().map(|name|{let spec=definition["outputs"].as_array().and_then(|a|a.iter().find(|p|p["name"]==*name)).ok_or(Error::Unavailable)?;let presentation=self.capability["presentation"]["series"].as_array().and_then(|a|a.iter().find(|p|p["output_name"]==*name)).ok_or(Error::Unavailable)?;Ok(json!({"name":name,"data_type":"DECIMAL","nullable":spec["nullable"],"unit":presentation["unit"]}))}).collect::<Result<Vec<_>>>()?));
        let input = input_metadata(window, input_kind)?;
        let payload = json!({"schema_version":2,"source_kind":"CHART_STUDY_TRANSIENT","authority":"DISPLAY_ONLY","publication_status":"NOT_A_RESEARCH_RESULT","source_selection":window["source_selection"],"instrument_id":window["instrument_id"],"bar_semantic":window["bar_semantic"],"input":input,"coverage":window["coverage"],"query_status":if complete{"DISPLAYABLE"}else{"INPUT_INCOMPLETE"},"calculation":calculation,"series":series,"preview":preview_output});
        if payload.to_string().len() > WORK {
            return Err(Error::Unavailable);
        }
        Ok(payload)
    }
}

fn input_metadata(window: &Value, kind: ChartInputKind) -> Result<Value> {
    if matches!(kind, ChartInputKind::Temporary) {
        if window["source_kind"] != "TEMPORARY_MARKET_DATA" {
            return Err(Error::Invalid);
        }
        for field in [
            "window_fingerprint",
            "calendar_fingerprint",
            "resolution_plan_fingerprint",
        ] {
            sha(&window[field])?;
        }
        return Ok(
            json!({"source_kind":"TEMPORARY_MARKET_DATA","anchor_kind":"BEFORE_TIME",
            "initialization":"FINITE_WINDOW_START","before_ns":window["requested_before_ns"],
            "target_bar_count":window["requested_bar_count"],"resolved_start_ns":window["resolved_start_ns"],
            "resolved_end_ns":window["resolved_end_ns"],"window_fingerprint":window["window_fingerprint"],
            "calendar_fingerprint":window["calendar_fingerprint"],"resolution_plan_fingerprint":window["resolution_plan_fingerprint"],
            "resolution_mode":window["resolution_mode"]}),
        );
    }
    let mut input = serde_json::Map::new();
    for field in [
        "requested_before_ns",
        "requested_bar_count",
        "resolved_start_ns",
        "resolved_end_ns",
        "revision_evidence",
        "history_projection_fingerprint",
        "resolution_mode",
        "resolution_plan_fingerprint",
        "derived_projection_fingerprint",
        "aggregation_semantics_version",
        "calendar_fingerprint",
        "resume_after_sequence",
        "resume_plan_fingerprint",
    ] {
        input.insert(
            match field {
                "requested_before_ns" => "before_ns",
                "requested_bar_count" => "target_bar_count",
                other => other,
            }
            .into(),
            window[field].clone(),
        );
    }
    input.insert("anchor_kind".into(), json!("BEFORE_TIME"));
    input.insert("initialization".into(), json!("FINITE_WINDOW_START"));
    Ok(Value::Object(input))
}

fn execution_result(
    value: &Value,
    declaration: &Value,
    artifact: &Value,
    input: &str,
    definition: &Definition,
    capability: &Value,
    count: usize,
) -> Result<()> {
    if value["type_declaration"] != *declaration
        || value["artifact_fingerprint"] != *artifact
        || value["input_fingerprint"] != input
        || value["definition"] != definition.to_record()
        || value["definition_fingerprint"] != definition.fingerprint()
        || value["implementation_fingerprint"] != capability["implementation_fingerprint"]
    {
        return Err(Error::Unavailable);
    }
    validate_outputs(&definition.to_record(), &value["outputs"], count)?;
    Ok(())
}
fn point(output: &Value, index: usize, time: &Value, preview: bool) -> Result<Value> {
    ns(time)?;
    Ok(
        json!({"time_ns":time,"value":output["values"][index],"readiness":output["states"][index],"reason":output["reasons"][index],"quality":if preview{"PREVIEW_UNCLOSED"}else{"CLOSED_COMPLETE"},"closed":!preview}),
    )
}
fn validate_outputs(definition: &Value, outputs: &Value, count: usize) -> Result<()> {
    let ports = definition["outputs"].as_array().ok_or(Error::Unavailable)?;
    let columns = outputs.as_object().ok_or(Error::Unavailable)?;
    if ports.len() != columns.len() {
        return Err(Error::Unavailable);
    }
    for port in ports {
        let name = text(&port["name"])?;
        let column = columns.get(name).ok_or(Error::Unavailable)?;
        exact(column, &["values", "states", "reasons"])?;
        let values = column["values"].as_array().ok_or(Error::Unavailable)?;
        let states = column["states"].as_array().ok_or(Error::Unavailable)?;
        let reasons = column["reasons"].as_array().ok_or(Error::Unavailable)?;
        if [values.len(), states.len(), reasons.len()] != [count; 3] {
            return Err(Error::Unavailable);
        }
        for ((value, state), reason) in values.iter().zip(states).zip(reasons) {
            let null = value.is_null();
            let nullable = port["nullable"].as_bool().ok_or(Error::Unavailable)?;
            if !null {
                let s = text(value)?;
                if port["data_type"] == "DECIMAL" {
                    let unsigned = s.strip_prefix('-').unwrap_or(s);
                    let Some((integer, fraction)) = unsigned.split_once('.') else {
                        return Err(Error::Unavailable);
                    };
                    if integer.is_empty()
                        || integer.len() > 26
                        || (!integer.bytes().all(|b| b.is_ascii_digit()))
                        || (integer.len() > 1 && integer.starts_with('0'))
                        || fraction.len() != 12
                        || !fraction.bytes().all(|b| b.is_ascii_digit())
                    {
                        return Err(Error::Unavailable);
                    }
                } else if port["data_type"] != "STRING" {
                    return Err(Error::Unavailable);
                }
            }
            let valid = match state.as_str() {
                Some("PARTIAL") => reason == "WARMUP_INCOMPLETE" && (!null || nullable),
                Some("READY") => {
                    if null {
                        nullable && reason == "VALUE_UNDEFINED"
                    } else {
                        reason == "NONE"
                    }
                }
                Some("UNAVAILABLE") => {
                    null && (reason == "INPUT_UNAVAILABLE" || reason == "DEPENDENCY_UNAVAILABLE")
                }
                _ => false,
            };
            if !valid {
                return Err(Error::Unavailable);
            }
        }
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    #[test]
    fn request_decimal_matches_the_current_transport_contract() {
        for value in ["0", "0.00", "1", "-1.25", "12.000000000001"] {
            assert!(super::request_decimal(value), "{value}")
        }
        for value in [
            "-0", "-0.00", "00", "1.", ".1", "1e2", "+1", "--1", "1.2.3", "NaN", "Infinity",
        ] {
            assert!(!super::request_decimal(value), "{value}")
        }
    }
    #[test]
    fn every_output_and_readiness_pair_is_checked_atomically() {
        let definition = serde_json::json!({"outputs":[{"name":"a","data_type":"DECIMAL","nullable":true},{"name":"b","data_type":"DECIMAL","nullable":false}]});
        for (value, state, reason, valid) in [
            (serde_json::json!("1.000000000000"), "READY", "NONE", true),
            (serde_json::Value::Null, "READY", "VALUE_UNDEFINED", true),
            (
                serde_json::Value::Null,
                "UNAVAILABLE",
                "INPUT_UNAVAILABLE",
                true,
            ),
            (
                serde_json::Value::Null,
                "PARTIAL",
                "WARMUP_INCOMPLETE",
                true,
            ),
            (serde_json::Value::Null, "READY", "NONE", false),
            (
                serde_json::json!("1.000000000000"),
                "UNAVAILABLE",
                "INPUT_UNAVAILABLE",
                false,
            ),
            (serde_json::json!("NaN"), "READY", "NONE", false),
            (serde_json::json!("1.0"), "READY", "NONE", false),
        ] {
            let mut outputs = serde_json::json!({"a":{"values":[value],"states":[state],"reasons":[reason]},"b":{"values":["2.000000000000"],"states":["READY"],"reasons":["NONE"]}});
            assert_eq!(
                super::validate_outputs(&definition, &outputs, 1).is_ok(),
                valid
            );
            outputs["b"]["reasons"] = serde_json::json!(["INPUT_UNAVAILABLE"]);
            assert!(super::validate_outputs(&definition, &outputs, 1).is_err());
        }
    }
    #[test]
    fn full_source_calendar_is_required_for_the_advertised_input_policy() {
        let mut calendar = serde_json::json!({"timezone":{"name":"UTC"},"holidays":[],"weekend_days":[],"special_schedules":[],"effective_from":null,"effective_to":null,"sessions":[{"opens_at":"00:00:00","closes_at":"00:00:00","session_type":"CONTINUOUS","belongs_to_trading_day_offset":0,"allows_market_data":true}]});
        assert!(super::utc_continuous_calendar(&calendar));
        calendar["timezone"]["name"] = serde_json::json!("Asia/Shanghai");
        assert!(!super::utc_continuous_calendar(&calendar));
        calendar["timezone"]["name"] = serde_json::json!("UTC");
        calendar["holidays"] = serde_json::json!(["2026-01-01"]);
        assert!(!super::utc_continuous_calendar(&calendar));
    }
}

#[cfg(test)]
mod admission_tests;

mod temporary;
pub use temporary::PreparedTemporaryBatch;
