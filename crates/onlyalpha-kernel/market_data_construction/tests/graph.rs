mod support;
use support::*;
use onlyalpha_market_data_construction::*;
#[test]
fn compilation_is_stable_and_lane_keyed(){let g=graph();let reversed=OnlyConstructionGraph::new(g.providers().to_vec(),g.edges().iter().cloned().rev().collect()).unwrap();assert_eq!(g.fingerprint(),reversed.fingerprint());let a=OnlyConstructionPlan::compile(&g,"source").unwrap();let b=OnlyConstructionPlan::compile(&reversed,"source").unwrap();assert_eq!(a,b);assert_eq!(a.lanes().iter().map(|l|l.level()).collect::<Vec<_>>(),vec![1,2]);assert_eq!(a.lanes()[1].source_lane_id(),a.lanes()[0].lane_id());assert_ne!(a,OnlyConstructionPlan::compile(&g,"other").unwrap());assert_eq!(OnlyConstructionGraph::from_record(&g.to_record()).unwrap(),g);}
#[test]
fn invalid_graphs_and_relations_reject(){let root=OnlyConstructionInput::Bar(kind(A,1));assert!(OnlyConstructionGraph::new(vec![root.clone(),root.clone()],vec![]).is_err());assert!(OnlyConstructionGraph::new(vec![root.clone()],vec![edge(1,3),edge(1,3)]).is_err());assert!(OnlyConstructionGraph::new(vec![root],vec![edge(3,9)]).is_err());
 let a=kind(A,1);let b=kind(A,3);let r=OnlyConstructionRecipe::derived(a.semantic().clone(),OnlyConstructionSemantic::Bar(b.semantic().clone()),"CUSTOM",1u32.into(),OnlyMissingPolicy::Reject,OnlyIncompletePolicy::Drop).unwrap();let backwards=OnlyConstructionEdge::new(OnlyConstructionInput::Bar(b),a,r).unwrap();assert!(OnlyConstructionGraph::new(vec![],vec![edge(1,3),backwards]).is_err());
 let mut row=graph().to_record();row["schema_version"]=true.into();assert!(OnlyConstructionGraph::from_record(&row).is_err());let provider=row["provider_inputs"][0].clone();row["schema_version"]=1.into();row["provider_inputs"].as_array_mut().unwrap().push(provider);assert!(OnlyConstructionGraph::from_record(&row).is_err());}
