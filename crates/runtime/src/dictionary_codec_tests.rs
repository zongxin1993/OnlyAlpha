//! Exact physical-codec vectors; these never construct a Source proof or grant.
use super::*;
use serde_json::json;

fn source(value: &Value, sequence: u64) -> (String, Anchor) {
    let raw = encode(value, json!({"kind":"TEST","sequence":sequence}), sequence, None).unwrap();
    let frame = inspect(&raw, &digest(raw.as_bytes()), sequence).unwrap();
    let (decoded, anchor) = decode_anchor(&frame).unwrap();
    assert_eq!(&decoded, value);
    (raw, anchor)
}
fn altered(raw: &str, change: impl FnOnce(&mut Value)) -> String {
    let mut value: Value = serde_json::from_str(raw).unwrap();
    change(&mut value);
    value.to_string()
}
fn accepts(raw: &str, sequence: u64, anchor: Option<&Anchor>) -> bool {
    inspect(raw, &digest(raw.as_bytes()), sequence).and_then(|frame| decode(&frame, anchor)).is_ok()
}
#[test]
fn fixed_anchor_dictionary_roundtrip_preserves_the_full_canonical_value() {
    let original = json!({"integer":18446744073709551615_u64,"decimal":"0.00000001","history":(0..4096).map(|n|json!({"n":n,"hash":digest(n.to_string().as_bytes())})).collect::<Vec<_>>()});
    let (raw, anchor) = source(&original, 1);
    assert_eq!(anchor.sequence(), 1);
    assert_eq!(anchor.physical(), digest(raw.as_bytes()));
    assert_eq!(anchor.logical(), digest(original.to_string().as_bytes()));
    assert_eq!(anchor.bytes(), original.to_string().as_bytes());
    let mut next = original.clone(); next["new"]=json!({"receipt":"actual complete new command","decimal":"123.456789"});
    let encoded = encode(&next, json!({"kind":"TEST"}), 2, Some(&anchor)).unwrap();
    let frame = inspect(&encoded, &digest(encoded.as_bytes()), 2).unwrap();
    assert_eq!(decode(&frame, Some(&anchor)).unwrap(), next);
    assert_eq!(frame.logical, digest(next.to_string().as_bytes()));
    assert_eq!(frame.size, next.to_string().len());
    assert_eq!(frame.basis.as_ref().unwrap().sequence, 1);
    assert_eq!(frame.basis.as_ref().unwrap().physical, anchor.physical());
    assert_eq!(frame.basis.as_ref().unwrap().logical, anchor.logical());
    let legacy = crate::codec::encode(&next, json!({"kind":"TEST"})).unwrap();
    assert!(encoded.len() * 8 < legacy.len(), "dictionary encoding should remove actual growing snapshot repetition: {} vs {}", encoded.len(), legacy.len());
    // A cold independent decoder must reconstruct the same original value.
    let cold = inspect(&raw, &digest(raw.as_bytes()), 1).unwrap();
    let (_, cold_anchor) = decode_anchor(&cold).unwrap();
    assert_eq!(decode(&frame, Some(&cold_anchor)).unwrap(), next);
}
#[test]
fn dictionary_bases_are_fixed_non_recursive_and_match_both_original_digests() {
    let value=json!({"history":"same complete original history".repeat(4096)});
    let (_, anchor)=source(&value,1); let (_, next_anchor)=source(&value,17);
    for n in [2,16] {
        let raw=encode(&value,json!({}),n,Some(&anchor)).unwrap();
        assert!(accepts(&raw,n,Some(&anchor)));
        assert!(!accepts(&raw,n,None));
        assert!(!accepts(&raw,n,Some(&next_anchor)));
        assert!(decode_anchor(&inspect(&raw,&digest(raw.as_bytes()),n).unwrap()).is_err());
        for field in ["sequence","physical_sha256","logical_sha256"] {
            let changed=altered(&raw,|v| v["basis"][field]=if field=="sequence"{json!(17)}else{json!("f".repeat(64))});
            assert!(!accepts(&changed,n,Some(&anchor)),"{field}");
        }
        let missing=altered(&raw,|v|v["basis"]=Value::Null);
        assert!(!accepts(&missing,n,Some(&anchor)));
    }
    assert!(encode(&value,json!({}),17,Some(&anchor)).is_err());
    assert!(encode(&value,json!({}),18,Some(&anchor)).is_err());
    assert!(encode(&value,json!({}),0,None).is_err());
    for n in [1,17,33] {assert_eq!(anchor_sequence(n).unwrap(),n);}
    assert_eq!(anchor_sequence(32).unwrap(),17);
    assert_eq!(anchor_sequence(u64::MAX).unwrap(),u64::MAX-14);
    // Even identical logical base bytes from a differently encoded physical
    // frame cannot silently replace the originally pinned anchor.
    let (raw, original)=source(&value,1);
    let physical_changed=altered(&raw,|v|{
        v["summary"]["physical_observation"]=json!("different encoded frame, same complete logical bytes");
    });
    assert_ne!(raw,physical_changed);
    let (_, different)=decode_anchor(&inspect(&physical_changed,&digest(physical_changed.as_bytes()),1).unwrap()).unwrap();
    assert_eq!(original.logical(),different.logical());
    let target=encode(&value,json!({}),2,Some(&original)).unwrap();
    assert!(!accepts(&target,2,Some(&different)));
}
#[test]
fn exact_single_zstd_frame_refuses_truncation_tail_concatenation_skippable_legacy_and_bombs() {
    let value=json!({"retained":"original full bytes".repeat(8192)});
    let (raw,anchor)=source(&value,1);
    for (sequence,base) in [(1,None),(2,Some(&anchor))] {
        let raw=if sequence==1{raw.clone()}else{encode(&value,json!({}),2,base).unwrap()};
        for fault in ["truncated","tail","concat","skippable","legacy","declared-small","declared-large","hash","base64","noncanonical-json","unknown-codec","extra-field"] {
            let changed=altered(&raw,|v|{
                let mut data=STANDARD.decode(v["data"].as_str().unwrap()).unwrap();
                match fault {
                    "truncated"=>{data.pop();},
                    "tail"=>data.push(0),
                    "concat"=>{let second=data.clone();data.extend(second);},
                    "skippable"=>data=vec![0x50,0x2a,0x4d,0x18,0,0,0,0],
                    "legacy"=>data=vec![0x24,0xb5,0x2f,0xfd,0,0],
                    "declared-small"=>v["logical_size"]=json!(1),
                    "declared-large"=>v["logical_size"]=json!(LIMIT+1),
                    "hash"=>v["logical_sha256"]=json!("f".repeat(64)),
                    "base64"=>v["data"]=json!("!!!!"),
                    "noncanonical-json"=>{
                        let invalid=b"{ \"a\": 1}";
                        let mut compressor=zstd::bulk::Compressor::new(3).unwrap();
                        data=compressor.compress(invalid).unwrap();v["logical_size"]=json!(invalid.len());v["logical_sha256"]=json!(digest(invalid));
                    },
                    "unknown-codec"=>v["codec"]=json!("UNKNOWN"),
                    _=>v["extra"]=json!(true),
                }
                if matches!(fault,"truncated"|"tail"|"concat"|"skippable"|"legacy"|"noncanonical-json"){v["data"]=json!(STANDARD.encode(data));}
            });
            assert!(!accepts(&changed,sequence,base),"{sequence}/{fault}");
        }
        assert!(inspect(&raw,&"f".repeat(64),sequence).is_err());
        let noncanonical=raw+" ";assert!(!accepts(&noncanonical,sequence,base));
    }
    let huge=json!({"history":"x".repeat(LIMIT+1)});
    assert!(encode(&huge,json!({}),1,None).is_err());
    assert!(encode(&huge,json!({}),2,Some(&anchor)).is_err());
    let oversized=" ".repeat(STORED_LIMIT+1);assert!(inspect(&oversized,&digest(oversized.as_bytes()),1).is_err());
}
