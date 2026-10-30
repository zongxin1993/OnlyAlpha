//! Immutable durable identities. JSON records preserve the existing wire schemas;
//! canonical identity projects dataclass fields, independently of wire markers.
use super::*;
use onlyalpha_domain::{
    base::OnlyDomainModel,
    market::{OnlyBarType, OnlyBarTypeInput},
    time::OnlyUtcDateTime,
};
use onlyalpha_market_data_construction::OnlyConstructionIdentity;
const SCOPE: &[&str] = &[
    "source_id",
    "market",
    "instrument_id",
    "data_kind",
    "start_ns",
    "end_ns",
    "data_version",
    "bar_type",
    "first_sequence",
    "last_sequence",
    "bar_construction",
];
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Scope {
    pub(super) record: Value,
}
impl Scope {
    pub fn from_json(raw: &str) -> Result<Self> {
        Self::from_record(&decode(raw)?)
    }
    pub fn from_record(input: &Value) -> Result<Self> {
        exact_keys(input, SCOPE)?;
        for key in [
            "source_id",
            "market",
            "instrument_id",
            "data_kind",
            "data_version",
        ] {
            text(&input[key])?;
        }
        if integer(&input["start_ns"])? >= integer(&input["end_ns"])? {
            return Err(Error::Invalid);
        }
        optional_text(&input["bar_type"])?;
        sequence(input)?;
        if !input["bar_construction"].is_null() {
            let identity = OnlyConstructionIdentity::from_record(&input["bar_construction"])
                .map_err(|_| Error::Unprovable)?;
            let instrument = text(&input["instrument_id"])?;
            let bar_type = OnlyBarType::new(OnlyBarTypeInput {
                instrument_id: instrument.parse().map_err(|_| Error::Invalid)?,
                semantic: identity.plan().target().clone(),
            })
            .map_err(|_| Error::Invalid)?;
            if input["data_kind"] != "BAR"
                || identity.plan().context().source() != text(&input["source_id"])?
                || identity.plan().context().instrument().to_string() != instrument
                || input["data_version"] != input["bar_construction"]["data_version"]
                || input["bar_type"] != fingerprint(&bar_type.to_record())?
            {
                return Err(Error::Unprovable);
            }
        }
        Ok(Self {
            record: input.clone(),
        })
    }
    pub fn to_record(&self) -> Value {
        self.record.clone()
    }
    pub fn start_ns(&self) -> i64 {
        self.record["start_ns"].as_i64().expect("validated")
    }
    pub fn end_ns(&self) -> i64 {
        self.record["end_ns"].as_i64().expect("validated")
    }
    pub fn kind(&self) -> &str {
        self.record["data_kind"].as_str().expect("validated")
    }
    pub fn family_matches(&self, other: &Scope) -> bool {
        SCOPE
            .iter()
            .filter(|k| !["start_ns", "end_ns", "first_sequence", "last_sequence"].contains(k))
            .all(|k| self.record[k] == other.record[k])
    }
    pub(super) fn canonical(&self) -> Value {
        let mut v = self.record.clone();
        v["bar_construction"] = projection(&v["bar_construction"]);
        v
    }
    pub fn with_range(&self, start: i64, end: i64) -> Result<Self> {
        let mut v = self.record.clone();
        v["start_ns"] = start.into();
        v["end_ns"] = end.into();
        Self::from_record(&v)
    }
    pub(super) fn contains(&self, fact: &Value) -> Result<bool> {
        let t = integer(&fact["ts_event_ns"])?;
        Ok(fact["source_id"] == self.record["source_id"]
            && fact["instrument_id"] == self.record["instrument_id"]
            && fact["data_kind"] == self.record["data_kind"]
            && if self.kind() == "BAR" {
                self.start_ns() < t && t <= self.end_ns()
            } else {
                self.start_ns() <= t && t <= self.end_ns()
            })
    }
}
fn sequence(v: &Value) -> Result<()> {
    match (v["first_sequence"].is_null(), v["last_sequence"].is_null()) {
        (true, true) => Ok(()),
        (false, false) if integer(&v["first_sequence"])? <= integer(&v["last_sequence"])? => Ok(()),
        _ => Err(Error::Invalid),
    }
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Segment {
    pub(super) record: Value,
}
impl Segment {
    pub fn from_record(input: &Value) -> Result<Self> {
        let mut v = input.clone();
        let o = v.as_object_mut().ok_or(Error::Invalid)?;
        for key in ["integration_binding_fingerprint", "bar_construction"] {
            o.entry(key).or_insert(Value::Null);
        }
        let mut fields = vec![
            "segment_id",
            "capture_session_id",
            "source_id",
            "market",
            "stream",
            "provider",
            "venue",
            "capture_mode",
            "provider_schema",
            "codec",
            "schema_version",
            "record_count",
            "raw_count",
            "canonical_count",
            "content_hash",
            "created_at",
            "sealed_at",
            "integration_binding_fingerprint",
        ];
        fields.extend_from_slice(&SCOPE[2..]); // instrument through construction; source and market above
        exact_keys(&v, &fields)?;
        for key in [
            "segment_id",
            "capture_session_id",
            "source_id",
            "market",
            "stream",
            "provider",
            "venue",
            "provider_schema",
            "codec",
        ] {
            text(&v[key])?;
        }
        provenance(&v["capture_mode"])?;
        if v["schema_version"] != 1
            || integer(&v["record_count"])? <= 0
            || v["raw_count"] != v["record_count"]
            || integer(&v["canonical_count"])? < 0
            || !crate::is_sha256_hex(text(&v["content_hash"])?)
        {
            return Err(Error::Invalid);
        }
        if let Some(s) = optional_text(&v["integration_binding_fingerprint"])?
            && !crate::is_sha256_hex(s)
        {
            return Err(Error::Invalid);
        }
        for key in ["created_at", "sealed_at"] {
            v[key] = utc(text(&v[key])?)?.1.into();
        }
        if utc(text(&v["created_at"])?)?.0 > utc(text(&v["sealed_at"])?)?.0 {
            return Err(Error::Invalid);
        }
        if !v["bar_construction"].is_null() {
            let identity = OnlyConstructionIdentity::from_record(&v["bar_construction"])
                .map_err(|_| Error::Unprovable)?;
            if !identity.plan().recipe().is_native()
                || identity.plan().context().source() != text(&v["source_id"])?
            {
                return Err(Error::Unprovable);
            }
        }
        let scope_fields = [
            "instrument_id",
            "data_kind",
            "start_ns",
            "end_ns",
            "data_version",
        ];
        if scope_fields.iter().all(|k| !v[k].is_null()) {
            Self::scope_record(&v)?;
        } else if integer(&v["canonical_count"])? != 0
            || scope_fields.iter().any(|k| !v[k].is_null())
            || ["bar_type", "first_sequence", "last_sequence"]
                .iter()
                .any(|k| !v[k].is_null())
        {
            return Err(Error::Unprovable);
        }
        Ok(Self { record: v })
    }
    fn scope_record(v: &Value) -> Result<Scope> {
        let mut s = json!({});
        for k in SCOPE {
            s[k] = v[k].clone();
        }
        Scope::from_record(&s)
    }
    pub fn recovery_scope(&self) -> Result<Scope> {
        Self::scope_record(&self.record)
    }
    pub fn id(&self) -> &str {
        self.record["segment_id"].as_str().expect("validated")
    }
    pub fn content_hash(&self) -> &str {
        self.record["content_hash"].as_str().expect("validated")
    }
    pub fn to_record(&self) -> Value {
        self.record.clone()
    }
    pub fn metadata_fingerprint(&self) -> Result<String> {
        let mut v = self.record.clone();
        v["bar_construction"] = projection(&v["bar_construction"]);
        fingerprint(&v)
    }
}
/// Only the physical writer can create this expected proof from retained WAL.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct PhysicalProof {
    pub(super) record: Value,
}
impl PhysicalProof {
    pub fn to_record(&self) -> Value {
        self.record.clone()
    }
    pub(super) fn build(segment: &Segment, mut partitions: Vec<Value>) -> Result<Self> {
        partitions.sort_by_key(|v| v["table"].as_str().unwrap_or_default().to_owned());
        let body = json!([
            1,
            segment.id(),
            segment.content_hash(),
            segment.metadata_fingerprint()?,
            segment.record["raw_count"],
            segment.record["canonical_count"],
            partitions
        ]);
        let result = Self {
            record: json!({"schema_version":1,"segment_id":segment.id(),"segment_content_hash":segment.content_hash(),"segment_metadata_fingerprint":segment.metadata_fingerprint()?,"raw_count":segment.record["raw_count"],"canonical_count":segment.record["canonical_count"],"partitions":body[6],"fingerprint":fingerprint(&body)?}),
        };
        result.validate(segment)?;
        Ok(result)
    }
    pub(super) fn validate(&self, segment: &Segment) -> Result<()> {
        let v = &self.record;
        exact_keys(
            v,
            &[
                "schema_version",
                "segment_id",
                "segment_content_hash",
                "segment_metadata_fingerprint",
                "raw_count",
                "canonical_count",
                "partitions",
                "fingerprint",
            ],
        )?;
        let p = v["partitions"].as_array().ok_or(Error::Unprovable)?;
        let mut tables = std::collections::BTreeSet::new();
        let mut raw = 0i64;
        let mut canonical = 0i64;
        for part in p {
            exact_keys(part, &["table", "row_count", "row_set_digest"])?;
            let t = text(&part["table"])?;
            if !TABLES.contains(&t)
                || !tables.insert(t)
                || !crate::is_sha256_hex(text(&part["row_set_digest"])?)
            {
                return Err(Error::Unprovable);
            }
            let n = integer(&part["row_count"])?;
            if n < 0 {
                return Err(Error::Unprovable);
            }
            if t == TABLES[0] {
                raw = n;
            } else {
                canonical = canonical.checked_add(n).ok_or(Error::Unprovable)?;
            }
        }
        let mut ordered = p.clone();
        ordered.sort_by_key(|v| v["table"].as_str().unwrap_or_default().to_owned());
        if p.len() != 4
            || *p != ordered
            || raw != integer(&segment.record["raw_count"])?
            || canonical != integer(&segment.record["canonical_count"])?
            || v["schema_version"] != 1
            || v["segment_id"] != segment.id()
            || v["segment_content_hash"] != segment.content_hash()
            || v["segment_metadata_fingerprint"] != segment.metadata_fingerprint()?
            || v["raw_count"] != segment.record["raw_count"]
            || v["canonical_count"] != segment.record["canonical_count"]
            || v["fingerprint"]
                != fingerprint(&json!([
                    1,
                    segment.id(),
                    segment.content_hash(),
                    segment.metadata_fingerprint()?,
                    v["raw_count"],
                    v["canonical_count"],
                    p
                ]))?
        {
            return Err(Error::Unprovable);
        }
        Ok(())
    }
}
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum CoverageStatus {
    Complete,
    Incomplete,
    Unprovable,
}
impl CoverageStatus {
    pub fn as_str(self) -> &'static str {
        match self {
            Self::Complete => "COMPLETE",
            Self::Incomplete => "INCOMPLETE",
            Self::Unprovable => "UNPROVABLE",
        }
    }
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Manifest {
    pub(super) record: Value,
    pub(super) scope: Scope,
}
impl Manifest {
    pub fn status(&self) -> CoverageStatus {
        match self.record["coverage_status"].as_str() {
            Some("COMPLETE") => CoverageStatus::Complete,
            Some("INCOMPLETE") => CoverageStatus::Incomplete,
            _ => CoverageStatus::Unprovable,
        }
    }
    pub fn to_record(&self) -> Value {
        self.record.clone()
    }
    pub fn id(&self) -> &str {
        self.record["manifest_id"].as_str().expect("validated")
    }
    pub(super) fn build(
        scope: Scope,
        refs: Value,
        status: CoverageStatus,
        proof: Value,
        issues: Value,
        gaps: Value,
    ) -> Result<Self> {
        let fp = fingerprint(
            &json!({"scope":scope.canonical(),"segments":refs,"coverage_status":status.as_str(),"proof":proof,"issues":issues,"gaps":gaps}),
        )?;
        Ok(Self {
            record: json!({"manifest_id":format!("manifest:{fp}"),"scope":scope.record,"segment_refs":refs,"coverage_status":status.as_str(),"proof":proof,"issues":issues,"gaps":gaps,"fingerprint":fp}),
            scope,
        })
    }
    pub(super) fn read(v: Value) -> Result<Self> {
        exact_keys(
            &v,
            &[
                "manifest_id",
                "scope",
                "segment_refs",
                "coverage_status",
                "proof",
                "issues",
                "gaps",
                "fingerprint",
            ],
        )?;
        let scope = Scope::from_record(&v["scope"])?;
        refs(&v["segment_refs"])?;
        strings(&v["proof"])?;
        strings(&v["issues"])?;
        let status = match text(&v["coverage_status"])? {
            "COMPLETE" => CoverageStatus::Complete,
            "INCOMPLETE" => CoverageStatus::Incomplete,
            "UNPROVABLE" => CoverageStatus::Unprovable,
            _ => return Err(Error::Unprovable),
        };
        for gap in v["gaps"].as_array().ok_or(Error::Unprovable)? {
            let keys = if scope.kind() == "TRADE" {
                ["first_sequence", "last_sequence"]
            } else {
                ["start_ns", "end_ns"]
            };
            exact_keys(gap, &keys)?;
            if integer(&gap[keys[0]])? > integer(&gap[keys[1]])?
                || scope.kind() != "TRADE" && gap[keys[0]] == gap[keys[1]]
            {
                return Err(Error::Unprovable);
            }
        }
        let rebuilt = Self::build(
            scope,
            v["segment_refs"].clone(),
            status,
            v["proof"].clone(),
            v["issues"].clone(),
            v["gaps"].clone(),
        )?;
        if rebuilt.record != v {
            return Err(Error::Unprovable);
        }
        Ok(rebuilt)
    }
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct SealedRevision {
    pub(super) revision: Value,
    pub(super) seal: Value,
    pub(super) manifest: Manifest,
}
impl SealedRevision {
    pub fn revision(&self) -> Value {
        self.revision.clone()
    }
    pub fn seal(&self) -> Value {
        self.seal.clone()
    }
    pub fn manifest(&self) -> &Manifest {
        &self.manifest
    }
    pub fn id(&self) -> &str {
        self.revision["revision_id"].as_str().expect("validated")
    }
    pub(super) fn build(
        manifest: Manifest,
        normalizers: Value,
        parent: Value,
        reason: Value,
        time: &str,
    ) -> Result<Self> {
        if manifest.status() != CoverageStatus::Complete
            || !array(&manifest.record["issues"])?.is_empty()
            || !array(&manifest.record["gaps"])?.is_empty()
        {
            return Err(Error::Unprovable);
        }
        let ordered = pairs(&normalizers)?;
        if ordered.windows(2).any(|p| p[0] > p[1]) {
            return Err(Error::Unprovable);
        }
        optional_text(&parent)?;
        text(&reason)?;
        let time = utc(time)?.1;
        let fp = fingerprint(
            &json!({"scope":manifest.scope.canonical(),"manifest":manifest.record["fingerprint"],"segments":manifest.record["segment_refs"],"normalizers":normalizers,"parent":parent,"reason":reason}),
        )?;
        let revision = json!({"revision_id":format!("market-data-revision:{fp}"),"scope":manifest.scope.record,"manifest_id":manifest.id(),"segment_refs":manifest.record["segment_refs"],"normalizers":normalizers,"parent_revision_id":parent,"creation_reason":reason,"fingerprint":fp});
        let mut checks = vec![
            "SEGMENT_HASH_VERIFIED",
            "SCHEMA_COMPATIBLE",
            "CANONICAL_IDENTITY_UNIQUE",
            "REQUESTED_SCOPE_VERIFIED",
            "COVERAGE_COMPLETE",
            "NO_UNRESOLVED_CORRUPTION",
        ];
        if manifest.scope.kind() == "BAR" {
            checks.push("BAR_TEMPORAL_GRID_VERIFIED");
        }
        let seal_fp = fingerprint(
            &json!({"revision":fp,"manifest":manifest.record["fingerprint"],"checks":checks}),
        )?;
        let seal = json!({"seal_id":format!("seal:{seal_fp}"),"revision_id":revision["revision_id"],"revision_fingerprint":fp,"checks":checks,"sealed_at":time});
        Ok(Self {
            revision,
            seal,
            manifest,
        })
    }
    pub(super) fn read(revision: Value, seal: Value, manifest: Manifest) -> Result<Self> {
        exact_keys(
            &revision,
            &[
                "revision_id",
                "scope",
                "manifest_id",
                "segment_refs",
                "normalizers",
                "parent_revision_id",
                "creation_reason",
                "fingerprint",
            ],
        )?;
        exact_keys(
            &seal,
            &[
                "seal_id",
                "revision_id",
                "revision_fingerprint",
                "checks",
                "sealed_at",
            ],
        )?;
        let rebuilt = Self::build(
            manifest,
            revision["normalizers"].clone(),
            revision["parent_revision_id"].clone(),
            revision["creation_reason"].clone(),
            text(&seal["sealed_at"])?,
        )?;
        let mut seal = seal;
        seal["sealed_at"] = utc(text(&seal["sealed_at"])?)?.1.into();
        if rebuilt.revision != revision || rebuilt.seal != seal {
            return Err(Error::Unprovable);
        }
        Ok(rebuilt)
    }
}
pub(super) fn refs(v: &Value) -> Result<Vec<(String, String)>> {
    let result = pairs(v)?;
    let mut ids = std::collections::BTreeSet::new();
    if result.windows(2).any(|p| p[0] >= p[1])
        || result
            .iter()
            .any(|(id, h)| !ids.insert(id) || !crate::is_sha256_hex(h))
    {
        return Err(Error::Unprovable);
    }
    Ok(result)
}
pub(super) fn pairs(v: &Value) -> Result<Vec<(String, String)>> {
    array(v)?
        .iter()
        .map(|p| {
            let a = array(p)?;
            if a.len() != 2 {
                return Err(Error::Unprovable);
            }
            Ok((text(&a[0])?.into(), text(&a[1])?.into()))
        })
        .collect()
}
pub(super) fn strings(v: &Value) -> Result<Vec<&str>> {
    array(v)?.iter().map(text).collect()
}
pub(super) fn projection(v: &Value) -> Value {
    match v {
        Value::Object(o) => Value::Object(
            o.iter()
                .filter(|(k, _)| k.as_str() != "schema_version")
                .map(|(k, v)| (k.clone(), projection(v)))
                .collect(),
        ),
        Value::Array(a) => Value::Array(a.iter().map(projection).collect()),
        _ => v.clone(),
    }
}
pub(super) fn utc(s: &str) -> Result<(OnlyUtcDateTime, String)> {
    let t: OnlyUtcDateTime = s.parse().map_err(|_| Error::Invalid)?;
    let formatted = t.to_string();
    Ok((
        t,
        format!(
            "{}+00:00",
            formatted.strip_suffix('Z').ok_or(Error::Invalid)?
        ),
    ))
}
pub(super) fn provenance(v: &Value) -> Result<()> {
    if matches!(
        text(v)?,
        "REALTIME_STREAM" | "REST_BACKFILL" | "REPAIR" | "REPLAY"
    ) {
        Ok(())
    } else {
        Err(Error::Invalid)
    }
}
/// Source facts and retained proof captured only by the owning exact physical
/// reader. Portable proof records supplied by a caller cannot construct this.
#[derive(Debug)]
pub struct SealedInput {
    pub(super) revision: SealedRevision,
    pub(super) evidence: Value,
    pub(super) segments: Value,
    pub(super) facts: Vec<Value>,
}
impl SealedInput {
    pub fn revision(&self) -> &SealedRevision {
        &self.revision
    }
    pub fn evidence(&self) -> &Value {
        &self.evidence
    }
    pub fn segments(&self) -> &Value {
        &self.segments
    }
    pub fn facts(&self) -> &[Value] {
        &self.facts
    }
}

/// Validate retained capture metadata and physical receipts at their original owner.
/// This proves historical record consistency, not current source availability or a new read grant.
pub(crate) fn validate_retained_input(evidence: &Value, segments: &Value) -> Result<()> {
    exact_keys(
        evidence,
        &["revision", "manifest", "seal", "physical_proofs"],
    )?;
    let manifest = Manifest::read(evidence["manifest"].clone())?;
    let revision = SealedRevision::read(
        evidence["revision"].clone(),
        evidence["seal"].clone(),
        manifest,
    )?;
    let references = refs(&revision.revision["segment_refs"])?;
    let segments = array(segments)?;
    let proofs = array(&evidence["physical_proofs"])?;
    if references.len() != segments.len() || references.len() != proofs.len() {
        return Err(Error::Unprovable);
    }
    for ((reference, value), proof) in references.iter().zip(segments).zip(proofs) {
        let segment = Segment::from_record(value)?;
        if segment.id() != reference.0
            || segment.content_hash() != reference.1
            || !segment
                .recovery_scope()?
                .family_matches(&revision.manifest.scope)
        {
            return Err(Error::Unprovable);
        }
        PhysicalProof {
            record: proof.clone(),
        }
        .validate(&segment)?;
    }
    Ok(())
}
