//! Independent configuration/history vectors, not Product UI acceptance.
use onlyalpha_product_runtime::{
    source_access::Reference,
    watchlists::{Book, Error, List, Member},
};
use serde_json::{Value, json};
const LIST: &str = "0926c6a2-0cb8-47a5-8d94-cdb89b336182";
const NAMESPACE: &str = "b52eb762-34cf-47d4-8cca-56ef93f0d2ac";
fn source() -> Reference {
    Reference::new("source", &"a".repeat(64), Some("test.market_data")).unwrap()
}
fn member() -> Member {
    Member::new(source(), "BTCUSDT.BINANCE").unwrap()
}
fn list() -> List {
    List::new(LIST, "日常", vec![member()]).unwrap()
}
#[test]
fn exact_member_context_and_order_are_configuration_identity() {
    let a = member();
    let other = Member::new(
        Reference::new("other", &"a".repeat(64), Some("test.market_data")).unwrap(),
        "BTCUSDT.BINANCE",
    )
    .unwrap();
    let mixed = List::new(LIST, "日常", vec![a.clone(), other.clone()]).unwrap();
    assert!(List::new(LIST, "日常", vec![a.clone(), a]).is_err());
    let book = Book::new(1, vec![mixed]).unwrap();
    assert_eq!(Book::from_record(&book.to_record(), 2).unwrap(), book);
    let reverse = Book::new(
        1,
        vec![List::new(LIST, "日常", vec![other, member()]).unwrap()],
    )
    .unwrap();
    assert_ne!(
        book.fingerprint(NAMESPACE).unwrap(),
        reverse.fingerprint(NAMESPACE).unwrap()
    );
    assert!(
        Member::new(
            Reference::new("source", &"a".repeat(64), None).unwrap(),
            "BTCUSDT.BINANCE"
        )
        .is_err()
    );
    for value in [
        "BTCUSDT",
        "BTCUSDT. BINANCE",
        " BTCUSDT.BINANCE",
        "BTCUSDT.BINANCE ",
        ".BINANCE",
    ] {
        assert!(Member::new(source(), value).is_err(), "{value}");
    }
}
#[test]
fn configuration_bounds_and_unicode_names_preserve_python_semantics() {
    for name in [
        "",
        " ",
        " leading",
        "trailing\u{1c}",
        "line\nfeed",
        "control\u{1f}",
    ] {
        assert!(List::new(LIST, name, vec![]).is_err(), "{name:?}");
    }
    assert!(List::new(LIST, &"中".repeat(64), vec![]).is_ok());
    assert!(List::new(LIST, &"中".repeat(65), vec![]).is_err());
    assert!(List::new(LIST, "DEL\u{7f}", vec![]).is_ok());
    assert!(List::new(&LIST.to_uppercase(), "日常", vec![]).is_err());
    assert!(Book::new(0, vec![list(), list()]).is_err());
    assert!(Book::new(0, vec![list(), List::new(LIST, "another", vec![]).unwrap()]).is_err());
    assert!(
        Book::new(
            0,
            vec![
                list(),
                List::new("1926c6a2-0cb8-47a5-8d94-cdb89b336182", "日常", vec![]).unwrap()
            ]
        )
        .is_err()
    );
    assert!(Book::new(i64::MAX as u64 + 1, vec![]).is_err());
    let members = (0..101)
        .map(|i| Member::new(source(), &format!("S{i}.VENUE")).unwrap())
        .collect();
    assert!(List::new(LIST, "large", members).is_err());
    let lists = (0..21)
        .map(|i| {
            List::new(
                &format!("{i:08x}-0cb8-47a5-8d94-cdb89b336182"),
                &format!("list{i}"),
                vec![],
            )
            .unwrap()
        })
        .collect();
    assert!(Book::new(0, lists).is_err());
    let lists = (0..3)
        .map(|i| {
            List::new(
                &format!("{i:08x}-0cb8-47a5-8d94-cdb89b336182"),
                &format!("list{i}"),
                (0..100)
                    .map(|j| Member::new(source(), &format!("S{j}.VENUE")).unwrap())
                    .collect(),
            )
            .unwrap()
        })
        .collect();
    assert!(Book::new(0, lists).is_err());
}
#[test]
fn malformed_history_never_becomes_an_empty_book() {
    let good = Book::new(1, vec![list()]).unwrap().to_record();
    let mut changed = good.clone();
    changed["version"] = json!(true);
    assert_eq!(Book::from_record(&changed, 2), Err(Error::Invalid));
    changed = good.clone();
    changed["extra"] = Value::Null;
    assert!(Book::from_record(&changed, 2).is_err());
    changed = good.clone();
    changed["lists"][0]["members"][0]["source"]["expected_type_id"] = Value::Null;
    assert!(Book::from_record(&changed, 2).is_err());
    changed = good.clone();
    changed["lists"][0]["members"][0]["extra"] = json!(1);
    assert!(Book::from_record(&changed, 2).is_err());
    for representation in [0, 3, -1] {
        assert!(Book::from_record(&good, representation).is_err());
    }
    assert!(Book::from_record(&json!({"version":0,"lists":[]}), 2).is_ok());
}
#[test]
fn original_representation_projects_only_after_retaining_original_identity() {
    let original = json!({"version":1,"lists":[{"list_id":LIST,"name":"日常","source":{"integration_id":"source","integration_revision_fingerprint":"a".repeat(64),"expected_type_id":"test.market_data"},"instrument_ids":["BTCUSDT.BINANCE"]}]});
    let book = Book::from_record(&original, 1).unwrap();
    assert_eq!(book, Book::new(1, vec![list()]).unwrap());
    assert_ne!(
        book.fingerprint(NAMESPACE).unwrap(),
        Book::record_fingerprint(NAMESPACE, &original).unwrap()
    );
    assert!(Book::from_record(&original, 2).is_err());
    let mut empty = original.clone();
    empty["lists"][0]["instrument_ids"] = json!([]);
    let projected = Book::from_record(&empty, 1).unwrap();
    assert!(projected.historical_intent(NAMESPACE, 0).unwrap().is_none());
    assert_eq!(
        book.historical_intent(NAMESPACE, 0).unwrap(),
        Some(Book::intent_fingerprint(NAMESPACE, 0, &original["lists"]).unwrap())
    );
}
#[test]
fn hashes_match_independent_python_utf8_and_sorted_json_preimages() {
    let book = Book::new(1, vec![list()]).unwrap();
    assert_eq!(
        book.fingerprint(NAMESPACE).unwrap(),
        "dc8b3d11c91e5695bca209441551e4fa1ad6a1c55eaf8a54a503776476a8f66f"
    );
    assert_eq!(
        Book::intent_fingerprint(NAMESPACE, 0, &book.to_record()["lists"]).unwrap(),
        "30d5044d1bda7eb3681f3e9743a8841e2b2a7e6dc5ef4ffaee3260a6aff61e85"
    );
    assert!(book.fingerprint("not-a-namespace").is_err());
    let special = Book::new(
        1,
        vec![List::new(LIST, "Δ中\"\\\u{7f}\u{2028}😀", vec![]).unwrap()],
    )
    .unwrap();
    assert_eq!(
        special.fingerprint(NAMESPACE).unwrap(),
        "bbb61171792007f63b903810e0a225fd51f51d542e158b10e99f0f3ab09f72ae"
    );
}
