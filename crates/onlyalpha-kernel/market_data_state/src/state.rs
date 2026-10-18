use std::{collections::{BTreeMap,BTreeSet,VecDeque},sync::Arc};
use num_bigint::BigUint;
use onlyalpha_domain::{base::OnlyDomainModel,market::{OnlyBar,OnlyBarType},time::OnlyTimestamp};
use crate::{model::*,snapshot::OnlyMarketDataSnapshot};
pub(crate) type SeriesMap=BTreeMap<String,Arc<OnlyMarketDataSeriesSnapshot>>;
pub(crate) fn key(kind:&OnlyBarType)->String{kind.to_record().to_string()}
pub(crate) fn end(bar:&OnlyBar)->OnlyTimestamp{OnlyTimestamp::from_datetime(*bar.bar_end())}
#[derive(Clone,Debug,PartialEq,Eq)]
pub struct OnlyMarketDataSeriesSnapshot {bar_type:OnlyBarType,version:BigUint,history:VecDeque<Arc<OnlyBar>>}
impl OnlyMarketDataSeriesSnapshot {
 pub(crate) fn new(bar_type:OnlyBarType,version:BigUint,history:VecDeque<Arc<OnlyBar>>)->Result<Self,OnlyMarketDataStateError>{
  if history.is_empty() || version<BigUint::from(history.len()){return Err(OnlyMarketDataStateError::Validation("empty history or inadequate version".into()));}
  let mut previous=None;
  for bar in &history {
   if bar.bar_type()!=&bar_type || !bar.is_closed() || *bar.revision()!=0.into() || bar.ts_event()!=bar.bar_end(){return Err(OnlyMarketDataStateError::Validation("only matching closed unrevised end-time facts are accepted".into()));}
   if previous.is_some_and(|prior|prior>=*bar.bar_end()){return Err(OnlyMarketDataStateError::Sequence);} previous=Some(*bar.bar_end());
  }
  Ok(Self{bar_type,version,history})
 }
 pub fn bar_type(&self)->&OnlyBarType{&self.bar_type}
 pub fn version(&self)->&BigUint{&self.version}
 pub fn history(&self)->&VecDeque<Arc<OnlyBar>>{&self.history}
 pub fn latest(&self)->&OnlyBar{self.history.back().expect("validated nonempty series")}
}
#[derive(Debug)]
pub struct OnlyMarketDataState {pub(crate) scope:OnlyMarketDataStateScope,pub(crate) history_limit:usize,pub(crate) series:SeriesMap}
impl OnlyMarketDataState {
 pub fn new(scope:OnlyMarketDataStateScope,config:OnlyMarketDataStateConfig)->Result<Self,OnlyMarketDataStateError>{if config.history_limit==0{return Err(OnlyMarketDataStateError::Configuration);}Ok(Self{scope,history_limit:config.history_limit,series:BTreeMap::new()})}
 pub fn scope(&self)->&OnlyMarketDataStateScope{&self.scope}
 pub fn history_limit(&self)->usize{self.history_limit}
 pub fn latest_closed(&self,kind:&OnlyBarType)->Option<&OnlyBar>{self.series.get(&key(kind)).map(|row|row.latest())}
 pub fn history(&self,kind:&OnlyBarType,count:usize)->Result<Vec<Arc<OnlyBar>>,OnlyMarketDataStateError>{suffix(self.series.get(&key(kind)).map(|s|s.as_ref()),count)}
 pub fn version(&self,kind:&OnlyBarType)->BigUint{self.series.get(&key(kind)).map_or_else(BigUint::default,|s|s.version().clone())}
 pub fn bar_types(&self)->Vec<OnlyBarType>{self.series.values().map(|s|s.bar_type().clone()).collect()}
 pub fn current_partial(&self,_kind:&OnlyBarType)->Option<&OnlyBar>{None}
 pub fn apply_closed(&mut self,bars:&[Arc<OnlyBar>],primary:&OnlyBarType,ts_init:OnlyTimestamp,quality_flags:Vec<String>)->Result<OnlyMarketDataSnapshot,OnlyMarketDataStateError>{
  if bars.is_empty(){return Err(OnlyMarketDataStateError::Validation("empty batch".into()));}
  let anchor=bars.iter().find(|bar|bar.bar_type()==primary).ok_or(OnlyMarketDataStateError::MissingData)?;
  let mut staged=self.series.clone();let mut updated=BTreeSet::new();
  for bar in bars {
   let k=key(bar.bar_type());if !updated.insert(k.clone()){return Err(OnlyMarketDataStateError::Sequence);}
   let previous=staged.get(&k);
   if previous.is_some_and(|s|s.latest().bar_end()>=bar.bar_end()){return Err(OnlyMarketDataStateError::Sequence);}
   let mut history=previous.map_or_else(VecDeque::new,|s|s.history().clone());history.push_back(bar.clone());
   while history.len()>self.history_limit{history.pop_front();}
   let version=previous.map_or_else(BigUint::default,|s|s.version().clone())+1u32;
   staged.insert(k,Arc::new(OnlyMarketDataSeriesSnapshot::new(bar.bar_type().clone(),version,history)?));
  }
  let snapshot=OnlyMarketDataSnapshot::runtime(self.scope.clone(),end(anchor),ts_init,primary.clone(),staged.clone(),updated,quality_flags)?;
  self.series=staged;Ok(snapshot)
 }
}
pub(crate) fn suffix(series:Option<&OnlyMarketDataSeriesSnapshot>,count:usize)->Result<Vec<Arc<OnlyBar>>,OnlyMarketDataStateError>{
 if count==0{return Err(OnlyMarketDataStateError::Configuration);}Ok(series.map_or_else(Vec::new,|s|s.history.iter().skip(s.history.len().saturating_sub(count)).cloned().collect()))
}
