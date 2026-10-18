use std::{collections::{BTreeMap,BTreeSet},sync::Arc};
use onlyalpha_domain::{identifiers::OnlyClusterId,market::{OnlyBar,OnlyBarType},time::OnlyTimestamp};
use crate::{model::*,state::{SeriesMap,end,key},OnlyMarketDataSeriesSnapshot};
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
  Ok(())
 }
 pub fn primary_bar(&self)->&OnlyBar{self.series[&key(&self.primary)].latest()}
 pub fn series(&self)->Vec<Arc<OnlyMarketDataSeriesSnapshot>>{self.series.values().cloned().collect()}
}
