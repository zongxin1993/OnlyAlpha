//! Immutable UTC microsecond intervals; no clock, persistence or market policy.
use crate::{base::invalid, errors::OnlyDomainError, time::OnlyUtcDateTime};

/// Nonempty half-open interval [start, end). Endpoints cannot be mutated independently.
#[derive(Clone, Copy, Debug, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub struct OnlyTimeRange {
    start: OnlyUtcDateTime,
    end: OnlyUtcDateTime,
}
impl OnlyTimeRange {
    pub fn new(start: OnlyUtcDateTime, end: OnlyUtcDateTime) -> Result<Self, OnlyDomainError> {
        if start >= end {
            return Err(invalid("time range must be increasing and is [start, end)"));
        }
        Ok(Self { start, end })
    }
    pub fn start(self) -> OnlyUtcDateTime {
        self.start
    }
    pub fn end(self) -> OnlyUtcDateTime {
        self.end
    }
    pub fn contains(self, value: OnlyUtcDateTime) -> bool {
        self.start <= value && value < self.end
    }
    pub fn overlaps(self, other: Self) -> bool {
        self.start < other.end && other.start < self.end
    }
    pub fn intersection(self, other: Self) -> Option<Self> {
        let start = self.start.max(other.start);
        let end = self.end.min(other.end);
        (start < end).then_some(Self { start, end })
    }
    pub fn subtract(self, other: Self) -> Vec<Self> {
        let Some(overlap) = self.intersection(other) else {
            return vec![self];
        };
        let mut result = Vec::new();
        if self.start < overlap.start {
            result.push(Self {
                start: self.start,
                end: overlap.start,
            });
        }
        if overlap.end < self.end {
            result.push(Self {
                start: overlap.end,
                end: self.end,
            });
        }
        result
    }
}

pub fn only_merge_ranges(ranges: &[OnlyTimeRange]) -> Vec<OnlyTimeRange> {
    let mut sorted = ranges.to_vec();
    sorted.sort_unstable();
    let mut merged: Vec<OnlyTimeRange> = Vec::new();
    for item in sorted {
        if let Some(previous) = merged.last_mut()
            && previous.end >= item.start
        {
            previous.end = previous.end.max(item.end);
            continue;
        }
        merged.push(item);
    }
    merged
}

pub fn only_missing_ranges(
    requested: OnlyTimeRange,
    coverage: &[OnlyTimeRange],
) -> Vec<OnlyTimeRange> {
    let mut missing = vec![requested];
    for covered in only_merge_ranges(coverage) {
        missing = missing
            .into_iter()
            .flat_map(|item| item.subtract(covered))
            .collect();
    }
    missing
}
