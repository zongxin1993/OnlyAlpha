use crate::{OnlyConstructionError,OnlyConstructionResult};
use onlyalpha_domain::base::OnlyDomainModel;
use serde_json::{Map,Value,Number};
use std::str::FromStr;
use sha2::{Digest,Sha256};
pub(crate) fn err(message:impl ToString)->OnlyConstructionError{OnlyConstructionError::Validation(message.to_string())}
pub(crate) fn object<'a>(v:&'a Value,version:u64,fields:&[&str])->OnlyConstructionResult<&'a Map<String,Value>>{let row=v.as_object().ok_or_else(||err("OBJECT_REQUIRED"))?;if row.len()!=fields.len()+1 || row.get("schema_version").and_then(Value::as_u64)!=Some(version) || fields.iter().any(|f|!row.contains_key(*f)){return Err(err("RECORD_FIELDS_OR_SCHEMA"));}Ok(row)}
pub(crate) fn text(v:&Value)->OnlyConstructionResult<&str>{v.as_str().ok_or_else(||err("TEXT_REQUIRED"))}
pub(crate) fn nonempty(v:&str)->OnlyConstructionResult<()>{if v.trim().is_empty(){return Err(err("EMPTY_IDENTITY"));}Ok(())}
pub(crate) fn array(v:&Value)->OnlyConstructionResult<&Vec<Value>>{v.as_array().ok_or_else(||err("ARRAY_REQUIRED"))}
pub(crate) fn integer<T:FromStr>(v:&Value)->OnlyConstructionResult<T>{v.as_number().ok_or_else(||err("INTEGER_REQUIRED"))?.to_string().parse().map_err(|_|err("INTEGER_REQUIRED"))}
pub(crate) fn number(v:impl ToString)->Value{Value::Number(Number::from_str(&v.to_string()).expect("integer spelling"))}
pub(crate) fn domain<T:OnlyDomainModel>(v:&Value)->OnlyConstructionResult<T>{T::from_record(v).map_err(err)}
pub(crate) fn hash(v:&Value)->String{use std::fmt::Write;let mut result=String::with_capacity(64);for byte in Sha256::digest(v.to_string().as_bytes()){write!(&mut result,"{byte:02x}").expect("string write");}result}
pub(crate) fn digest(v:&str)->OnlyConstructionResult<()>{if v.len()!=64 || !v.bytes().all(|b|b.is_ascii_digit() || (b'a'..=b'f').contains(&b)){return Err(err("FINGERPRINT_INVALID"));}Ok(())}
