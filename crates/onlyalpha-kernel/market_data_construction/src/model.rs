use std::collections::{BTreeMap,BTreeSet};
use num_bigint::BigUint;
use onlyalpha_domain::{base::OnlyDomainModel,market::{OnlyBarType,OnlyBarSemantic,OnlyBarFormation,OnlyTradeSemantic,OnlyTradeInputType}};
use serde_json::{Value,json};
use crate::record::*;
#[derive(Clone,Debug,PartialEq,Eq)]
pub enum OnlyConstructionError{Validation(String),Scope,Unavailable,RecoveryRequired,Sequence,Time}
impl std::fmt::Display for OnlyConstructionError{fn fmt(&self,f:&mut std::fmt::Formatter<'_>)->std::fmt::Result{write!(f,"{self:?}")}}
impl std::error::Error for OnlyConstructionError{}
pub type OnlyConstructionResult<T>=Result<T,OnlyConstructionError>;
#[derive(Clone,Debug,PartialEq,Eq)]
pub enum OnlyConstructionInput{Bar(OnlyBarType),Trade(OnlyTradeInputType)}
impl OnlyConstructionInput{
 pub fn to_record(&self)->Value{match self{Self::Bar(v)=>v.to_record(),Self::Trade(v)=>v.to_record()}}
 pub fn from_record(v:&Value)->OnlyConstructionResult<Self>{if v["semantic"]["kind"]=="TRADE"{Ok(Self::Trade(domain(v)?))}else{Ok(Self::Bar(domain(v)?))}}
 pub fn instrument(&self)->&onlyalpha_domain::identifiers::OnlyInstrumentId{match self{Self::Bar(v)=>v.instrument_id(),Self::Trade(v)=>v.instrument_id()}}
 pub(crate) fn key(&self)->String{self.to_record().to_string()}
 pub fn semantic(&self)->OnlyConstructionSemantic{match self{Self::Bar(v)=>OnlyConstructionSemantic::Bar(v.semantic().clone()),Self::Trade(_)=>OnlyConstructionSemantic::Trade}}
}
#[derive(Clone,Debug,PartialEq,Eq)]
pub enum OnlyConstructionSemantic{Bar(OnlyBarSemantic),Trade}
impl OnlyConstructionSemantic{
 pub fn to_record(&self)->Value{match self{Self::Bar(v)=>v.to_record(),Self::Trade=>OnlyTradeSemantic.to_record()}}
 pub fn from_record(v:&Value)->OnlyConstructionResult<Self>{if v["kind"]=="TRADE"{let _:OnlyTradeSemantic=domain(v)?;Ok(Self::Trade)}else{Ok(Self::Bar(domain(v)?))}}
}
#[derive(Clone,Copy,Debug,PartialEq,Eq)]
pub enum OnlyMissingPolicy{Reject,SkipWindow}
impl OnlyMissingPolicy{pub fn as_str(self)->&'static str{match self{Self::Reject=>"REJECT",Self::SkipWindow=>"SKIP_WINDOW"}}pub(crate) fn read(v:&Value)->OnlyConstructionResult<Self>{match text(v)?{"REJECT"=>Ok(Self::Reject),"SKIP_WINDOW"=>Ok(Self::SkipWindow),_=>Err(err("MISSING_POLICY"))}}}
#[derive(Clone,Copy,Debug,PartialEq,Eq)]
pub enum OnlyIncompletePolicy{Drop,Reject}
impl OnlyIncompletePolicy{pub fn as_str(self)->&'static str{match self{Self::Drop=>"DROP",Self::Reject=>"REJECT"}}pub(crate) fn read(v:&Value)->OnlyConstructionResult<Self>{match text(v)?{"DROP"=>Ok(Self::Drop),"REJECT"=>Ok(Self::Reject),_=>Err(err("INCOMPLETE_POLICY"))}}}
#[derive(Clone,Debug,PartialEq,Eq)]
pub struct OnlyConstructionRecipe{target:OnlyBarSemantic,base:Option<OnlyConstructionSemantic>,algorithm:Option<(String,BigUint)>,missing:Option<OnlyMissingPolicy>,incomplete:Option<OnlyIncompletePolicy>}
impl OnlyConstructionRecipe{
 pub fn native(target:OnlyBarSemantic)->Self{Self{target,base:None,algorithm:None,missing:None,incomplete:None}}
 pub fn derived(target:OnlyBarSemantic,base:OnlyConstructionSemantic,algorithm_id:&str,version:BigUint,missing:OnlyMissingPolicy,incomplete:OnlyIncompletePolicy)->OnlyConstructionResult<Self>{nonempty(algorithm_id)?;if version==BigUint::default(){return Err(err("ALGORITHM_VERSION"));}if let OnlyConstructionSemantic::Bar(source)=&base{if source.price_type()!=target.price_type() || source.adjustment_policy()!=target.adjustment_policy(){return Err(err("RECIPE_SEMANTICS"));}}Ok(Self{target,base:Some(base),algorithm:Some((algorithm_id.into(),version)),missing:Some(missing),incomplete:Some(incomplete)})}
 pub fn target(&self)->&OnlyBarSemantic{&self.target}
 pub fn base(&self)->Option<&OnlyConstructionSemantic>{self.base.as_ref()}
 pub fn algorithm(&self)->Option<(&str,&BigUint)>{self.algorithm.as_ref().map(|(id,v)|(id.as_str(),v))}
 pub fn missing(&self)->Option<OnlyMissingPolicy>{self.missing}
 pub fn incomplete(&self)->Option<OnlyIncompletePolicy>{self.incomplete}
 pub fn is_native(&self)->bool{self.base.is_none()}
 pub fn to_record(&self)->Value{let alignment=match &self.base{Some(OnlyConstructionSemantic::Bar(s))=>match s.formation(){OnlyBarFormation::FixedDuration(f)=>Some(f.alignment().as_str()),_=>None},_=>None};json!({"schema_version":1,"kind":if self.is_native(){"PROVIDER_NATIVE"}else{"DERIVED"},"target_semantic":self.target.to_record(),"base_semantic":self.base.as_ref().map(|v|v.to_record()),"algorithm_id":self.algorithm.as_ref().map(|(id,_)|id),"algorithm_version":self.algorithm.as_ref().map(|(_,v)|number(v)),"missing_policy":self.missing.map(|v|v.as_str()),"incomplete_policy":self.incomplete.map(|v|v.as_str()),"alignment_requirement":alignment})}
 pub fn from_record(v:&Value)->OnlyConstructionResult<Self>{let row=object(v,1,&["kind","target_semantic","base_semantic","algorithm_id","algorithm_version","missing_policy","incomplete_policy","alignment_requirement"])?;let target=domain(&row["target_semantic"])?;let result=match text(&row["kind"])?{"PROVIDER_NATIVE"=>Self::native(target),"DERIVED"=>Self::derived(target,OnlyConstructionSemantic::from_record(&row["base_semantic"])?,text(&row["algorithm_id"])?,integer(&row["algorithm_version"])?,OnlyMissingPolicy::read(&row["missing_policy"])?,OnlyIncompletePolicy::read(&row["incomplete_policy"])?)?,_=>return Err(err("RECIPE_KIND"))};if result.to_record()!=*v{return Err(err("RECIPE_RELATIONS"));}Ok(result)}
 pub fn fingerprint(&self)->String{hash(&self.to_record())}
}
#[derive(Clone,Debug,PartialEq,Eq)]
pub struct OnlyConstructionEdge{source:OnlyConstructionInput,target:OnlyBarType,recipe:OnlyConstructionRecipe}
impl OnlyConstructionEdge{
 pub fn new(source:OnlyConstructionInput,target:OnlyBarType,recipe:OnlyConstructionRecipe)->OnlyConstructionResult<Self>{if source.instrument()!=target.instrument_id() || recipe.base()!=Some(&source.semantic()) || recipe.target()!=target.semantic(){return Err(err("EDGE_RELATIONS"));}
 if let Some((id,_))=recipe.algorithm(){let trade=matches!(source,OnlyConstructionInput::Trade(_));let valid=match id{"TIME_BAR"|"ROLLING_TIME_BAR"=>!trade && matches!(target.semantic().formation(),OnlyBarFormation::FixedDuration(_)),"TICK_BAR"=>trade && matches!(target.semantic().formation(),OnlyBarFormation::TickCount(_)),"VOLUME_BAR"=>trade && matches!(target.semantic().formation(),OnlyBarFormation::Volume(_)),"VALUE_BAR"=>trade && matches!(target.semantic().formation(),OnlyBarFormation::Value(_)),_=>true};if !valid{return Err(err("ALGORITHM_INPUT_OUTPUT_KIND"));}}
 Ok(Self{source,target,recipe})}
 pub fn source(&self)->&OnlyConstructionInput{&self.source}
 pub fn target(&self)->&OnlyBarType{&self.target}
 pub fn recipe(&self)->&OnlyConstructionRecipe{&self.recipe}
 pub fn to_record(&self)->Value{json!({"source":self.source.to_record(),"target":self.target.to_record(),"recipe":self.recipe.to_record()})}
 pub fn from_record(v:&Value)->OnlyConstructionResult<Self>{let row=v.as_object().filter(|row|row.len()==3 && ["source","target","recipe"].iter().all(|k|row.contains_key(*k))).ok_or_else(||err("EDGE_FIELDS"))?;Self::new(OnlyConstructionInput::from_record(&row["source"])?,domain(&row["target"])?,OnlyConstructionRecipe::from_record(&row["recipe"])?) }
 pub fn lane_id(&self,source:&str)->OnlyConstructionResult<String>{nonempty(source)?;Ok(hash(&json!({"schema_version":1,"output":self.target.to_record(),"recipe_fingerprint":self.recipe.fingerprint(),"source_binding_identity":source})))}
}
#[derive(Clone,Debug,PartialEq,Eq)]
pub struct OnlyConstructionGraph{providers:Vec<OnlyConstructionInput>,edges:Vec<OnlyConstructionEdge>}
impl OnlyConstructionGraph{
 pub fn new(mut providers:Vec<OnlyConstructionInput>,mut edges:Vec<OnlyConstructionEdge>)->OnlyConstructionResult<Self>{providers.sort_by_key(|p|p.key());edges.sort_by_key(|e|e.to_record().to_string());let provider_keys:BTreeSet<_>=providers.iter().map(|p|p.key()).collect();let targets:BTreeSet<_>=edges.iter().map(|e|OnlyConstructionInput::Bar(e.target.clone()).key()).collect();if provider_keys.len()!=providers.len() || targets.len()!=edges.len() || !provider_keys.is_disjoint(&targets) || edges.iter().any(|e|!provider_keys.contains(&e.source.key()) && !targets.contains(&e.source.key())){return Err(err("GRAPH_MEMBERSHIP"));}let graph=Self{providers,edges};graph.ordered_edges()?;Ok(graph)}
 pub fn providers(&self)->&[OnlyConstructionInput]{&self.providers}
 pub fn edges(&self)->&[OnlyConstructionEdge]{&self.edges}
 pub(crate) fn ordered_edges(&self)->OnlyConstructionResult<Vec<(OnlyConstructionEdge,usize)>>{let mut levels:BTreeMap<_,usize>=self.providers.iter().map(|p|(p.key(),0)).collect();let mut pending=self.edges.clone();let mut result=vec![];while !pending.is_empty(){let mut next=vec![];let before=pending.len();for edge in pending{if let Some(level)=levels.get(&edge.source.key()).copied(){let level=level+1;levels.insert(OnlyConstructionInput::Bar(edge.target.clone()).key(),level);result.push((edge,level));}else{next.push(edge);}}if next.len()==before{return Err(err("GRAPH_CYCLE"));}pending=next;}Ok(result)}
 pub fn to_record(&self)->Value{json!({"schema_version":1,"provider_inputs":self.providers.iter().map(|p|p.to_record()).collect::<Vec<_>>(),"derived_dependencies":self.edges.iter().map(|e|e.to_record()).collect::<Vec<_>>()})}
 pub fn from_record(v:&Value)->OnlyConstructionResult<Self>{let row=object(v,1,&["provider_inputs","derived_dependencies"])?;let providers=array(&row["provider_inputs"])?.iter().map(OnlyConstructionInput::from_record).collect::<OnlyConstructionResult<_>>()?;let edges=array(&row["derived_dependencies"])?.iter().map(OnlyConstructionEdge::from_record).collect::<OnlyConstructionResult<_>>()?;Self::new(providers,edges)}
 pub fn fingerprint(&self)->String{hash(&self.to_record())}
}
