//! Immutable fee vocabulary and exact identity scopes, without fee-policy selection.
use crate::{
    base::{domain_model, invalid, whitespace},
    enums::domain_enum,
    errors::OnlyDomainError,
    identifiers::*,
};
use serde_json::{Value, json};
use std::str::FromStr;

domain_enum! {OnlyFeeAuthority{Market=>"MARKET",Venue=>"VENUE",Regulator=>"REGULATOR",Clearing=>"CLEARING",Broker=>"BROKER",Platform=>"PLATFORM"}}
domain_enum! {OnlyFeeType{StampDuty=>"STAMP_DUTY",TransferFee=>"TRANSFER_FEE",ExchangeFee=>"EXCHANGE_FEE",ClearingFee=>"CLEARING_FEE",RegulatoryFee=>"REGULATORY_FEE",BrokerCommission=>"BROKER_COMMISSION",PlatformFee=>"PLATFORM_FEE",ContractFee=>"CONTRACT_FEE",OpenFee=>"OPEN_FEE",CloseFee=>"CLOSE_FEE",CloseTodayFee=>"CLOSE_TODAY_FEE",MakerFee=>"MAKER_FEE",TakerFee=>"TAKER_FEE"}}
domain_enum! {OnlyFeeCalculationBasis{Notional=>"NOTIONAL",Quantity=>"QUANTITY",Contracts=>"CONTRACTS"}}
domain_enum! {OnlyFeeEconomicDirection{Charge=>"CHARGE",Rebate=>"REBATE"}}
domain_enum! {OnlyFeeCalculationScope{Fill=>"FILL",OrderCumulative=>"ORDER_CUMULATIVE"}}
domain_enum! {OnlyFeeResolutionPolicy{FillEffective=>"FILL_EFFECTIVE",OrderFixed=>"ORDER_FIXED"}}
domain_enum! {OnlyFeeScheduleAuthority{Market=>"MARKET",Broker=>"BROKER"}}
domain_enum! {OnlyBrokerFeeAccountScopeType{AllAccounts=>"ALL_ACCOUNTS",ExactAccount=>"EXACT_ACCOUNT"}}
domain_enum! {OnlyFeeRoundingMode{HalfEven=>"HALF_EVEN",HalfUp=>"HALF_UP",Ceiling=>"CEILING",Floor=>"FLOOR"}}
domain_enum! {OnlyFeeCalculationPipeline{BoundsThenRound=>"BOUNDS_THEN_ROUND",RoundThenBounds=>"ROUND_THEN_BOUNDS"}}
domain_enum! {OnlyLocalFeeFinality{Estimated=>"ESTIMATED",ModelProvisional=>"MODEL_PROVISIONAL",ModelConfirmed=>"MODEL_CONFIRMED"}}

domain_model!(OnlyFeeSubject,OnlyFeeSubjectInput,1,None,{
 runtime_id:OnlyRuntimeId,account_id:OnlyAccountId,cluster_id:OnlyClusterId,order_id:OnlyOrderId,instrument_id:OnlyInstrumentId,
});
impl OnlyFeeSubject {
    fn validate(&self) -> Result<(), OnlyDomainError> {
        Ok(())
    }
}

domain_model!(OnlyBrokerFeeAccountScope,OnlyBrokerFeeAccountScopeInput,1,None,{
 scope_type:OnlyBrokerFeeAccountScopeType,account_id:Option<OnlyAccountId>,
});
impl OnlyBrokerFeeAccountScope {
    fn validate(&self) -> Result<(), OnlyDomainError> {
        if (*self.scope_type() == OnlyBrokerFeeAccountScopeType::ExactAccount)
            != self.account_id().is_some()
        {
            return Err(invalid(
                "broker account scope conflicts with account identity",
            ));
        }
        Ok(())
    }
}
domain_model!(OnlyFeeScheduleIdentity,OnlyFeeScheduleIdentityInput,1,None,{
 authority:OnlyFeeScheduleAuthority,schedule_id:String,version:String,fingerprint:String,
});
impl OnlyFeeScheduleIdentity {
    fn validate(&self) -> Result<(), OnlyDomainError> {
        nonempty(&[self.schedule_id(), self.version()])?;
        require_digest(self.fingerprint())
    }
}
domain_model!(OnlyFeeScheduleFamilyIdentity,OnlyFeeScheduleFamilyIdentityInput,1,None,{
 authority:OnlyFeeScheduleAuthority,schedule_id:String,scope_fingerprint:String,
});
impl OnlyFeeScheduleFamilyIdentity {
    fn validate(&self) -> Result<(), OnlyDomainError> {
        nonempty(&[self.schedule_id()])?;
        require_digest(self.scope_fingerprint())
    }
}
domain_model!(OnlyMarketFeePackIdentity,OnlyMarketFeePackIdentityInput,1,None,{
 pack_id:String,pack_version:String,fingerprint:String,
});
impl OnlyMarketFeePackIdentity {
    fn validate(&self) -> Result<(), OnlyDomainError> {
        nonempty(&[self.pack_id(), self.pack_version()])?;
        require_digest(self.fingerprint())
    }
    pub fn canonical_identity(&self) -> Value {
        json!({"fingerprint":self.fingerprint(),"pack_id":self.pack_id(),"pack_version":self.pack_version()})
    }
}
domain_model!(OnlyBrokerFeeContractIdentity,OnlyBrokerFeeContractIdentityInput,1,None,{
 contract_id:String,contract_version:String,broker_id:String,account_scope:OnlyBrokerFeeAccountScope,fingerprint:String,
});
impl OnlyBrokerFeeContractIdentity {
    fn validate(&self) -> Result<(), OnlyDomainError> {
        nonempty(&[
            self.contract_id(),
            self.contract_version(),
            self.broker_id(),
        ])?;
        require_digest(self.fingerprint())
    }
}
domain_model!(OnlyFeeComponentIdentity,OnlyFeeComponentIdentityInput,1,None,{
 fee_type:OnlyFeeType,authority:OnlyFeeAuthority,source_id:String,schedule_id:String,schedule_version:String,
 schedule_fingerprint:String,rule_id:String,rule_fingerprint:String,calculation_scope:OnlyFeeCalculationScope,
 resolution_policy:OnlyFeeResolutionPolicy,economic_direction:OnlyFeeEconomicDirection,
});
impl OnlyFeeComponentIdentity {
    fn validate(&self) -> Result<(), OnlyDomainError> {
        nonempty(&[
            self.source_id(),
            self.schedule_id(),
            self.schedule_version(),
            self.rule_id(),
        ])?;
        require_digest(self.schedule_fingerprint())?;
        require_digest(self.rule_fingerprint())
    }
    pub fn sort_key(&self) -> [&str; 9] {
        [
            self.fee_type().as_str(),
            self.authority().as_str(),
            self.source_id(),
            self.schedule_id(),
            self.schedule_version(),
            self.rule_id(),
            self.calculation_scope().as_str(),
            self.resolution_policy().as_str(),
            self.economic_direction().as_str(),
        ]
    }
}
fn require_digest(value: &str) -> Result<(), OnlyDomainError> {
    if value.len() != 64
        || !value
            .bytes()
            .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
    {
        return Err(invalid("fingerprint requires a lowercase SHA-256 digest"));
    }
    Ok(())
}
fn nonempty(values: &[&str]) -> Result<(), OnlyDomainError> {
    if values
        .iter()
        .any(|value| value.trim_matches(whitespace).is_empty())
    {
        return Err(invalid("fee identity cannot be empty"));
    }
    Ok(())
}

use crate::{
    base::OnlyDomainModel,
    numeric::{OnlyDecimal, only_add},
    time::OnlyTimestamp,
    value::{OnlyCurrency, OnlyMoney},
};
use sha2::{Digest, Sha256};
use std::collections::HashSet;

pub fn only_fee_fingerprint(payload: &Value) -> Result<String, OnlyDomainError> {
    let encoded = serde_json::to_vec(payload)
        .map_err(|error| OnlyDomainError::Serialization(error.to_string()))?;
    use std::fmt::Write;
    let mut output = String::with_capacity(64);
    for byte in Sha256::digest(encoded) {
        write!(&mut output, "{byte:02x}")
            .map_err(|error| OnlyDomainError::Serialization(error.to_string()))?;
    }
    Ok(output)
}
fn nonnegative(value: &OnlyDecimal) -> bool {
    !value.is_negative() || value.is_zero()
}
fn one_currency(values: &[&OnlyMoney]) -> bool {
    values
        .windows(2)
        .all(|pair| pair[0].currency() == pair[1].currency())
}

domain_model!(OnlyFeeBasisValues,OnlyFeeBasisValuesInput,1,None,{notional:OnlyMoney,quantity:OnlyDecimal,contracts:OnlyDecimal});
impl OnlyFeeBasisValues {
    fn validate(&self) -> Result<(), OnlyDomainError> {
        if ![self.notional().amount(), self.quantity(), self.contracts()]
            .into_iter()
            .all(nonnegative)
        {
            return Err(invalid("fee basis values cannot be negative"));
        }
        Ok(())
    }
    pub fn value(&self, basis: OnlyFeeCalculationBasis) -> &OnlyDecimal {
        match basis {
            OnlyFeeCalculationBasis::Notional => self.notional().amount(),
            OnlyFeeCalculationBasis::Quantity => self.quantity(),
            OnlyFeeCalculationBasis::Contracts => self.contracts(),
        }
    }
}

domain_model!(OnlyOrderFeeApplicabilityScopeIdentity,OnlyOrderFeeApplicabilityScopeIdentityInput,2,None,{
 market_product_id:String,market:String,venue:String,instrument_class:String,broker_id:String,account_id:OnlyAccountId,
 instrument_id:OnlyInstrumentId,charge_currency:OnlyCurrency,fingerprint:String,
});
impl OnlyOrderFeeApplicabilityScopeIdentity {
    fn payload_for(fields: &OnlyOrderFeeApplicabilityScopeIdentityInput) -> Value {
        json!([
            fields.market_product_id,
            fields.market,
            fields.venue,
            fields.instrument_class,
            fields.broker_id,
            fields.account_id.to_string(),
            fields.instrument_id.to_string(),
            fields.charge_currency.to_record(),
        ])
    }
    pub fn authority_payload(&self) -> Value {
        Self::payload_for(&self.fields)
    }
    /// Seal new input. Existing sealed records must use the validating reader instead.
    pub fn create(
        mut fields: OnlyOrderFeeApplicabilityScopeIdentityInput,
    ) -> Result<Self, OnlyDomainError> {
        if !fields.fingerprint.is_empty() {
            return Err(invalid("new fee scope input must be unsealed"));
        }
        fields.fingerprint = only_fee_fingerprint(&Self::payload_for(&fields))?;
        Self::new(fields)
    }
    fn validate(&self) -> Result<(), OnlyDomainError> {
        nonempty(&[
            self.market_product_id(),
            self.market(),
            self.venue(),
            self.instrument_class(),
            self.broker_id(),
        ])?;
        require_digest(self.fingerprint())?;
        if *self.fingerprint() != only_fee_fingerprint(&self.authority_payload())? {
            return Err(invalid("ORDER_FEE_SCOPE_AUTHORITY_CHANGED"));
        }
        Ok(())
    }
}

domain_model!(OnlyOrderFeePolicyBinding,OnlyOrderFeePolicyBindingInput,3,None,{
 runtime_id:OnlyRuntimeId,account_id:OnlyAccountId,cluster_id:OnlyClusterId,order_id:OnlyOrderId,instrument_id:OnlyInstrumentId,
 market_product_id:String,market_product_version:String,market_fee_pack:OnlyMarketFeePackIdentity,broker_fee_contract:OnlyBrokerFeeContractIdentity,
 applicability_scope:OnlyOrderFeeApplicabilityScopeIdentity,order_fixed_schedules:Vec<OnlyFeeScheduleIdentity>,
 fill_effective_families:Vec<OnlyFeeScheduleFamilyIdentity>,charge_currency:OnlyCurrency,bound_at:OnlyTimestamp,fingerprint:String,
});
impl OnlyOrderFeePolicyBinding {
    fn payload_for(fields: &OnlyOrderFeePolicyBindingInput) -> Value {
        json!([
            fields.runtime_id.to_string(),
            fields.account_id.to_string(),
            fields.cluster_id.to_string(),
            fields.order_id.to_string(),
            fields.instrument_id.to_string(),
            fields.market_product_id,
            fields.market_product_version,
            fields.market_fee_pack.to_record(),
            fields.broker_fee_contract.to_record(),
            fields.applicability_scope.to_record(),
            fields
                .order_fixed_schedules
                .iter()
                .map(|item| item.to_record())
                .collect::<Vec<_>>(),
            fields
                .fill_effective_families
                .iter()
                .map(|item| item.to_record())
                .collect::<Vec<_>>(),
            fields.charge_currency.to_record(),
            fields.bound_at.to_record(),
        ])
    }
    pub fn authority_payload(&self) -> Value {
        Self::payload_for(&self.fields)
    }
    /// Derive one new binding identity; never overwrite a supplied sealed fingerprint.
    pub fn create(mut fields: OnlyOrderFeePolicyBindingInput) -> Result<Self, OnlyDomainError> {
        if !fields.fingerprint.is_empty() {
            return Err(invalid("new fee binding input must be unsealed"));
        }
        fields.fingerprint = only_fee_fingerprint(&Self::payload_for(&fields))?;
        Self::new(fields)
    }
    fn validate(&self) -> Result<(), OnlyDomainError> {
        let fields = &self.fields;
        nonempty(&[self.market_product_id(), self.market_product_version()])?;
        let mut fixed = HashSet::new();
        let mut families = HashSet::new();
        if self
            .order_fixed_schedules()
            .iter()
            .any(|item| !fixed.insert((item.authority(), item.schedule_id(), item.version())))
        {
            return Err(invalid("duplicate order-fixed schedule identity"));
        }
        if self
            .fill_effective_families()
            .iter()
            .any(|item| !families.insert((item.authority(), item.schedule_id())))
        {
            return Err(invalid("duplicate fill-effective schedule family"));
        }
        let scope = self.applicability_scope();
        if scope.account_id() != self.account_id()
            || scope.instrument_id() != self.instrument_id()
            || scope.market_product_id() != self.market_product_id()
            || scope.charge_currency() != self.charge_currency()
        {
            return Err(invalid("order fee applicability conflicts with binding"));
        }
        if self.broker_fee_contract().broker_id() != scope.broker_id() {
            return Err(invalid(
                "order fee Broker conflicts with applicability scope",
            ));
        }
        let account_scope = self.broker_fee_contract().account_scope();
        if *account_scope.scope_type() == OnlyBrokerFeeAccountScopeType::ExactAccount
            && account_scope.account_id().as_ref() != Some(&fields.account_id)
        {
            return Err(invalid(
                "order fee Broker account scope conflicts with binding",
            ));
        }
        require_digest(self.fingerprint())?;
        if *self.fingerprint() != only_fee_fingerprint(&self.authority_payload())? {
            return Err(invalid("ORDER_FEE_BINDING_CONFLICT"));
        }
        Ok(())
    }
}

domain_model!(OnlyFeeTargetComponent,OnlyFeeTargetComponentInput,1,None,{
 identity:OnlyFeeComponentIdentity,raw_amount:OnlyMoney,bounded_amount:OnlyMoney,target_amount:OnlyMoney,local_finality:OnlyLocalFeeFinality,
});
impl OnlyFeeTargetComponent {
    fn validate(&self) -> Result<(), OnlyDomainError> {
        let values = [
            self.raw_amount(),
            self.bounded_amount(),
            self.target_amount(),
        ];
        if !one_currency(&values) || values.into_iter().any(|value| !nonnegative(value.amount())) {
            return Err(invalid("fee target component currency or amount invalid"));
        }
        Ok(())
    }
}
domain_model!(OnlyFeeAssessment,OnlyFeeAssessmentInput,2,None,{
 assessment_id:String,subject:OnlyFeeSubject,trade_id:Option<OnlyTradeId>,components:Vec<OnlyFeeTargetComponent>,
 total_charges:OnlyMoney,total_rebates:OnlyMoney,policy_fingerprint:String,resolution_fingerprint:String,
 local_finality:OnlyLocalFeeFinality,binding:OnlyOrderFeePolicyBinding,
});
impl OnlyFeeAssessment {
    fn validate(&self) -> Result<(), OnlyDomainError> {
        nonempty(&[self.assessment_id()])?;
        require_digest(self.policy_fingerprint())?;
        require_digest(self.resolution_fingerprint())?;
        if !one_currency(&[self.total_charges(), self.total_rebates()])
            || !nonnegative(self.total_charges().amount())
            || !nonnegative(self.total_rebates().amount())
        {
            return Err(invalid("fee assessment currency or totals invalid"));
        }
        let currency = self.total_charges().currency();
        let mut charges: OnlyDecimal = "0".parse()?;
        let mut rebates: OnlyDecimal = "0".parse()?;
        for (index, item) in self.components().iter().enumerate() {
            if self.components()[..index]
                .iter()
                .any(|prior| prior.identity() == item.identity())
            {
                return Err(invalid("duplicate fee component identity"));
            }
            if item.target_amount().currency() != currency {
                return Err(invalid("fee assessment component currency mismatch"));
            }
            match item.identity().economic_direction() {
                OnlyFeeEconomicDirection::Charge => {
                    charges = only_add(&charges, item.target_amount().amount())?
                }
                OnlyFeeEconomicDirection::Rebate => {
                    rebates = only_add(&rebates, item.target_amount().amount())?
                }
            }
        }
        if &charges != self.total_charges().amount() || &rebates != self.total_rebates().amount() {
            return Err(invalid("fee assessment totals disagree with components"));
        }
        let bound = self.binding();
        let subject = self.subject();
        if (
            bound.runtime_id(),
            bound.account_id(),
            bound.cluster_id(),
            bound.order_id(),
            bound.instrument_id(),
        ) != (
            subject.runtime_id(),
            subject.account_id(),
            subject.cluster_id(),
            subject.order_id(),
            subject.instrument_id(),
        ) {
            return Err(invalid("fee assessment binding scope mismatch"));
        }
        if currency != bound.charge_currency() {
            return Err(invalid("fee assessment currency conflicts with binding"));
        }
        Ok(())
    }
}
domain_model!(OnlyOrderFeeEstimate,OnlyOrderFeeEstimateInput,2,None,{
 expected:OnlyFeeAssessment,maximum:OnlyFeeAssessment,reservation_charge:OnlyMoney,estimated_rebate:OnlyMoney,assumptions_fingerprint:String,
});
impl OnlyOrderFeeEstimate {
    fn validate(&self) -> Result<(), OnlyDomainError> {
        if !one_currency(&[
            self.expected().total_charges(),
            self.expected().total_rebates(),
            self.maximum().total_charges(),
            self.maximum().total_rebates(),
            self.reservation_charge(),
            self.estimated_rebate(),
        ]) {
            return Err(invalid("fee estimate currency mismatch"));
        }
        if self.expected().subject() != self.maximum().subject()
            || self.expected().binding() != self.maximum().binding()
        {
            return Err(invalid(
                "fee estimate assessments require one subject and binding",
            ));
        }
        if self.reservation_charge() != self.maximum().total_charges() {
            return Err(invalid("fee reservation must equal maximum charges"));
        }
        Ok(())
    }
}
domain_model!(OnlyOrderFundingPlan,OnlyOrderFundingPlanInput,1,None,{
 order_id:OnlyOrderId,principal_reservation:OnlyMoney,fee_reservation:OnlyMoney,total_reservation:OnlyMoney,binding_fingerprint:String,estimate_fingerprint:String,
});
impl OnlyOrderFundingPlan {
    fn validate(&self) -> Result<(), OnlyDomainError> {
        if !one_currency(&[self.principal_reservation(), self.fee_reservation()]) {
            return Err(invalid("funding plan currency mismatch"));
        }
        if self
            .principal_reservation()
            .checked_add(self.fee_reservation())?
            != *self.total_reservation()
        {
            return Err(invalid(
                "funding plan total does not conserve principal and fee",
            ));
        }
        Ok(())
    }
}
