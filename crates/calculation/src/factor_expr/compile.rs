//! Static causal validation and DAG / instruction-stream compilation for declarative factor expressions.

use crate::factor_expr::parser::{BinaryOp, Expr, UnaryOp, parse};
use crate::{
    Result,
    record::{err, hash},
};
use onlyalpha_operators::algebra::{
    Decimal, Kernel, MAX_CELLS, MAX_INPUT_DIGITS, MAX_INPUT_SCALE, MAX_WINDOW, MAX_WINDOW_WORK,
    Operator, Parameters,
};
use onlyalpha_operators::registry::{
    ExecutionShape, NUMERIC_POLICY, SEMANTIC_VERSION, StateCapability,
};
use serde_json::{Value, json};
use std::collections::{BTreeMap, BTreeSet};
use std::num::NonZeroUsize;

pub const MAX_DAG_NODES: usize = 1024;
pub const MAX_INPUT_FIELDS: usize = 128;

/// Forbidden field words in all expressions
/// (account, execution, runtime, non-deterministic, or external environment state).
const FORBIDDEN_STATE_WORDS: &[&str] = &[
    "account",
    "position",
    "cash",
    "fill",
    "filled",
    "order",
    "execution",
    "portfolio",
    "equity",
    "equities",
    "balance",
    "pnl",
    "margin",
    "fee",
    "commission",
    "slippage",
    "broker",
    "venue",
    "clock",
    "now",
    "rand",
    "env",
];

/// Additional field words forbidden exclusively in causal `FactorExpr` inputs.
const FORBIDDEN_FACTOR_WORDS: &[&str] = &["future", "target", "label"];

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum ExprKind {
    Factor,
    Target,
}

impl ExprKind {
    pub fn as_str(self) -> &'static str {
        match self {
            Self::Factor => "FACTOR",
            Self::Target => "TARGET",
        }
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, PartialOrd, Ord)]
pub enum CompareOp {
    Lt,
    Le,
    Gt,
    Ge,
    Eq,
    Ne,
}

impl CompareOp {
    pub fn symbol(self) -> &'static str {
        match self {
            Self::Lt => "<",
            Self::Le => "<=",
            Self::Gt => ">",
            Self::Ge => ">=",
            Self::Eq => "==",
            Self::Ne => "!=",
        }
    }

    pub fn code(self) -> &'static str {
        match self {
            Self::Lt => "lt",
            Self::Le => "le",
            Self::Gt => "gt",
            Self::Ge => "ge",
            Self::Eq => "eq",
            Self::Ne => "ne",
        }
    }
}

#[derive(Clone, Debug)]
pub enum Instruction {
    Input(String),
    Constant(Decimal),
    Compare {
        op: CompareOp,
        lhs: usize,
        rhs: usize,
    },
    Op {
        kernel: Kernel,
        parameters: Parameters,
        inputs: Vec<usize>,
    },
    Lead {
        input: usize,
        offset: NonZeroUsize,
    },
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct ResourceEstimate {
    pub node_count: usize,
    pub stateful_op_count: usize,
    pub max_state_cells: usize,
    pub work_per_row: usize,
    pub minimum_observations: usize,
    pub max_lookahead: usize,
}

#[derive(Clone, Debug)]
pub(crate) struct CompiledDag {
    pub(crate) source: String,
    pub(crate) instructions: Vec<Instruction>,
    pub(crate) output: usize,
    pub(crate) inputs: BTreeSet<String>,
    pub(crate) operator_ids: BTreeSet<String>,
    pub(crate) has_cross_section: bool,
    pub(crate) budget: ResourceEstimate,
    pub(crate) canonical: String,
    pub(crate) fingerprint: String,
}

pub(crate) fn canonical_decimal(value: &Decimal) -> String {
    if value == &Decimal::from(0) {
        return "0".to_owned();
    }
    value.normalized().to_plain_string()
}

fn identifier_words(name: &str) -> Vec<String> {
    let bytes = name.as_bytes();
    let mut words = Vec::new();
    let mut start = 0usize;
    for i in 0..bytes.len() {
        let b = bytes[i];
        if b == b'_' {
            if start < i {
                words.push(name[start..i].to_ascii_lowercase());
            }
            start = i + 1;
            continue;
        }
        if i > start {
            let prev = bytes[i - 1];
            let next = bytes.get(i + 1).copied();
            let boundary = (prev.is_ascii_lowercase() && b.is_ascii_uppercase())
                || (prev.is_ascii_digit() && b.is_ascii_alphabetic())
                || (prev.is_ascii_alphabetic() && b.is_ascii_digit())
                || (prev.is_ascii_uppercase()
                    && b.is_ascii_uppercase()
                    && next.is_some_and(|n| n.is_ascii_lowercase()));
            if boundary {
                words.push(name[start..i].to_ascii_lowercase());
                start = i;
            }
        }
    }
    if start < bytes.len() {
        words.push(name[start..].to_ascii_lowercase());
    }
    words
}

fn matches_forbidden_word(word: &str, list: &[&str]) -> bool {
    if list.contains(&word) {
        return true;
    }
    if word.len() > 3
        && let Some(stem) = word.strip_suffix('s')
        && list.contains(&stem)
    {
        return true;
    }
    if word.len() > 4
        && let Some(stem) = word.strip_suffix("es")
        && list.contains(&stem)
    {
        return true;
    }
    false
}

fn validate_field(name: &str, kind: ExprKind, allowed: Option<&BTreeSet<String>>) -> Result<()> {
    for word in identifier_words(name) {
        if word.starts_with("rand") || matches_forbidden_word(&word, FORBIDDEN_STATE_WORDS) {
            return Err(err("FACTOR_EXPR_FORBIDDEN_INPUT"));
        }
        if kind == ExprKind::Factor && matches_forbidden_word(&word, FORBIDDEN_FACTOR_WORDS) {
            return Err(err("FACTOR_EXPR_FORBIDDEN_INPUT"));
        }
    }
    let lower = name.to_ascii_lowercase();
    if matches_forbidden_word(&lower, FORBIDDEN_STATE_WORDS)
        || (kind == ExprKind::Factor && matches_forbidden_word(&lower, FORBIDDEN_FACTOR_WORDS))
    {
        return Err(err("FACTOR_EXPR_FORBIDDEN_INPUT"));
    }
    if let Some(allowed) = allowed
        && !allowed.contains(name)
    {
        return Err(err("FACTOR_EXPR_UNDECLARED_INPUT"));
    }
    Ok(())
}

fn eval_constant_decimal(expr: &Expr) -> Result<Decimal> {
    match expr {
        Expr::Number { value, .. } => Ok(value.clone()),
        Expr::Unary {
            op: UnaryOp::Pos,
            expr,
        } => eval_constant_decimal(expr),
        Expr::Unary {
            op: UnaryOp::Neg,
            expr,
        } => {
            let inner = eval_constant_decimal(expr)?;
            if inner == 0 {
                Ok(Decimal::from(0))
            } else {
                Ok(-inner)
            }
        }
        _ => Err(err("FACTOR_EXPR_CONSTANT_PARAM_REQUIRED")),
    }
}

fn eval_constant_i64(expr: &Expr) -> Result<i64> {
    let dec = eval_constant_decimal(expr)?;
    if !dec.is_integer() {
        return Err(err("FACTOR_EXPR_INTEGER_PARAM_REQUIRED"));
    }
    let plain = dec.with_scale(0).to_plain_string();
    plain
        .parse::<i64>()
        .map_err(|_| err("FACTOR_EXPR_INVALID_PARAMETER"))
}

fn positive_window(expr: &Expr, kind: ExprKind) -> Result<NonZeroUsize> {
    let raw = eval_constant_i64(expr)?;
    if raw < 0 {
        return Err(err(if kind == ExprKind::Factor {
            "FACTOR_EXPR_LOOKAHEAD_FORBIDDEN"
        } else {
            "FACTOR_EXPR_INVALID_PARAMETER"
        }));
    }
    if raw == 0 {
        return Err(err("FACTOR_EXPR_INVALID_PARAMETER"));
    }
    let period = usize::try_from(raw).map_err(|_| err("FACTOR_EXPR_INVALID_PARAMETER"))?;
    if period > MAX_WINDOW {
        return Err(err("FACTOR_EXPR_WINDOW_BUDGET"));
    }
    NonZeroUsize::new(period).ok_or_else(|| err("FACTOR_EXPR_INVALID_PARAMETER"))
}

fn canonical_params(op: Operator, params: &Parameters) -> String {
    let mut parts = Vec::new();
    if let Some(period) = params.period {
        parts.push(format!("p={}", period.get()));
    }
    if let Some(weight) = params.weight {
        parts.push(format!("w={}", weight.get()));
    }
    if let Some(factor) = &params.factor {
        parts.push(format!("f={}", canonical_decimal(factor)));
    }
    if let Some(q) = &params.quantile {
        parts.push(format!("q={}", canonical_decimal(q)));
    }
    if op == Operator::CrossSectionPercentile {
        parts.push(format!(
            "d={}",
            if params.lower_is_better { "L" } else { "H" }
        ));
    }
    parts.join(";")
}

fn params_json(op: Operator, params: &Parameters) -> Value {
    let mut map = serde_json::Map::new();
    if let Some(period) = params.period {
        map.insert("period".into(), json!(period.get()));
    }
    if let Some(weight) = params.weight {
        map.insert("weight".into(), json!(weight.get()));
    }
    if let Some(factor) = &params.factor {
        map.insert("factor".into(), json!(canonical_decimal(factor)));
    }
    if let Some(q) = &params.quantile {
        map.insert("quantile".into(), json!(canonical_decimal(q)));
    }
    if op == Operator::CrossSectionPercentile {
        map.insert(
            "direction".into(),
            json!(if params.lower_is_better {
                "LOWER_IS_BETTER"
            } else {
                "HIGHER_IS_BETTER"
            }),
        );
    }
    Value::Object(map)
}

struct Compiler<'a> {
    kind: ExprKind,
    allowed: Option<&'a BTreeSet<String>>,
    instructions: Vec<Instruction>,
    warmup: Vec<usize>,
    lookahead: Vec<usize>,
    cse: BTreeMap<String, usize>,
    inputs: BTreeSet<String>,
    operator_ids: BTreeSet<String>,
    has_cross_section: bool,
}

impl<'a> Compiler<'a> {
    fn new(kind: ExprKind, allowed: Option<&'a BTreeSet<String>>) -> Self {
        Self {
            kind,
            allowed,
            instructions: Vec::new(),
            warmup: Vec::new(),
            lookahead: Vec::new(),
            cse: BTreeMap::new(),
            inputs: BTreeSet::new(),
            operator_ids: BTreeSet::new(),
            has_cross_section: false,
        }
    }

    fn emit(&mut self, key: String, inst: Instruction, w: usize, l: usize) -> Result<usize> {
        if let Some(&existing) = self.cse.get(&key) {
            return Ok(existing);
        }
        if self.instructions.len() >= MAX_DAG_NODES {
            return Err(err("FACTOR_EXPR_NODE_BUDGET"));
        }
        let id = self.instructions.len();
        self.instructions.push(inst);
        self.warmup.push(w);
        self.lookahead.push(l);
        self.cse.insert(key, id);
        Ok(id)
    }

    fn emit_input(&mut self, name: &str) -> Result<usize> {
        validate_field(name, self.kind, self.allowed)?;
        if !self.inputs.contains(name) && self.inputs.len() >= MAX_INPUT_FIELDS {
            return Err(err("FACTOR_EXPR_INPUT_BUDGET"));
        }
        self.inputs.insert(name.to_owned());
        self.emit(format!("in:{name}"), Instruction::Input(name.into()), 1, 0)
    }

    fn emit_const(&mut self, value: Decimal) -> Result<usize> {
        let (_, scale) = value.as_bigint_and_exponent();
        if value.digits() > MAX_INPUT_DIGITS || scale.unsigned_abs() > MAX_INPUT_SCALE as u64 {
            return Err(err("FACTOR_EXPR_NUMERIC_BUDGET"));
        }
        let normalized = if value == 0 {
            Decimal::from(0)
        } else {
            value.normalized()
        };
        let key = format!("const:{}", canonical_decimal(&normalized));
        self.emit(key, Instruction::Constant(normalized), 1, 0)
    }

    fn emit_compare(&mut self, op: CompareOp, lhs: usize, rhs: usize) -> Result<usize> {
        let key = format!("cmp:{}:{lhs},{rhs}", op.code());
        let w = self.warmup[lhs].max(self.warmup[rhs]);
        let l = self.lookahead[lhs].max(self.lookahead[rhs]);
        self.emit(key, Instruction::Compare { op, lhs, rhs }, w, l)
    }

    fn emit_op(
        &mut self,
        operator: Operator,
        parameters: Parameters,
        inputs: Vec<usize>,
    ) -> Result<usize> {
        let spec = operator.spec();
        if inputs.len() != spec.inputs {
            return Err(err("FACTOR_EXPR_ARITY"));
        }
        let kernel = Kernel::new(operator, parameters.clone())
            .map_err(|_| err("FACTOR_EXPR_INVALID_PARAMETER"))?;
        if spec.shape == ExecutionShape::CrossSection {
            self.has_cross_section = true;
        }
        self.operator_ids.insert(operator.type_id());
        let input_w = inputs.iter().map(|&id| self.warmup[id]).max().unwrap_or(1);
        let op_w = spec
            .minimum_observations(parameters.period)
            .ok_or_else(|| err("FACTOR_EXPR_INVALID_PARAMETER"))?;
        let w = input_w.saturating_add(op_w.saturating_sub(1));
        let l = inputs
            .iter()
            .map(|&id| self.lookahead[id])
            .max()
            .unwrap_or(0);
        let args_key = inputs
            .iter()
            .map(usize::to_string)
            .collect::<Vec<_>>()
            .join(",");
        let key = format!(
            "op:{}:{}:{args_key}",
            operator.type_id(),
            canonical_params(operator, &parameters)
        );
        self.emit(
            key,
            Instruction::Op {
                kernel,
                parameters,
                inputs,
            },
            w,
            l,
        )
    }

    fn emit_lead(&mut self, input: usize, offset: NonZeroUsize) -> Result<usize> {
        if self.kind == ExprKind::Factor {
            return Err(err("FACTOR_EXPR_LOOKAHEAD_FORBIDDEN"));
        }
        let w = self.warmup[input];
        let l = self.lookahead[input].saturating_add(offset.get());
        if l > MAX_WINDOW {
            return Err(err("FACTOR_EXPR_WINDOW_BUDGET"));
        }
        let key = format!("lead:{input}:{}", offset.get());
        self.emit(key, Instruction::Lead { input, offset }, w, l)
    }

    fn compile_expr(&mut self, expr: &Expr) -> Result<usize> {
        match expr {
            Expr::Field(name) => self.emit_input(name),
            Expr::Number { value, .. } => self.emit_const(value.clone()),
            Expr::Unary { op, expr } => match op {
                UnaryOp::Pos => self.compile_expr(expr),
                UnaryOp::Neg => {
                    if let Ok(constant) = eval_constant_decimal(expr) {
                        let neg = if constant == 0 {
                            Decimal::from(0)
                        } else {
                            -constant
                        };
                        self.emit_const(neg)
                    } else {
                        let zero = self.emit_const(Decimal::from(0))?;
                        let inner = self.compile_expr(expr)?;
                        self.emit_op(Operator::Subtract, Parameters::default(), vec![zero, inner])
                    }
                }
                UnaryOp::Not => {
                    let inner = self.compile_expr(expr)?;
                    let zero = self.emit_const(Decimal::from(0))?;
                    let one = self.emit_const(Decimal::from(1))?;
                    self.emit_op(
                        Operator::Where,
                        Parameters::default(),
                        vec![inner, zero, one],
                    )
                }
            },
            Expr::Binary { op, lhs, rhs } => {
                let a = self.compile_expr(lhs)?;
                let b = self.compile_expr(rhs)?;
                match op {
                    BinaryOp::Add => self.emit_op(Operator::Add, Parameters::default(), vec![a, b]),
                    BinaryOp::Sub => {
                        self.emit_op(Operator::Subtract, Parameters::default(), vec![a, b])
                    }
                    BinaryOp::Mul => {
                        self.emit_op(Operator::Multiply, Parameters::default(), vec![a, b])
                    }
                    BinaryOp::Div => {
                        self.emit_op(Operator::Divide, Parameters::default(), vec![a, b])
                    }
                    BinaryOp::Lt => self.emit_compare(CompareOp::Lt, a, b),
                    BinaryOp::Le => self.emit_compare(CompareOp::Le, a, b),
                    BinaryOp::Gt => self.emit_compare(CompareOp::Gt, a, b),
                    BinaryOp::Ge => self.emit_compare(CompareOp::Ge, a, b),
                    BinaryOp::Eq => self.emit_compare(CompareOp::Eq, a, b),
                    BinaryOp::Ne => self.emit_compare(CompareOp::Ne, a, b),
                    BinaryOp::And => {
                        let one = self.emit_const(Decimal::from(1))?;
                        let zero = self.emit_const(Decimal::from(0))?;
                        let b_bool = self.emit_op(
                            Operator::Where,
                            Parameters::default(),
                            vec![b, one, zero],
                        )?;
                        let b_zero = self.emit_op(
                            Operator::Where,
                            Parameters::default(),
                            vec![b, zero, zero],
                        )?;
                        self.emit_op(
                            Operator::Where,
                            Parameters::default(),
                            vec![a, b_bool, b_zero],
                        )
                    }
                    BinaryOp::Or => {
                        let one = self.emit_const(Decimal::from(1))?;
                        let zero = self.emit_const(Decimal::from(0))?;
                        let b_one = self.emit_op(
                            Operator::Where,
                            Parameters::default(),
                            vec![b, one, one],
                        )?;
                        let b_bool = self.emit_op(
                            Operator::Where,
                            Parameters::default(),
                            vec![b, one, zero],
                        )?;
                        self.emit_op(
                            Operator::Where,
                            Parameters::default(),
                            vec![a, b_one, b_bool],
                        )
                    }
                }
            }
            Expr::Call { name, args } => self.compile_call(name, args),
        }
    }

    fn compile_call(&mut self, name: &str, args: &[Expr]) -> Result<usize> {
        let key = name.to_ascii_lowercase();
        match key.as_str() {
            "add" => self.compile_binary_op(Operator::Add, args),
            "sub" | "subtract" => self.compile_binary_op(Operator::Subtract, args),
            "mul" | "multiply" => self.compile_binary_op(Operator::Multiply, args),
            "div" | "divide" => self.compile_binary_op(Operator::Divide, args),
            "abs" => self.compile_unary_op(Operator::Abs, args),
            "sign" => self.compile_unary_op(Operator::Sign, args),
            "log" => self.compile_unary_op(Operator::Log, args),
            "cumsum" => self.compile_unary_op(Operator::CumSum, args),
            "scale" => {
                if args.len() != 2 {
                    return Err(err("FACTOR_EXPR_ARITY"));
                }
                let x = self.compile_expr(&args[0])?;
                let factor = eval_constant_decimal(&args[1])?;
                let factor = if factor == 0 {
                    Decimal::from(0)
                } else {
                    factor.normalized()
                };
                self.emit_op(
                    Operator::Scale,
                    Parameters {
                        factor: Some(factor),
                        ..Default::default()
                    },
                    vec![x],
                )
            }
            "where" | "if" => {
                if args.len() != 3 {
                    return Err(err("FACTOR_EXPR_ARITY"));
                }
                let c = self.compile_expr(&args[0])?;
                let t = self.compile_expr(&args[1])?;
                let f = self.compile_expr(&args[2])?;
                self.emit_op(Operator::Where, Parameters::default(), vec![c, t, f])
            }
            "greater" | "max2" => {
                if args.len() != 2 {
                    return Err(err("FACTOR_EXPR_ARITY"));
                }
                let a = self.compile_expr(&args[0])?;
                let b = self.compile_expr(&args[1])?;
                let cond = self.emit_compare(CompareOp::Gt, a, b)?;
                self.emit_op(Operator::Where, Parameters::default(), vec![cond, a, b])
            }
            "less" | "min2" => {
                if args.len() != 2 {
                    return Err(err("FACTOR_EXPR_ARITY"));
                }
                let a = self.compile_expr(&args[0])?;
                let b = self.compile_expr(&args[1])?;
                let cond = self.emit_compare(CompareOp::Lt, a, b)?;
                self.emit_op(Operator::Where, Parameters::default(), vec![cond, a, b])
            }
            "ref" | "delay" => {
                if args.len() != 2 {
                    return Err(err("FACTOR_EXPR_ARITY"));
                }
                let x = self.compile_expr(&args[0])?;
                let offset = eval_constant_i64(&args[1])?;
                if offset == 0 {
                    Ok(x)
                } else if offset > 0 {
                    let period = usize::try_from(offset)
                        .ok()
                        .filter(|&p| p <= MAX_WINDOW)
                        .and_then(NonZeroUsize::new)
                        .ok_or_else(|| err("FACTOR_EXPR_WINDOW_BUDGET"))?;
                    self.emit_op(
                        Operator::Delay,
                        Parameters {
                            period: Some(period),
                            ..Default::default()
                        },
                        vec![x],
                    )
                } else {
                    if self.kind == ExprKind::Factor {
                        return Err(err("FACTOR_EXPR_LOOKAHEAD_FORBIDDEN"));
                    }
                    let lead = offset
                        .checked_neg()
                        .and_then(|n| usize::try_from(n).ok())
                        .filter(|&p| p <= MAX_WINDOW)
                        .and_then(NonZeroUsize::new)
                        .ok_or_else(|| err("FACTOR_EXPR_WINDOW_BUDGET"))?;
                    self.emit_lead(x, lead)
                }
            }
            "lead" => {
                if args.len() != 2 {
                    return Err(err("FACTOR_EXPR_ARITY"));
                }
                if self.kind == ExprKind::Factor {
                    return Err(err("FACTOR_EXPR_LOOKAHEAD_FORBIDDEN"));
                }
                let x = self.compile_expr(&args[0])?;
                let lead = positive_window(&args[1], self.kind)?;
                self.emit_lead(x, lead)
            }
            "delta" => self.compile_window_op(Operator::Delta, args),
            "regressionresidual3" => {
                self.compile_multi_window_op(Operator::RegressionResidual3, args)
            }
            "conditionalbeta" => self.compile_multi_window_op(Operator::ConditionalBeta, args),
            "cumproductif" => self.compile_binary_op(Operator::CumProductIf, args),
            "pow" => self.compile_binary_op(Operator::Pow, args),
            "csscale" => self.compile_unary_op(Operator::CrossSectionScale, args),
            "groupdemean" => self.compile_binary_op(Operator::GroupDemean, args),
            "product" => self.compile_window_op(Operator::RollingProduct, args),
            "sma" => {
                let [input, period, weight] = args else {
                    return Err(err("FACTOR_EXPR_ARITY"));
                };
                let period = positive_window(period, self.kind)?;
                let weight = usize::try_from(eval_constant_i64(weight)?)
                    .ok()
                    .and_then(NonZeroUsize::new)
                    .filter(|w| *w <= period)
                    .ok_or_else(|| err("FACTOR_EXPR_INVALID_PARAMETER"))?;
                let input = self.compile_expr(input)?;
                self.emit_op(
                    Operator::SMA,
                    Parameters {
                        period: Some(period),
                        weight: Some(weight),
                        ..Default::default()
                    },
                    vec![input],
                )
            }
            "mean" | "rolling_mean" => self.compile_window_op(Operator::RollingMean, args),
            "sum" | "rolling_sum" => self.compile_window_op(Operator::RollingSum, args),
            "std" | "rolling_std" => self.compile_window_op(Operator::RollingStd, args),
            "var" | "rolling_var" => self.compile_window_op(Operator::RollingVar, args),
            "min" | "rolling_min" => self.compile_window_op(Operator::RollingMin, args),
            "max" | "rolling_max" => self.compile_window_op(Operator::RollingMax, args),
            "wma" | "decay_linear" => self.compile_window_op(Operator::DecayLinear, args),
            "ema" => self.compile_window_op(Operator::EMA, args),
            "rma" => self.compile_window_op(Operator::RMA, args),
            "slope" | "rolling_slope" => self.compile_window_op(Operator::RollingSlope, args),
            "rsquare" => self.compile_window_op(Operator::RollingRSquared, args),
            "resi" => self.compile_window_op(Operator::RollingResidual, args),
            "idxmax" => self.compile_window_op(Operator::RollingArgMax, args),
            "idxmin" => self.compile_window_op(Operator::RollingArgMin, args),
            "quantile" => self.compile_window_op(Operator::RollingQuantile, args),
            "tsrank" | "ts_rank" => self.compile_window_op(Operator::TSRank, args),
            "cov" | "rolling_covariance" => {
                self.compile_multi_window_op(Operator::RollingCovariance, args)
            }
            "corr" | "rolling_correlation" => {
                self.compile_multi_window_op(Operator::RollingCorrelation, args)
            }
            "rank" => match args.len() {
                1 => self.compile_unary_op(Operator::CrossSectionRank, args),
                2 => self.compile_window_op(Operator::TSRank, args),
                _ => Err(err("FACTOR_EXPR_ARITY")),
            },
            "csrank" | "cross_section_rank" => {
                self.compile_unary_op(Operator::CrossSectionRank, args)
            }
            "cszscore" | "cross_section_zscore" => {
                self.compile_unary_op(Operator::CrossSectionZScore, args)
            }
            "csdemean" | "cross_section_demean" => {
                self.compile_unary_op(Operator::CrossSectionDemean, args)
            }
            "cscorr" | "cross_section_correlation" => {
                self.compile_binary_op(Operator::CrossSectionCorrelation, args)
            }
            "cspercentile" | "cross_section_percentile" => {
                if args.is_empty() || args.len() > 2 {
                    return Err(err("FACTOR_EXPR_ARITY"));
                }
                let x = self.compile_expr(&args[0])?;
                let lower_is_better = if args.len() == 1 {
                    false
                } else {
                    match eval_constant_i64(&args[1])? {
                        1 => false,
                        -1 => true,
                        _ => return Err(err("FACTOR_EXPR_INVALID_PARAMETER")),
                    }
                };
                self.emit_op(
                    Operator::CrossSectionPercentile,
                    Parameters {
                        lower_is_better,
                        ..Default::default()
                    },
                    vec![x],
                )
            }
            _ => Err(err("FACTOR_EXPR_UNKNOWN_OPERATOR")),
        }
    }

    fn compile_unary_op(&mut self, operator: Operator, args: &[Expr]) -> Result<usize> {
        if args.len() != 1 {
            return Err(err("FACTOR_EXPR_ARITY"));
        }
        let x = self.compile_expr(&args[0])?;
        self.emit_op(operator, Parameters::default(), vec![x])
    }

    fn compile_binary_op(&mut self, operator: Operator, args: &[Expr]) -> Result<usize> {
        if args.len() != 2 {
            return Err(err("FACTOR_EXPR_ARITY"));
        }
        let a = self.compile_expr(&args[0])?;
        let b = self.compile_expr(&args[1])?;
        self.emit_op(operator, Parameters::default(), vec![a, b])
    }

    fn compile_window_op(&mut self, operator: Operator, args: &[Expr]) -> Result<usize> {
        let quantile = match (operator, args) {
            (Operator::RollingQuantile, [_, _, q]) => Some(eval_constant_decimal(q)?),
            (Operator::RollingQuantile, _) => return Err(err("FACTOR_EXPR_ARITY")),
            (_, [_, _]) => None,
            _ => return Err(err("FACTOR_EXPR_ARITY")),
        };
        let x = self.compile_expr(&args[0])?;
        let period = positive_window(&args[1], self.kind)?;
        self.emit_op(
            operator,
            Parameters {
                period: Some(period),
                quantile,
                ..Default::default()
            },
            vec![x],
        )
    }

    fn compile_multi_window_op(&mut self, operator: Operator, args: &[Expr]) -> Result<usize> {
        let arity = operator.input_count();
        if args.len() != arity + 1 {
            return Err(err("FACTOR_EXPR_ARITY"));
        }
        let inputs = args[..arity]
            .iter()
            .map(|input| self.compile_expr(input))
            .collect::<Result<Vec<_>>>()?;
        let period = positive_window(&args[arity], self.kind)?;
        self.emit_op(
            operator,
            Parameters {
                period: Some(period),
                ..Default::default()
            },
            inputs,
        )
    }

    fn finish(self, source: String, output: usize) -> Result<CompiledDag> {
        let mut stateful_op_count = 0usize;
        let mut max_state_cells = 0usize;
        let mut work_per_row = 0usize;
        for inst in &self.instructions {
            match inst {
                Instruction::Op { kernel, .. } => {
                    let history = kernel.history_limit();
                    if kernel.operator().spec().state() == StateCapability::Checkpointable {
                        stateful_op_count += 1;
                        let cells = history
                            .checked_mul(kernel.operator().input_count())
                            .ok_or_else(|| err("FACTOR_EXPR_RESOURCE_BUDGET"))?;
                        max_state_cells = max_state_cells
                            .checked_add(cells)
                            .ok_or_else(|| err("FACTOR_EXPR_RESOURCE_BUDGET"))?;
                    }
                    work_per_row = work_per_row
                        .checked_add(kernel.work_per_row())
                        .ok_or_else(|| err("FACTOR_EXPR_RESOURCE_BUDGET"))?;
                }
                Instruction::Input(_)
                | Instruction::Constant(_)
                | Instruction::Compare { .. }
                | Instruction::Lead { .. } => {
                    work_per_row = work_per_row
                        .checked_add(1)
                        .ok_or_else(|| err("FACTOR_EXPR_RESOURCE_BUDGET"))?;
                }
            }
        }
        if max_state_cells > MAX_CELLS || work_per_row > MAX_WINDOW_WORK {
            return Err(err("FACTOR_EXPR_RESOURCE_BUDGET"));
        }
        let minimum_observations = self.warmup[output];
        let max_lookahead = self.lookahead[output];
        if self.kind == ExprKind::Factor && max_lookahead != 0 {
            return Err(err("FACTOR_EXPR_LOOKAHEAD_FORBIDDEN"));
        }
        let budget = ResourceEstimate {
            node_count: self.instructions.len(),
            stateful_op_count,
            max_state_cells,
            work_per_row,
            minimum_observations,
            max_lookahead,
        };
        let canonical = format_canonical(&self.instructions, output);
        let fingerprint = dag_fingerprint(self.kind, &self.instructions, output);
        Ok(CompiledDag {
            source,
            instructions: self.instructions,
            output,
            inputs: self.inputs,
            operator_ids: self.operator_ids,
            has_cross_section: self.has_cross_section,
            budget,
            canonical,
            fingerprint,
        })
    }
}

fn canonical_op_name(op: Operator) -> &'static str {
    use Operator::*;
    match op {
        Add => "Add",
        Subtract => "Sub",
        Multiply => "Mul",
        Divide => "Div",
        Abs => "Abs",
        Sign => "Sign",
        Log => "Log",
        Delay => "Ref",
        Delta => "Delta",
        RollingMean => "Mean",
        RollingSum => "Sum",
        RollingStd => "Std",
        RollingVar => "Var",
        RollingMin => "Min",
        RollingMax => "Max",
        RollingCovariance => "Cov",
        RollingCorrelation => "Corr",
        TSRank => "TsRank",
        Scale => "Scale",
        DecayLinear => "WMA",
        Where => "Where",
        RollingSlope => "Slope",
        RollingRSquared => "Rsquare",
        RollingResidual => "Resi",
        RollingArgMax => "IdxMax",
        RollingArgMin => "IdxMin",
        RollingQuantile => "Quantile",
        EMA => "EMA",
        RMA => "RMA",
        CumSum => "CumSum",
        CrossSectionPercentile => "CSPercentile",
        CrossSectionRank => "CSRank",
        CrossSectionZScore => "CSZScore",
        CrossSectionDemean => "CSDemean",
        CrossSectionCorrelation => "CSCorr",
        CrossSectionScale => "CSScale",
        GroupDemean => "GroupDemean",
        RollingProduct => "Product",
        SMA => "SMA",
        Pow => "Pow",
        RegressionResidual3 => "RegressionResidual3",
        ConditionalBeta => "ConditionalBeta",
        CumProductIf => "CumProductIf",
    }
}

fn format_canonical(instructions: &[Instruction], root: usize) -> String {
    let mut ref_count = vec![0usize; instructions.len()];
    ref_count[root] += 1;
    for inst in instructions {
        match inst {
            Instruction::Input(_) | Instruction::Constant(_) => {}
            Instruction::Compare { lhs, rhs, .. } => {
                ref_count[*lhs] += 1;
                ref_count[*rhs] += 1;
            }
            Instruction::Lead { input, .. } => {
                ref_count[*input] += 1;
            }
            Instruction::Op { inputs, .. } => {
                for &id in inputs {
                    ref_count[id] += 1;
                }
            }
        }
    }
    let mut bindings = Vec::new();
    let mut rendered: Vec<String> = Vec::with_capacity(instructions.len());
    for (id, inst) in instructions.iter().enumerate() {
        let expr = match inst {
            Instruction::Input(name) => format!("${name}"),
            Instruction::Constant(value) => canonical_decimal(value),
            Instruction::Compare { op, lhs, rhs } => {
                format!("({} {} {})", rendered[*lhs], op.symbol(), rendered[*rhs])
            }
            Instruction::Lead { input, offset } => {
                format!("Ref({}, -{})", rendered[*input], offset.get())
            }
            Instruction::Op {
                kernel,
                parameters,
                inputs,
            } => {
                let op = kernel.operator();
                let name = canonical_op_name(op);
                let mut parts: Vec<String> = inputs.iter().map(|&i| rendered[i].clone()).collect();
                if let Some(period) = parameters.period {
                    parts.push(period.get().to_string());
                }
                if let Some(weight) = parameters.weight {
                    parts.push(weight.get().to_string());
                }
                if let Some(factor) = &parameters.factor {
                    parts.push(canonical_decimal(factor));
                }
                if let Some(q) = &parameters.quantile {
                    parts.push(canonical_decimal(q));
                }
                if op == Operator::CrossSectionPercentile {
                    parts.push(if parameters.lower_is_better {
                        "-1".into()
                    } else {
                        "1".into()
                    });
                }
                format!("{name}({})", parts.join(", "))
            }
        };
        let is_atom = matches!(inst, Instruction::Input(_) | Instruction::Constant(_));
        if !is_atom && id != root && ref_count[id] > 1 {
            let alias = format!("v{id}");
            bindings.push(format!("let {alias} = {expr};"));
            rendered.push(alias);
        } else {
            rendered.push(expr);
        }
    }
    if bindings.is_empty() {
        rendered[root].clone()
    } else {
        format!("{} {}", bindings.join(" "), rendered[root])
    }
}

fn dag_fingerprint(kind: ExprKind, instructions: &[Instruction], output: usize) -> String {
    let nodes: Vec<Value> = instructions
        .iter()
        .map(|inst| match inst {
            Instruction::Input(name) => json!({"kind": "INPUT", "field": name}),
            Instruction::Constant(val) => {
                json!({"kind": "CONSTANT", "value": canonical_decimal(val)})
            }
            Instruction::Compare { op, lhs, rhs } => {
                json!({"kind": "COMPARE", "op": op.code(), "args": [lhs, rhs]})
            }
            Instruction::Lead { input, offset } => {
                json!({"kind": "LEAD", "input": input, "offset": offset.get()})
            }
            Instruction::Op {
                kernel,
                parameters,
                inputs,
            } => json!({
                "kind": "OP",
                "type_id": kernel.operator().type_id(),
                "parameters": params_json(kernel.operator(), parameters),
                "args": inputs,
            }),
        })
        .collect();
    let doc = json!({
        "schema_version": 1,
        "kind": kind.as_str(),
        "numeric_policy": NUMERIC_POLICY,
        "operator_semantic_version": SEMANTIC_VERSION,
        "nodes": nodes,
        "output": output,
    });
    hash(&doc)
}

pub(crate) fn compile(
    source: &str,
    kind: ExprKind,
    allowed: Option<&BTreeSet<String>>,
) -> Result<CompiledDag> {
    let ast = parse(source)?;
    let mut compiler = Compiler::new(kind, allowed);
    let root = compiler.compile_expr(&ast)?;
    compiler.finish(source.to_owned(), root)
}
