//! Actual new-work profile selection and original logical economics.
const FIXTURE:&str=include_str!("../../../test-data/execution/domain-inputs.json");
const SETTLEMENT_FIXTURE:&str=include_str!("../../../test-data/settlement/common-v1.json");
#[path="../../execution/tests/support/mod.rs"] mod support;
use onlyalpha_runtime::Runtime;
use onlyalpha_execution::digest;
use serde_json::{Value,json};
use std::{fs,path::PathBuf,sync::atomic::{AtomicU64,Ordering}};
static NEXT:AtomicU64=AtomicU64::new(0);
struct Root(PathBuf);
impl Root {fn new()->Self{let path=std::env::temp_dir().join(format!("oa-storage4-{}-{}",std::process::id(),NEXT.fetch_add(1,Ordering::Relaxed)));fs::create_dir(&path).unwrap();Self(path)}}
impl Drop for Root {fn drop(&mut self){fs::remove_dir_all(&self.0).unwrap();}}
#[test]
fn new_work_explicitly_selects_dictionary_storage4_while_preserving_complete_logical_execution() {
    let root=Root::new();let mut runtime=Runtime::create(&root.0,support::config(),&"b".repeat(64)).unwrap();
    for value in [support::open(1,"BUY"),support::stage(2,1,"UNKNOWN"),support::fill(3,1,"1","10.00","1.00"),support::terminal(4,1,"CANCELLED")] {runtime.apply(&value).unwrap();}
    let original=runtime.records().unwrap();let state=runtime.state().unwrap();let events=runtime.pending_events().unwrap();
    let db=rusqlite::Connection::open(root.0.join("runtime.sqlite3")).unwrap();
    let version:i64=db.pragma_query_value(None,"user_version",|row|row.get(0)).unwrap();
    assert_eq!(version,4,"new Work must explicitly select the dictionary codec; schema2/3 readers retain exact historical meanings");
    let mut statement=db.prepare("SELECT sequence,payload,digest,ready,delivered FROM records ORDER BY sequence").unwrap();
    let rows=statement.query_map([],|row|Ok((row.get::<_,i64>(0)?,row.get::<_,String>(1)?,row.get::<_,String>(2)?,row.get::<_,i64>(3)?,row.get::<_,i64>(4)?))).unwrap().collect::<rusqlite::Result<Vec<_>>>().unwrap();
    let anchor_physical=rows[0].2.clone();let anchor_logical=digest(original[0].prepared().record().to_string().as_bytes());
    for (sequence,raw,physical,ready,delivered) in rows {
        let frame:Value=serde_json::from_str(&raw).unwrap();
        assert_eq!(frame["codec"],"ZSTD_CANONICAL_JSON_DICTIONARY_V1");
        assert_eq!(physical,digest(raw.as_bytes()));
        assert_eq!(frame["logical_sha256"],digest(original[sequence as usize-1].prepared().record().to_string().as_bytes()));
        assert_eq!((ready,delivered),(1,0));
        if sequence==1 {assert_eq!(frame["basis"],Value::Null);}else{
            assert_eq!(frame["basis"],json!({"sequence":1,"physical_sha256":anchor_physical,"logical_sha256":anchor_logical}));
        }
    }
    drop(statement);drop(db);drop(runtime);
    let reopened=Runtime::open(&root.0,support::config(),&"b".repeat(64)).unwrap();
    assert_eq!(reopened.records().unwrap(),original);assert_eq!(reopened.state().unwrap(),state);assert_eq!(reopened.pending_events().unwrap(),events);drop(reopened);
}
