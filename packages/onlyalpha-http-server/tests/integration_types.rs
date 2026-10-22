//! Native route contract checks; not Shipping UI product acceptance.
use axum::{
    Router,
    body::{Body, to_bytes},
};
use http::{Request, StatusCode};
use hyper::service::Service;
use hyper_util::service::TowerToHyperService;
use onlyalpha_http_server::integration_types::router;
use onlyalpha_integration_contract::{
    Category, Descriptor, Error,
    authoring::{PluginProjection, Registration},
};
use onlyalpha_product_runtime::integration_catalog::AuthoringCatalog;
use serde_json::{Value, value::RawValue};
use std::{collections::BTreeMap, sync::Arc};
const WORK: usize = 8 * 1024 * 1024;
fn validator(_: &RawValue, _: usize) -> Result<(), Error> {
    panic!("metadata GET must never execute authoring validation")
}
fn registration(id: &str, category: Category, null_probe: bool) -> Registration {
    let vectors: Vec<Value> = serde_json::from_str(include_str!(
        "../../onlyalpha-product-runtime/tests/fixtures/integration_resolver.json"
    ))
    .unwrap();
    let mut fields: BTreeMap<String, Box<RawValue>> =
        serde_json::from_str(vectors[0]["descriptor"].as_str().unwrap()).unwrap();
    fields.insert(
        "type_id".into(),
        RawValue::from_string(serde_json::to_string(id).unwrap()).unwrap(),
    );
    fields.insert(
        "category".into(),
        RawValue::from_string(serde_json::to_string(category.as_str()).unwrap()).unwrap(),
    );
    if null_probe {
        fields.insert(
            "probe_contract".into(),
            RawValue::from_string("null".into()).unwrap(),
        );
    }
    let descriptor = Descriptor::from_json(&serde_json::to_string(&fields).unwrap(), WORK).unwrap();
    Registration::new(
        PluginProjection::new(
            category,
            "controlled.component",
            "1.0.0",
            "1.0",
            vec!["HISTORICAL_BARS".into(), "PAGINATION:CURSOR".into()],
        )
        .unwrap(),
        descriptor,
        validator,
    )
    .unwrap()
}
fn application() -> (Router, Vec<Value>) {
    let catalog = AuthoringCatalog::new(vec![
        registration("controlled.z", Category::DataSource, true),
        registration("controlled.a", Category::Broker, false),
    ])
    .unwrap();
    let expected = catalog
        .iter()
        .map(|r| {
            let mut dto: Value = serde_json::from_str(r.descriptor().document().get()).unwrap();
            dto["fingerprint"] = r.descriptor().fingerprint().into();
            dto
        })
        .collect();
    (router(Arc::new(catalog)), expected)
}
async fn request(app: &Router, method: &str, path: &str) -> (StatusCode, Vec<u8>) {
    let service = TowerToHyperService::new(app.clone());
    let response = service
        .call(
            Request::builder()
                .method(method)
                .uri(path)
                .body(Body::empty())
                .unwrap(),
        )
        .await
        .unwrap();
    let status = response.status();
    let body = to_bytes(response.into_body(), 1024 * 1024).await.unwrap();
    (status, body.to_vec())
}
async fn json(app: &Router, path: &str) -> (StatusCode, Value) {
    let (status, body) = request(app, "GET", path).await;
    (status, serde_json::from_slice(&body).unwrap())
}
#[tokio::test(flavor = "current_thread")]
async fn list_and_exact_get_preserve_the_complete_existing_product_dto() {
    let (app, expected) = application();
    let (status, list) = json(&app, "/api/v2/integration-types").await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(list, serde_json::json!({"items":expected}));
    for dto in &expected {
        let (status, read) = json(
            &app,
            &format!(
                "/api/v2/integration-types/{}",
                dto["type_id"].as_str().unwrap()
            ),
        )
        .await;
        assert_eq!(status, StatusCode::OK);
        assert_eq!(read, *dto);
    }
    assert_eq!(
        expected[0]["configuration_contract"]["fields"][0]["default"],
        Value::Null
    );
    assert_eq!(
        expected[0]["probe_contract"]["fingerprint"],
        "b1f977003c7ae3d7dfe8d2de02b263ac80a4a0f2cef532ea1cb093b23b463964"
    );
    assert_eq!(expected[1]["probe_contract"], Value::Null);
    let (_, bytes) = request(&app, "GET", "/api/v2/integration-types/controlled.a").await;
    let dto: BTreeMap<String, Box<RawValue>> = serde_json::from_slice(&bytes).unwrap();
    let config: BTreeMap<String, Box<RawValue>> =
        serde_json::from_str(dto["configuration_contract"].get()).unwrap();
    let fields: Vec<BTreeMap<String, Box<RawValue>>> =
        serde_json::from_str(config["fields"].get()).unwrap();
    assert_eq!(fields[3]["default"].get(), "2.0");
}
#[tokio::test(flavor = "current_thread")]
async fn exact_filter_query_decoding_and_existing_error_envelopes_are_retained() {
    let (app, expected) = application();
    for path in [
        "/api/v2/integration-types?category=DATA_SOURCE",
        "/api/v2/integration-types?%63ategory=DATA%5FSOURCE",
        "/api/v2/integration-types?ignored=1&category=BROKER&category=DATA_SOURCE",
    ] {
        assert_eq!(
            json(&app, path).await,
            (
                StatusCode::OK,
                serde_json::json!({"items":[expected[1].clone()]})
            )
        );
    }
    assert_eq!(
        json(&app, "/api/v2/integration-types?category=AGENT_PROVIDER").await,
        (StatusCode::OK, serde_json::json!({"items":[]}))
    );
    for value in ["broker", "", "DATA+SOURCE", "UNKNOWN"] {
        assert_eq!(
            json(&app, &format!("/api/v2/integration-types?category={value}")).await,
            (
                StatusCode::BAD_REQUEST,
                serde_json::json!({"error":{"code":"INTEGRATION_TYPE_CONTRACT_INVALID","detail":"Unknown Integration Type category"}})
            )
        );
    }
    for id in [
        "controlled.missing",
        "CONTROLLED.A",
        "controlled.a.v2",
        "latest",
    ] {
        assert_eq!(
            json(&app, &format!("/api/v2/integration-types/{id}")).await,
            (
                StatusCode::NOT_FOUND,
                serde_json::json!({"error":{"code":"INTEGRATION_TYPE_NOT_FOUND","detail":"Integration Type is not available"}})
            )
        );
    }
}
#[tokio::test(flavor = "current_thread")]
async fn empty_catalog_and_read_only_surface_do_not_manufacture_installations() {
    let app = router(Arc::new(AuthoringCatalog::new(vec![]).unwrap()));
    assert_eq!(
        json(&app, "/api/v2/integration-types").await,
        (StatusCode::OK, serde_json::json!({"items":[]}))
    );
    for method in ["HEAD", "POST", "PUT", "PATCH", "DELETE"] {
        for path in [
            "/api/v2/integration-types",
            "/api/v2/integration-types/controlled.a",
        ] {
            assert_eq!(
                request(&app, method, path).await.0,
                StatusCode::METHOD_NOT_ALLOWED
            );
        }
    }
}
