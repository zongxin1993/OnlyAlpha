use crate::{Error, boundary, err, fields, hash, sha};
use onlyalpha_clock::BigInt;
use onlyalpha_domain::{base::OnlyDomainModel, market::OnlyBar, time::OnlyTimestamp};
use serde_json::{Value, json};
use std::collections::BTreeMap;
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Source {
    record: Value,
}
impl Source {
    pub fn new(
        id: &str,
        snapshot: &str,
        binding: &str,
        data_version: &str,
        priority: u32,
        rows: u64,
    ) -> Result<Self, Error> {
        for s in [id, snapshot, binding] {
            sha(s)?;
        }
        version(data_version)?;
        if rows > 65536 {
            return Err(err("SOURCE_BOUND"));
        }
        Ok(Self {
            record: json!({"schema_version":1,"source":id,"snapshot":snapshot,"dataset_binding":binding,"data_version":data_version,"priority":priority,"rows":rows}),
        })
    }
    pub fn id(&self) -> &str {
        self.record["source"].as_str().expect("validated")
    }
    pub fn record(&self) -> Value {
        self.record.clone()
    }
    fn from_record(v: &Value) -> Result<Self, Error> {
        fields(
            v,
            &[
                "schema_version",
                "source",
                "snapshot",
                "dataset_binding",
                "data_version",
                "priority",
                "rows",
            ],
        )?;
        let text = |k: &str| v[k].as_str().ok_or_else(|| err("SOURCE"));
        let s = Self::new(
            text("source")?,
            text("snapshot")?,
            text("dataset_binding")?,
            text("data_version")?,
            u32::try_from(v["priority"].as_u64().ok_or_else(|| err("PRIORITY"))?)
                .map_err(|_| err("PRIORITY"))?,
            v["rows"].as_u64().ok_or_else(|| err("ROWS"))?,
        )?;
        if s.record != *v {
            return Err(err("SOURCE_CANONICAL"));
        }
        Ok(s)
    }
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct MarketInput {
    source: String,
    sequence: u64,
    data_version: String,
    bar: OnlyBar,
}
impl MarketInput {
    pub fn new(
        source: &str,
        sequence: u64,
        data_version: &str,
        bar: OnlyBar,
    ) -> Result<Self, Error> {
        sha(source)?;
        version(data_version)?;
        let v = bar.to_record();
        if sequence == 0
            || sequence > 65536
            || !bar.is_closed()
            || bar.ts_event() != bar.bar_end()
            || v["revision"] != 0
            || v["adjustment_type"] != "RAW"
            || bar.ts_init() < bar.ts_event()
        {
            return Err(err("MARKET_INPUT"));
        }
        Ok(Self {
            source: source.into(),
            sequence,
            data_version: data_version.into(),
            bar,
        })
    }
    pub fn source(&self) -> &str {
        &self.source
    }
    pub fn sequence(&self) -> u64 {
        self.sequence
    }
    pub fn bar(&self) -> &OnlyBar {
        &self.bar
    }
    pub fn event_ns(&self) -> BigInt {
        OnlyTimestamp::from_datetime(*self.bar.ts_event()).to_unix_nanos()
    }
    pub fn record(&self) -> Value {
        json!({"schema_version":1,"source":self.source,"sequence":self.sequence,"data_version":self.data_version,"bar":self.bar.to_record()})
    }
    pub fn identity(&self) -> String {
        hash(&self.record())
    }
    fn from_record(v: &Value) -> Result<Self, Error> {
        fields(
            v,
            &[
                "schema_version",
                "source",
                "sequence",
                "data_version",
                "bar",
            ],
        )?;
        let s = Self::new(
            v["source"].as_str().ok_or_else(|| err("SOURCE"))?,
            v["sequence"].as_u64().ok_or_else(|| err("SEQUENCE"))?,
            v["data_version"]
                .as_str()
                .ok_or_else(|| err("DATA_VERSION"))?,
            boundary(OnlyBar::from_record(&v["bar"]))?,
        )?;
        if s.record() != *v {
            return Err(err("MARKET_CANONICAL"));
        }
        Ok(s)
    }
}
#[derive(Clone, Debug)]
pub struct Inputs {
    sources: Vec<Source>,
    records: Vec<MarketInput>,
}
impl Inputs {
    pub fn new(mut sources: Vec<Source>, facts: Vec<MarketInput>) -> Result<Self, Error> {
        if sources.is_empty() || sources.len() > 64 || facts.len() > 131072 {
            return Err(err("INPUT_BOUND"));
        }
        sources.sort_by_key(|s| s.id().to_owned());
        let mut by_source = BTreeMap::new();
        for s in &sources {
            if by_source.insert(s.id().to_owned(), s).is_some() {
                return Err(err("DUPLICATE_SOURCE"));
            }
        }
        let mut unique = BTreeMap::new();
        for f in facts {
            let s = by_source
                .get(f.source())
                .ok_or_else(|| err("FOREIGN_SOURCE"))?;
            if s.record["data_version"] != f.data_version {
                return Err(err("DATA_VERSION"));
            }
            let key = (f.source.clone(), f.sequence);
            match unique.entry(key) {
                std::collections::btree_map::Entry::Vacant(entry) => {
                    entry.insert(f);
                }
                std::collections::btree_map::Entry::Occupied(entry) => {
                    if entry.get().record() != f.record() {
                        return Err(err("CONFLICTING_INPUT"));
                    }
                }
            }
        }
        let mut records: Vec<_> = unique.into_values().collect();
        if records.len() > 65536 {
            return Err(err("INPUT_BOUND"));
        }
        // BAR is the only admitted family. Exact semantic BarType precedes declared Source priority.
        records.sort_by_key(|f| {
            (
                f.event_ns(),
                f.bar.instrument_id().to_string(),
                f.bar.bar_type().to_record().to_string(),
                by_source[&f.source].record["priority"]
                    .as_u64()
                    .expect("priority"),
                f.source.clone(),
                f.sequence,
                f.identity(),
            )
        });
        let mut counts = BTreeMap::<String, u64>::new();
        for f in &records {
            let count = counts.entry(f.source.clone()).or_default();
            *count += 1;
            if f.sequence != *count {
                return Err(err("SOURCE_ORDER_OR_GAP"));
            }
        }
        for s in &sources {
            if counts.get(s.id()).copied().unwrap_or(0) != s.record["rows"].as_u64().expect("rows")
            {
                return Err(err("SOURCE_COMPLETENESS"));
            }
        }
        Ok(Self { sources, records })
    }
    pub fn records(&self) -> &[MarketInput] {
        &self.records
    }
    pub fn record(&self) -> Value {
        json!({"schema_version":1,"sources":self.sources.iter().map(Source::record).collect::<Vec<_>>(),"records":self.records.iter().map(MarketInput::record).collect::<Vec<_>>()})
    }
    pub fn fingerprint(&self) -> String {
        hash(&self.record())
    }
    pub fn from_record(v: &Value) -> Result<Self, Error> {
        fields(v, &["schema_version", "sources", "records"])?;
        if v["schema_version"] != 1 || v.to_string().len() > 128 * 1024 * 1024 {
            return Err(err("INPUT_FORMAT"));
        }
        let sources = v["sources"]
            .as_array()
            .ok_or_else(|| err("SOURCES"))?
            .iter()
            .map(Source::from_record)
            .collect::<Result<Vec<_>, _>>()?;
        let records = v["records"]
            .as_array()
            .ok_or_else(|| err("RECORDS"))?
            .iter()
            .map(MarketInput::from_record)
            .collect::<Result<Vec<_>, _>>()?;
        let result = Self::new(sources, records)?;
        if result.record() != *v {
            return Err(err("INPUT_CANONICAL"));
        }
        Ok(result)
    }
}

fn version(value: &str) -> Result<(), Error> {
    if value.trim().is_empty() || value.len() > 256 {
        return Err(err("DATA_VERSION"));
    }
    Ok(())
}
