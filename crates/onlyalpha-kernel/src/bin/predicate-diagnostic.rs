//! Bounded, read-only local diagnostic process. It exposes no trading capabilities.
use onlyalpha_kernel::predicate::Predicate;
use std::io::{self, Read, Write};

const LIMIT: usize = 65_536;
const HEADER: &str = "ONLYALPHA_PREDICATE_DIAGNOSTIC_V1";

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
            || !(3..=5).contains(&fields.len())
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
        let operands: Result<Vec<Option<bool>>, ()> = fields[3..]
            .iter()
            .map(|token| match *token {
                "true" => Ok(Some(true)),
                "false" => Ok(Some(false)),
                "null" => Ok(None),
                _ => Err(()),
            })
            .collect();
        let operands = operands?;
        match Predicate::resolve(fields[1], fields[2]).and_then(|op| op.evaluate(&operands)) {
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
