//! Physical storage only. Neither an encoded frame nor its SHA grants execution.
use onlyalpha_execution::{Error,digest};
use serde_json::{Value,json};
use base64::{Engine,engine::general_purpose::STANDARD};
use flate2::{Compression,Decompress,FlushDecompress,Status,write::ZlibEncoder};
use std::io::Write;
pub(crate) const LIMIT:usize=8*1024*1024;
pub(crate) const STORED_LIMIT:usize=16*1024*1024;
const NAME:&str="ZLIB_CANONICAL_JSON_V1";
#[cfg(test)]
std::thread_local!{
 pub(crate) static DECODED_BYTES:std::cell::Cell<u64>=const{std::cell::Cell::new(0)};
 pub(crate) static PHYSICAL_HASHES:std::cell::Cell<u64>=const{std::cell::Cell::new(0)};
}
fn bad()->Error{Error("RUNTIME_STORAGE_CODEC_INVALID".into())}
pub(crate) struct Frame {pub logical:String,pub size:usize,pub summary:Value,data:String}
fn exact(v:&Value,keys:&[&str])->Result<(),Error>{if v.as_object().is_none_or(|m|m.len()!=keys.len()||keys.iter().any(|k|!m.contains_key(*k))){Err(bad())}else{Ok(())}}
pub(crate) fn encode(value:&Value,summary:Value)->Result<String,Error>{
 let bytes=serde_json::to_vec(value)?;encode_bytes(&bytes,summary)
}
// Internal callers supply this operation's canonical bytes. The reader still
// verifies the full logical digest and canonical JSON before accepting data.
pub(crate) fn encode_bytes(bytes:&[u8],summary:Value)->Result<String,Error>{
 if bytes.len()>LIMIT{return Err(bad());}
 let mut encoder=ZlibEncoder::new(Vec::new(),Compression::fast());encoder.write_all(bytes).map_err(|_|bad())?;let compressed=encoder.finish().map_err(|_|bad())?;
 let frame=json!({"schema_version":1,"codec":NAME,"logical_sha256":digest(bytes),"logical_size":bytes.len(),"summary":summary,"data":STANDARD.encode(compressed)}).to_string();
 if frame.len()>STORED_LIMIT{return Err(bad());}Ok(frame)
}
pub(crate) fn inspect(raw:&str,physical:&str)->Result<Frame,Error>{
 if raw.len()>STORED_LIMIT||{
  #[cfg(test)] PHYSICAL_HASHES.with(|count|count.set(count.get()+1));
  digest(raw.as_bytes())!=physical
 }{return Err(bad());}
 let v:Value=serde_json::from_str(raw)?;exact(&v,&["schema_version","codec","logical_sha256","logical_size","summary","data"])?;
 let canonical = v.to_string();
 if canonical.as_str()!=raw||v["schema_version"]!=1||v["codec"]!=NAME{return Err(bad());}
 let logical=v["logical_sha256"].as_str().filter(|s|s.len()==64&&s.bytes().all(|b|b.is_ascii_digit()||(b'a'..=b'f').contains(&b))).ok_or_else(bad)?.to_owned();
 let size=usize::try_from(v["logical_size"].as_u64().ok_or_else(bad)?).map_err(|_|bad())?;if size>LIMIT{return Err(bad());}
 let data=v["data"].as_str().filter(|s|s.len()<=STORED_LIMIT).ok_or_else(bad)?.to_owned();
 Ok(Frame{logical,size,summary:v["summary"].clone(),data})
}
pub(crate) fn decode(frame:&Frame)->Result<Value,Error>{
 if frame.size>LIMIT{return Err(bad());}
 let compressed=STANDARD.decode(&frame.data).map_err(|_|bad())?;if STANDARD.encode(&compressed)!=frame.data{return Err(bad());}
 let mut output=vec![0;frame.size.checked_add(1).ok_or_else(bad)?];let mut decoder=Decompress::new(true);
 let status=decoder.decompress(&compressed,&mut output,FlushDecompress::Finish).map_err(|_|bad())?;
 if status!=Status::StreamEnd||decoder.total_in()!=compressed.len() as u64||decoder.total_out()!=frame.size as u64{return Err(bad());}
 #[cfg(test)] DECODED_BYTES.with(|count|count.set(count.get()+decoder.total_out()));
 output.truncate(frame.size);if digest(&output)!=frame.logical{return Err(bad());}
 let value:Value=serde_json::from_slice(&output)?;if serde_json::to_vec(&value)?!=output{return Err(bad());}Ok(value)
}
#[cfg(test)]
mod tests {
 use super::*;
 #[test]fn exact_lossless_codec_rejects_truncation_tail_concat_unknown_and_bombs(){
  let value=json!({"large":"complete-seen-history".repeat(2048),"decimal":"0.00000001","integer":18446744073709551615_u64});
  let raw=encode(&value,json!({"kind":"TEST"})).unwrap();let original:Value=serde_json::from_str(&raw).unwrap();let frame=inspect(&raw,&digest(raw.as_bytes())).unwrap();assert_eq!(decode(&frame).unwrap(),value);
  for fault in ["truncated","tail","concat","size-small","size-big","hash","codec","base64"] {
   let mut changed=original.clone();let mut data=STANDARD.decode(changed["data"].as_str().unwrap()).unwrap();
   match fault {"truncated"=>{data.pop();},"tail"=>data.push(0),"concat"=>{let second=data.clone();data.extend(second);},"size-small"=>changed["logical_size"]=json!(1),"size-big"=>changed["logical_size"]=json!(LIMIT+1),"hash"=>changed["logical_sha256"]=json!("f".repeat(64)),"codec"=>changed["codec"]=json!("UNKNOWN"),_=>changed["data"]=json!("!!!!")}
   if matches!(fault,"truncated"|"tail"|"concat"){changed["data"]=json!(STANDARD.encode(data));}
   let raw=changed.to_string();assert!(inspect(&raw,&digest(raw.as_bytes())).and_then(|f|decode(&f)).is_err(),"{fault}");
  }
  let oversized=json!({"history":"x".repeat(LIMIT+1)});assert!(encode(&oversized,json!({})).is_err());
 }
}
