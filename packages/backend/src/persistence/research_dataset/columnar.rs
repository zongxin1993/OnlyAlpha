//! Physical Parquet encoding only; semantic content identity is independent.
use crate::application::research_dataset::*;
use arrow_array::{
    Array, ArrayRef, BooleanArray, Date32Array, Decimal128Array, Int32Array, Int64Array,
    RecordBatch, StringArray,
};
use arrow_schema::{DataType, Field, Schema};
use onlyalpha_domain::time::{OnlyTimestamp, OnlyUtcDateTime};
use parquet::{
    arrow::{ArrowWriter, arrow_reader::ParquetRecordBatchReaderBuilder},
    basic::Compression,
    file::properties::WriterProperties,
};
use serde_json::{Value, json};
use std::{fs::File, sync::Arc};
fn data_type(kind: &str) -> DataType {
    match kind {
        "utf8" => DataType::Utf8,
        "int64" => DataType::Int64,
        "int32" => DataType::Int32,
        "date32" => DataType::Date32,
        "bool" => DataType::Boolean,
        _ => DataType::Decimal128(38, 18),
    }
}
fn arrow_schema() -> Arc<Schema> {
    Arc::new(Schema::new(
        COLUMNS
            .iter()
            .map(|(name, kind, nullable, _)| Field::new(*name, data_type(kind), *nullable))
            .collect::<Vec<_>>(),
    ))
}
fn date_days(raw: &str) -> Result<i32> {
    let t: OnlyUtcDateTime = format!("{raw}T00:00:00Z").parse().map_err(|_| INVALID)?;
    (OnlyTimestamp::from_datetime(t).unix_nanos()
        / bigdecimal::num_bigint::BigInt::from(86_400_000_000_000_i64))
    .to_string()
    .parse()
    .map_err(|_| INVALID)
}
fn date_text(days: i32) -> Result<String> {
    let t = OnlyTimestamp::from_unix_nanos((i128::from(days) * 86_400_000_000_000_i128).into())
        .to_datetime_exact()
        .map_err(|_| INVALID)?;
    Ok(t.date().to_string())
}
fn decimal_int(v: &Value) -> Result<i128> {
    let raw = text(v)?;
    let value: bigdecimal::BigDecimal = raw.parse().map_err(|_| INVALID)?;
    let scaled = value.with_scale(18);
    if value != scaled {
        return Err(INVALID);
    }
    scaled
        .as_bigint_and_exponent()
        .0
        .to_string()
        .parse()
        .map_err(|_| INVALID)
}
pub fn write(file: &File, rows: &[Value]) -> Result<()> {
    let mut columns: Vec<ArrayRef> = vec![];
    for (name, kind, nullable, _) in COLUMNS {
        let values = rows.iter().map(|r| &r[*name]).collect::<Vec<_>>();
        if !nullable && values.iter().any(|v| v.is_null()) {
            return Err(INVALID);
        }
        let array: ArrayRef = match *kind {
            "utf8" => Arc::new(StringArray::from(
                values.iter().map(|v| v.as_str()).collect::<Vec<_>>(),
            )),
            "int64" => Arc::new(Int64Array::from(
                values.iter().map(|v| v.as_i64()).collect::<Vec<_>>(),
            )),
            "int32" => Arc::new(Int32Array::from(
                values
                    .iter()
                    .map(|v| {
                        if v.is_null() {
                            Ok(None)
                        } else {
                            Ok(Some(i32::try_from(number(v)?).map_err(|_| INVALID)?))
                        }
                    })
                    .collect::<Result<Vec<_>>>()?,
            )),
            "bool" => Arc::new(BooleanArray::from(
                values.iter().map(|v| v.as_bool()).collect::<Vec<_>>(),
            )),
            "date32" => Arc::new(Date32Array::from(
                values
                    .iter()
                    .map(|v| Ok(Some(date_days(text(v)?)?)))
                    .collect::<Result<Vec<_>>>()?,
            )),
            _ => Arc::new(
                Decimal128Array::from(
                    values
                        .iter()
                        .map(|v| {
                            if v.is_null() {
                                Ok(None)
                            } else {
                                Ok(Some(decimal_int(v)?))
                            }
                        })
                        .collect::<Result<Vec<_>>>()?,
                )
                .with_precision_and_scale(38, 18)
                .map_err(|_| INVALID)?,
            ),
        };
        columns.push(array);
    }
    let schema = arrow_schema();
    let batch = RecordBatch::try_new(schema.clone(), columns).map_err(|_| INVALID)?;
    let props = WriterProperties::builder()
        .set_compression(Compression::ZSTD(Default::default()))
        .build();
    let mut writer =
        ArrowWriter::try_new(file, schema, Some(props)).map_err(|_| "DATASET_STORE_UNAVAILABLE")?;
    writer
        .write(&batch)
        .map_err(|_| "DATASET_STORE_UNAVAILABLE")?;
    writer.close().map_err(|_| "DATASET_STORE_UNAVAILABLE")?;
    file.sync_all().map_err(|_| "DATASET_STORE_UNAVAILABLE")
}
pub fn read(file: File, max_rows: usize, max_bytes: u64) -> Result<Vec<Value>> {
    if file
        .metadata()
        .map_err(|_| "DATASET_STORE_UNAVAILABLE")?
        .len()
        > max_bytes
    {
        return Err("DATASET_READ_BUDGET_EXCEEDED");
    }
    let builder =
        ParquetRecordBatchReaderBuilder::try_new(file).map_err(|_| "DATASET_SNAPSHOT_CORRUPT")?;
    let count =
        usize::try_from(builder.metadata().file_metadata().num_rows()).map_err(|_| INVALID)?;
    if count > max_rows {
        return Err("DATASET_READ_BUDGET_EXCEEDED");
    }
    let logical_bytes =
        builder
            .metadata()
            .row_groups()
            .iter()
            .try_fold(0_u64, |total, group| {
                let size = u64::try_from(group.total_byte_size())
                    .map_err(|_| "DATASET_SNAPSHOT_CORRUPT")?;
                total
                    .checked_add(size)
                    .ok_or("DATASET_READ_BUDGET_EXCEEDED")
            })?;
    if logical_bytes > max_bytes {
        return Err("DATASET_READ_BUDGET_EXCEEDED");
    }

    if builder.schema().as_ref() != arrow_schema().as_ref() {
        return Err("DATASET_SCHEMA_UNSUPPORTED");
    }
    let reader = builder
        .with_batch_size(1024)
        .build()
        .map_err(|_| "DATASET_SNAPSHOT_CORRUPT")?;
    let mut rows = vec![];
    for batch in reader {
        let batch = batch.map_err(|_| "DATASET_SNAPSHOT_CORRUPT")?;
        if rows
            .len()
            .checked_add(batch.num_rows())
            .is_none_or(|n| n > max_rows)
        {
            return Err("DATASET_READ_BUDGET_EXCEEDED");
        }
        for i in 0..batch.num_rows() {
            let mut row = json!({});
            for (c, (name, kind, nullable, _)) in COLUMNS.iter().enumerate() {
                let array = batch.column(c);
                let value = if array.is_null(i) {
                    if !nullable {
                        return Err(INVALID);
                    }
                    Value::Null
                } else {
                    macro_rules! value {
                        ($t:ty) => {
                            array.as_any().downcast_ref::<$t>().ok_or(INVALID)?.value(i)
                        };
                    }
                    match *kind {
                        "utf8" => json!(value!(StringArray)),
                        "int64" => json!(value!(Int64Array)),
                        "int32" => json!(value!(Int32Array)),
                        "bool" => json!(value!(BooleanArray)),
                        "date32" => json!(date_text(value!(Date32Array))?),
                        _ => json!(
                            bigdecimal::BigDecimal::new(value!(Decimal128Array).into(), 18)
                                .to_string()
                        ),
                    }
                };
                row[*name] = value;
            }
            rows.push(row);
        }
    }
    if rows.len() != count {
        return Err("DATASET_SNAPSHOT_CORRUPT");
    }
    Ok(rows)
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::{
        io::{Seek, SeekFrom},
        os::unix::fs::OpenOptionsExt,
    };
    #[test]
    fn compressed_oversized_logical_payload_is_denied_before_arrow_decode() {
        let mut row = json!({});
        for (name, kind, nullable, _) in COLUMNS {
            row[*name] = if *nullable {
                Value::Null
            } else {
                match *kind {
                    "utf8" => json!("x"),
                    "date32" => json!("1970-01-01"),
                    "bool" => json!(true),
                    "decimal128(38,18)" => json!("1.000000000000000000"),
                    _ => json!(0),
                }
            };
        }
        row["bar_semantic_json"] = json!("x".repeat(2 * 1024 * 1024));
        let mut entropy = [0u8; 16];
        getrandom::fill(&mut entropy).unwrap();
        let path = std::env::temp_dir().join(format!("onlyalpha-columnar-{}", hash(&entropy)));
        let mut file = std::fs::OpenOptions::new()
            .read(true)
            .write(true)
            .create_new(true)
            .mode(0o600)
            .open(&path)
            .unwrap();
        write(&file, &[row]).unwrap();
        assert!(file.metadata().unwrap().len() < 65536);
        file.seek(SeekFrom::Start(0)).unwrap();
        let result = read(file, 1, 65536);
        std::fs::remove_file(path).unwrap();
        assert!(matches!(result, Err("DATASET_READ_BUDGET_EXCEEDED")));
    }
}
