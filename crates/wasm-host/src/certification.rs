//! Automatic dual-kernel admission certification for L3 WASM extended operators.
//!
//! Before any WASM extended operator can enter READY state, the host runs the same
//! certification suite required for built-in L1 operators (ADR 0152 §2.6):
//! 1. Contract metadata & `DECIMAL28_HALF_EVEN_Q12_V1` policy verification
//! 2. `VectorKernel == EventKernel` exact pointwise equivalence (zero tolerance)
//! 3. Multi-prefix causality verification (rejects any future look-ahead)
//! 4. Warmup & null/empty boundary handling (plus non-trivial post-warmup output check)
//! 5. Deterministic snapshot capture, dirty-state overwrite restore, corrupt-snapshot Fail-Closed
//!    rejection, and multi-step post-warmup suffix equivalence
//! 6. Cross-instance determinism for BOTH `VectorKernel` and `EventKernel` (outputs & exact fuel)
//! 7. Independent golden test vectors with at least one verified numeric result
//! 8. Strict cumulative certification fuel budget (`ResourceBudget::max_certification_fuel`)

use crate::contract::{
    Error, ReadyCertificate, Result, digest_hex, format_host_decimal,
    validate_canonical_parameters, validate_non_empty_id,
};
use crate::operator_plugin::{UnverifiedExtendedOperator, WasmExtendedOperator};
use onlyalpha_operators::algebra::Decimal;
use sha2::{Digest, Sha256};
use std::collections::{BTreeMap, BTreeSet};

/// Independent numeric golden vector verified during extended-operator admission.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct GoldenCase {
    pub name: String,
    pub columns: Vec<Vec<Option<Decimal>>>,
    pub expected: Vec<Option<Decimal>>,
}

impl GoldenCase {
    fn update_digest(&self, digest: &mut Sha256) -> Result<()> {
        digest.update((self.name.len() as u64).to_be_bytes());
        digest.update(self.name.as_bytes());
        digest.update((self.columns.len() as u64).to_be_bytes());
        for series in self.columns.iter().chain(std::iter::once(&self.expected)) {
            digest.update((series.len() as u64).to_be_bytes());
            for cell in series {
                match cell {
                    Some(value) => {
                        let decimal = format_host_decimal(value, "golden cell")?;
                        digest.update([1]);
                        digest.update((decimal.len() as u64).to_be_bytes());
                        digest.update(decimal.as_bytes());
                    }
                    None => digest.update([0]),
                }
            }
        }
        Ok(())
    }
}

/// Admission certification request for one L3 WASM extended operator.
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct CertificationRequest {
    pub plugin_id: String,
    pub canonical_parameters: BTreeMap<String, String>,
    pub golden_cases: Vec<GoldenCase>,
}

struct CertificationFuelBudget {
    total_limit: u64,
    remaining: u64,
}

impl CertificationFuelBudget {
    fn new(total_limit: u64) -> Self {
        Self {
            total_limit,
            remaining: total_limit,
        }
    }

    fn next_call_limit(&self, stage: &'static str) -> Result<u64> {
        if self.remaining == 0 {
            return Err(cert_fail(
                stage,
                format!(
                    "certification exhausted cumulative fuel budget {}",
                    self.total_limit
                ),
            ));
        }
        Ok(self.remaining)
    }

    fn charge(&mut self, consumed: u64, stage: &'static str) -> Result<()> {
        if consumed > self.remaining {
            self.remaining = 0;
            return Err(cert_fail(
                stage,
                format!(
                    "certification exceeded cumulative fuel budget {}",
                    self.total_limit
                ),
            ));
        }
        self.remaining -= consumed;
        Ok(())
    }
}

pub(crate) fn certify_extended_operator(
    unverified: UnverifiedExtendedOperator,
    request: CertificationRequest,
    metadata_fuel: u64,
) -> Result<WasmExtendedOperator> {
    validate_non_empty_id(&request.plugin_id, "plugin_id")?;
    validate_canonical_parameters(&request.canonical_parameters)?;

    let arity = unverified.metadata().input_arity as usize;
    let warmup = unverified.metadata().warmup as usize;
    let params = &request.canonical_parameters;
    let budget = unverified.budget();
    let mut cert_fuel = CertificationFuelBudget::new(budget.max_certification_fuel);
    cert_fuel.charge(metadata_fuel, "metadata")?;
    if request.golden_cases.is_empty() {
        return Err(cert_fail(
            "golden",
            "an independent numeric golden case is required".into(),
        ));
    }

    // Stage 1: Deterministic standard certification suites scaled to operator arity & warmup.
    let suites = build_standard_suites(arity, warmup);

    // Stage 2: Empty input and all-null boundary handling (including warmup null invariant).
    verify_empty_and_all_null(&unverified, arity, warmup, params, &mut cert_fuel)?;

    // Stage 3-6: Pointwise equivalence, causality, warmup/nulls, snapshot capture/restore, determinism.
    let mut corrupt_snapshot_checked = false;
    for (suite_name, columns) in &suites {
        let len = columns.first().map_or(0, Vec::len);

        // Cross-instance determinism: run vector evaluation twice on independent fresh stores.
        let limit1 = cert_fuel.next_call_limit("vector_eval")?;
        let first_vec = unverified
            .evaluate_vector_with_fuel(columns, params, limit1)
            .map_err(|err| cert_fail("vector_eval", format!("{suite_name}: {err}")))?;
        cert_fuel.charge(first_vec.fuel_consumed, "vector_eval")?;

        let limit2 = cert_fuel.next_call_limit("determinism")?;
        let second_vec = unverified
            .evaluate_vector_with_fuel(columns, params, limit2)
            .map_err(|err| cert_fail("determinism", format!("{suite_name}: {err}")))?;
        cert_fuel.charge(second_vec.fuel_consumed, "determinism")?;

        if first_vec.value != second_vec.value {
            return Err(cert_fail(
                "determinism",
                format!("{suite_name}: repeated eval_vector produced different outputs"),
            ));
        }
        if first_vec.fuel_consumed != second_vec.fuel_consumed {
            return Err(cert_fail(
                "determinism",
                format!(
                    "{suite_name}: repeated eval_vector consumed different fuel ({} vs {})",
                    first_vec.fuel_consumed, second_vec.fuel_consumed
                ),
            ));
        }

        verify_warmup(suite_name, warmup, &first_vec.value)?;

        // Non-triviality check on clean non-null series: a valid operator must emit at least
        // one non-null value once warmup is satisfied, rejecting always-None no-op stubs.
        if *suite_name == "clean_series"
            && len >= warmup
            && !first_vec.value[warmup - 1..].iter().any(Option::is_some)
        {
            return Err(cert_fail(
                "warmup",
                format!(
                    "{suite_name}: operator produced all-None outputs after warmup {warmup} on clean non-null inputs"
                ),
            ));
        }

        // Pointwise Vector == Event equivalence (zero tolerance).
        let event_out =
            run_event_series(&unverified, columns, params, &mut cert_fuel, "event_eval")
                .map_err(|err| cert_fail("event_eval", format!("{suite_name}: {err}")))?;
        if first_vec.value != event_out {
            return Err(cert_fail(
                "vector_event_equivalence",
                format!(
                    "{suite_name}: vector output {:?} != event output {:?}",
                    first_vec.value, event_out
                ),
            ));
        }

        // Multi-prefix causality: prefix output must equal prefix of full output.
        verify_causality(
            &unverified,
            suite_name,
            columns,
            warmup,
            params,
            &first_vec.value,
            &mut cert_fuel,
        )?;

        // Snapshot capture/restore determinism (including EventKernel fuel determinism,
        // multi-step post-warmup suffix, dirty-state overwrite, and corrupt-snapshot rejection).
        let check_corrupt = !corrupt_snapshot_checked && *suite_name == "clean_series";
        verify_snapshot_restore(
            &unverified,
            suite_name,
            columns,
            warmup,
            params,
            &first_vec.value,
            check_corrupt,
            &mut cert_fuel,
        )?;
        if check_corrupt {
            corrupt_snapshot_checked = true;
        }
    }

    // Record only verified cases, preserving their declared order and column boundaries.
    let mut evidence = Sha256::new();
    let mut verified_numeric = false;
    for golden in &request.golden_cases {
        if golden.name.trim().is_empty() || golden.name.len() > 256 {
            return Err(Error::InvalidHostInput(
                "golden case name must be non-empty and <= 256 bytes".into(),
            ));
        }
        verify_warmup(&golden.name, warmup, &golden.expected)?;
        let limit = cert_fuel.next_call_limit("golden")?;
        let vec_out = unverified
            .evaluate_vector_with_fuel(&golden.columns, params, limit)
            .map_err(|err| cert_fail("golden", format!("{}: {err}", golden.name)))?;
        cert_fuel.charge(vec_out.fuel_consumed, "golden")?;
        if vec_out.value != golden.expected {
            return Err(cert_fail(
                "golden",
                format!(
                    "{}: vector output differs from the independent expected values",
                    golden.name
                ),
            ));
        }
        let evt_out = run_event_series(
            &unverified,
            &golden.columns,
            params,
            &mut cert_fuel,
            "golden_event",
        )
        .map_err(|err| cert_fail("golden_event", format!("{}: {err}", golden.name)))?;
        if evt_out != golden.expected {
            return Err(cert_fail(
                "golden_event",
                format!(
                    "{}: event output {:?} != golden {:?}",
                    golden.name, evt_out, golden.expected
                ),
            ));
        }
        if !golden.expected.is_empty() {
            verify_causality(
                &unverified,
                &golden.name,
                &golden.columns,
                warmup,
                params,
                &golden.expected,
                &mut cert_fuel,
            )?;
            verify_snapshot_restore(
                &unverified,
                &golden.name,
                &golden.columns,
                warmup,
                params,
                &golden.expected,
                false,
                &mut cert_fuel,
            )?;
        }
        verified_numeric |= golden.expected.iter().any(Option::is_some);
        golden.update_digest(&mut evidence)?;
    }
    if !verified_numeric {
        return Err(cert_fail(
            "golden",
            "independent golden cases must verify at least one numeric result".into(),
        ));
    }

    let certificate = ReadyCertificate::issue(
        request.plugin_id,
        unverified.metadata(),
        unverified.artifact_sha256().to_owned(),
        request.canonical_parameters.clone(),
        suites.len() + 2,
        request.golden_cases.len(),
        digest_hex(&evidence.finalize()),
    );

    Ok(unverified.into_certified(request.canonical_parameters, certificate))
}

fn verify_warmup(suite_name: &str, warmup: usize, values: &[Option<Decimal>]) -> Result<()> {
    if let Some(index) = values
        .iter()
        .take(warmup.saturating_sub(1))
        .position(Option::is_some)
    {
        return Err(cert_fail(
            "warmup",
            format!(
                "{suite_name}: index {index} has a non-null value before declared warmup {warmup}"
            ),
        ));
    }
    Ok(())
}

fn verify_causality(
    unverified: &UnverifiedExtendedOperator,
    suite_name: &str,
    columns: &[Vec<Option<Decimal>>],
    warmup: usize,
    params: &BTreeMap<String, String>,
    expected_full: &[Option<Decimal>],
    cert_fuel: &mut CertificationFuelBudget,
) -> Result<()> {
    let len = expected_full.len();
    for prefix_len in select_causality_prefixes(len, warmup) {
        let prefix_cols: Vec<Vec<Option<Decimal>>> = columns
            .iter()
            .map(|col| col[..prefix_len].to_vec())
            .collect();
        let limit = cert_fuel.next_call_limit("causality")?;
        let prefix_out = unverified
            .evaluate_vector_with_fuel(&prefix_cols, params, limit)
            .map_err(|err| {
                cert_fail("causality", format!("{suite_name}[..{prefix_len}]: {err}"))
            })?;
        cert_fuel.charge(prefix_out.fuel_consumed, "causality")?;
        if prefix_out.value != expected_full[..prefix_len] {
            return Err(cert_fail(
                "causality",
                format!(
                    "{suite_name}: look-ahead detected at prefix length {prefix_len}: {:?} != {:?}",
                    prefix_out.value,
                    &expected_full[..prefix_len]
                ),
            ));
        }
    }
    Ok(())
}

fn verify_empty_and_all_null(
    unverified: &UnverifiedExtendedOperator,
    arity: usize,
    warmup: usize,
    params: &BTreeMap<String, String>,
    cert_fuel: &mut CertificationFuelBudget,
) -> Result<()> {
    let empty_cols = vec![Vec::new(); arity];
    let empty_limit = cert_fuel.next_call_limit("empty_boundary")?;
    let empty_out = unverified
        .evaluate_vector_with_fuel(&empty_cols, params, empty_limit)
        .map_err(|err| cert_fail("empty_boundary", err.to_string()))?;
    cert_fuel.charge(empty_out.fuel_consumed, "empty_boundary")?;
    if !empty_out.value.is_empty() {
        return Err(cert_fail(
            "empty_boundary",
            "empty input produced non-empty output".into(),
        ));
    }

    let null_len = warmup.saturating_add(2).max(4);
    let null_cols = vec![vec![None; null_len]; arity];
    let null_limit = cert_fuel.next_call_limit("all_null_boundary")?;
    let null_vec = unverified
        .evaluate_vector_with_fuel(&null_cols, params, null_limit)
        .map_err(|err| cert_fail("all_null_boundary", err.to_string()))?;
    cert_fuel.charge(null_vec.fuel_consumed, "all_null_boundary")?;

    verify_warmup("all_null_boundary", warmup, &null_vec.value)?;

    let null_evt = run_event_series(
        unverified,
        &null_cols,
        params,
        cert_fuel,
        "all_null_boundary",
    )
    .map_err(|err| cert_fail("all_null_boundary", err.to_string()))?;
    if null_vec.value != null_evt {
        return Err(cert_fail(
            "all_null_boundary",
            format!(
                "all-null vector {:?} != event {:?}",
                null_vec.value, null_evt
            ),
        ));
    }
    Ok(())
}

#[allow(clippy::too_many_arguments)]
fn verify_snapshot_restore(
    unverified: &UnverifiedExtendedOperator,
    suite_name: &str,
    columns: &[Vec<Option<Decimal>>],
    warmup: usize,
    params: &BTreeMap<String, String>,
    expected_full: &[Option<Decimal>],
    check_corrupt_snapshot: bool,
    cert_fuel: &mut CertificationFuelBudget,
) -> Result<()> {
    let len = expected_full.len();
    let split_points = select_snapshot_splits(len, warmup);
    let dirty_split = warmup.min(len);
    let mut corrupt_tested = !check_corrupt_snapshot;

    for split in split_points {
        // Run stream A up to `split` and capture snapshot, recording exact per-step fuel.
        let init_limit_a = cert_fuel.next_call_limit("snapshot_restore")?;
        let (mut stream_a, init_fuel_a) = unverified
            .new_stream_with_fuel(params, init_limit_a)
            .map_err(|err| cert_fail("snapshot_restore", format!("{suite_name}: {err}")))?;
        cert_fuel.charge(init_fuel_a, "snapshot_restore")?;

        let mut prefix_outputs = Vec::with_capacity(split);
        let mut prefix_fuels = Vec::with_capacity(split);
        for row_idx in 0..split {
            let row: Vec<Option<Decimal>> = columns.iter().map(|c| c[row_idx].clone()).collect();
            let step_limit = cert_fuel.next_call_limit("snapshot_restore")?;
            let step = stream_a
                .step_with_fuel(&row, step_limit)
                .map_err(|err| cert_fail("snapshot_restore", format!("{suite_name}: {err}")))?;
            cert_fuel.charge(step.fuel_consumed, "snapshot_restore")?;
            prefix_outputs.push(step.value);
            prefix_fuels.push(step.fuel_consumed);
        }
        let cap_limit_a = cert_fuel.next_call_limit("snapshot_restore")?;
        let snap_a = stream_a
            .capture_state_with_fuel(cap_limit_a)
            .map_err(|err| cert_fail("snapshot_restore", format!("{suite_name}: {err}")))?;
        cert_fuel.charge(snap_a.fuel_consumed, "snapshot_restore")?;
        drop(stream_a);

        // Run independent stream B up to `split` and verify EventKernel output, fuel, and snapshot determinism.
        let init_limit_b = cert_fuel.next_call_limit("snapshot_determinism")?;
        let (mut stream_b, init_fuel_b) = unverified
            .new_stream_with_fuel(params, init_limit_b)
            .map_err(|err| cert_fail("snapshot_determinism", format!("{suite_name}: {err}")))?;
        cert_fuel.charge(init_fuel_b, "snapshot_determinism")?;
        if init_fuel_a != init_fuel_b {
            return Err(cert_fail(
                "determinism",
                format!(
                    "{suite_name} split={split}: init-event fuel mismatch ({init_fuel_a} vs {init_fuel_b})"
                ),
            ));
        }

        for row_idx in 0..split {
            let row: Vec<Option<Decimal>> = columns.iter().map(|c| c[row_idx].clone()).collect();
            let step_limit = cert_fuel.next_call_limit("snapshot_determinism")?;
            let step = stream_b
                .step_with_fuel(&row, step_limit)
                .map_err(|err| cert_fail("snapshot_determinism", format!("{suite_name}: {err}")))?;
            cert_fuel.charge(step.fuel_consumed, "snapshot_determinism")?;
            if step.value != prefix_outputs[row_idx] {
                return Err(cert_fail(
                    "determinism",
                    format!("{suite_name} split={split} row={row_idx}: step-event output mismatch"),
                ));
            }
            if step.fuel_consumed != prefix_fuels[row_idx] {
                return Err(cert_fail(
                    "determinism",
                    format!(
                        "{suite_name} split={split} row={row_idx}: step-event fuel mismatch ({} vs {})",
                        prefix_fuels[row_idx], step.fuel_consumed
                    ),
                ));
            }
        }
        let cap_limit_b = cert_fuel.next_call_limit("snapshot_determinism")?;
        let snap_b = stream_b
            .capture_state_with_fuel(cap_limit_b)
            .map_err(|err| cert_fail("snapshot_determinism", format!("{suite_name}: {err}")))?;
        cert_fuel.charge(snap_b.fuel_consumed, "snapshot_determinism")?;
        drop(stream_b);

        if snap_a.value != snap_b.value {
            return Err(cert_fail(
                "snapshot_determinism",
                format!("{suite_name} split={split}: snapshot bytes are not deterministic"),
            ));
        }
        if snap_a.fuel_consumed != snap_b.fuel_consumed {
            return Err(cert_fail(
                "determinism",
                format!(
                    "{suite_name} split={split}: capture-state fuel mismatch ({} vs {})",
                    snap_a.fuel_consumed, snap_b.fuel_consumed
                ),
            ));
        }

        // Restore into a brand-new isolated WASM instance and execute the suffix.
        let init_limit_r1 = cert_fuel.next_call_limit("snapshot_restore")?;
        let (mut restored_1, init_fuel_r1) = unverified
            .new_stream_with_fuel(params, init_limit_r1)
            .map_err(|err| cert_fail("snapshot_restore", format!("{suite_name}: {err}")))?;
        cert_fuel.charge(init_fuel_r1, "snapshot_restore")?;
        let res_limit_1 = cert_fuel.next_call_limit("snapshot_restore")?;
        let restore_fuel_1 = restored_1
            .restore_state_with_fuel(&snap_a.value, res_limit_1)
            .map_err(|err| cert_fail("snapshot_restore", format!("{suite_name}: {err}")))?;
        cert_fuel.charge(restore_fuel_1, "snapshot_restore")?;

        let mut combined = prefix_outputs.clone();
        let mut suffix_fuels = Vec::with_capacity(len.saturating_sub(split));
        for row_idx in split..len {
            let row: Vec<Option<Decimal>> = columns.iter().map(|c| c[row_idx].clone()).collect();
            let step_limit = cert_fuel.next_call_limit("snapshot_restore")?;
            let step = restored_1
                .step_with_fuel(&row, step_limit)
                .map_err(|err| cert_fail("snapshot_restore", format!("{suite_name}: {err}")))?;
            cert_fuel.charge(step.fuel_consumed, "snapshot_restore")?;
            combined.push(step.value);
            suffix_fuels.push(step.fuel_consumed);
        }
        drop(restored_1);

        if combined != expected_full {
            return Err(cert_fail(
                "snapshot_restore",
                format!(
                    "{suite_name} split={split}: restored suffix {:?} != expected {:?}",
                    combined, expected_full
                ),
            ));
        }

        // On the post-warmup split, verify BOTH restore fuel determinism (clean pair)
        // AND dirty-state overwrite (pre-polluted instance restored cleanly).
        if split == dirty_split {
            // 1. Clean-pair restore fuel determinism.
            let init_limit_r2 = cert_fuel.next_call_limit("determinism")?;
            let (mut restored_2, init_fuel_r2) = unverified
                .new_stream_with_fuel(params, init_limit_r2)
                .map_err(|err| cert_fail("determinism", format!("{suite_name}: {err}")))?;
            cert_fuel.charge(init_fuel_r2, "determinism")?;
            let res_limit_2 = cert_fuel.next_call_limit("determinism")?;
            let restore_fuel_2 = restored_2
                .restore_state_with_fuel(&snap_a.value, res_limit_2)
                .map_err(|err| cert_fail("determinism", format!("{suite_name}: {err}")))?;
            cert_fuel.charge(restore_fuel_2, "determinism")?;
            if restore_fuel_1 != restore_fuel_2 {
                return Err(cert_fail(
                    "determinism",
                    format!(
                        "{suite_name} split={split}: restore-state fuel mismatch ({restore_fuel_1} vs {restore_fuel_2})"
                    ),
                ));
            }
            for (offset, row_idx) in (split..len).enumerate() {
                let row: Vec<Option<Decimal>> =
                    columns.iter().map(|c| c[row_idx].clone()).collect();
                let step_limit = cert_fuel.next_call_limit("determinism")?;
                let step = restored_2
                    .step_with_fuel(&row, step_limit)
                    .map_err(|err| cert_fail("determinism", format!("{suite_name}: {err}")))?;
                cert_fuel.charge(step.fuel_consumed, "determinism")?;
                if step.fuel_consumed != suffix_fuels[offset] {
                    return Err(cert_fail(
                        "determinism",
                        format!(
                            "{suite_name} split={split} row={row_idx}: post-restore step fuel mismatch ({} vs {})",
                            suffix_fuels[offset], step.fuel_consumed
                        ),
                    ));
                }
            }
            drop(restored_2);

            // 2. Dirty-state overwrite check: pollute stream with distinct values before restoring.
            let init_limit_dirty = cert_fuel.next_call_limit("snapshot_restore")?;
            let (mut dirty_stream, init_fuel_dirty) = unverified
                .new_stream_with_fuel(params, init_limit_dirty)
                .map_err(|err| cert_fail("snapshot_restore", format!("{suite_name}: {err}")))?;
            cert_fuel.charge(init_fuel_dirty, "snapshot_restore")?;
            let dirty_val: Decimal = "999999.75"
                .parse()
                .expect("static dirty certification decimal");
            let dirty_row = vec![Some(dirty_val); columns.len()];
            for _ in 0..3 {
                let step_limit = cert_fuel.next_call_limit("snapshot_restore")?;
                let step = dirty_stream
                    .step_with_fuel(&dirty_row, step_limit)
                    .map_err(|err| cert_fail("snapshot_restore", format!("{suite_name}: {err}")))?;
                cert_fuel.charge(step.fuel_consumed, "snapshot_restore")?;
            }
            let dirty_res_limit = cert_fuel.next_call_limit("snapshot_restore")?;
            let dirty_restore_fuel = dirty_stream
                .restore_state_with_fuel(&snap_a.value, dirty_res_limit)
                .map_err(|err| cert_fail("snapshot_restore", format!("{suite_name}: {err}")))?;
            cert_fuel.charge(dirty_restore_fuel, "snapshot_restore")?;

            let mut dirty_combined = prefix_outputs;
            for row_idx in split..len {
                let row: Vec<Option<Decimal>> =
                    columns.iter().map(|c| c[row_idx].clone()).collect();
                let step_limit = cert_fuel.next_call_limit("snapshot_restore")?;
                let step = dirty_stream
                    .step_with_fuel(&row, step_limit)
                    .map_err(|err| cert_fail("snapshot_restore", format!("{suite_name}: {err}")))?;
                cert_fuel.charge(step.fuel_consumed, "snapshot_restore")?;
                dirty_combined.push(step.value);
            }
            drop(dirty_stream);
            if dirty_combined != expected_full {
                return Err(cert_fail(
                    "snapshot_restore",
                    format!(
                        "{suite_name} split={split}: restore over dirty state failed: {:?} != {:?}",
                        dirty_combined, expected_full
                    ),
                ));
            }

            // 3. Fail-Closed corrupt/truncated snapshot rejection check.
            if !corrupt_tested {
                let bad_snapshot: Vec<u8> = if snap_a.value.is_empty() {
                    vec![0xFF, 0x00, 0xAB, 0xCD]
                } else {
                    snap_a.value[..snap_a.value.len() - 1].to_vec()
                };
                let init_limit_bad = cert_fuel.next_call_limit("snapshot_restore")?;
                let (mut bad_stream, init_fuel_bad) = unverified
                    .new_stream_with_fuel(params, init_limit_bad)
                    .map_err(|err| cert_fail("snapshot_restore", format!("{suite_name}: {err}")))?;
                cert_fuel.charge(init_fuel_bad, "snapshot_restore")?;
                let bad_limit = cert_fuel.next_call_limit("snapshot_restore")?;
                match bad_stream.restore_state_with_fuel(&bad_snapshot, bad_limit) {
                    Err(Error::GuestError { .. }) => {
                        cert_fuel
                            .charge(bad_stream.consumed_call_fuel(bad_limit), "snapshot_restore")?;
                    }
                    Err(err) => {
                        return Err(cert_fail(
                            "snapshot_restore",
                            format!("{suite_name}: {err}"),
                        ));
                    }
                    Ok(_) => {
                        return Err(cert_fail(
                            "snapshot_restore",
                            format!(
                                "{suite_name} split={split}: restore-state silently accepted truncated/corrupt snapshot"
                            ),
                        ));
                    }
                }
                if !bad_stream.is_poisoned() {
                    return Err(cert_fail(
                        "snapshot_restore",
                        "failed restore-state did not poison operator stream".into(),
                    ));
                }
                corrupt_tested = true;
            }
        }
    }
    Ok(())
}

fn run_event_series(
    unverified: &UnverifiedExtendedOperator,
    columns: &[Vec<Option<Decimal>>],
    params: &BTreeMap<String, String>,
    cert_fuel: &mut CertificationFuelBudget,
    stage: &'static str,
) -> Result<Vec<Option<Decimal>>> {
    let len = columns.first().map_or(0, Vec::len);
    let init_limit = cert_fuel.next_call_limit(stage)?;
    let (mut stream, init_fuel) = unverified.new_stream_with_fuel(params, init_limit)?;
    cert_fuel.charge(init_fuel, stage)?;
    let mut out = Vec::with_capacity(len);
    for row_idx in 0..len {
        let row: Vec<Option<Decimal>> = columns.iter().map(|col| col[row_idx].clone()).collect();
        let step_limit = cert_fuel.next_call_limit(stage)?;
        let step = stream.step_with_fuel(&row, step_limit)?;
        cert_fuel.charge(step.fuel_consumed, stage)?;
        out.push(step.value);
    }
    Ok(out)
}

fn select_causality_prefixes(len: usize, warmup: usize) -> Vec<usize> {
    if len <= 16 {
        return (1..=len).collect();
    }
    let mut set = BTreeSet::new();
    for k in 1..=4.min(len) {
        set.insert(k);
    }
    let w_start = warmup.saturating_sub(2).max(1);
    let w_end = warmup.saturating_add(3).min(len);
    for k in w_start..=w_end {
        set.insert(k);
    }
    set.insert((len / 2).max(1));
    for k in len.saturating_sub(2).max(1)..=len {
        set.insert(k);
    }
    set.into_iter().collect()
}

fn select_snapshot_splits(len: usize, warmup: usize) -> Vec<usize> {
    let mut set = BTreeSet::new();
    set.insert(0);
    if len >= 1 {
        set.insert(1);
        set.insert(warmup.saturating_sub(1).min(len));
        set.insert(warmup.min(len));
        set.insert(warmup.saturating_add(3).min(len));
        set.insert(len.saturating_sub(1));
    }
    set.into_iter().collect()
}

fn build_standard_suites(
    arity: usize,
    warmup: usize,
) -> Vec<(&'static str, Vec<Vec<Option<Decimal>>>)> {
    // Always include at least 8 post-warmup rows so snapshot restore covers multi-step steady-state suffixes.
    let base_len = warmup.saturating_add(8).max(10);

    let d = |s: &str| {
        s.parse::<Decimal>()
            .expect("static certification decimal literal must be valid")
    };

    // 1. Clean monotonic / varying positive & negative series.
    let clean: Vec<Vec<Option<Decimal>>> = (0..arity)
        .map(|col_idx| {
            (0..base_len)
                .map(|t| {
                    let sign = if (t + col_idx) % 4 == 3 { -1 } else { 1 };
                    let whole = sign * ((t as i64 + 1) * 10 + (col_idx as i64) * 3);
                    let frac = ((t * 17 + col_idx * 5) % 100) as i64;
                    let raw = if whole < 0 {
                        format!("-{}.{:02}", whole.abs(), frac)
                    } else {
                        format!("{whole}.{frac:02}")
                    };
                    Some(d(&raw))
                })
                .collect()
        })
        .collect();

    // 2. Series with leading, interior, and trailing nulls plus exact zeros and tiny Q12 decimals.
    let with_nulls: Vec<Vec<Option<Decimal>>> = (0..arity)
        .map(|col_idx| {
            (0..base_len)
                .map(|t| {
                    if t == 0 || t == base_len / 2 || (col_idx > 0 && t == 2) {
                        None
                    } else if t == 1 {
                        Some(d("0"))
                    } else if t == 3 {
                        // Small decimal that `BigDecimal::to_string()` would render in scientific notation (`1E-7`).
                        Some(d("0.0000001"))
                    } else {
                        let raw = format!("{}.5", (t + col_idx + 2) * 4);
                        Some(d(&raw))
                    }
                })
                .collect()
        })
        .collect();

    // 3. Single observation series.
    let single: Vec<Vec<Option<Decimal>>> = (0..arity)
        .map(|col_idx| vec![Some(d(&format!("{}.25", col_idx + 7)))])
        .collect();

    vec![
        ("clean_series", clean),
        ("nulls_and_zeros", with_nulls),
        ("single_row", single),
    ]
}

fn cert_fail(stage: &'static str, reason: String) -> Error {
    Error::CertificationFailed { stage, reason }
}
