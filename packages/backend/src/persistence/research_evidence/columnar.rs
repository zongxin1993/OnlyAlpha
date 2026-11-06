//! Public CalculationResult1 / StatisticsResult1 physical and semantic codecs.
use super::super::{INVALID, Result, hash};
use arrow_array::{
    Array, ArrayRef, BooleanArray, Decimal128Array, Int64Array, RecordBatch, StringArray,
};
use arrow_schema::{DataType, Field, Schema};
use parquet::{
    arrow::{ArrowWriter, arrow_reader::ParquetRecordBatchReaderBuilder},
    basic::Compression,
    file::properties::WriterProperties,
};
use serde_json::{Value, json};
use std::{fs::File, sync::Arc};

fn decimal(value: &Value, scale: i8) -> Result<i128> {
    let raw = value
        .as_str()
        .filter(|s| s.len() <= 128 && s.bytes().all(|b| b.is_ascii_digit() || b"+-.".contains(&b)))
        .ok_or(INVALID)?;
    let number: bigdecimal::BigDecimal = raw.parse().map_err(|_| INVALID)?;
    let fixed = number.with_scale(i64::from(scale));
    let coefficient = fixed.as_bigint_and_exponent().0;
    if fixed != number || coefficient.to_string().trim_start_matches('-').len() > 38 {
        return Err(INVALID);
    }
    coefficient.to_string().parse().map_err(|_| INVALID)
}
fn decimal_text(value: i128, scale: i8) -> String {
    let digits = value.unsigned_abs().to_string();
    let padded = format!("{:0>width$}", digits, width = scale as usize + 1);
    let boundary = padded.len() - scale as usize;
    format!(
        "{}{}.{}",
        if value < 0 { "-" } else { "" },
        &padded[..boundary],
        &padded[boundary..]
    )
}
pub(super) fn schema_payload(schema: &Schema) -> Result<Value> {
    let mut fields = Vec::new();
    for field in schema.fields() {
        let kind = match field.data_type() {
            DataType::Int64 => json!({"kind":"INTEGER","bit_width":64,"signed":true}),
            DataType::Boolean => json!({"kind":"BOOLEAN"}),
            DataType::Utf8 => json!({"kind":"STRING"}),
            DataType::Decimal128(precision, scale) => {
                json!({"kind":"DECIMAL","bit_width":128,"precision":precision,"scale":scale})
            }
            _ => return Err(INVALID),
        };
        fields.push(json!({"name":field.name(),"data_type":kind,"nullable":field.is_nullable()}));
    }
    Ok(json!(fields))
}
fn schema_from_ports(ports: &Value) -> Result<Arc<Schema>> {
    let mut fields = vec![Field::new("ts_event_ns", DataType::Int64, false)];
    let mut ports = ports.as_array().ok_or(INVALID)?.iter().collect::<Vec<_>>();
    ports.sort_by_key(|p| p["name"].as_str().unwrap_or(""));
    let mut previous = "ts_event_ns";
    for port in ports {
        let name = port["name"]
            .as_str()
            .filter(|n| !n.is_empty() && *n != "ts_event_ns")
            .ok_or(INVALID)?;
        if name == previous {
            return Err(INVALID);
        }
        previous = name;
        let data = match port["data_type"].as_str() {
            Some("DECIMAL") => DataType::Decimal128(38, 18),
            Some("INTEGER") => DataType::Int64,
            Some("BOOLEAN") => DataType::Boolean,
            Some("STRING") => DataType::Utf8,
            _ => return Err(INVALID),
        };
        fields.push(Field::new(
            name,
            data,
            port["nullable"].as_bool().ok_or(INVALID)?,
        ));
    }
    Ok(Arc::new(Schema::new(fields)))
}
fn encode(schema: Arc<Schema>, rows: &[Value]) -> Result<Vec<u8>> {
    let mut columns: Vec<ArrayRef> = Vec::new();
    for field in schema.fields() {
        let values = rows
            .iter()
            .map(|r| r.get(field.name()).ok_or(INVALID))
            .collect::<Result<Vec<_>>>()?;
        if !field.is_nullable() && values.iter().any(|v| v.is_null()) {
            return Err(INVALID);
        }
        let column: ArrayRef = match field.data_type() {
            DataType::Int64 => Arc::new(Int64Array::from(
                values
                    .iter()
                    .map(|v| {
                        if v.is_null() {
                            Ok(None)
                        } else {
                            v.as_i64().map(Some).ok_or(INVALID)
                        }
                    })
                    .collect::<Result<Vec<_>>>()?,
            )),
            DataType::Boolean => Arc::new(BooleanArray::from(
                values
                    .iter()
                    .map(|v| {
                        if v.is_null() {
                            Ok(None)
                        } else {
                            v.as_bool().map(Some).ok_or(INVALID)
                        }
                    })
                    .collect::<Result<Vec<_>>>()?,
            )),
            DataType::Utf8 => Arc::new(StringArray::from(
                values
                    .iter()
                    .map(|v| {
                        if v.is_null() {
                            Ok(None)
                        } else {
                            v.as_str().map(Some).ok_or(INVALID)
                        }
                    })
                    .collect::<Result<Vec<_>>>()?,
            )),
            DataType::Decimal128(precision, scale) => Arc::new(
                Decimal128Array::from(
                    values
                        .iter()
                        .map(|v| {
                            if v.is_null() {
                                Ok(None)
                            } else {
                                decimal(v, *scale).map(Some)
                            }
                        })
                        .collect::<Result<Vec<_>>>()?,
                )
                .with_precision_and_scale(*precision, *scale)
                .map_err(|_| INVALID)?,
            ),
            _ => return Err(INVALID),
        };
        columns.push(column);
    }
    let batch = RecordBatch::try_new(schema.clone(), columns).map_err(|_| INVALID)?;
    let properties = WriterProperties::builder()
        .set_compression(Compression::ZSTD(Default::default()))
        .build();
    let mut bytes = Vec::new();
    {
        let mut writer =
            ArrowWriter::try_new(&mut bytes, schema, Some(properties)).map_err(|_| INVALID)?;
        writer.write(&batch).map_err(|_| INVALID)?;
        writer.close().map_err(|_| INVALID)?;
    }
    Ok(bytes)
}
pub(super) fn calculation_rows(
    axis: &[Value],
    columns: &Value,
    ports: &Value,
) -> Result<(Arc<Schema>, Vec<Value>)> {
    let schema = schema_from_ports(ports)?;
    let values = columns.as_object().ok_or(INVALID)?;
    if values.len() + 1 != schema.fields().len() {
        return Err(INVALID);
    }
    let mut rows = Vec::new();
    let mut previous = None;
    for (index, at) in axis.iter().enumerate() {
        let at = at.as_i64().ok_or(INVALID)?;
        if previous.is_some_and(|p| p >= at) {
            return Err(INVALID);
        }
        previous = Some(at);
        let mut row = serde_json::Map::from_iter([("ts_event_ns".into(), json!(at))]);
        for field in schema.fields().iter().skip(1) {
            let column = values
                .get(field.name())
                .and_then(Value::as_array)
                .filter(|v| v.len() == axis.len())
                .ok_or(INVALID)?;
            let tagged = &column[index];
            if tagged
                .as_object()
                .is_none_or(|m| m.len() != 2 || !m.contains_key("type") || !m.contains_key("value"))
            {
                return Err(INVALID);
            }
            if onlyalpha_calculation::product::normalize_scalar(tagged, 8 * 1024 * 1024)
                .map_err(|_| INVALID)?
                != *tagged
            {
                return Err(INVALID);
            }
            let value = if tagged["type"] == "NULL" {
                if !tagged["value"].is_null() || !field.is_nullable() {
                    return Err(INVALID);
                }
                Value::Null
            } else {
                match field.data_type() {
                    DataType::Decimal128(_, scale) if tagged["type"] == "DECIMAL" => {
                        json!(decimal_text(decimal(&tagged["value"], *scale)?, *scale))
                    }
                    DataType::Int64 if tagged["type"] == "INTEGER" => json!(
                        tagged["value"]
                            .as_i64()
                            .or_else(|| tagged["value"].as_str().and_then(|s| s.parse().ok()))
                            .ok_or(INVALID)?
                    ),
                    DataType::Boolean if tagged["type"] == "BOOLEAN" => {
                        json!(tagged["value"].as_bool().ok_or(INVALID)?)
                    }
                    DataType::Utf8 if tagged["type"] == "STRING" => {
                        json!(tagged["value"].as_str().ok_or(INVALID)?)
                    }
                    _ => return Err(INVALID),
                }
            };
            row.insert(field.name().into(), value);
        }
        rows.push(Value::Object(row));
    }
    Ok((schema, rows))
}
pub(super) fn write_calculation(
    axis: &[Value],
    columns: &Value,
    ports: &Value,
) -> Result<(Value, Vec<Value>, Vec<u8>)> {
    let (schema, rows) = calculation_rows(axis, columns, ports)?;
    Ok((
        schema_payload(&schema)?,
        rows.clone(),
        encode(schema, &rows)?,
    ))
}
pub(super) fn statistics_schema() -> Arc<Schema> {
    Arc::new(Schema::new(vec![
        Field::new("ts_event_ns", DataType::Int64, false),
        Field::new("statistic_value", DataType::Decimal128(38, 12), true),
        Field::new("sample_count", DataType::Int64, false),
        Field::new("status", DataType::Utf8, false),
    ]))
}
pub(super) fn write_statistics(rows: &[Value]) -> Result<(Value, Vec<u8>)> {
    let schema = statistics_schema();
    Ok((schema_payload(&schema)?, encode(schema, rows)?))
}
pub(super) fn read(file: File, expected_schema: &Value, max_rows: usize) -> Result<Vec<Value>> {
    let builder = ParquetRecordBatchReaderBuilder::try_new(file).map_err(|_| INVALID)?;
    if schema_payload(builder.schema())? != *expected_schema {
        return Err(INVALID);
    }
    let reader = builder.with_batch_size(8192).build().map_err(|_| INVALID)?;
    let mut rows = Vec::new();
    for batch in reader {
        let batch = batch.map_err(|_| INVALID)?;
        if rows.len().saturating_add(batch.num_rows()) > max_rows {
            return Err(INVALID);
        }
        let schema = batch.schema();
        for index in 0..batch.num_rows() {
            let mut row = serde_json::Map::new();
            for (field, column) in schema.fields().iter().zip(batch.columns()) {
                let value = if column.is_null(index) {
                    if !field.is_nullable() {
                        return Err(INVALID);
                    }
                    Value::Null
                } else {
                    match field.data_type() {
                        DataType::Int64 => json!(
                            column
                                .as_any()
                                .downcast_ref::<Int64Array>()
                                .ok_or(INVALID)?
                                .value(index)
                        ),
                        DataType::Boolean => json!(
                            column
                                .as_any()
                                .downcast_ref::<BooleanArray>()
                                .ok_or(INVALID)?
                                .value(index)
                        ),
                        DataType::Utf8 => json!(
                            column
                                .as_any()
                                .downcast_ref::<StringArray>()
                                .ok_or(INVALID)?
                                .value(index)
                        ),
                        DataType::Decimal128(precision, scale)
                            if *precision == 38 && matches!(*scale, 12 | 18) =>
                        {
                            json!(decimal_text(
                                column
                                    .as_any()
                                    .downcast_ref::<Decimal128Array>()
                                    .ok_or(INVALID)?
                                    .value(index),
                                *scale
                            ))
                        }
                        _ => return Err(INVALID),
                    }
                };
                row.insert(field.name().into(), value);
            }
            rows.push(Value::Object(row));
        }
    }
    Ok(rows)
}
pub(super) fn partition(
    node: &str,
    instrument: &str,
    schema: &Value,
    rows: &[Value],
) -> Result<String> {
    use sha2::{Digest, Sha256};
    let mut digest = Sha256::new();
    for value in std::iter::once(json!({"schema_version":1,"node_fingerprint":node,"instrument_id":instrument,"arrow_schema":schema,"row_count":rows.len()})).chain(rows.iter().cloned()){
        let bytes=onlyalpha_metadata_json::canonical_json(&value.to_string(),8*1024*1024).map_err(|_|INVALID)?;
        digest.update((bytes.len() as u64).to_be_bytes());digest.update(bytes.as_bytes());
    }
    Ok(digest
        .finalize()
        .iter()
        .map(|b| format!("{b:02x}"))
        .collect())
}
pub(super) fn calculation_content(partitions: &[Value]) -> Result<String> {
    let mut rows=partitions.iter().map(|p|json!({"node_fingerprint":p["node_fingerprint"],"instrument_id":p["instrument_id"],"row_count":p["row_count"],"semantic_fingerprint":p["semantic_fingerprint"],"arrow_schema":p["arrow_schema"]})).collect::<Vec<_>>();
    rows.sort_by_key(|p| {
        (
            p["node_fingerprint"].as_str().unwrap_or("").to_owned(),
            p["instrument_id"].as_str().unwrap_or("").to_owned(),
        )
    });
    hash(&json!({"schema_version":1,"partitions":rows}))
}
