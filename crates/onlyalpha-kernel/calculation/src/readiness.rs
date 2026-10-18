//! Pure dependency barrier over exact committed instance snapshots.
use crate::{
    CalculationSnapshot, ExecutionBinding, InputPosition, Result, StateOutcome, record::*,
};
use std::collections::{BTreeMap, BTreeSet};
#[derive(Clone, Debug)]
pub struct ReadinessRequirement {
    binding: ExecutionBinding,
    required: bool,
    dependencies: BTreeSet<String>,
}
impl ReadinessRequirement {
    pub fn new(
        binding: ExecutionBinding,
        required: bool,
        dependencies: Vec<String>,
    ) -> Result<Self> {
        if dependencies.len() > 256 {
            return Err(err("DEPENDENCY_BUDGET"));
        }
        let unique: BTreeSet<_> = dependencies.iter().cloned().collect();
        if unique.len() != dependencies.len() || unique.contains(binding.scope()) {
            return Err(err("DEPENDENCY_INVALID"));
        }
        Ok(Self {
            binding,
            required,
            dependencies: unique,
        })
    }
}
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum ReadinessStatus {
    Missing,
    Stale,
    Blocked,
    State(StateOutcome),
}
#[derive(Debug)]
pub struct ReadinessBarrier {
    statuses: BTreeMap<String, ReadinessStatus>,
    ready: bool,
    degraded: bool,
}
impl ReadinessBarrier {
    pub fn ready(&self) -> bool {
        self.ready
    }
    pub fn degraded(&self) -> bool {
        self.degraded
    }
    pub fn statuses(&self) -> &BTreeMap<String, ReadinessStatus> {
        &self.statuses
    }
}
#[derive(Debug)]
pub struct ReadinessPlan {
    requirements: BTreeMap<String, ReadinessRequirement>,
    ordered: Vec<String>,
}
impl ReadinessPlan {
    pub fn new(requirements: Vec<ReadinessRequirement>) -> Result<Self> {
        if requirements.is_empty()
            || requirements.len() > 256
            || !requirements.iter().any(|r| r.required)
        {
            return Err(err("READINESS_PLAN_BUDGET"));
        }
        let generation = requirements[0].binding.digests()[0].clone();
        let mut nodes = BTreeMap::new();
        for r in requirements {
            if r.binding.digests()[0] != generation
                || nodes.insert(r.binding.scope().to_owned(), r).is_some()
            {
                return Err(err("READINESS_BINDING_INVALID"));
            }
        }
        if nodes
            .values()
            .any(|r| r.dependencies.iter().any(|d| !nodes.contains_key(d)))
        {
            return Err(err("MISSING_DEPENDENCY"));
        }
        let mut ordered = Vec::new();
        let mut visited = BTreeSet::new();
        while ordered.len() < nodes.len() {
            let before = ordered.len();
            for (id, r) in &nodes {
                if !visited.contains(id) && r.dependencies.iter().all(|d| visited.contains(d)) {
                    visited.insert(id.clone());
                    ordered.push(id.clone());
                }
            }
            if before == ordered.len() {
                return Err(err("DEPENDENCY_CYCLE"));
            }
        }
        Ok(Self {
            requirements: nodes,
            ordered,
        })
    }
    pub fn evaluate(
        &self,
        snapshots: &BTreeMap<String, CalculationSnapshot>,
        expected: &BTreeMap<String, InputPosition>,
    ) -> Result<ReadinessBarrier> {
        if expected.len() != self.requirements.len()
            || self.requirements.keys().ne(expected.keys())
            || snapshots.keys().any(|k| !self.requirements.contains_key(k))
        {
            return Err(err("EXACT_READINESS_CONTEXT_REQUIRED"));
        }
        let mut statuses = BTreeMap::new();
        for id in &self.ordered {
            let r = &self.requirements[id];
            let status = match snapshots.get(id) {
                None => ReadinessStatus::Missing,
                Some(snapshot) => {
                    if snapshot.binding() != &r.binding {
                        return Err(err("SNAPSHOT_BINDING_MISMATCH"));
                    }
                    let outcome = snapshot.outcome();
                    if !matches!(outcome, StateOutcome::Ready | StateOutcome::Warming) {
                        ReadinessStatus::State(outcome)
                    } else if snapshot.position().as_ref() != Some(&expected[id]) {
                        ReadinessStatus::Stale
                    } else if r.dependencies.iter().any(|d| {
                        statuses.get(d) != Some(&ReadinessStatus::State(StateOutcome::Ready))
                    }) {
                        ReadinessStatus::Blocked
                    } else {
                        ReadinessStatus::State(outcome)
                    }
                }
            };
            statuses.insert(id.clone(), status);
        }
        let ready = self
            .requirements
            .iter()
            .filter(|(_, r)| r.required)
            .all(|(id, _)| statuses[id] == ReadinessStatus::State(StateOutcome::Ready));
        let degraded = self
            .requirements
            .iter()
            .filter(|(_, r)| !r.required)
            .any(|(id, _)| statuses[id] != ReadinessStatus::State(StateOutcome::Ready));
        Ok(ReadinessBarrier {
            statuses,
            ready,
            degraded,
        })
    }
}
