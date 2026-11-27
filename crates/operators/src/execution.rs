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
    type Input: ?Sized;
    type Output;

    fn step(&mut self, values: &Self::Input) -> Result<Self::Output>;
    fn capture_state(&self) -> Columns;
    fn restore_state(&mut self, state: Columns) -> Result<()>;
}

impl VectorKernel for Kernel {
    fn evaluate(&self, columns: &[Vec<Option<Decimal>>]) -> Result<Vec<Option<Decimal>>> {
        Kernel::evaluate(self, columns)
    }
}

#[derive(Clone, Debug)]
pub struct CrossSectionStream {
    kernel: Kernel,
    instrument_count: usize,
}

impl CrossSectionStream {
    pub fn new(kernel: Kernel, instrument_count: usize) -> Result<Self> {
        if !kernel.operator().is_cross_section() || instrument_count == 0 {
            return Err(Error::InvalidInputs);
        }
        if instrument_count.saturating_mul(kernel.operator().input_count())
            > crate::algebra::MAX_CELLS
        {
            return Err(Error::BudgetExceeded);
        }
        Ok(Self {
            kernel,
            instrument_count,
        })
    }
}

impl EventKernel for CrossSectionStream {
    type Input = [Vec<Option<Decimal>>];
    type Output = Vec<Option<Decimal>>;

    fn step(&mut self, values: &Self::Input) -> Result<Self::Output> {
        if self.kernel.validate_columns(values)? != self.instrument_count {
            return Err(Error::InvalidInputs);
        }
        self.kernel.cross_section(values)
    }

    fn capture_state(&self) -> Columns {
        Vec::new()
    }

    fn restore_state(&mut self, state: Columns) -> Result<()> {
        if state.is_empty() {
            Ok(())
        } else {
            Err(Error::InvalidInputs)
        }
    }
}

impl EventKernel for Stream {
    type Input = [Option<Decimal>];
    type Output = Option<Decimal>;

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
