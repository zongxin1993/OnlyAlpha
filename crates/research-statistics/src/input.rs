use super::{Cell, Error, SeriesBinding, error};
use onlyalpha_domain::{identifiers::OnlyInstrumentId, time::OnlyTimestamp};
use onlyalpha_operators::algebra::{MAX_INPUT_DIGITS, MAX_INPUT_SCALE};
use sha2::{Digest, Sha256};
use std::collections::{BTreeMap, BTreeSet};

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct EvaluationAxis<'a> {
    pub snapshot: &'a str,
    pub content_digest: &'a str,
    pub instruments: &'a [OnlyInstrumentId],
    pub timestamps: &'a [OnlyTimestamp],
    pub warmup: usize,
}

fn fingerprint(text: &str) -> bool {
    text.len() == 64 && text.bytes().all(|b| matches!(b, b'0'..=b'9' | b'a'..=b'f'))
}

impl EvaluationAxis<'_> {
    pub(crate) fn validate(&self) -> Result<(), Error> {
        if !fingerprint(self.snapshot) || !fingerprint(self.content_digest) {
            return Err(error("RESEARCH_STATISTICS_BINDING"));
        }
        if self.instruments.is_empty()
            || self
                .instruments
                .windows(2)
                .any(|p| p[0].to_string() >= p[1].to_string())
            || self.warmup >= self.timestamps.len()
            || self
                .timestamps
                .iter()
                .any(|t| i64::try_from(t.unix_nanos()).is_err())
            || self.timestamps.windows(2).any(|p| p[0] >= p[1])
        {
            return Err(error("RESEARCH_STATISTICS_AXIS"));
        }
        Ok(())
    }

    fn matches(&self, other: &Self) -> bool {
        self.snapshot == other.snapshot
            && self.content_digest == other.content_digest
            && self.warmup == other.warmup
            && (std::ptr::eq(self.timestamps, other.timestamps)
                || self.timestamps == other.timestamps)
            && (std::ptr::eq(self.instruments, other.instruments)
                || self.instruments == other.instruments)
    }
}

#[derive(Clone, Copy, Debug)]
pub struct SeriesRef<'a> {
    pub axis: EvaluationAxis<'a>,
    pub name: &'a str,
    pub fingerprint: &'a str,
    pub values: &'a [Vec<Cell>],
}

#[derive(Clone, Copy, Debug)]
pub struct FactorSeriesRef<'a>(pub SeriesRef<'a>);

#[derive(Clone, Copy, Debug)]
pub struct TargetSeriesRef<'a>(pub SeriesRef<'a>);

pub struct EvaluationInput<'a> {
    pub axis: EvaluationAxis<'a>,
    pub factors: &'a [FactorSeriesRef<'a>],
    pub targets: &'a [TargetSeriesRef<'a>],
    pub minimum_observations: usize,
}

pub(crate) fn valid_name(name: &str) -> bool {
    !name.is_empty() && name.trim() == name && name.len() <= 512 && name.chars().count() <= 128
}

pub(super) fn finish_digest(hash: Sha256) -> String {
    use std::fmt::Write;
    let mut text = String::with_capacity(64);
    for byte in hash.finalize() {
        write!(&mut text, "{byte:02x}").expect("写入 String 不会失败");
    }
    text
}

/// 对一个标的的时序列按冻结面板 v1 格式计算内容摘要。
pub fn column_digest(column: &[Cell]) -> Result<String, Error> {
    let mut hash = Sha256::new();
    for cell in column {
        let Some(value) = cell else {
            hash.update([0]);
            continue;
        };
        if value.as_bigint_and_scale().1.unsigned_abs() > MAX_INPUT_SCALE as u64
            || value.digits() > MAX_INPUT_DIGITS
        {
            return Err(error("FACTOR_EXPR_NUMERIC_BUDGET"));
        }
        let (coefficient, scale) = value.normalized().as_bigint_and_exponent();
        let text = coefficient.to_string();
        hash.update([1]);
        hash.update((text.len() as u64).to_be_bytes());
        hash.update(text.as_bytes());
        hash.update(scale.to_be_bytes());
    }
    Ok(finish_digest(hash))
}

pub(crate) fn bind<'a>(
    axis: EvaluationAxis<'_>,
    series: impl Iterator<Item = SeriesRef<'a>>,
) -> Result<Vec<SeriesBinding>, Error> {
    let mut names = BTreeSet::new();
    let mut results = BTreeMap::new();
    let mut bindings = Vec::new();
    for series in series {
        if !axis.matches(&series.axis) || !fingerprint(series.fingerprint) {
            return Err(error("RESEARCH_STATISTICS_BINDING"));
        }
        if !valid_name(series.name) || !names.insert(series.name) {
            return Err(error("RESEARCH_DEFINITION_NAME"));
        }
        if series.values.len() != axis.instruments.len()
            || series
                .values
                .iter()
                .any(|column| column.len() != axis.timestamps.len())
        {
            return Err(error("RESEARCH_STATISTICS_SHAPE"));
        }
        let mut hash = Sha256::new();
        hash.update(b"onlyalpha.research.series.v1\0");
        for column in series.values {
            hash.update(column_digest(column)?.as_bytes());
        }
        let values_digest = finish_digest(hash);
        if results
            .insert(series.fingerprint, values_digest.clone())
            .is_some_and(|previous| previous != values_digest)
        {
            return Err(error("RESEARCH_STATISTICS_BINDING"));
        }
        bindings.push(SeriesBinding {
            name: series.name.into(),
            fingerprint: series.fingerprint.into(),
            values_digest,
        });
    }
    Ok(bindings)
}
