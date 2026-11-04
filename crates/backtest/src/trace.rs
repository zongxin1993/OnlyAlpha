//! Canonical trace transport. Only the owning caller can authenticate its source.
use crate::{Error,err};
use onlyalpha_runtime::ReplayEntryRef;
use serde_json::Value;
use sha2::{Digest,Sha256};
use std::io::{self,Write};
const BOUND:usize=128*1024*1024;
fn output<T>(result:io::Result<T>)->Result<T,Error>{result.map_err(|error|err(&format!("TRACE_OUTPUT_{error}")))}
fn bytes(writer:&mut dyn Write,raw:&[u8])->Result<(),Error>{output(writer.write_all(raw))}
fn json(writer:&mut dyn Write,value:&Value)->Result<(),Error>{serde_json::to_writer(writer,value).map_err(|error|err(&format!("TRACE_OUTPUT_{error}")))}
// Value's canonical map ordering is binding,inputs,schema_version,state,steps.
pub(crate) fn logical(writer:&mut dyn Write,binding:&Value,inputs:&Value,state:&Value,refs:&[ReplayEntryRef],mut read:impl FnMut(&ReplayEntryRef)->Result<Value,Error>)->Result<(),Error>{
    bytes(writer,b"{\"binding\":")?;json(writer,binding)?;bytes(writer,b",\"inputs\":")?;json(writer,inputs)?;
    bytes(writer,b",\"schema_version\":1,\"state\":")?;json(writer,state)?;bytes(writer,b",\"steps\":[")?;
    for (index,reference) in refs.iter().enumerate(){
        if index>0{bytes(writer,b",")?;}
        bytes(writer,if reference.ready(){b"{\"ready\":true,\"step\":"}else{b"{\"ready\":false,\"step\":"})?;
        let step=read(reference)?;json(writer,&step)?;bytes(writer,b"}")?;
    }
    bytes(writer,b"]}")
}
// Each actual canonical SQL frame is copied once, without logical expansion.
pub(crate) fn encoded(writer:&mut dyn Write,binding:&Value,inputs:&Value,state:&Value,refs:&[ReplayEntryRef],mut write:impl FnMut(&ReplayEntryRef,&mut dyn Write)->Result<u64,Error>)->Result<(),Error>{
    let mut writer=Limited{writer,total:0};let writer=&mut writer;
    bytes(writer,b"{\"binding\":")?;json(writer,binding)?;bytes(writer,b",\"inputs\":")?;json(writer,inputs)?;
    bytes(writer,b",\"kind\":\"RUNTIME_ENCODED_REPLAY_TRACE\",\"schema_version\":2,\"state\":")?;json(writer,state)?;bytes(writer,b",\"steps\":[")?;
    for (index,reference) in refs.iter().enumerate(){
        if index>0{bytes(writer,b",")?;}bytes(writer,b"{\"entry\":")?;
        let size=write(reference,writer)?;
        if size!=reference.encoded_size(){return Err(err("TRACE_ENCODED_SIZE"));}
        bytes(writer,if reference.ready(){b",\"ready\":true}"}else{b",\"ready\":false}"})?;
    }
    bytes(writer,b"]}")
}
pub(crate) fn bounded(writer:&mut dyn Write,write:impl FnOnce(&mut dyn Write)->Result<(),Error>)->Result<(),Error>{
    write(&mut Limited{writer,total:0})
}
struct Limited<'a>{writer:&'a mut dyn Write,total:usize}
impl Write for Limited<'_>{
    fn write(&mut self,raw:&[u8])->io::Result<usize>{
        if self.total.checked_add(raw.len()).is_none_or(|n|n>BOUND){return Err(io::Error::other("trace exceeds 128 MiB"));}
        let n=self.writer.write(raw)?;self.total+=n;Ok(n)
    }
    fn flush(&mut self)->io::Result<()>{self.writer.flush()}
}
struct Hash(Sha256);
impl Write for Hash{
    fn write(&mut self,raw:&[u8])->io::Result<usize>{self.0.update(raw);Ok(raw.len())}
    fn flush(&mut self)->io::Result<()>{Ok(())}
}
pub(crate) fn fingerprint(write:impl FnOnce(&mut dyn Write)->Result<(),Error>)->Result<String,Error>{
    let mut writer=Hash(Sha256::new());
    {let mut buffered=io::BufWriter::with_capacity(64*1024,&mut writer);write(&mut buffered)?;output(buffered.flush())?;}
    Ok(writer.0.finalize().iter().map(|byte|format!("{byte:02x}")).collect())
}
pub(crate) fn value(write:impl FnOnce(&mut dyn Write)->Result<(),Error>)->Result<Value,Error>{
    let mut raw=Vec::new();write(&mut Limited{writer:&mut raw,total:0})?;
    serde_json::from_slice(&raw).map_err(|error|err(&format!("TRACE_JSON_{error}")))
}


#[cfg(test)]
mod archive_bound_tests {
    use super::*;
    struct Count(usize);
    impl Write for Count {
        fn write(&mut self,raw:&[u8])->io::Result<usize>{self.0+=raw.len();Ok(raw.len())}
        fn flush(&mut self)->io::Result<()>{Ok(())}
    }
    #[test]
    fn archive_writer_refuses_the_next_byte_without_sending_it_to_the_consumer() {
        let mut sink=Count(0);let chunk=[0_u8;64*1024];
        let result=bounded(&mut sink,|writer|{
            for _ in 0..BOUND/chunk.len(){output(writer.write_all(&chunk))?;}
            output(writer.write_all(b"x"))
        });
        assert!(result.is_err());assert_eq!(sink.0,BOUND,"the cap applies to actual consumer bytes, not only a later buffer check");
    }
}
