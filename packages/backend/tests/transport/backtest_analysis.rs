//! Technical boundary only: analysis data never grants a Run or access token.
use super::{declaration,operation,Operation};
use crate::transport::research_wire::BacktestAnalysisContextView;
use http::Method;
use serde_json::{Value,json};
#[test]
fn exact_completed_backtest_analysis_is_a_typed_human_read_without_a_business_command() {
    let path="/api/v2/backtest/runs/{run_id}/analysis-context";
    assert_eq!(operation(&Method::POST,path),Some(Operation::Implemented));
    assert_eq!(operation(&Method::GET,path),None);
    let (_,document)=declaration();let value:Value=serde_json::to_value(document).unwrap();let op=&value["paths"][path]["post"];
    assert_eq!(op["security"],json!([{"LocalDeveloperCookie":[]}]));
    assert_eq!(op["responses"]["200"]["content"]["application/json"]["schema"]["$ref"],"#/components/schemas/BacktestAnalysisContextView");
    for status in ["400","401","403","409","503"]{assert_eq!(op["responses"][status]["content"]["application/json"]["schema"]["$ref"],"#/components/schemas/NativeErrorEnvelope");}
    assert!(op["responses"].get("501").is_none());
    assert!(op.get("requestBody").is_none(),"the Human cannot post summary, counts, evidence or an APPROVED value");
    assert!(op["parameters"].as_array().unwrap().iter().all(|p|p["name"]!="Idempotency-Key"));
    let response=json!({"schema_version":1,"run_id":"00000000-0000-4000-8000-000000009301","assertion":"signed-data-assertion","expires_at":4000000000_u64});
    assert_eq!(serde_json::to_value(serde_json::from_value::<BacktestAnalysisContextView>(response.clone()).unwrap()).unwrap(),response);
    for key in ["grant","run_permit","backend_credential","scopes"]{
        let mut bad=response.clone();bad[key]=json!(true);assert!(serde_json::from_value::<BacktestAnalysisContextView>(bad).is_err());
    }
}
