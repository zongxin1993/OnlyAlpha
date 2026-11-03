use super::*;
#[tokio::test]
async fn only_the_owning_verified_negative_uses_the_structured_backtest_observation() {
    use axum::body::to_bytes;
    use serde_json::{Value,json};
    let command=CommandId::new("00000000-0000-4000-8000-000000008209").unwrap();
    for code in [crate::persistence::research_preparation::BACKTEST_NOT_ACCEPTED,"RESEARCH_PREPARATION_NOT_FOUND","RESEARCH_PREPARATION_OUTCOME_UNKNOWN","RESEARCH_PREPARATION_COMMAND_CONFLICT","RESEARCH_PREPARATION_CORRUPT","RESEARCH_PREPARATION_UNAVAILABLE"] {
        let result=backtest_command_observation_error(&command,code);
        if code==crate::persistence::research_preparation::BACKTEST_NOT_ACCEPTED {
            let value=result.unwrap();
            assert_eq!(value,json!({"schema_version":2,"command_id":command.value(),"state":"NOT_ACCEPTED"}));
            let typed:crate::transport::research_wire::BacktestPreparationCommandReply=serde_json::from_value(value.clone()).unwrap();
            assert_eq!(serde_json::to_value(typed).unwrap(),value);
            let response=Json(value).into_response();assert_eq!(response.status(),http::StatusCode::OK);
        }else{
            let response=result.unwrap_err().into_response();assert_eq!(response.status(),http::StatusCode::SERVICE_UNAVAILABLE);
            let body:Value=serde_json::from_slice(&to_bytes(response.into_body(),32768).await.unwrap()).unwrap();assert_eq!(body["error"]["code"],code);
        }
    }
}
