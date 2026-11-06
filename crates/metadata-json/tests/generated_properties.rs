//! Generated structured metadata properties; the parser sees both original insertion orders.
use onlyalpha_metadata_json::{canonical_json, fingerprint};
use sha2::{Digest, Sha256};
use std::collections::BTreeSet;

const SEED: &str = "onlyalpha-metadata-properties-v1";
const CASES: usize = 2000;
const WORK: usize = 8 * 1024 * 1024;

struct Inputs {
    case: usize,
    draw: u64,
}
impl Inputs {
    fn below(&mut self, bound: u64) -> u64 {
        let limit = u64::MAX - u64::MAX % bound;
        loop {
            let mut hash = Sha256::new();
            hash.update(SEED.as_bytes());
            hash.update((self.case as u64).to_le_bytes());
            hash.update(self.draw.to_le_bytes());
            self.draw += 1;
            let bytes = hash.finalize();
            let value = u64::from_le_bytes(bytes[..8].try_into().unwrap());
            if value < limit {
                return value % bound;
            }
        }
    }
    fn scalar(&mut self) -> char {
        // Supplement uniform Unicode-scalar sampling with escaping/sorting boundaries.
        const EDGES: &[char] = &[
            '\0',
            '\n',
            '"',
            '\\',
            '\u{7f}',
            '\u{80}',
            '\u{d7ff}',
            '\u{e000}',
            '\u{10000}',
            '\u{10ffff}',
        ];
        if self.below(4) == 0 {
            return EDGES[self.below(EDGES.len() as u64) as usize];
        }
        loop {
            if let Some(value) = char::from_u32(self.below(0x110000) as u32) {
                return value;
            }
        }
    }
    fn text(&mut self, minimum: u64, maximum: u64) -> String {
        let length = minimum + self.below(maximum - minimum + 1);
        (0..length).map(|_| self.scalar()).collect()
    }
    fn integer(&mut self) -> String {
        if self.below(10) == 0 {
            return "0".into();
        }
        // Geometric length has no fixed magnitude ceiling. Periodic large bases
        // ensure this finite run also executes arbitrary-precision, non-i64 paths.
        let mut length = if self.case.is_multiple_of(11) {
            1000
        } else {
            1
        };
        while self.below(2) == 0 {
            length += 1;
        }
        let mut value = if self.below(2) == 0 {
            String::new()
        } else {
            "-".into()
        };
        value.push(char::from(b'1' + self.below(9) as u8));
        for _ in 1..length {
            value.push(char::from(b'0' + self.below(10) as u8));
        }
        value
    }
    fn value(&mut self) -> String {
        match self.below(4) {
            0 => "null".into(),
            1 => (self.below(2) == 0).to_string(),
            2 => self.integer(),
            _ => serde_json::to_string(&self.text(0, 20)).unwrap(),
        }
    }
}

fn document<'a>(entries: impl Iterator<Item = &'a (String, String)>) -> String {
    let fields: Vec<_> = entries
        .map(|(key, value)| format!("{key}:{value}"))
        .collect();
    format!("{{{}}}", fields.join(","))
}

#[test]
fn generated_metadata_is_idempotent_order_independent_and_fingerprint_stable() {
    let mut exercised = BTreeSet::new();
    for case in 0..CASES {
        let mut input = Inputs { case, draw: 0 };
        let count = if case == 0 { 0 } else { 1 + input.below(12) };
        let mut unique = BTreeSet::new();
        let mut entries = Vec::new();
        while entries.len() < count as usize {
            let key = input.text(1, 12);
            if unique.insert(key.clone()) {
                entries.push((serde_json::to_string(&key).unwrap(), input.value()));
            }
        }
        // Keep insertion order in a Vec; do not pre-normalize through serde_json::Map.
        let raw = document(entries.iter());
        let reversed = document(entries.iter().rev());
        let context = format!("seed={SEED} property=canonical case={case} raw={raw}");
        assert!(
            exercised.insert(raw.clone()),
            "{context}: duplicate generated raw JSON"
        );
        let canonical = canonical_json(&raw, WORK).expect(&context);
        assert_eq!(
            canonical_json(&canonical, WORK).expect(&context),
            canonical,
            "{context}"
        );
        assert_eq!(
            canonical_json(&reversed, WORK).expect(&context),
            canonical,
            "{context}"
        );
        let original_fingerprint = fingerprint(&raw, WORK).expect(&context);
        assert_eq!(
            fingerprint(&canonical, WORK).expect(&context),
            original_fingerprint,
            "{context}"
        );
        assert_eq!(
            fingerprint(&reversed, WORK).expect(&context),
            original_fingerprint,
            "{context}"
        );
    }
}
