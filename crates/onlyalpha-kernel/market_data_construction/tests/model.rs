mod support;
use support::*;
use onlyalpha_market_data_construction::*;
use onlyalpha_domain::base::OnlyDomainModel;
#[test]
fn recipe_records_and_identity_are_exact(){let e=edge(1,3);let recipe=e.recipe();let row=recipe.to_record();assert_eq!(row["schema_version"],1);assert_eq!(row["algorithm_id"],"TIME_BAR");assert_eq!(OnlyConstructionRecipe::from_record(&row).unwrap(),*recipe);let mut bad=row.clone();bad["algorithm_version"]=true.into();assert!(OnlyConstructionRecipe::from_record(&bad).is_err());bad=row.clone();bad["extra"]=1.into();assert!(OnlyConstructionRecipe::from_record(&bad).is_err());
 let other=kind("BTCUSD.TEST",3);assert!(OnlyConstructionEdge::new(e.source().clone(),other,e.recipe().clone()).is_err());
 let native=OnlyConstructionRecipe::native(kind(A,3).semantic().clone());assert_eq!(native.to_record()["kind"],"PROVIDER_NATIVE");assert_ne!(native.fingerprint(),recipe.fingerprint());assert_eq!(recipe.fingerprint().len(),64);
}
