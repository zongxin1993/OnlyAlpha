use crate::*;
use num_bigint::BigUint;
use std::{collections::VecDeque, sync::Arc};
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct OnlyEventFailure {
    pub event: Arc<OnlyEvent>,
    pub result: OnlyEventHandlerResult,
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct OnlyEventSamples<T> {
    pub samples: Vec<T>,
    pub total: BigUint,
    pub evicted: BigUint,
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct OnlyEventDiagnostics {
    pub dispatches: OnlyEventSamples<OnlyEventDispatchReport>,
    pub failures: OnlyEventSamples<OnlyEventFailure>,
    pub replacements: OnlyEventSamples<OnlyEventEnqueueReceipt>,
    pub abandoned_pending: BigUint,
}
struct Retained<T> {
    capacity: usize,
    values: VecDeque<T>,
    total: BigUint,
    evicted: BigUint,
}
impl<T: Clone> Retained<T> {
    fn new(capacity: usize) -> Self {
        Self {
            capacity,
            values: VecDeque::new(),
            total: BigUint::ZERO,
            evicted: BigUint::ZERO,
        }
    }
    fn push(&mut self, value: T) {
        self.total += 1u32;
        if self.values.len() == self.capacity {
            self.values.pop_front();
            self.evicted += 1u32;
        }
        self.values.push_back(value);
    }
    fn snapshot(&self) -> OnlyEventSamples<T> {
        OnlyEventSamples {
            samples: self.values.iter().cloned().collect(),
            total: self.total.clone(),
            evicted: self.evicted.clone(),
        }
    }
}
pub(crate) struct Diagnostics {
    dispatches: Retained<OnlyEventDispatchReport>,
    failures: Retained<OnlyEventFailure>,
    replacements: Retained<OnlyEventEnqueueReceipt>,
    pub(crate) abandoned_pending: BigUint,
}
impl Diagnostics {
    pub(crate) fn new(capacity: usize) -> Self {
        Self {
            dispatches: Retained::new(capacity),
            failures: Retained::new(capacity),
            replacements: Retained::new(capacity),
            abandoned_pending: BigUint::ZERO,
        }
    }
    pub(crate) fn dispatch(&mut self, report: OnlyEventDispatchReport) {
        for result in &report.handler_results {
            if result.outcome != OnlyEventHandlerOutcome::Succeeded {
                self.failures.push(OnlyEventFailure {
                    event: report.event.clone(),
                    result: result.clone(),
                });
            }
        }
        self.dispatches.push(report);
    }
    pub(crate) fn replacement(&mut self, receipt: OnlyEventEnqueueReceipt) {
        self.replacements.push(receipt);
    }
    pub(crate) fn snapshot(&self) -> OnlyEventDiagnostics {
        OnlyEventDiagnostics {
            dispatches: self.dispatches.snapshot(),
            failures: self.failures.snapshot(),
            replacements: self.replacements.snapshot(),
            abandoned_pending: self.abandoned_pending.clone(),
        }
    }
}
