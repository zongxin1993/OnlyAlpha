//! 冻结研究切片。来源快照由 Dataset Store 负责，内容摘要标识本次实际消费的面板。
use super::{Cohort, error};
use onlyalpha_domain::{identifiers::OnlyInstrumentId, time::OnlyTimestamp};
use onlyalpha_execution::{Error, digest};
use onlyalpha_operators::algebra::MAX_CELLS;
use onlyalpha_research_statistics::column_digest;

/// 标的按 `SYMBOL.VENUE` 文本顺序排列，所有列共用同一条严格递增的事件时间轴。
#[derive(Clone, Debug)]
pub struct ResearchPanel {
    snapshot: String,
    content_digest: String,
    instrument_ids: Vec<OnlyInstrumentId>,
    timestamps: Vec<OnlyTimestamp>,
    instruments: Vec<Cohort>,
    warmup: usize,
}

impl ResearchPanel {
    /// `snapshot` 是正式数据集快照的 SHA-256 指纹。每只标的须传入自身的实际时间轴。
    /// `warmup` 是首个纳入统计的行索引，预热行保留在求值输入中。
    pub fn new(
        snapshot: &str,
        mut instruments: Vec<(OnlyInstrumentId, Vec<OnlyTimestamp>, Cohort)>,
        warmup: usize,
    ) -> Result<Self, Error> {
        if snapshot.len() != 64
            || !snapshot
                .bytes()
                .all(|b| matches!(b, b'0'..=b'9' | b'a'..=b'f'))
        {
            return Err(error("RESEARCH_PANEL_SNAPSHOT"));
        }
        instruments.sort_by_cached_key(|(id, _, _)| id.to_string());
        if instruments.windows(2).any(|pair| pair[0].0 == pair[1].0) {
            return Err(error("RESEARCH_PANEL_DUPLICATE_INSTRUMENT"));
        }
        let Some((_, timestamps, first)) = instruments.first() else {
            return Err(error("RESEARCH_PANEL_EMPTY"));
        };
        if first.is_empty() {
            return Err(error("RESEARCH_PANEL_NO_FIELDS"));
        }
        if timestamps.is_empty()
            || timestamps
                .iter()
                .any(|t| i64::try_from(t.unix_nanos()).is_err())
            || timestamps.windows(2).any(|pair| pair[0] >= pair[1])
        {
            return Err(error("RESEARCH_PANEL_TIME_AXIS"));
        }
        if warmup >= timestamps.len() {
            return Err(error("RESEARCH_PANEL_WARMUP"));
        }
        if timestamps
            .len()
            .saturating_mul(instruments.len())
            .saturating_mul(first.len())
            > MAX_CELLS
        {
            return Err(error("RESEARCH_RESOURCE_BUDGET"));
        }
        if first
            .keys()
            .any(|name| name.len() > onlyalpha_calculation::factor_expr::MAX_IDENT_LEN)
        {
            return Err(error("RESEARCH_PANEL_SCHEMA"));
        }
        for (_, axis, cohort) in &instruments {
            if axis != timestamps {
                return Err(error("RESEARCH_PANEL_TIME_AXIS"));
            }
            if cohort.keys().ne(first.keys()) {
                return Err(error("RESEARCH_PANEL_SCHEMA"));
            }
            if cohort.values().any(|column| column.len() != axis.len()) {
                return Err(error("RESEARCH_PANEL_LENGTH"));
            }
        }

        let timestamps = std::mem::take(&mut instruments[0].1);
        let (instrument_ids, instruments): (Vec<_>, Vec<_>) = instruments
            .into_iter()
            .map(|(id, _, cohort)| (id, cohort))
            .unzip();
        let content_digest = panel_digest(&instrument_ids, &timestamps, &instruments, warmup)?;
        Ok(Self {
            snapshot: snapshot.to_owned(),
            content_digest,
            instrument_ids,
            timestamps,
            instruments,
            warmup,
        })
    }

    /// 将独立提供的预期指纹与构造时从冻结数据算出的内容摘要精确比对。
    pub fn verify_content(&self, expected: &str) -> Result<(), Error> {
        if self.content_digest != expected {
            return Err(error("RESEARCH_PANEL_CONTENT_MISMATCH"));
        }
        Ok(())
    }

    pub fn instrument_ids(&self) -> &[OnlyInstrumentId] {
        &self.instrument_ids
    }

    pub fn timestamps(&self) -> &[OnlyTimestamp] {
        &self.timestamps
    }

    pub fn instruments(&self) -> &[Cohort] {
        &self.instruments
    }

    pub fn periods(&self) -> usize {
        self.timestamps.len()
    }

    pub fn instrument_count(&self) -> usize {
        self.instrument_ids.len()
    }

    pub fn warmup(&self) -> usize {
        self.warmup
    }

    pub fn snapshot(&self) -> &str {
        &self.snapshot
    }

    pub fn content_digest(&self) -> &str {
        &self.content_digest
    }
}

// v1：计数和字节长度用大端 u64。列名按 Cohort 的 BTreeMap 键序写一次。
// 每个标的依次写入 ID 和各列的 64 字节小写十六进制 SHA-256，避免复制整个数值矩阵。
fn panel_digest(
    ids: &[OnlyInstrumentId],
    timestamps: &[OnlyTimestamp],
    cohorts: &[Cohort],
    warmup: usize,
) -> Result<String, Error> {
    let mut bytes = b"onlyalpha.research.panel.v1\0".to_vec();
    bytes.extend_from_slice(&(warmup as u64).to_be_bytes());
    bytes.extend_from_slice(&(timestamps.len() as u64).to_be_bytes());
    for timestamp in timestamps {
        push_text(&mut bytes, &timestamp.unix_nanos().to_string());
    }
    bytes.extend_from_slice(&(cohorts[0].len() as u64).to_be_bytes());
    for name in cohorts[0].keys() {
        push_text(&mut bytes, name);
    }
    bytes.extend_from_slice(&(ids.len() as u64).to_be_bytes());
    for (id, cohort) in ids.iter().zip(cohorts) {
        push_text(&mut bytes, &id.to_string());
        for column in cohort.values() {
            bytes.extend_from_slice(column_digest(column)?.as_bytes());
        }
    }
    Ok(digest(&bytes))
}

fn push_text(bytes: &mut Vec<u8>, value: &str) {
    bytes.extend_from_slice(&(value.len() as u64).to_be_bytes());
    bytes.extend_from_slice(value.as_bytes());
}
