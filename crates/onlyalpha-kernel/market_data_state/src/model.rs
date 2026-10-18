use onlyalpha_domain::identifiers::{OnlyEngineId,OnlyRuntimeId};
#[derive(Clone,Debug,PartialEq,Eq)]
pub struct OnlyMarketDataStateScope {engine_id:OnlyEngineId,runtime_id:OnlyRuntimeId}
impl OnlyMarketDataStateScope {
 pub fn new(engine_id:OnlyEngineId,runtime_id:OnlyRuntimeId)->Self{Self{engine_id,runtime_id}}
 pub fn engine_id(&self)->&OnlyEngineId{&self.engine_id}
 pub fn runtime_id(&self)->&OnlyRuntimeId{&self.runtime_id}
}
#[derive(Clone,Copy,Debug,PartialEq,Eq)]
pub struct OnlyMarketDataStateConfig {pub history_limit:usize}
impl Default for OnlyMarketDataStateConfig {fn default()->Self{Self{history_limit:1024}}}
#[derive(Clone,Debug,PartialEq,Eq)]
pub enum OnlyMarketDataStateError {Configuration,Validation(String),Sequence,Scope,MissingData,Time,Record(String)}
impl std::fmt::Display for OnlyMarketDataStateError {fn fmt(&self,f:&mut std::fmt::Formatter<'_>)->std::fmt::Result{write!(f,"{self:?}")}}
impl std::error::Error for OnlyMarketDataStateError {}
