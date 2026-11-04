//! Explicit storage4 physical encoding; a decoded value grants no execution
//! or source freshness. The Store observes the actual base and target rows.
use base64::{Engine, engine::general_purpose::STANDARD};
use onlyalpha_execution::{Error, digest};
use serde_json::{Value, json};

pub(crate) const NAME: &str = "ZSTD_CANONICAL_JSON_DICTIONARY_V1";
pub(crate) const LIMIT: usize = crate::codec::LIMIT;
const STORED_LIMIT: usize = 16 * 1024 * 1024;
const PERIOD: u64 = 16;
const MAGIC: [u8; 4] = [0x28, 0xb5, 0x2f, 0xfd];
fn bad() -> Error { Error("RUNTIME_STORAGE_DICTIONARY_CODEC_INVALID".into()) }
fn exact(value: &Value, fields: &[&str]) -> Result<(), Error> {
    if value.as_object().is_none_or(|object| object.len()!=fields.len() || fields.iter().any(|field| !object.contains_key(*field))) { Err(bad()) } else { Ok(()) }
}
fn pin(value: &Value) -> Result<String, Error> {
    value.as_str().filter(|value| value.len()==64 && value.bytes().all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))).map(str::to_owned).ok_or_else(bad)
}
pub(crate) fn anchor_sequence(sequence: u64) -> Result<u64, Error> {
    let previous=sequence.checked_sub(1).ok_or_else(bad)?;
    Ok(previous/PERIOD*PERIOD+1)
}
#[derive(Clone)]
pub(crate) struct Basis {
    pub sequence: u64,
    pub physical: String,
    pub logical: String,
}
pub(crate) struct Frame {
    pub logical: String,
    pub size: usize,
    pub summary: Value,
    pub basis: Option<Basis>,
    sequence: u64,
    physical: String,
    data: String,
}
/// Immutable codec data only. Its fields cannot be filled by a parsed DTO.
/// Reusing it requires the Store to observe the same actual complete base row.
pub(crate) struct Anchor {
    sequence: u64,
    physical: String,
    logical: String,
    bytes: Vec<u8>,
}
impl Anchor {
    pub(crate) fn sequence(&self) -> u64 { self.sequence }
    pub(crate) fn physical(&self) -> &str { &self.physical }
    pub(crate) fn logical(&self) -> &str { &self.logical }
    pub(crate) fn bytes(&self) -> &[u8] { &self.bytes }
}
fn basis_for(sequence: u64, anchor: Option<&Anchor>) -> Result<Option<Basis>, Error> {
    let expected=anchor_sequence(sequence)?;
    if sequence==expected {
        if anchor.is_some() { return Err(bad()); }
        Ok(None)
    } else {
        let anchor=anchor.filter(|anchor| anchor.sequence==expected).ok_or_else(bad)?;
        Ok(Some(Basis { sequence: expected, physical: anchor.physical.clone(), logical: anchor.logical.clone() }))
    }
}
#[cfg(test)]
pub(crate) fn encode(value: &Value, summary: Value, sequence: u64, anchor: Option<&Anchor>) -> Result<String, Error> {
    let bytes=serde_json::to_vec(value)?;
    encode_bytes(&bytes,summary,sequence,anchor)
}
// Canonical bytes from the same operation only; this encodes data, not proof.
pub(crate) fn encode_bytes(bytes: &[u8], summary: Value, sequence: u64, anchor: Option<&Anchor>) -> Result<String, Error> {
    let basis=basis_for(sequence,anchor)?;
    if bytes.len()>LIMIT { return Err(bad()); }
    // Dedicated bulk-only contexts never enter a stream, clone an unfinished
    // context, train a dictionary, use seekable IO or expose uninitialized Vec.
    let mut compressor=match anchor {
        Some(anchor)=>zstd::bulk::Compressor::with_dictionary(3,anchor.bytes()),
        None=>zstd::bulk::Compressor::new(3),
    }.map_err(|_|bad())?;
    compressor.include_contentsize(true).map_err(|_|bad())?;
    compressor.include_checksum(true).map_err(|_|bad())?;
    compressor.window_log(23).map_err(|_|bad())?;
    let compressed=compressor.compress(bytes).map_err(|_|bad())?;
    let basis=basis.map(|basis| json!({"sequence":basis.sequence,"physical_sha256":basis.physical,"logical_sha256":basis.logical}));
    let raw=json!({"schema_version":1,"codec":NAME,"logical_sha256":digest(bytes),"logical_size":bytes.len(),"summary":summary,"basis":basis,"data":STANDARD.encode(compressed)}).to_string();
    if raw.len()>STORED_LIMIT { return Err(bad()); }
    Ok(raw)
}
pub(crate) fn inspect(raw: &str, physical: &str, sequence: u64) -> Result<Frame, Error> {
    if raw.len()>STORED_LIMIT { return Err(bad()); }
    #[cfg(test)] crate::codec::PHYSICAL_HASHES.with(|count|count.set(count.get()+1));
    if digest(raw.as_bytes())!=physical { return Err(bad()); }
    let value:Value=serde_json::from_str(raw)?;
    exact(&value,&["schema_version","codec","logical_sha256","logical_size","summary","basis","data"])?;
    if value.to_string()!=raw || value["schema_version"]!=1 || value["codec"]!=NAME { return Err(bad()); }
    let logical=pin(&value["logical_sha256"])?;
    let size=usize::try_from(value["logical_size"].as_u64().ok_or_else(bad)?).map_err(|_|bad())?;
    if size>LIMIT { return Err(bad()); }
    let data=value["data"].as_str().filter(|data|data.len()<=STORED_LIMIT).ok_or_else(bad)?.to_owned();
    let expected=anchor_sequence(sequence)?;
    let basis=if sequence==expected {
        if !value["basis"].is_null() { return Err(bad()); } None
    } else {
        let basis=&value["basis"];
        exact(basis,&["sequence","physical_sha256","logical_sha256"])?;
        if basis["sequence"].as_u64()!=Some(expected) { return Err(bad()); }
        Some(Basis { sequence: expected, physical:pin(&basis["physical_sha256"])?, logical:pin(&basis["logical_sha256"])? })
    };
    Ok(Frame { logical,size,summary:value["summary"].clone(),basis,sequence,physical:physical.to_owned(),data })
}
fn decode_bytes(frame: &Frame, anchor: Option<&Anchor>) -> Result<(Value,Vec<u8>), Error> {
    let basis=basis_for(frame.sequence,anchor)?;
    if !match (&frame.basis,&basis) {
        (None,None)=>true,
        (Some(expected),Some(actual))=>expected.sequence==actual.sequence && expected.physical==actual.physical && expected.logical==actual.logical,
        _=>false,
    } { return Err(bad()); }
    if frame.size>LIMIT { return Err(bad()); }
    let compressed=STANDARD.decode(&frame.data).map_err(|_|bad())?;
    if STANDARD.encode(&compressed)!=frame.data || !compressed.starts_with(&MAGIC) { return Err(bad()); }
    // Zstd's one-shot API permits concatenated/skippable frames. This format
    // admits exactly one regular frame and an exact bounded declared size.
    if zstd::zstd_safe::find_frame_compressed_size(&compressed).map_err(|_|bad())?!=compressed.len()
        || zstd::zstd_safe::get_frame_content_size(&compressed).map_err(|_|bad())?!=Some(frame.size as u64) { return Err(bad()); }
    let mut output=vec![0_u8;frame.size];
    let mut decoder=match anchor {
        Some(anchor)=>zstd::bulk::Decompressor::with_dictionary(anchor.bytes()),
        None=>zstd::bulk::Decompressor::new(),
    }.map_err(|_|bad())?;
    let count=decoder.decompress_to_buffer(&compressed,output.as_mut_slice()).map_err(|_|bad())?;
    if count!=frame.size || digest(&output)!=frame.logical { return Err(bad()); }
    #[cfg(test)] crate::codec::DECODED_BYTES.with(|counter|counter.set(counter.get()+count as u64));
    let value:Value=serde_json::from_slice(&output)?;
    if serde_json::to_vec(&value)?!=output { return Err(bad()); }
    Ok((value,output))
}
pub(crate) fn decode(frame: &Frame, anchor: Option<&Anchor>) -> Result<Value, Error> {
    decode_bytes(frame,anchor).map(|(value,_)|value)
}
pub(crate) fn decode_anchor(frame: &Frame) -> Result<(Value,Anchor), Error> {
    if frame.sequence!=anchor_sequence(frame.sequence)? || frame.basis.is_some() { return Err(bad()); }
    let (value,bytes)=decode_bytes(frame,None)?;
    Ok((value,Anchor { sequence:frame.sequence,physical:frame.physical.clone(),logical:frame.logical.clone(),bytes }))
}
#[cfg(test)]
#[path="dictionary_codec_tests.rs"]
mod tests;
