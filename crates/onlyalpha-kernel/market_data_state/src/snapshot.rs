use std::{collections::{BTreeMap,BTreeSet},sync::Arc};
use onlyalpha_domain::{identifiers::OnlyClusterId,market::{OnlyBar,OnlyBarType},time::OnlyTimestamp};
use num_bigint::BigUint;
use crate::{model::*,state::{SeriesMap,end,key,suffix},OnlyMarketDataSeriesSnapshot};
#[derive(Clone,Debug,PartialEq,Eq)]
pub struct OnlyMarketDataSnapshot {pub(crate) scope:OnlyMarketDataStateScope,pub(crate) cluster_id:Option<OnlyClusterId>,pub(crate) ts_event:OnlyTimestamp,pub(crate) ts_init:OnlyTimestamp,pub(crate) primary:OnlyBarType,pub(crate) visible:BTreeMap<String,OnlyBarType>,pub(crate) series:SeriesMap,pub(crate) updated:BTreeSet<String>,pub(crate) quality_flags:Vec<String>}
impl OnlyMarketDataSnapshot {
 pub(crate) fn runtime(scope:OnlyMarketDataStateScope,ts_event:OnlyTimestamp,ts_init:OnlyTimestamp,primary:OnlyBarType,series:SeriesMap,updated:BTreeSet<String>,quality_flags:Vec<String>)->Result<Self,OnlyMarketDataStateError>{
 let visible=series.iter().map(|(k,s)|(k.clone(),s.bar_type().clone())).collect();
 let result=Self{scope,cluster_id:None,ts_event,ts_init,primary,visible,series,updated,quality_flags};result.validate()?;Ok(result)
 }
 pub(crate) fn validate(&self)->Result<(),OnlyMarketDataStateError>{
  if self.ts_init<self.ts_event{return Err(OnlyMarketDataStateError::Time);}
  if !self.visible.contains_key(&key(&self.primary)){return Err(OnlyMarketDataStateError::Scope);}
  let anchor=self.series.get(&key(&self.primary)).ok_or(OnlyMarketDataStateError::MissingData)?;
  if end(anchor.latest())!=self.ts_event || self.series.values().any(|s|end(s.latest())>self.ts_event){return Err(OnlyMarketDataStateError::Time);}
  if self.series.keys().any(|k|!self.visible.contains_key(k)) || self.updated.iter().any(|k|!self.series.contains_key(k)){return Err(OnlyMarketDataStateError::Scope);}
  if self.cluster_id.is_none() && self.visible.len()!=self.series.len(){return Err(OnlyMarketDataStateError::Scope);}
  if self.cluster_id.is_some() && self.visible.values().any(|kind|kind.instrument_id()!=self.primary.instrument_id()){return Err(OnlyMarketDataStateError::Scope);}
  Ok(())
 }
 pub fn primary_bar(&self)->&OnlyBar{self.series[&key(&self.primary)].latest()}
 pub fn series(&self)->Vec<Arc<OnlyMarketDataSeriesSnapshot>>{self.series.values().cloned().collect()}
}

impl OnlyMarketDataSnapshot {
 pub fn scope(&self)->&OnlyMarketDataStateScope{&self.scope}
 pub fn cluster_id(&self)->Option<&OnlyClusterId>{self.cluster_id.as_ref()}
 pub fn ts_event(&self)->&OnlyTimestamp{&self.ts_event}
 pub fn ts_init(&self)->&OnlyTimestamp{&self.ts_init}
 pub fn primary_bar_type(&self)->&OnlyBarType{&self.primary}
 pub fn quality_flags(&self)->&[String]{&self.quality_flags}
 pub fn visible_bar_types(&self)->Vec<OnlyBarType>{self.visible.values().cloned().collect()}
 pub fn updated_bar_types(&self)->Vec<OnlyBarType>{self.updated.iter().map(|k|self.visible[k].clone()).collect()}
 fn check_scope(&self,kind:&OnlyBarType)->Result<String,OnlyMarketDataStateError>{let k=key(kind);if !self.visible.contains_key(&k){return Err(OnlyMarketDataStateError::Scope);}Ok(k)}
 pub fn latest_closed(&self,kind:&OnlyBarType)->Result<Option<&OnlyBar>,OnlyMarketDataStateError>{Ok(self.series.get(&self.check_scope(kind)?).map(|s|s.latest()))}
 pub fn require_latest_closed(&self,kind:&OnlyBarType)->Result<&OnlyBar,OnlyMarketDataStateError>{self.latest_closed(kind)?.ok_or(OnlyMarketDataStateError::MissingData)}
 pub fn require_same_event_time(&self,kind:&OnlyBarType)->Result<&OnlyBar,OnlyMarketDataStateError>{let bar=self.require_latest_closed(kind)?;if end(bar)!=self.ts_event{return Err(OnlyMarketDataStateError::Time);}Ok(bar)}
 pub fn history(&self,kind:&OnlyBarType,count:usize)->Result<Vec<Arc<OnlyBar>>,OnlyMarketDataStateError>{suffix(self.series.get(&self.check_scope(kind)?).map(|s|s.as_ref()),count)}
 pub fn version(&self,kind:&OnlyBarType)->Result<BigUint,OnlyMarketDataStateError>{Ok(self.series.get(&self.check_scope(kind)?).map_or_else(BigUint::default,|s|s.version().clone()))}
 pub fn was_updated(&self,kind:&OnlyBarType)->Result<bool,OnlyMarketDataStateError>{Ok(self.updated.contains(&self.check_scope(kind)?))}
 pub fn current_partial(&self,kind:&OnlyBarType)->Result<Option<&OnlyBar>,OnlyMarketDataStateError>{self.check_scope(kind)?;Ok(None)}
 pub fn restrict(&self,cluster_id:OnlyClusterId,allowed:&[OnlyBarType],primary:&OnlyBarType)->Result<Self,OnlyMarketDataStateError>{
  if allowed.is_empty() || self.cluster_id.as_ref().is_some_and(|id|id!=&cluster_id){return Err(OnlyMarketDataStateError::Scope);}
  let mut visible=BTreeMap::new();
  for kind in allowed {let k=key(kind);
   if kind.instrument_id()!=primary.instrument_id() || (self.cluster_id.is_some() && !self.visible.contains_key(&k)) || visible.insert(k,kind.clone()).is_some(){return Err(OnlyMarketDataStateError::Scope);}
  }
  if !visible.contains_key(&key(primary)){return Err(OnlyMarketDataStateError::Scope);}
  let series=self.series.iter().filter(|(k,_)|visible.contains_key(*k)).map(|(k,s)|(k.clone(),s.clone())).collect();
  let updated=self.updated.iter().filter(|k|visible.contains_key(*k)).cloned().collect();
  let result=Self{scope:self.scope.clone(),cluster_id:Some(cluster_id),ts_event:self.ts_event.clone(),ts_init:self.ts_init.clone(),primary:primary.clone(),visible,series,updated,quality_flags:self.quality_flags.clone()};result.validate()?;Ok(result)
 }
}
