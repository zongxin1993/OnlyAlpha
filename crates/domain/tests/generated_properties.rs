//! Original financial/temporal/identifier properties, exercised through public Rust APIs.
use onlyalpha_domain::{
    base::OnlyDomainModel,
    enums::OnlyCurrencyType,
    identifiers::{OnlyInstrumentId, OnlySymbol, OnlyVenueId},
    time::OnlyTimestamp,
    value::{OnlyCurrency, OnlyMoney, OnlyQuantity},
};
use sha2::{Digest, Sha256};
use std::{collections::BTreeSet, str::FromStr};

const SEED: &str = "onlyalpha-domain-properties-v1";
const CASES: usize = 2000;

struct Inputs {
    property: &'static str,
    case: usize,
    draw: u64,
}
impl Inputs {
    fn new(property: &'static str, case: usize) -> Self {
        Self {
            property,
            case,
            draw: 0,
        }
    }
    fn below(&mut self, bound: u64) -> u64 {
        // Rejection sampling gives every member of the original integer range support.
        let limit = u64::MAX - u64::MAX % bound;
        loop {
            let mut hash = Sha256::new();
            hash.update(SEED.as_bytes());
            hash.update(self.property.as_bytes());
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
    fn decimal(&mut self, non_negative: bool) -> String {
        let minimum = if non_negative { 0_i64 } else { -1_000_000 };
        let coefficient = minimum + self.below((1_000_001 - minimum) as u64) as i64;
        let places = self.below(7);
        format!("{coefficient}e-{places}")
    }
    fn identifier(&mut self, maximum: u64) -> String {
        const ALPHABET: &[u8] = b"ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789";
        let length = 1 + self.below(maximum);
        (0..length)
            .map(|_| ALPHABET[self.below(36) as usize] as char)
            .collect()
    }
}

#[test]
fn generated_money_json_round_trips_preserve_exact_decimal_and_currency() {
    let mut exercised = BTreeSet::new();
    for case in 0..CASES {
        let mut input = Inputs::new("money", case);
        let mut amount = if case < 35 {
            // Boundary coefficients across every scale supplement the generated interior.
            format!(
                "{}e-{}",
                [-1_000_000, -1, 0, 1, 1_000_000][case / 7],
                case % 7
            )
        } else {
            input.decimal(false)
        };
        while exercised.contains(&amount) {
            amount = input.decimal(false);
        }
        let context = format!("seed={SEED} property=money case={case} amount={amount}");
        assert!(
            exercised.insert(amount.clone()),
            "{context}: duplicate generated input"
        );
        let currency = OnlyCurrency::new("CNY", 6, OnlyCurrencyType::Fiat).expect(&context);
        let value = OnlyMoney::new(amount.parse().expect(&context), currency).expect(&context);
        let wire = value.to_json().expect(&context);
        let restored = OnlyMoney::from_json(&wire).expect(&context);
        assert_eq!(restored, value, "{context}");
        // The accessor is statically an exact financial Decimal, never binary64.
        let _: &onlyalpha_domain::numeric::OnlyDecimal = restored.amount();
    }
}

#[test]
fn generated_quantity_add_then_subtract_restores_the_original() {
    let mut exercised = BTreeSet::new();
    for case in 0..CASES {
        let mut input = Inputs::new("quantity", case);
        let left = if case < 7 {
            format!("0e-{case}")
        } else {
            input.decimal(true)
        };
        let right = if case < 7 {
            format!("1000000e-{case}")
        } else {
            input.decimal(true)
        };
        let context =
            format!("seed={SEED} property=quantity case={case} left={left} right={right}");
        assert!(
            exercised.insert((left.clone(), right.clone())),
            "{context}: duplicate generated input"
        );
        let original = OnlyQuantity::new(left.parse().expect(&context), 6).expect(&context);
        let increment = OnlyQuantity::new(right.parse().expect(&context), 6).expect(&context);
        let sum = original.checked_add(&increment).expect(&context);
        let restored = sum.checked_subtract(&increment).expect(&context);
        assert_eq!(restored, original, "{context}");
    }
}

#[test]
fn generated_timestamp_datetime_round_trips_keep_microseconds_and_utc() {
    let mut exercised = BTreeSet::new();
    for case in 0..CASES {
        let mut input = Inputs::new("timestamp", case);
        let micros = if case < 5 {
            [-2_000_000_000_000_000_i64, -1, 0, 1, 2_000_000_000_000_000][case]
        } else {
            input.below(4_000_000_000_000_001) as i64 - 2_000_000_000_000_000
        };
        let context = format!("seed={SEED} property=timestamp case={case} micros={micros}");
        assert!(
            exercised.insert(micros),
            "{context}: duplicate generated input"
        );
        let timestamp = OnlyTimestamp::from_unix_micros(micros.into());
        let datetime = timestamp.to_datetime().expect(&context);
        assert!(
            datetime.to_string().ends_with('Z'),
            "{context}: UTC wire suffix missing"
        );
        let restored = OnlyTimestamp::from_datetime(datetime);
        assert_eq!(restored, timestamp, "{context}");
        assert_eq!(
            restored.to_datetime().expect(&context),
            datetime,
            "{context}"
        );
    }
}

#[test]
fn generated_instrument_identifier_text_round_trips_preserve_both_components() {
    let mut exercised = BTreeSet::new();
    for case in 0..CASES {
        let mut input = Inputs::new("instrument", case);
        let symbol = if case == 0 {
            "0".into()
        } else {
            input.identifier(16)
        };
        let venue = if case == 0 {
            "0".into()
        } else {
            input.identifier(12)
        };
        let context =
            format!("seed={SEED} property=instrument case={case} symbol={symbol} venue={venue}");
        assert!(
            exercised.insert((symbol.clone(), venue.clone())),
            "{context}: duplicate generated input"
        );
        let identifier = OnlyInstrumentId::new(
            OnlySymbol::new(&symbol).expect(&context),
            OnlyVenueId::new(&venue).expect(&context),
        );
        let restored = OnlyInstrumentId::from_str(&identifier.to_string()).expect(&context);
        assert_eq!(restored, identifier, "{context}");
    }
}
