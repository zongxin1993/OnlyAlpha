//! Bounded, read-only local diagnostic process. It exposes no trading capabilities.
use onlyalpha_predicates::boolean_equality::{
    BooleanEqualityPredicate, BooleanLiteralEqualityPredicate,
};
use onlyalpha_predicates::integer_predicate::{
    IntegerLiteralPredicate, IntegerOperand, IntegerPredicate,
};
use onlyalpha_predicates::predicate::Predicate;
use onlyalpha_predicates::string_equality::{
    StringEqualityPredicate, StringLiteralEqualityPredicate,
};
use std::io::{self, Read, Write};

const LIMIT: usize = 65_536;
const HEADER: &str = "ONLYALPHA_PREDICATE_DIAGNOSTIC_V4";

fn integer(token: &str) -> Result<Option<IntegerOperand<'_>>, ()> {
    if token == "null" {
        return Ok(None);
    }
    if token.strip_prefix('-').unwrap_or(token).len() > 256 {
        return Err(());
    }
    IntegerOperand::parse(token).map(Some).map_err(|_| ())
}

fn boolean(token: &str) -> Result<Option<bool>, ()> {
    match token {
        "true" => Ok(Some(true)),
        "false" => Ok(Some(false)),
        "null" => Ok(None),
        _ => Err(()),
    }
}

fn string(token: &str) -> Result<Option<String>, ()> {
    if token == "null" {
        return Ok(None);
    }
    let raw = token.strip_prefix("utf8:").ok_or(())?;
    let (pairs, remainder) = raw.as_bytes().as_chunks::<2>();
    if raw.len() > 8192
        || !remainder.is_empty()
        || !raw
            .bytes()
            .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
    {
        return Err(());
    }
    let bytes: Result<Vec<_>, ()> = pairs
        .iter()
        .map(|pair| {
            u8::from_str_radix(std::str::from_utf8(pair).map_err(|_| ())?, 16).map_err(|_| ())
        })
        .collect();
    String::from_utf8(bytes?).map(Some).map_err(|_| ())
}

fn evaluate(frame: &[u8]) -> Result<String, ()> {
    if frame.len() > LIMIT || !frame.ends_with(b"\n") || frame.contains(&b'\r') {
        return Err(());
    }
    let text = std::str::from_utf8(frame).map_err(|_| ())?;
    let mut lines = text.lines();
    let header = lines.next().ok_or(())?;
    let (protocol, context) = header.split_once('\t').ok_or(())?;
    if protocol != HEADER
        || context.len() != 64
        || !context
            .bytes()
            .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
    {
        return Err(());
    }
    let mut output = format!("{header}\n");
    let mut count = 0;
    for (index, row) in lines.enumerate() {
        count += 1;
        let fields: Vec<_> = row.split('\t').collect();
        if count > 128
            || !(3..=7).contains(&fields.len())
            || fields[0] != index.to_string()
            || fields[1].is_empty()
            || fields[1].len() > 192
            || !fields[1]
                .bytes()
                .all(|b| b.is_ascii_lowercase() || b.is_ascii_digit() || b"._".contains(&b))
            || fields[2].is_empty()
            || fields[2].len() > 32
            || !fields[2]
                .bytes()
                .all(|b| b.is_ascii_alphanumeric() || b"._+-".contains(&b))
        {
            return Err(());
        }
        let result = if fields[1].ends_with(".string.literal") {
            if !(5..=7).contains(&fields.len()) {
                return Err(());
            }
            let literal = string(fields[3])?.ok_or(())?;
            let position = boolean(fields[4])?.ok_or(())?;
            let operands: Result<Vec<_>, ()> = fields[5..].iter().map(|v| string(v)).collect();
            let owned = operands?;
            let operands: Vec<_> = owned.iter().map(|v| v.as_deref()).collect();
            StringLiteralEqualityPredicate::resolve(fields[1], fields[2], &literal, position)
                .and_then(|op| op.evaluate(&operands))
        } else if fields[1].ends_with(".string.refs") {
            if fields.len() > 5 {
                return Err(());
            }
            let operands: Result<Vec<_>, ()> = fields[3..].iter().map(|v| string(v)).collect();
            let owned = operands?;
            let operands: Vec<_> = owned.iter().map(|v| v.as_deref()).collect();
            StringEqualityPredicate::resolve(fields[1], fields[2])
                .and_then(|op| op.evaluate(&operands))
        } else if fields[1].ends_with(".boolean.literal") {
            if !(5..=7).contains(&fields.len()) {
                return Err(());
            }
            let literal = boolean(fields[3])?.ok_or(())?;
            let position = boolean(fields[4])?.ok_or(())?;
            let operands: Result<Vec<_>, ()> = fields[5..].iter().map(|v| boolean(v)).collect();
            let operands = operands?;
            BooleanLiteralEqualityPredicate::resolve(fields[1], fields[2], literal, position)
                .and_then(|op| op.evaluate(&operands))
        } else if fields[1].ends_with(".boolean.refs") {
            if fields.len() > 5 {
                return Err(());
            }
            let operands: Result<Vec<_>, ()> = fields[3..].iter().map(|v| boolean(v)).collect();
            let operands = operands?;
            BooleanEqualityPredicate::resolve(fields[1], fields[2])
                .and_then(|op| op.evaluate(&operands))
        } else if fields[1].ends_with(".integer.literal") {
            if !(5..=7).contains(&fields.len()) {
                return Err(());
            }
            let literal = integer(fields[3])?.ok_or(())?;
            let literal_left = match fields[4] {
                "true" => true,
                "false" => false,
                _ => return Err(()),
            };
            let operands: Result<Vec<_>, ()> =
                fields[5..].iter().map(|token| integer(token)).collect();
            let operands = operands?;
            IntegerLiteralPredicate::resolve(fields[1], fields[2], literal, literal_left)
                .and_then(|op| op.evaluate(&operands))
        } else if fields[1].ends_with(".integer.refs") {
            if fields.len() > 5 {
                return Err(());
            }
            let operands: Result<Vec<_>, ()> =
                fields[3..].iter().map(|token| integer(token)).collect();
            let operands = operands?;
            IntegerPredicate::resolve(fields[1], fields[2]).and_then(|op| op.evaluate(&operands))
        } else {
            if fields.len() > 5 {
                return Err(());
            }
            let operands: Result<Vec<Option<bool>>, ()> =
                fields[3..].iter().map(|token| boolean(token)).collect();
            let operands = operands?;
            Predicate::resolve(fields[1], fields[2]).and_then(|op| op.evaluate(&operands))
        };
        match result {
            Ok(value) => output.push_str(&format!(
                "{row}\tOK\t{}\n",
                match value {
                    Some(true) => "true",
                    Some(false) => "false",
                    None => "null",
                }
            )),
            Err(error) => output.push_str(&format!("{row}\tERROR\t{error:?}\n")),
        }
    }
    if count == 0 || output.len() > LIMIT {
        return Err(());
    }
    Ok(output)
}

fn main() {
    let mut frame = Vec::new();
    let result = io::stdin()
        .take((LIMIT + 1) as u64)
        .read_to_end(&mut frame)
        .map_err(|_| ())
        .and_then(|_| evaluate(&frame));
    match result {
        Ok(output) => {
            if io::stdout().write_all(output.as_bytes()).is_err() {
                std::process::exit(2);
            }
        }
        Err(()) => std::process::exit(2),
    }
}
