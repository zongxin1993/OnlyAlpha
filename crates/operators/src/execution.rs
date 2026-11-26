//! Vector and event execution contracts over one numeric implementation.
//!
//! [`VectorKernel`] consumes complete columns in one call. [`EventKernel`]
//! advances one observation at a time and can capture/restore the exact state it
//! retains. Both are implemented by the same [`crate::algebra`] semantics; the
//! certification suite proves pointwise equivalence.
use crate::algebra::{Columns, Decimal, Error, Kernel, Stream};

pub type Result<T> = std::result::Result<T, Error>;

pub trait VectorKernel {
    fn evaluate(&self, columns: &[Vec<Option<Decimal>>]) -> Result<Vec<Option<Decimal>>>;
}

pub trait EventKernel {
    fn step(&mut self, values: &[Option<Decimal>]) -> Result<Option<Decimal>>;
    fn capture_state(&self) -> Columns;
    fn restore_state(&mut self, state: Columns) -> Result<()>;
}

impl VectorKernel for Kernel {
    fn evaluate(&self, columns: &[Vec<Option<Decimal>>]) -> Result<Vec<Option<Decimal>>> {
        Kernel::evaluate(self, columns)
    }
}

impl EventKernel for Stream {
    fn step(&mut self, values: &[Option<Decimal>]) -> Result<Option<Decimal>> {
        Stream::push(self, values)
    }

    fn capture_state(&self) -> Columns {
        Stream::checkpoint(self)
    }

    fn restore_state(&mut self, state: Columns) -> Result<()> {
        Stream::restore(self, state)
    }
}
