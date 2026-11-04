//! Rebuildable immutable transition data never replaces source or planner proof.
use super::*;
use crate::{Components,Record,Store,coordinate,recover};
const FIXTURE:&str=include_str!("../../../test-data/execution/domain-inputs.json");
const SETTLEMENT_FIXTURE:&str=include_str!("../../../test-data/settlement/common-v1.json");
#[path="../tests/support/mod.rs"] mod support;
use support::{Harness,MemoryStore,config,open,stage,fill,terminal};
#[test]
fn only_a_complete_transition_from_its_full_before_data_populates_the_shared_slot(){
    let mut history=Harness::new(config()).unwrap();let planned=history.prepare(&open(1,"BUY")).unwrap();let copy=planned.clone();
    assert!(!planned.has_validated_transition_data());coordinate(&mut history.store,&mut history.components,&planned).unwrap();
    assert!(planned.has_validated_transition_data());assert!(copy.has_validated_transition_data());
    let retained=history.store.rows[0].clone();assert!(retained.prepared().has_validated_transition_data());
    let passive=retained.observation_snapshot(true,false).unwrap();
    assert!(passive.prepared().has_validated_transition_data());assert!(!passive.prepared().is_planned());
    let decoded=Prepared::decode(&planned.encode().unwrap()).unwrap();
    assert!(!decoded.has_validated_transition_data());assert!(!decoded.is_planned());
    for source in [passive.prepared(),&decoded]{
        let mut foreign=Harness::new(config()).unwrap();let before=foreign.checkpoint().unwrap();
        assert!(coordinate(&mut foreign.store,&mut foreign.components,source).is_err());assert!(foreign.store.rows.is_empty());assert_eq!(foreign.checkpoint().unwrap(),before);
    }
}
#[test]
fn partial_lost_index_or_caller_result_checkpoints_cannot_certify_a_new_body(){
    for cut in [1,3,6] {
        for control in ["partial","lost-index","absent-index"] {
            let mut history=Harness::new(config()).unwrap();let planned=history.prepare(&open(1,"BUY")).unwrap();history.commit_only(&planned).unwrap();
            for index in 0..cut{history.components.install_projection(&history.store,&planned,index).unwrap();}
            let mut checkpoint=history.checkpoint().unwrap();
            match control {"lost-index"=>checkpoint["pending"]=json!([planned.id(),0]),"absent-index"=>checkpoint["pending"]=Value::Null,_=>{}}
            history.components.restore(&checkpoint,&hash(&checkpoint)).unwrap();
            let unknown=Prepared::decode(&planned.encode().unwrap()).unwrap();assert!(!unknown.has_validated_transition_data());
            coordinate(&mut history.store,&mut history.components,&unknown).unwrap();
            assert!(!unknown.has_validated_transition_data(),"{control}, cut{cut} borrowed an already installed result as transition-before proof");
            assert!(!history.store.rows[0].prepared().has_validated_transition_data(),"a caller's checkpoint must not label the actual source record");
        }
    }
}
#[test]
fn a_ready_idempotent_observation_never_labels_a_transport_body(){
    let mut history=Harness::new(config()).unwrap();let planned=history.prepare(&open(1,"BUY")).unwrap();coordinate(&mut history.store,&mut history.components,&planned).unwrap();
    let unknown=Prepared::decode(&planned.encode().unwrap()).unwrap();let before=history.checkpoint().unwrap();
    coordinate(&mut history.store,&mut history.components,&unknown).unwrap();assert!(!unknown.has_validated_transition_data());assert_eq!(history.checkpoint().unwrap(),before);
}
#[test]
fn independent_cold_genesis_replay_reestablishes_data_without_a_serialized_marker(){
    let mut history=Harness::new(config()).unwrap();
    for input in [open(1,"BUY"),stage(2,1,"UNKNOWN"),fill(3,1,"1","10.00","1.00"),terminal(4,1,"CANCELLED")]{let p=history.prepare(&input).unwrap();coordinate(&mut history.store,&mut history.components,&p).unwrap();}
    let mut cold=MemoryStore::default();cold.rows=history.store.rows.iter().map(|record|Record::decode(&record.record()).unwrap()).collect();
    assert!(cold.rows.iter().all(|record|!record.prepared().has_validated_transition_data()));
    let mut components=Components::new(config()).unwrap();recover(&mut cold,&mut components).unwrap();
    assert!(cold.rows.iter().all(|record|record.prepared().has_validated_transition_data()));
    assert_eq!(components.checkpoint().unwrap(),history.checkpoint().unwrap());assert_eq!(cold.head().unwrap(),4);
}
