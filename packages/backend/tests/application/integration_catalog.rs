//! Installed authoring is an immutable executable projection, never readiness.
use onlyalpha_backend::application::integration_catalog::AuthoringCatalog;
use onlyalpha_integration_contract::{
    Category, Descriptor, Error, IntegrationTypeId,
    authoring::{PluginProjection, Registration},
};
use serde_json::{Value, value::RawValue};
const WORK: usize = 8 * 1024 * 1024;
fn configuration(_: &RawValue, _: usize) -> Result<(), Error> {
    Err(Error::Configuration)
}
fn registration(id: &str, category: Category, version: &str) -> Registration {
    let vectors: Vec<Value> =
        serde_json::from_str(include_str!("fixtures/integration_resolver.json")).unwrap();
    let mut document: Value =
        serde_json::from_str(vectors[0]["descriptor"].as_str().unwrap()).unwrap();
    document["type_id"] = id.into();
    document["category"] = match category {
        Category::DataSource => "DATA_SOURCE",
        Category::Broker => "BROKER",
        _ => panic!("unsupported test category"),
    }
    .into();
    document["implementation_version"] = version.into();
    let descriptor = Descriptor::from_json(&document.to_string(), WORK).unwrap();
    Registration::new(
        PluginProjection::new(
            category,
            "controlled.component",
            version,
            "1.0",
            vec!["HISTORICAL_BARS".into(), "PAGINATION:CURSOR".into()],
        )
        .unwrap(),
        descriptor,
        configuration,
    )
    .unwrap()
}
#[test]
fn empty_catalog_proves_no_installed_authoring_without_altering_type_identity() {
    let catalog = AuthoringCatalog::new(vec![]).unwrap();
    assert!(
        catalog
            .get(&IntegrationTypeId::new("controlled.missing").unwrap())
            .is_none()
    );
    assert_eq!(catalog.iter().count(), 0);
}
#[test]
fn exact_lookup_and_deterministic_order_retain_actual_executable_validation() {
    let catalog = AuthoringCatalog::new(vec![
        registration("controlled.z", Category::DataSource, "1"),
        registration("controlled.a", Category::Broker, "2"),
    ])
    .unwrap();
    assert_eq!(
        catalog
            .iter()
            .map(|r| r.descriptor().id().value())
            .collect::<Vec<_>>(),
        vec!["controlled.a", "controlled.z"]
    );
    let registered = catalog
        .get(&IntegrationTypeId::new("controlled.a").unwrap())
        .unwrap();
    assert_eq!(registered.descriptor().category(), Category::Broker);
    assert_eq!(
        registered
            .validate_public_configuration(&RawValue::from_string("{}".into()).unwrap(), WORK),
        Err(Error::Configuration)
    );
    for absent in ["controlled", "controlled.other", "controlled.a.v2"] {
        assert!(
            catalog
                .get(&IntegrationTypeId::new(absent).unwrap())
                .is_none()
        );
    }
}
#[test]
fn duplicate_type_identity_is_invalid_even_if_projection_or_version_differs() {
    for (category, version) in [
        (Category::DataSource, "1"),
        (Category::DataSource, "2"),
        (Category::Broker, "1"),
    ] {
        assert!(matches!(
            AuthoringCatalog::new(vec![
                registration("controlled.same", Category::DataSource, "1"),
                registration("controlled.same", category, version)
            ]),
            Err(Error::Type)
        ));
    }
}
