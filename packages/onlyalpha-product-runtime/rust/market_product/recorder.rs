use super::*;
use crate::market_data_wal::Wal;
use base64::{Engine, engine::general_purpose::STANDARD};
use onlyalpha_domain::{base::OnlyDomainModel, market::OnlyBar};
use onlyalpha_integration_contract::source::{Observation, Recorder, SourceError};
use onlyalpha_market_data_construction::OnlyConstructionIdentity;
use serde_json::json;
/// Physical WAL ownership stays with the Host. One recorder binds a real capture
/// session, native plan and actual admitted Runtime binding before provider I/O.
enum WalAccess<'a> {
    Borrowed(&'a mut Wal),
    Owned(Wal),
}
impl WalAccess<'_> {
    fn get(&mut self) -> &mut Wal {
        match self {
            Self::Borrowed(wal) => wal,
            Self::Owned(wal) => wal,
        }
    }
}
pub(super) struct WalRecorder<'a> {
    wal: WalAccess<'a>,
    segment: String,
    base_segment: String,
    ordinal: Option<u64>,
    created_at: String,
    failed: bool,
    capture: String,
    scope: market_data::Scope,
    construction: OnlyConstructionIdentity,
    binding: String,
    version: String,
    implementation: String,
    provenance: &'static str,
    session: crate::source_access::Session,
    selection: crate::source_access::Selection,
    permission: crate::source_access::Permission,
    identity: onlyalpha_integration_contract::source::MarketIdentity,
    records: usize,
    last_receive: Option<i64>,
    clock: std::sync::Arc<dyn onlyalpha_integration_contract::source::Clock>,
}
impl<'a> WalRecorder<'a> {
    pub(super) fn open(
        wal: &'a mut Wal,
        resolved: &Resolved,
        session: crate::source_access::Session,
        scope: market_data::Scope,
        segment: &str,
        capture: &str,
        at: &str,
    ) -> Result<Self> {
        Self::build(
            WalAccess::Borrowed(wal),
            resolved,
            session,
            scope,
            segment,
            capture,
            at,
        )
    }
    pub(super) fn owned(
        wal: Wal,
        resolved: &Resolved,
        session: crate::source_access::Session,
        scope: market_data::Scope,
        segment: &str,
        capture: &str,
        at: &str,
    ) -> Result<Self> {
        Self::build(
            WalAccess::Owned(wal),
            resolved,
            session,
            scope,
            segment,
            capture,
            at,
        )
    }
    fn build(
        mut wal: WalAccess<'a>,
        resolved: &Resolved,
        session: crate::source_access::Session,
        scope: market_data::Scope,
        segment: &str,
        capture: &str,
        at: &str,
    ) -> Result<Self> {
        let realtime = matches!(&wal, WalAccess::Owned(_));
        let permission = if realtime {
            crate::source_access::Permission::RealtimePreview
        } else {
            crate::source_access::Permission::ClosedHistory
        };
        session.require_selection(&resolved.selection, permission)?;
        if capture.is_empty()
            || capture.len() > 48
            || scope.to_record()["source_id"] != resolved.identity().source_id
        {
            return Err(Error::Invalid);
        }
        let construction =
            OnlyConstructionIdentity::from_record(&scope.to_record()["bar_construction"])
                .map_err(|_| Error::Invalid)?;
        let rotating = matches!(&wal, WalAccess::Owned(_));
        let active = if rotating {
            format!("{segment}-{:016x}", 0)
        } else {
            segment.into()
        };
        crate::market_data_wal::id(&active).map_err(|_| Error::Invalid)?;
        let _: onlyalpha_domain::time::OnlyUtcDateTime = at.parse().map_err(|_| Error::Invalid)?;
        if !rotating {
            wal.get()
                .create_segment(&active, at)
                .map_err(|_| Error::Unavailable)?;
        }
        Ok(Self {
            wal,
            segment: active,
            base_segment: segment.into(),
            ordinal: rotating.then_some(0),
            created_at: at.into(),
            failed: false,
            capture: format!("native:{}:{}", resolved.implementation, capture),
            scope,
            construction,
            binding: resolved.binding.fingerprint().into(),
            version: resolved.data_version.clone(),
            implementation: resolved.implementation.clone(),
            provenance: if realtime {
                "REALTIME_STREAM"
            } else {
                "REST_BACKFILL"
            },
            session,
            selection: resolved.selection.clone(),
            permission,
            identity: resolved.identity().clone(),
            records: 0,
            last_receive: None,
            clock: std::sync::Arc::clone(&resolved.clock),
        })
    }
    pub(super) fn seal(&mut self, at: &str) -> Result<Option<Value>> {
        if self.records == 0 {
            return Ok(None);
        }
        self.wal
            .get()
            .seal(at)
            .map(|value| {
                self.records = 0;
                Some(value)
            })
            .map_err(|_| Error::Unavailable)
    }
    fn bundle(&self, o: Observation) -> Result<Value> {
        self.session
            .require_selection(&self.selection, self.permission)?;
        let s = self.scope.to_record();
        if o.identity != self.identity || o.identity.market != s["market"] {
            return Err(Error::Conflict);
        }
        let raw_hash = hash(&o.bytes);
        let raw_id = format!(
            "raw-event:{}",
            fp(
                &json!({"source_id":o.identity.source_id,"capture_session_id":self.capture,"stream":o.stream,"provider_event_type":o.event_type,"provider_event_id":o.provider_event_id,"provider_sequence":o.provider_sequence,"ts_event_ns":o.event_ns,"ts_receive_ns":o.receive_ns,"raw_sha256":raw_hash})
            )?
        );
        let mut facts = vec![];
        for bar in &o.bars {
            if !*bar.is_closed()
                || bar.instrument_id().to_string() != s["instrument_id"]
                || bar.bar_type().semantic() != self.construction.plan().target()
            {
                return Err(Error::Conflict);
            }
            let start = ns(*bar.bar_start())?;
            let end = ns(*bar.bar_end())?;
            if self.provenance != "REALTIME_STREAM"
                && (start < self.scope.start_ns() || end > self.scope.end_ns())
            {
                return Err(Error::Conflict);
            }
            let update = update(bar, &o.identity.source_id, &self.version)?;
            let update_id = update["update_id"].clone();
            facts.push(json!({"canonical_fact_id":update_id,"raw_event_id":raw_id,"source_id":o.identity.source_id,"segment_id":self.segment,"capture_session_id":self.capture,"data_kind":"BAR","instrument_id":bar.instrument_id().to_string(),"ts_event_ns":end,"ts_receive_ns":o.receive_ns,"ts_ingest_ns":o.receive_ns,"canonical_payload_hash":fp(&update)?,"canonical_payload":update,"normalizer_id":"binance.spot.native","normalizer_version":self.implementation,"quality_state":"VALID","provenance":self.provenance}));
        }
        Ok(
            json!({"schema_version":1,"evidence":{"raw_event_id":raw_id,"source_id":o.identity.source_id,"capture_session_id":self.capture,"provider":o.identity.provider,"venue":o.identity.venue,"market":o.identity.market,"stream":o.stream,"provider_event_type":o.event_type,"provider_event_id":o.provider_event_id,"provider_sequence":o.provider_sequence,"ts_event_ns":o.event_ns,"ts_receive_ns":o.receive_ns,"payload_codec":"application/json","provider_schema":"v1","payload_base64":STANDARD.encode(o.bytes),"raw_sha256":raw_hash,"provenance":self.provenance,"integration_binding_fingerprint":self.binding,"bar_construction":self.construction.to_record()},"canonical_facts":facts}),
        )
    }
}
impl Recorder for WalRecorder<'_> {
    fn record(&mut self, o: Observation) -> std::result::Result<(), SourceError> {
        if self.failed {
            return Err(SourceError::Evidence);
        }
        let received = o.receive_ns;
        let result = (|| {
            self.session
                .require_selection(&self.selection, self.permission)
                .map_err(|_| SourceError::Stopped)?;
            if let Some(ordinal) = self.ordinal {
                ordinal.checked_add(1).ok_or(SourceError::Evidence)?;
                self.segment = format!("{}-{ordinal:016x}", self.base_segment);
            }
            // Validate the whole atomic observation before creating its physical segment.
            let bundle = self.bundle(o).map_err(|_| SourceError::Evidence)?;
            if self.ordinal.is_some() {
                self.wal
                    .get()
                    .create_segment(&self.segment, &self.created_at)
                    .map_err(|_| SourceError::Evidence)?;
            }
            self.wal
                .get()
                .append(&bundle.to_string())
                .map_err(|_| SourceError::Evidence)?;
            self.records += 1;
            self.last_receive = Some(received);
            if let Some(ordinal) = self.ordinal {
                let at = time(self.clock.now_ns()?.max(received))
                    .map_err(|_| SourceError::Evidence)?
                    .to_string();
                self.seal(&at).map_err(|_| SourceError::Evidence)?;
                self.ordinal = Some(ordinal.checked_add(1).ok_or(SourceError::Evidence)?);
                self.created_at = at;
            }
            Ok(())
        })();
        if result.is_err() {
            self.failed = true;
        }
        result
    }
    fn finish(&mut self) -> std::result::Result<(), SourceError> {
        if self.failed {
            return Err(SourceError::Evidence);
        }
        if self.records > 0 {
            let at = time(
                self.clock
                    .now_ns()?
                    .max(self.last_receive.ok_or(SourceError::Evidence)?),
            )
            .map_err(|_| SourceError::Evidence)?
            .to_string();
            self.seal(&at).map_err(|_| SourceError::Evidence)?;
            self.records = 0;
        }
        Ok(())
    }
}
fn update(bar: &OnlyBar, source: &str, version: &str) -> Result<Value> {
    let id = format!(
        "market-fact:bar:{}",
        fp(
            &json!({"kind":"BAR","source":source,"instrument":bar.instrument_id().to_json().map_err(|_|Error::Invalid)?,"bar_type":bar.bar_type().to_json().map_err(|_|Error::Invalid)?,"bar_start":bar.bar_start().to_string(),"data_version":version})
        )?
    );
    let minutes: i64 = bar
        .bar_type()
        .semantic()
        .stride_minutes()
        .map_err(|_| Error::Invalid)?
        .to_string()
        .parse()
        .map_err(|_| Error::Invalid)?;
    let event = ns(*bar.ts_event())?;
    Ok(
        json!({"schema_version":3,"update_id":id,"runtime_id":"market-data-product","source_id":source,"source_sequence":ns(*bar.bar_start())?/(minutes*60_000_000_000),"data_version":version,"instrument_id":bar.instrument_id().to_string(),"data_type":"BAR","payload":{"kind":"BAR","value":bar.to_record()},"ts_event":event,"ts_init":event,"quality_flags":["VALID"],"metadata":[],"correlation_id":null,"sequence_semantics":"CONTIGUOUS","sequence_scope":{"source_id":source,"instrument_id":bar.instrument_id().to_json().map_err(|_|Error::Invalid)?,"data_type":"BAR","bar_type":bar.bar_type().to_record()}}),
    )
}
