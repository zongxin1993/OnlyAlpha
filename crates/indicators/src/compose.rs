//! Pure operator-composed indicator DAG with dual vector and event execution.
//!
//! Every indicator in this crate is assembled strictly from certified
//! [`onlyalpha_operators`] kernels and streams without private rolling state.

use onlyalpha_operators::algebra::{Columns, Decimal, Error, Kernel, Operator, Parameters, Stream};
use onlyalpha_operators::execution::{EventKernel, VectorKernel};

pub type Result<T> = std::result::Result<T, Error>;

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct IndicatorState(Vec<Columns>);

impl IndicatorState {
    pub fn as_slice(&self) -> &[Columns] {
        &self.0
    }

    pub fn from_columns(columns: Vec<Columns>) -> Self {
        Self(columns)
    }
}

#[derive(Clone, Debug)]
enum Node {
    Input(usize),
    Constant(Decimal),
    Op { kernel: Kernel, inputs: Vec<usize> },
}

pub(crate) struct Builder {
    input_count: usize,
    nodes: Vec<Node>,
}

impl Builder {
    pub(crate) fn new(input_count: usize) -> Self {
        Self {
            input_count,
            nodes: Vec::new(),
        }
    }

    pub(crate) fn input(&mut self, index: usize) -> usize {
        assert!(index < self.input_count);
        let id = self.nodes.len();
        self.nodes.push(Node::Input(index));
        id
    }

    pub(crate) fn constant(&mut self, value: Decimal) -> usize {
        let id = self.nodes.len();
        self.nodes.push(Node::Constant(value));
        id
    }

    pub(crate) fn op(
        &mut self,
        operator: Operator,
        parameters: Parameters,
        inputs: &[usize],
    ) -> Result<usize> {
        let kernel = Kernel::new(operator, parameters)?;
        if inputs.len() != operator.input_count() {
            return Err(Error::InvalidInputs);
        }
        let id = self.nodes.len();
        self.nodes.push(Node::Op {
            kernel,
            inputs: inputs.to_vec(),
        });
        Ok(id)
    }

    pub(crate) fn finish(
        self,
        outputs: Vec<usize>,
        minimum_observations: usize,
    ) -> ComposedIndicator {
        ComposedIndicator {
            input_count: self.input_count,
            nodes: self.nodes,
            outputs,
            minimum_observations,
        }
    }
}

#[derive(Clone, Debug)]
pub struct ComposedIndicator {
    input_count: usize,
    nodes: Vec<Node>,
    outputs: Vec<usize>,
    minimum_observations: usize,
}

impl ComposedIndicator {
    pub fn input_count(&self) -> usize {
        self.input_count
    }

    pub fn output_count(&self) -> usize {
        self.outputs.len()
    }

    pub fn minimum_observations(&self) -> usize {
        self.minimum_observations
    }

    pub fn evaluate_vector(
        &self,
        inputs: &[Vec<Option<Decimal>>],
    ) -> Result<Vec<Vec<Option<Decimal>>>> {
        if inputs.len() != self.input_count {
            return Err(Error::InvalidInputs);
        }
        let len = inputs.first().map_or(0, Vec::len);
        if inputs.iter().any(|column| column.len() != len) {
            return Err(Error::InvalidInputs);
        }
        let mut values: Vec<Vec<Option<Decimal>>> = Vec::with_capacity(self.nodes.len());
        for node in &self.nodes {
            let column = match node {
                Node::Input(index) => inputs[*index].clone(),
                Node::Constant(value) => vec![Some(value.clone()); len],
                Node::Op { kernel, inputs } => {
                    let args: Vec<Vec<Option<Decimal>>> =
                        inputs.iter().map(|&id| values[id].clone()).collect();
                    VectorKernel::evaluate(kernel, &args)?
                }
            };
            values.push(column);
        }
        Ok(self.outputs.iter().map(|&id| values[id].clone()).collect())
    }

    pub fn event_stream(&self) -> Result<ComposedStream> {
        let mut streams = Vec::with_capacity(self.nodes.len());
        for node in &self.nodes {
            match node {
                Node::Op { kernel, .. } => streams.push(Some(Stream::new(kernel.clone())?)),
                Node::Input(_) | Node::Constant(_) => streams.push(None),
            }
        }
        Ok(ComposedStream {
            indicator: self.clone(),
            streams,
        })
    }
}

#[derive(Clone, Debug)]
pub struct ComposedStream {
    indicator: ComposedIndicator,
    streams: Vec<Option<Stream>>,
}

impl ComposedStream {
    pub fn step(&mut self, values: &[Option<Decimal>]) -> Result<Vec<Option<Decimal>>> {
        if values.len() != self.indicator.input_count {
            return Err(Error::InvalidInputs);
        }
        let mut candidate = self.streams.clone();
        let mut cells: Vec<Option<Decimal>> = Vec::with_capacity(self.indicator.nodes.len());
        for (index, node) in self.indicator.nodes.iter().enumerate() {
            let cell = match node {
                Node::Input(input_index) => values[*input_index].clone(),
                Node::Constant(value) => Some(value.clone()),
                Node::Op { inputs, .. } => {
                    let args: Vec<Option<Decimal>> =
                        inputs.iter().map(|&id| cells[id].clone()).collect();
                    let stream = candidate[index].as_mut().expect("op node has stream");
                    EventKernel::step(stream, &args)?
                }
            };
            cells.push(cell);
        }
        self.streams = candidate;
        Ok(self
            .indicator
            .outputs
            .iter()
            .map(|&id| cells[id].clone())
            .collect())
    }

    pub fn capture_state(&self) -> IndicatorState {
        let states = self
            .streams
            .iter()
            .filter_map(|stream| stream.as_ref().map(EventKernel::capture_state))
            .collect();
        IndicatorState(states)
    }

    pub fn restore_state(&mut self, state: IndicatorState) -> Result<()> {
        let expected = self.streams.iter().filter(|s| s.is_some()).count();
        if state.0.len() != expected {
            return Err(Error::InvalidInputs);
        }
        let mut candidate = self.streams.clone();
        let mut iter = state.0.into_iter();
        for stream in candidate.iter_mut().flatten() {
            let columns = iter.next().expect("checked length");
            EventKernel::restore_state(stream, columns)?;
        }
        self.streams = candidate;
        Ok(())
    }
}
