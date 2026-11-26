//! Bounded deterministic lexer and recursive-descent parser for Qlib expressions.

use crate::{Result, record::err};
use onlyalpha_operators::algebra::{Decimal, MAX_INPUT_DIGITS, MAX_INPUT_SCALE};
use std::str::FromStr;

pub const MAX_EXPR_BYTES: usize = 16 * 1024;
pub const MAX_EXPR_DEPTH: usize = 64;
pub const MAX_IDENT_LEN: usize = 64;
pub const MAX_CALL_ARGS: usize = 8;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(crate) enum BinaryOp {
    Add,
    Sub,
    Mul,
    Div,
    Lt,
    Le,
    Gt,
    Ge,
    Eq,
    Ne,
    And,
    Or,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(crate) enum UnaryOp {
    Neg,
    Pos,
    Not,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub(crate) enum Expr {
    Field(String),
    Number {
        raw: String,
        value: Decimal,
    },
    Unary {
        op: UnaryOp,
        expr: Box<Expr>,
    },
    Binary {
        op: BinaryOp,
        lhs: Box<Expr>,
        rhs: Box<Expr>,
    },
    Call {
        name: String,
        args: Vec<Expr>,
    },
}

#[derive(Clone, Debug, PartialEq, Eq)]
enum Token {
    Field(String),
    Ident(String),
    Number(String),
    Plus,
    Minus,
    Star,
    Slash,
    Bang,
    Lt,
    Le,
    Gt,
    Ge,
    EqEq,
    BangEq,
    AndAnd,
    OrOr,
    LParen,
    RParen,
    Comma,
    Eof,
}

fn tokenize(source: &str) -> Result<Vec<Token>> {
    if source.is_empty() {
        return Err(err("QLIB_EMPTY_EXPRESSION"));
    }
    if source.len() > MAX_EXPR_BYTES {
        return Err(err("QLIB_BYTE_BUDGET"));
    }
    let bytes = source.as_bytes();
    let mut i = 0;
    let mut tokens = Vec::new();
    while i < bytes.len() {
        let b = bytes[i];
        if b.is_ascii_whitespace() {
            i += 1;
            continue;
        }
        match b {
            b'+' => {
                tokens.push(Token::Plus);
                i += 1;
            }
            b'-' => {
                tokens.push(Token::Minus);
                i += 1;
            }
            b'*' => {
                tokens.push(Token::Star);
                i += 1;
            }
            b'/' => {
                tokens.push(Token::Slash);
                i += 1;
            }
            b'(' => {
                tokens.push(Token::LParen);
                i += 1;
            }
            b')' => {
                tokens.push(Token::RParen);
                i += 1;
            }
            b',' => {
                tokens.push(Token::Comma);
                i += 1;
            }
            b'<' => {
                if bytes.get(i + 1) == Some(&b'=') {
                    tokens.push(Token::Le);
                    i += 2;
                } else {
                    tokens.push(Token::Lt);
                    i += 1;
                }
            }
            b'>' => {
                if bytes.get(i + 1) == Some(&b'=') {
                    tokens.push(Token::Ge);
                    i += 2;
                } else {
                    tokens.push(Token::Gt);
                    i += 1;
                }
            }
            b'=' => {
                if bytes.get(i + 1) == Some(&b'=') {
                    tokens.push(Token::EqEq);
                    i += 2;
                } else {
                    return Err(err("QLIB_SYNTAX_TOKEN"));
                }
            }
            b'!' => {
                if bytes.get(i + 1) == Some(&b'=') {
                    tokens.push(Token::BangEq);
                    i += 2;
                } else {
                    tokens.push(Token::Bang);
                    i += 1;
                }
            }
            b'&' => {
                if bytes.get(i + 1) == Some(&b'&') {
                    tokens.push(Token::AndAnd);
                    i += 2;
                } else {
                    return Err(err("QLIB_SYNTAX_TOKEN"));
                }
            }
            b'|' => {
                if bytes.get(i + 1) == Some(&b'|') {
                    tokens.push(Token::OrOr);
                    i += 2;
                } else {
                    return Err(err("QLIB_SYNTAX_TOKEN"));
                }
            }
            b'$' => {
                i += 1;
                let start = i;
                if i >= bytes.len() || !(bytes[i].is_ascii_alphabetic() || bytes[i] == b'_') {
                    return Err(err("QLIB_INVALID_FIELD"));
                }
                while i < bytes.len() && (bytes[i].is_ascii_alphanumeric() || bytes[i] == b'_') {
                    i += 1;
                }
                let name = &source[start..i];
                if name.len() > MAX_IDENT_LEN {
                    return Err(err("QLIB_INVALID_FIELD"));
                }
                tokens.push(Token::Field(name.to_owned()));
            }
            b'0'..=b'9' => {
                let start = i;
                while i < bytes.len() && bytes[i].is_ascii_digit() {
                    i += 1;
                }
                if i < bytes.len() && bytes[i] == b'.' {
                    i += 1;
                    let frac_start = i;
                    while i < bytes.len() && bytes[i].is_ascii_digit() {
                        i += 1;
                    }
                    if i == frac_start {
                        return Err(err("QLIB_INVALID_NUMBER"));
                    }
                }
                if i < bytes.len() && matches!(bytes[i], b'e' | b'E') {
                    i += 1;
                    if i < bytes.len() && matches!(bytes[i], b'+' | b'-') {
                        i += 1;
                    }
                    let exp_start = i;
                    while i < bytes.len() && bytes[i].is_ascii_digit() {
                        i += 1;
                    }
                    if i == exp_start {
                        return Err(err("QLIB_INVALID_NUMBER"));
                    }
                }
                if i < bytes.len()
                    && (bytes[i].is_ascii_alphabetic() || bytes[i] == b'_' || bytes[i] == b'.')
                {
                    return Err(err("QLIB_INVALID_NUMBER"));
                }
                tokens.push(Token::Number(source[start..i].to_owned()));
            }
            b if b.is_ascii_alphabetic() || b == b'_' => {
                let start = i;
                while i < bytes.len() && (bytes[i].is_ascii_alphanumeric() || bytes[i] == b'_') {
                    i += 1;
                }
                let ident = &source[start..i];
                if ident.len() > MAX_IDENT_LEN {
                    return Err(err("QLIB_INVALID_IDENTIFIER"));
                }
                tokens.push(Token::Ident(ident.to_owned()));
            }
            _ => return Err(err("QLIB_SYNTAX_TOKEN")),
        }
    }
    if tokens.is_empty() {
        return Err(err("QLIB_EMPTY_EXPRESSION"));
    }
    tokens.push(Token::Eof);
    Ok(tokens)
}

fn parse_decimal(raw: &str) -> Result<Decimal> {
    if raw.len() > 512 {
        return Err(err("QLIB_NUMERIC_BUDGET"));
    }
    let value = Decimal::from_str(raw).map_err(|_| err("QLIB_INVALID_NUMBER"))?;
    let (_, scale) = value.as_bigint_and_exponent();
    if value.digits() > MAX_INPUT_DIGITS || scale.unsigned_abs() > MAX_INPUT_SCALE as u64 {
        return Err(err("QLIB_NUMERIC_BUDGET"));
    }
    Ok(value)
}

struct Parser {
    tokens: Vec<Token>,
    pos: usize,
    depth: usize,
}

impl Parser {
    fn new(tokens: Vec<Token>) -> Self {
        Self {
            tokens,
            pos: 0,
            depth: 0,
        }
    }

    fn peek(&self) -> &Token {
        self.tokens.get(self.pos).unwrap_or(&Token::Eof)
    }

    fn bump(&mut self) -> Token {
        let tok = self.peek().clone();
        if self.pos < self.tokens.len() {
            self.pos += 1;
        }
        tok
    }

    fn enter(&mut self) -> Result<()> {
        self.depth += 1;
        if self.depth > MAX_EXPR_DEPTH {
            return Err(err("QLIB_DEPTH_BUDGET"));
        }
        Ok(())
    }

    fn exit(&mut self) {
        self.depth = self.depth.saturating_sub(1);
    }

    fn parse_expr(&mut self) -> Result<Expr> {
        self.parse_or()
    }

    fn parse_binary_chain<F, M>(&mut self, mut parse_operand: F, mut match_op: M) -> Result<Expr>
    where
        F: FnMut(&mut Self) -> Result<Expr>,
        M: FnMut(&Token) -> Option<BinaryOp>,
    {
        let mut lhs = parse_operand(self)?;
        let mut pushed = 0usize;
        while let Some(op) = match_op(self.peek()) {
            self.bump();
            if let Err(err) = self.enter() {
                self.depth = self.depth.saturating_sub(pushed);
                return Err(err);
            }
            pushed += 1;
            let rhs = match parse_operand(self) {
                Ok(rhs) => rhs,
                Err(err) => {
                    self.depth = self.depth.saturating_sub(pushed);
                    return Err(err);
                }
            };
            lhs = Expr::Binary {
                op,
                lhs: Box::new(lhs),
                rhs: Box::new(rhs),
            };
        }
        self.depth = self.depth.saturating_sub(pushed);
        Ok(lhs)
    }

    fn parse_or(&mut self) -> Result<Expr> {
        self.parse_binary_chain(Self::parse_and, |tok| match tok {
            Token::OrOr => Some(BinaryOp::Or),
            _ => None,
        })
    }

    fn parse_and(&mut self) -> Result<Expr> {
        self.parse_binary_chain(Self::parse_comparison, |tok| match tok {
            Token::AndAnd => Some(BinaryOp::And),
            _ => None,
        })
    }

    fn parse_comparison(&mut self) -> Result<Expr> {
        self.parse_binary_chain(Self::parse_additive, |tok| match tok {
            Token::Lt => Some(BinaryOp::Lt),
            Token::Le => Some(BinaryOp::Le),
            Token::Gt => Some(BinaryOp::Gt),
            Token::Ge => Some(BinaryOp::Ge),
            Token::EqEq => Some(BinaryOp::Eq),
            Token::BangEq => Some(BinaryOp::Ne),
            _ => None,
        })
    }

    fn parse_additive(&mut self) -> Result<Expr> {
        self.parse_binary_chain(Self::parse_multiplicative, |tok| match tok {
            Token::Plus => Some(BinaryOp::Add),
            Token::Minus => Some(BinaryOp::Sub),
            _ => None,
        })
    }

    fn parse_multiplicative(&mut self) -> Result<Expr> {
        self.parse_binary_chain(Self::parse_unary, |tok| match tok {
            Token::Star => Some(BinaryOp::Mul),
            Token::Slash => Some(BinaryOp::Div),
            _ => None,
        })
    }

    fn parse_unary(&mut self) -> Result<Expr> {
        let op = match self.peek() {
            Token::Minus => Some(UnaryOp::Neg),
            Token::Plus => Some(UnaryOp::Pos),
            Token::Bang => Some(UnaryOp::Not),
            _ => None,
        };
        if let Some(op) = op {
            self.bump();
            self.enter()?;
            let expr = self.parse_unary();
            self.exit();
            return Ok(Expr::Unary {
                op,
                expr: Box::new(expr?),
            });
        }
        self.parse_primary()
    }

    fn parse_primary(&mut self) -> Result<Expr> {
        match self.bump() {
            Token::Field(name) => Ok(Expr::Field(name)),
            Token::Number(raw) => {
                let value = parse_decimal(&raw)?;
                Ok(Expr::Number { raw, value })
            }
            Token::LParen => {
                self.enter()?;
                let expr = self.parse_expr();
                self.exit();
                let expr = expr?;
                if *self.peek() != Token::RParen {
                    return Err(err("QLIB_UNCLOSED_PAREN"));
                }
                self.bump();
                Ok(expr)
            }
            Token::Ident(name) => {
                if *self.peek() != Token::LParen {
                    return Err(err("QLIB_BARE_IDENTIFIER"));
                }
                self.bump();
                self.enter()?;
                let mut args = Vec::new();
                if *self.peek() != Token::RParen {
                    loop {
                        if args.len() >= MAX_CALL_ARGS {
                            self.exit();
                            return Err(err("QLIB_ARITY"));
                        }
                        let arg = self.parse_expr();
                        match arg {
                            Ok(expr) => args.push(expr),
                            Err(e) => {
                                self.exit();
                                return Err(e);
                            }
                        }
                        match self.peek() {
                            Token::Comma => {
                                self.bump();
                            }
                            Token::RParen => break,
                            _ => {
                                self.exit();
                                return Err(err("QLIB_SYNTAX_CALL"));
                            }
                        }
                    }
                }
                self.bump();
                self.exit();
                Ok(Expr::Call { name, args })
            }
            _ => Err(err("QLIB_SYNTAX_UNEXPECTED")),
        }
    }
}

pub(crate) fn parse(source: &str) -> Result<Expr> {
    let tokens = tokenize(source)?;
    let mut parser = Parser::new(tokens);
    let expr = parser.parse_expr()?;
    if *parser.peek() != Token::Eof {
        return Err(err("QLIB_TRAILING_TOKENS"));
    }
    Ok(expr)
}
