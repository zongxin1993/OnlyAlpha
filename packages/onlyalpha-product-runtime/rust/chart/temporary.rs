//! Explicit volatile chart input. Never upgrades a window to Research evidence.
use super::*;
struct TemporaryRequest {
    source_reference: Value,
    page: String,
    window: WindowRequest,
    expected: String,
    calculation: Value,
}
fn parse(raw: &str, clock_ns: i64) -> Result<TemporaryRequest> {
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
            "source_kind",
            "source_reference",
            "page_id",
            "instrument_id",
            "bar_semantic",
            "window",
            "expected_window_fingerprint",
            "calculation",
        ],
    )?;
    if request["schema_version"] != 2
        || request["source_kind"] != "TEMPORARY_MARKET_DATA"
        || !crate::command::uuid4(text(&request["page_id"])?)
    {
        return Err(Error::Invalid);
    }
    let source = &request["source_reference"];
    exact(
        source,
        &[
            "integration_id",
            "integration_revision_fingerprint",
            "expected_type_id",
        ],
    )?;
    text(&source["integration_id"])?;
    text(&source["expected_type_id"])?;
    sha(&source["integration_revision_fingerprint"])?;
    let semantic =
        OnlyBarSemantic::from_record(&request["bar_semantic"]).map_err(|_| Error::Invalid)?;
    if request["bar_semantic"]["formation"]["kind"] != "FIXED_DURATION" {
        return Err(Error::Invalid);
    }
    let window = &request["window"];
    exact(window, &["anchor_kind", "before_ns", "target_bar_count"])?;
    let before = ns(&window["before_ns"])?;
    if window["anchor_kind"] != "BEFORE_TIME" || before == 0 || before > clock_ns {
        return Err(Error::Invalid);
    }
    let count = window["target_bar_count"]
        .as_u64()
        .filter(|count| (1..=2000).contains(count))
        .ok_or(Error::Invalid)? as usize;
    if !request["calculation"].is_object() {
        return Err(Error::Invalid);
    }
    Ok(TemporaryRequest {
        source_reference: source.clone(),
        page: text(&request["page_id"])?.into(),
        window: WindowRequest {
            instrument_id: text(&request["instrument_id"])?.into(),
            semantic,
            before_ns: Some(before),
            bar_count: count,
            clock_ns,
        },
        expected: sha(&request["expected_window_fingerprint"])?.into(),
        calculation: request["calculation"].clone(),
    })
}
impl ChartQuery {
    pub async fn prepare_temporary_before(
        &self,
        app: &Application,
        source: &Resolved,
        session: &Session,
        raw: &str,
        clock_ns: i64,
        deadline: Instant,
    ) -> Result<PreparedChart> {
        let request = parse(raw, clock_ns)?;
        let end = deadline.min(Instant::now() + Duration::from_secs(10));
        let history = self
            .temporary_input(app, source, session, &request, end)
            .await?;
        let (window, _) = history.parts()?;
        let complete = window["coverage"]["status"] == "COMPLETE";
        let (composition, calculation) = self.prepare_calculation(&request.calculation, end)?;
        history.parts()?;
        Ok(PreparedChart {
            input_kind: ChartInputKind::Temporary,
            composition,
            history,
            preview: None,
            calculation,
            complete,
            end,
        })
    }
    async fn temporary_input(
        &self,
        app: &Application,
        source: &Resolved,
        session: &Session,
        request: &TemporaryRequest,
        end: Instant,
    ) -> Result<Authorized<Value>> {
        session.require_selection(source.selection(), Permission::ClosedHistory)?;
        let reference = source.selection().reference();
        if request.source_reference["integration_id"] != reference.integration_id()
            || request.source_reference["integration_revision_fingerprint"] != reference.revision()
            || request.source_reference["expected_type_id"].as_str() != reference.expected_type_id()
        {
            return Err(Error::InputChanged);
        }
        remaining(end)?;
        let history = app
            .temporary_chart_window(
                source,
                session,
                &request.window,
                &request.page,
                &request.expected,
                end,
            )
            .await?;
        let (window, fence) = history.parts()?;
        let calendar = fence.calendar()?.to_record();
        if window["source_kind"] != "TEMPORARY_MARKET_DATA"
            || window["authority"] != "DISPLAY_ONLY"
            || window["publication_status"] != "NOT_A_RESEARCH_RESULT"
            || window["window_fingerprint"] != request.expected
            || window["resolved_end_ns"]
                != request
                    .window
                    .before_ns
                    .map(|n| json!(n.to_string()))
                    .unwrap_or(Value::Null)
            || fp(&calendar)? != sha(&window["calendar_fingerprint"])?
            || !utc_continuous_calendar(&calendar)
        {
            return Err(Error::InputChanged);
        }
        Ok(history)
    }
    pub async fn prepare_temporary_batch_before(
        &self,
        app: &Application,
        source: &Resolved,
        session: &Session,
        raw: &str,
        clock_ns: i64,
        deadline: Instant,
    ) -> Result<PreparedTemporaryBatch> {
        let (request, calculations) = parse_batch(raw, clock_ns)?;
        let end = deadline.min(Instant::now() + Duration::from_secs(10));
        let history = self
            .temporary_input(app, source, session, &request, end)
            .await?;
        let (mut composition, _) = self.compose(end)?;
        let mut admitted = Vec::with_capacity(calculations.len());
        for calculation in calculations {
            history.parts()?;
            match self.resolve_calculation(&calculation, &mut composition, end) {
                Ok(value) => admitted.push(Some(value)),
                // Only a proved per-item request rejection is locally scoped.
                Err(Error::Invalid) => admitted.push(None),
                Err(error) => return Err(error),
            }
        }
        history.parts()?;
        Ok(PreparedTemporaryBatch {
            composition,
            history,
            calculations: admitted,
            installation: Arc::clone(&self.installation),
            end,
        })
    }
}

fn parse_batch(raw: &str, clock_ns: i64) -> Result<(TemporaryRequest, Vec<Value>)> {
    if raw.len() > 65536 {
        return Err(Error::Invalid);
    }
    let canonical =
        onlyalpha_metadata_json::canonical_json(raw, WORK).map_err(|_| Error::Invalid)?;
    let mut value: Value = serde_json::from_str(&canonical).map_err(|_| Error::Invalid)?;
    exact(
        &value,
        &[
            "schema_version",
            "source_kind",
            "source_reference",
            "page_id",
            "instrument_id",
            "bar_semantic",
            "window",
            "expected_window_fingerprint",
            "calculations",
        ],
    )?;
    let calculations = value["calculations"]
        .as_array()
        .filter(|a| !a.is_empty() && a.len() <= 4)
        .ok_or(Error::Invalid)?
        .clone();
    let root = value.as_object_mut().ok_or(Error::Invalid)?;
    root.remove("calculations");
    root.insert("calculation".into(), json!({}));
    Ok((parse(&value.to_string(), clock_ns)?, calculations))
}

pub struct PreparedTemporaryBatch {
    composition: Composition,
    history: Authorized<Value>,
    calculations: Vec<Option<Calculation>>,
    installation: Arc<ChartInstallation>,
    end: Instant,
}
impl PreparedTemporaryBatch {
    pub fn cancellation(&self) -> Result<Cancellation> {
        Ok(self.composition.worker.cancellation()?)
    }
    pub fn execute(mut self) -> Result<ChartResult> {
        let (window, history) = self.history.into_parts()?;
        let complete = window["coverage"]["status"] == "COMPLETE";
        let mut results = Vec::with_capacity(self.calculations.len());
        for (index, calculation) in self.calculations.into_iter().enumerate() {
            remaining(self.end)?;
            history.check()?;
            let outcome = match calculation {
                None => {
                    json!({"status":"REJECTED", "request_index":index, "error":"CHART_STUDY_REQUEST_INVALID"})
                }
                Some(calculation) => match calculation.evaluate(
                    &mut self.composition,
                    ChartInputKind::Temporary,
                    &window,
                    None,
                    complete,
                    self.end,
                ) {
                    Ok(evaluation) => {
                        json!({"status":"EVALUATED", "request_index":index, "evaluation":evaluation})
                    }
                    Err(error) => return Err(error),
                },
            };
            history.check()?;
            results.push(outcome);
        }
        let payload = json!({"schema_version":2,"source_kind":"CHART_STUDY_TRANSIENT","authority":"DISPLAY_ONLY","publication_status":"NOT_A_RESEARCH_RESULT","window_fingerprint":window["window_fingerprint"],"results":results});
        if payload.to_string().len() > WORK {
            return Err(Error::Unavailable);
        }
        self.composition.worker.terminate()?;
        // A retained declaration never substitutes for current physical proof.
        self.installation.verify()?;
        remaining(self.end)?;
        history.check()?;
        Ok(ChartResult {
            payload,
            history,
            preview: None,
        })
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn batch_input_is_one_exact_bounded_window_and_never_raw_bars() {
        let mut value = request();
        value.as_object_mut().unwrap().remove("calculation");
        value["calculations"] = json!([{}, {}, {}, {}]);
        let clock = 20_i64 * 1440 * 60_000_000_000;
        let (common, items) = parse_batch(&value.to_string(), clock).unwrap();
        assert_eq!(items.len(), 4);
        assert_eq!(common.expected, "b".repeat(64));
        assert!(parse(&value.to_string(), clock).is_err());
        for count in [0, 5] {
            let mut bad = value.clone();
            bad["calculations"] = json!(vec![json!({}); count]);
            assert!(parse_batch(&bad.to_string(), clock).is_err());
        }
        for field in ["bars", "calculation", "runtime_generation", "results"] {
            let mut bad = value.clone();
            bad[field] = json!([]);
            assert!(parse_batch(&bad.to_string(), clock).is_err(), "{field}");
        }
        let mut bad = value.clone();
        bad["source_reference"]["integration_revision_fingerprint"] = json!("missing");
        assert!(parse_batch(&bad.to_string(), clock).is_err());
        bad = value;
        bad["window"]["target_bar_count"] = json!(2001);
        assert!(parse_batch(&bad.to_string(), clock).is_err());
    }
    fn request() -> Value {
        json!({"schema_version":2,"source_kind":"TEMPORARY_MARKET_DATA","page_id":"00000000-0000-4000-8000-000000000001",
            "source_reference":{"integration_id":"source","integration_revision_fingerprint":"a".repeat(64),"expected_type_id":"test.source"},
            "instrument_id":"TEST.TEST","bar_semantic":{"schema_version":3,"formation":{"schema_version":1,"kind":"FIXED_DURATION","window_minutes":7,"stride_minutes":7,"alignment":"SESSION_START"},"price_type":"LAST","adjustment_policy":"RAW"},
            "window":{"anchor_kind":"BEFORE_TIME","before_ns":((19_i64*1440+14)*60_000_000_000).to_string(),"target_bar_count":2000},
            "expected_window_fingerprint":"b".repeat(64),"calculation":{}})
    }
    #[test]
    fn temporary_chart_input_metadata_never_fabricates_sealed_history_or_research_evidence() {
        let window = json!({"source_kind":"TEMPORARY_MARKET_DATA","requested_before_ns":"6000000000000","requested_bar_count":2000,"resolved_start_ns":"1","resolved_end_ns":"6000000000000","window_fingerprint":"a".repeat(64),"calendar_fingerprint":"b".repeat(64),"resolution_plan_fingerprint":"c".repeat(64),"resolution_mode":"DERIVED"});
        let input = input_metadata(&window, ChartInputKind::Temporary).unwrap();
        assert_eq!(input["source_kind"], "TEMPORARY_MARKET_DATA");
        assert_eq!(input["window_fingerprint"], "a".repeat(64));
        assert_eq!(input["initialization"], "FINITE_WINDOW_START");
        for field in [
            "revision_evidence",
            "seal_id",
            "history_projection_fingerprint",
            "derived_projection_fingerprint",
            "research_result_id",
        ] {
            assert!(input.get(field).is_none(), "{field}");
        }
    }
    #[test]
    fn temporary_chart_admits_session_aligned_seven_minutes_and_rejects_other_input_kinds() {
        let good = request();
        let parsed = parse(&good.to_string(), 20_i64 * 1440 * 60_000_000_000).unwrap();
        assert_eq!(parsed.window.bar_count, 2000);
        assert_eq!(parsed.expected, "b".repeat(64));
        assert_eq!(
            parsed.window.before_ns,
            Some((19_i64 * 1440 + 14) * 60_000_000_000)
        );
        for field in [
            "include_unclosed_preview",
            "preview_stream_id",
            "expected_history_projection_fingerprint",
            "revision_evidence",
        ] {
            let mut bad = good.clone();
            bad[field] = json!(true);
            assert!(parse(&bad.to_string(), 20_i64 * 1440 * 60_000_000_000).is_err());
        }
        for (field, value) in [
            ("source_kind", json!("SEALED_HISTORY")),
            ("expected_window_fingerprint", json!("bad")),
            ("page_id", json!("latest")),
        ] {
            let mut bad = good.clone();
            bad[field] = value;
            assert!(parse(&bad.to_string(), 20_i64 * 1440 * 60_000_000_000).is_err());
        }
    }
}
