//! Retained physical witnesses, never a caller-provided semantic capability.
use super::super::{Directory,SourceLock,INVALID,UNAVAILABLE,LIMIT,Result};
use crate::persistence::research_runtime::RuntimeEvidenceHold;
use crate::security::protected_files::{self as protected,ReadError};
use rustix::fs;
use serde_json::Value;
use std::{ffi::OsStr,fs::File,io::{Read,Seek},os::fd::AsFd,path::Path,sync::Arc};

pub(crate) struct ReadCut {
    pub(crate) runtime:Arc<RuntimeEvidenceHold>,
    pub(crate) files:Vec<Witness>,
    pub(crate) locks:Vec<Arc<SourceLock>>,
}
impl ReadCut {
    pub(crate) fn verify(&self)->Result<()> {
        if self.locks.is_empty() || self.files.is_empty(){return Err(INVALID);}
        for source in &self.locks{source.verify()?;}
        self.runtime.verify()?;
        for file in &self.files{file.verify()?;}
        Ok(())
    }
}
pub(crate) struct Witness {directory:Directory,name:String,digest:String,size:u64,inode:u64,device:u64}
impl Witness {
    pub(crate) fn verify(&self)->Result<()>{
        self.directory.verify()?;
        let (raw,file)=read_file(&self.directory,&self.name)?;
        let stat=fs::fstat(file.as_fd()).map_err(|_|UNAVAILABLE)?;
        if stat.st_ino!=self.inode || stat.st_dev!=self.device || stat.st_size as u64!=self.size || byte_sha(&raw)!=self.digest {return Err(INVALID);}
        self.directory.verify()
    }
}
pub(crate) fn byte_sha(raw:&[u8])->String{
    use sha2::{Digest,Sha256};Sha256::digest(raw).iter().map(|b|format!("{b:02x}")).collect()
}
pub(crate) fn read_file(directory:&Directory,name:&str)->Result<(Vec<u8>,File)>{
    if name.is_empty()||matches!(name,"."|"..")||name.contains('/')||name.contains('\\')||name.contains('\0'){return Err(INVALID);}
    directory.verify()?;
    let fd=fs::openat(&directory.fd,name,fs::OFlags::RDONLY|fs::OFlags::NOFOLLOW|fs::OFlags::NONBLOCK|fs::OFlags::CLOEXEC,fs::Mode::empty()).map_err(|e|if matches!(e,rustix::io::Errno::NOENT|rustix::io::Errno::LOOP|rustix::io::Errno::NOTDIR){INVALID}else{UNAVAILABLE})?;
    let stat=fs::fstat(&fd).map_err(|_|UNAVAILABLE)?;
    if fs::FileType::from_raw_mode(stat.st_mode)!=fs::FileType::RegularFile || stat.st_nlink!=1 || stat.st_mode&0o022!=0
        || (stat.st_uid!=0&&stat.st_uid!=rustix::process::geteuid().as_raw()) || stat.st_size<0 || stat.st_size as u64>LIMIT as u64{return Err(INVALID);}
    let mut file=File::from(fd);let mut raw=Vec::new();
    file.by_ref().take(LIMIT as u64+1).read_to_end(&mut raw).map_err(|_|UNAVAILABLE)?;
    if raw.len()!=stat.st_size as usize{return Err(INVALID);}
    file.rewind().map_err(|_|UNAVAILABLE)?;
    Ok((raw,file))
}
pub(crate) fn witness(directory:&Directory,name:&str,raw:&[u8],file:&File)->Result<Witness>{
    let stat=fs::fstat(file.as_fd()).map_err(|_|UNAVAILABLE)?;
    let directory=Directory{path:directory.path.clone(),fd:protected::duplicate_directory(directory.fd.as_fd()).map_err(|_|UNAVAILABLE)?};
    Ok(Witness{directory,name:name.into(),digest:byte_sha(raw),size:raw.len() as u64,inode:stat.st_ino,device:stat.st_dev})
}
pub(crate) fn document(directory:&Directory,name:&str,witnesses:&mut Vec<Witness>)->Result<Value>{
    let (bytes,file)=read_file(directory,name)?;
    let value=crate::security::immutable_json::parsed(&bytes).map_err(|_|INVALID)?;
    witnesses.push(witness(directory,name,&bytes,&file)?);Ok(value)
}
pub(crate) fn optional_directory(root:&Directory,parts:&[&str])->Result<Option<Directory>>{
    root.verify()?;let mut path=root.path.clone();let mut fd=protected::duplicate_directory(root.fd.as_fd()).map_err(|_|UNAVAILABLE)?;
    for part in parts{
        if part.is_empty()||matches!(*part,"."|"..")||part.contains('/')||part.contains('\\')||part.contains('\0'){return Err(INVALID);}
        fd=match protected::open_directory_at(&fd,OsStr::new(part)){Ok(fd)=>fd,Err(ReadError::Missing)=>return Ok(None),Err(ReadError::Invalid)=>return Err(INVALID),Err(_)=>return Err(UNAVAILABLE)};
        path.push(part);
    }Ok(Some(Directory{path,fd}))
}
pub(crate) fn exact_files(directory:&Directory,names:&[&str])->Result<()>{
    let mut expected=names.iter().map(|n|(*n).to_owned()).collect::<Vec<_>>();expected.sort();
    if directory.names()?!=expected{return Err(INVALID);}Ok(())
}
pub(crate) fn data_file(directory:&Directory,relative:&str,witnesses:&mut Vec<Witness>)->Result<(Vec<u8>,File)>{
    let (parent,name)=relative.rsplit_once('/').unwrap_or(("",relative));
    let parts=parent.split('/').filter(|p|!p.is_empty()).collect::<Vec<_>>();
    let leaf=optional_directory(directory,&parts)?.ok_or(INVALID)?;
    let (bytes,file)=read_file(&leaf,name)?;witnesses.push(witness(&leaf,name,&bytes,&file)?);Ok((bytes,file))
}
pub(crate) fn capture_dataset(root:&Path,manifest:&Value,lineage:&Value,witnesses:&mut Vec<Witness>)->Result<()>{
    let root=Directory::open(root)?;let snapshot=manifest["snapshot_fingerprint"].as_str().filter(|p|crate::is_sha256_hex(p)).ok_or(INVALID)?;
    let leaf=optional_directory(&root,&["sha256",&snapshot[..2],snapshot])?.ok_or(INVALID)?;
    if document(&leaf,"manifest.json",witnesses)?!=*manifest{return Err(INVALID);}
    let partitions=manifest["partitions"].as_array().ok_or(INVALID)?;
    exact_files(&leaf,&["manifest.json","data"])?;
    let mut names=Vec::new();
    for (index,partition) in partitions.iter().enumerate(){let name=format!("data/p-{index:06}.parquet");
        if partition["relative_path"]!=name{return Err(INVALID);}let (raw,_)=data_file(&leaf,&name,witnesses)?;
        if partition["byte_sha256"]!=byte_sha(&raw){return Err(INVALID);}names.push(format!("p-{index:06}.parquet"));}
    let data=optional_directory(&leaf,&["data"])?.ok_or(INVALID)?;
    exact_files(&data,&names.iter().map(String::as_str).collect::<Vec<_>>())?;
    let id=lineage["materialization_id"].as_str().and_then(|p|p.strip_prefix("dataset-materialization:")).filter(|p|crate::is_sha256_hex(p)).ok_or(INVALID)?;
    let materialization=optional_directory(&root,&["materializations","sha256",&id[..2]])?.ok_or(INVALID)?;
    let stored=document(&materialization,&format!("{id}.json"),witnesses)?;
    if stored!=*lineage{return Err(INVALID);}
    Ok(())
}
