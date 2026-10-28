//! One actual native route declaration: serving and pure OpenAPI export share it.
use crate::transport::host::Host;
use crate::transport::wire::*;
use axum::{
    Router,
    body::{Body, to_bytes},
    extract::State,
    response::Response,
};
use http::{Method, Request, StatusCode};
use serde::de::DeserializeOwned;
use std::sync::{Arc, OnceLock};
use utoipa::openapi::{
    Info, OpenApi, OpenApiVersion,
    security::{ApiKey, ApiKeyValue, Http, HttpAuthScheme, SecurityScheme},
};
use utoipa_axum::{router::OpenApiRouter, routes};
async fn verify<T: DeserializeOwned>(response: Response) -> Response {
    if !response.status().is_success() {
        return response;
    }
    let (parts, body) = response.into_parts();
    let Ok(bytes) = to_bytes(body, 8 * 1024 * 1024).await else {
        return crate::transport::host::failure(
            StatusCode::SERVICE_UNAVAILABLE,
            "NATIVE_RESPONSE_UNAVAILABLE",
        );
    };
    if serde_json::from_slice::<T>(&bytes).is_err() {
        return crate::transport::host::failure(
            StatusCode::SERVICE_UNAVAILABLE,
            "NATIVE_RESPONSE_CONTRACT_INVALID",
        );
    }
    Response::from_parts(parts, Body::from(bytes))
}
pub fn declaration() -> (Router<Arc<Host>>, OpenApi) {
    let router=OpenApiRouter::<Arc<Host>>::new()
 .routes(routes!(market_data_stream_upgrade))
 .routes(routes!(temporary_market_data_stream_upgrade))
        .routes(routes!(agent_browser_access))
 .routes(routes!(agent_connection))
 .routes(routes!(proposal_grant))
 .routes(routes!(proposal_revoke))
 .routes(routes!(proposal_stage))
 .routes(routes!(proposal_context))
 .routes(routes!(proposal_read))
 .routes(routes!(proposal_confirm))
 .routes(routes!(proposal_withdraw))
 .routes(routes!(proposal_observe))
 .routes(routes!(admit_agent_session_v2))
 .routes(routes!(advance_agent_session_once_v2))
 .routes(routes!(creation_context_api_v2_backtest_creation_context_get))
 .routes(routes!(recent_runs_api_v2_backtest_runs_get))
 .routes(routes!(create_run_api_v2_backtest_runs_post))
 .routes(routes!(get_run_api_v2_backtest_runs_run_id_get))
 .routes(routes!(cancel_run_api_v2_backtest_runs_run_id_cancellation_post))
 .routes(routes!(get_evidence_api_v2_backtest_runs_run_id_evidence_get))
 .routes(routes!(get_artifact_api_v2_backtest_runs_run_id_evidence_artifacts_artifact_name_get))
 .routes(routes!(result_api_v2_backtest_runs_run_id_result_get))
 .routes(routes!(capabilities_api_v2_chart_studies_capabilities_get))
 .routes(routes!(evaluate_api_v2_chart_studies_evaluate_post))
 .routes(routes!(temporary_chart_studies_evaluate))
 .routes(routes!(temporary_chart_studies_evaluate_batch))
 .routes(routes!(list_integration_types_api_v2_integration_types_get))
 .routes(routes!(get_integration_type_api_v2_integration_types_type_id_get))
 .routes(routes!(list_integrations_api_v2_integrations_get))
 .routes(routes!(create_integration_api_v2_integrations_post))
 .routes(routes!(get_integration_api_v2_integrations_integration_id_get))
 .routes(routes!(get_integration_draft_api_v2_integrations_integration_id_draft_get))
 .routes(routes!(update_integration_draft_api_v2_integrations_integration_id_draft_put))
 .routes(routes!(reset_integration_draft_contract_api_v2_integrations_integration_id_draft_contract_reset_post))
 .routes(routes!(clear_integration_secret_api_v2_integrations_integration_id_draft_secrets_field_id_delete))
 .routes(routes!(set_integration_secret_api_v2_integrations_integration_id_draft_secrets_field_id_put))
 .routes(routes!(set_integration_lifecycle_api_v2_integrations_integration_id_lifecycle_put))
 .routes(routes!(get_integration_operational_status_api_v2_integrations_integration_id_operational_status_get))
 .routes(routes!(probe_integration_api_v2_integrations_integration_id_probe_post))
 .routes(routes!(list_integration_probe_attempts_api_v2_integrations_integration_id_probe_attempts_get))
 .routes(routes!(get_integration_probe_attempt_api_v2_integrations_integration_id_probe_attempts_probe_attempt_id_get))
 .routes(routes!(list_integration_revisions_api_v2_integrations_integration_id_revisions_get))
 .routes(routes!(publish_integration_revision_api_v2_integrations_integration_id_revisions_post))
 .routes(routes!(get_integration_revision_api_v2_integrations_integration_id_revisions_revision_fingerprint_get))
 .routes(routes!(create_acquisition_api_v2_market_data_acquisitions_post))
 .routes(routes!(get_acquisition_api_v2_market_data_acquisitions_acquisition_id_get))
 .routes(routes!(query_bars_api_v2_market_data_bars_get))
 .routes(routes!(temporary_bars_api_v2_chart_market_data_bars_get))
 .routes(routes!(latest_bar_api_v2_market_data_latest_bar_get))
 .routes(routes!(quotes_api_v2_market_data_quotes_get))
 .routes(routes!(list_sources_api_v2_market_data_sources_get))
 .routes(routes!(list_instruments_api_v2_market_instruments_get))
 .routes(routes!(search_instruments_api_v2_market_instruments_search_get))
 .routes(routes!(private_factor_authoring_inventory))
 .routes(routes!(private_factor_authoring_state))
 .routes(routes!(private_factor_draft_save))
 .routes(routes!(private_factor_display_update))
 .routes(routes!(private_factor_revision_publish))
 .routes(routes!(private_factor_authoring_command))
 .routes(routes!(browse_current_private_assets_v2))
 .routes(routes!(get_exact_private_factor_revision_v2))
 .routes(routes!(search_private_assets_v2))
 .routes(routes!(get_exact_private_strategy_revision_v2))
 .routes(routes!(get_qualification_decision_api_v2_qualification_decisions_decision_fingerprint_get))
 .routes(routes!(list_qualification_policies_api_v2_qualification_policies_get))
 .routes(routes!(get_qualification_policy_api_v2_qualification_policies_policy_id_revisions_policy_version_get))
 .routes(routes!(artifact_summary_api_v2_research_artifacts_research_result_fingerprint_get))
 .routes(routes!(candidate_catalog_api_v2_research_artifacts_research_result_fingerprint_candidates_get))
 .routes(routes!(candidate_graph_api_v2_research_artifacts_research_result_fingerprint_candidates_candidate_fingerprint_graph_get))
 .routes(routes!(market_series_api_v2_research_artifacts_research_result_fingerprint_market_series_get))
 .routes(routes!(signal_series_api_v2_research_artifacts_research_result_fingerprint_signals_candidate_fingerprint_role_series_get))
 .routes(routes!(statistics_catalog_api_v2_research_artifacts_research_result_fingerprint_statistics_get))
 .routes(routes!(statistic_series_api_v2_research_artifacts_research_result_fingerprint_statistics_statistics_fingerprint_series_get))
 .routes(routes!(variable_catalog_api_v2_research_artifacts_research_result_fingerprint_variables_get))
 .routes(routes!(variable_series_api_v2_research_artifacts_research_result_fingerprint_variables_calculation_fingerprint_node_fingerprint_output_name_series_get))
 .routes(routes!(get_complete_exact_catalog_context_v2))
 .routes(routes!(get_exact_catalog_readiness_v2))
 .routes(routes!(get_exact_catalog_context_v2))
 .routes(routes!(calculations_api_v2_research_catalog_calculations_get))
 .routes(routes!(dataset_fields_api_v2_research_catalog_dataset_fields_get))
 .routes(routes!(statistics_api_v2_research_catalog_statistics_get))
 .routes(routes!(universes_api_v2_research_catalog_universes_get))
 .routes(routes!(get_exact_dataset_snapshot_identity_v2))
 .routes(routes!(resolve_definition_api_v2_research_definitions_resolve_post))
 .routes(routes!(get_exact_evaluation_context_identity_v2))
 .routes(routes!(list_runs_api_v2_research_runs_get))
 .routes(routes!(submit_run_api_v2_research_runs_post))
 .routes(routes!(submit_research_run_command_v2))
 .routes(routes!(submit_private_strategy_research_v2))
 .routes(routes!(get_run_api_v2_research_runs_run_id_get))
 .routes(routes!(cancel_run_api_v2_research_runs_run_id_cancellation_post))
 .routes(routes!(get_run_execution_evidence_api_v2_research_runs_run_id_execution_evidence_get))
 .routes(routes!(get_active_runtime_generation_v2))
 .routes(routes!(get_exact_runtime_generation_v2))
 .routes(routes!(get_exact_search_authoring_input_v2))
 .routes(routes!(get_search_experiment_v2))
 .routes(routes!(get_search_iteration_ledger_v2))
 .routes(routes!(get_search_terminal_v2))
 .routes(routes!(submit_parameter_search_experiment_v2))
 .routes(routes!(advance_parameter_search_experiment_v2))
 .routes(routes!(submit_symbolic_search_experiment_v2))
 .routes(routes!(advance_symbolic_search_experiment_v2))
 .routes(routes!(get_exact_research_statistics_v2))
 .routes(routes!(get_strategy_api_v2_strategies_strategy_fingerprint_get))
 .routes(routes!(promote_strategy_api_v2_strategies_strategy_fingerprint_promotions_post))
 .routes(routes!(list_qualification_decisions_api_v2_strategies_strategy_fingerprint_qualification_decisions_get))
 .routes(routes!(promote_qualified_strategy_api_v2_strategies_strategy_fingerprint_qualification_promotions_post))
 .routes(routes!(evaluate_qualification_api_v2_strategies_strategy_fingerprint_qualifications_post))
 .routes(routes!(freeze_strategy_api_v2_strategy_freezes_post))
 .routes(routes!(read_api_v2_workspace_get))
 .routes(routes!(save_api_v2_workspace_put))
 .routes(routes!(command_api_v2_workspace_commands_command_id_get))
 .routes(routes!(read_api_v2_watchlists_get))
 .routes(routes!(save_api_v2_watchlists_put))
 .routes(routes!(command_api_v2_watchlists_commands_command_id_get))
 .routes(routes!(execution_health_execution_get))
 .routes(routes!(live_health_live_get))
 .routes(routes!(ready_health_ready_get))
 ;
    let (router, mut document) = router.split_for_parts();
    document.openapi = OpenApiVersion::Version31;
    document.info = Info::new("OnlyAlpha Product API", "2");
    document
        .components
        .get_or_insert_with(Default::default)
        .add_security_scheme(
            "AgentProposalBearer",
            SecurityScheme::Http(Http::new(HttpAuthScheme::Bearer)),
        );
    document
        .components
        .get_or_insert_default()
        .add_security_scheme(
            "LocalDeveloperCookie",
            SecurityScheme::ApiKey(ApiKey::Cookie(ApiKeyValue::new("onlyalpha_dev_session"))),
        );
    (router, document)
}
/// The ingress policy is a pure projection of the actual declared routes.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Operation {
    Implemented,
    Deferred,
    Denied,
}
pub fn operation(method: &Method, path: &str) -> Option<Operation> {
    static OPERATIONS: OnceLock<Vec<(String, String, Operation)>> = OnceLock::new();
    let entries = OPERATIONS.get_or_init(|| {
        let (_, doc) = declaration();
        let value = serde_json::to_value(doc).expect("typed OpenAPI serializes");
        let mut operations = vec![];
        for (path, methods) in value["paths"].as_object().expect("typed paths") {
            for (method, definition) in methods.as_object().expect("typed methods") {
                if matches!(method.as_str(), "get" | "post" | "put" | "patch" | "delete") {
                    let responses = definition["responses"]
                        .as_object()
                        .expect("typed responses");
                    let policy = if responses.len() == 1 && responses.contains_key("501") {
                        Operation::Deferred
                    } else if responses.len() == 1 && responses.contains_key("403") {
                        Operation::Denied
                    } else {
                        Operation::Implemented
                    };
                    operations.push((method.to_ascii_uppercase(), path.clone(), policy));
                }
            }
        }
        operations
    });
    entries
        .iter()
        .find(|(m, p, _)| m == method.as_str() && path_matches(p, path))
        .map(|(_, _, policy)| *policy)
}
fn path_matches(pattern: &str, path: &str) -> bool {
    let a: Vec<_> = pattern.split('/').collect();
    let b: Vec<_> = path.split('/').collect();
    a.len() == b.len()
        && a.iter().zip(b).all(|(p, v)| {
            if p.starts_with('{') && p.ends_with('}') {
                !v.is_empty() && v.len() <= 256
            } else {
                *p == v
            }
        })
}
pub fn navigation(method: &Method, path: &str) -> bool {
    matches!(*method, Method::GET | Method::HEAD)
        && [
            "/",
            "/factor-research",
            "/research",
            "/research/new",
            "/research/analysis",
            "/research/library",
            "/research/factors",
            "/research/runs",
            "/research/runs/{id}",
            "/research/results",
            "/research/results/{id}",
            "/research/results/{id}/statistics/{fp}",
            "/data",
            "/data/inputs",
            "/data/sources",
            "/data/sources/new",
            "/data/sources/{id}",
            "/strategies",
            "/strategies/{id}",
            "/backtest",
            "/backtest/runs",
            "/backtest/runs/{id}",
            "/system",
            "/system/health",
        ]
        .iter()
        .any(|p| path_matches(p, path))
}
#[utoipa::path(post, path = "/api/v2/agent/sessions", operation_id = "admit_agent_session_v2", tag = "workstation", security(("LocalDeveloperCookie" = [])), responses((status = 403, body = NativeErrorEnvelope)))]
async fn admit_agent_session_v2(State(host): State<Arc<Host>>, request: Request<Body>) -> Response {
    host.dispatch(request).await
}

#[utoipa::path(post, path = "/api/v2/agent/sessions/{session_fingerprint}/advance", operation_id = "advance_agent_session_once_v2", tag = "workstation", security(("LocalDeveloperCookie" = [])), params(("session_fingerprint" = String, Path)), responses((status = 403, body = NativeErrorEnvelope)))]
async fn advance_agent_session_once_v2(
    State(host): State<Arc<Host>>,
    request: Request<Body>,
) -> Response {
    host.dispatch(request).await
}

#[utoipa::path(get, path = "/api/v2/backtest/creation-context", operation_id = "creation_context_api_v2_backtest_creation_context_get", tag = "workstation", security(("LocalDeveloperCookie" = [])), responses((status = 501, body = NativeErrorEnvelope)))]
async fn creation_context_api_v2_backtest_creation_context_get(
    State(host): State<Arc<Host>>,
    request: Request<Body>,
) -> Response {
    host.dispatch(request).await
}

#[utoipa::path(get, path = "/api/v2/backtest/runs", operation_id = "recent_runs_api_v2_backtest_runs_get", tag = "workstation", security(("LocalDeveloperCookie" = [])), responses((status = 501, body = NativeErrorEnvelope)))]
async fn recent_runs_api_v2_backtest_runs_get(
    State(host): State<Arc<Host>>,
    request: Request<Body>,
) -> Response {
    host.dispatch(request).await
}

#[utoipa::path(post, path = "/api/v2/backtest/runs", operation_id = "create_run_api_v2_backtest_runs_post", tag = "workstation", security(("LocalDeveloperCookie" = [])), params(("Idempotency-Key" = String, Header)), responses((status = 501, body = NativeErrorEnvelope)))]
async fn create_run_api_v2_backtest_runs_post(
    State(host): State<Arc<Host>>,
    request: Request<Body>,
) -> Response {
    host.dispatch(request).await
}

#[utoipa::path(get, path = "/api/v2/backtest/runs/{run_id}", operation_id = "get_run_api_v2_backtest_runs__run_id__get", tag = "workstation", security(("LocalDeveloperCookie" = [])), params(("run_id" = String, Path)), responses((status = 501, body = NativeErrorEnvelope)))]
async fn get_run_api_v2_backtest_runs_run_id_get(
    State(host): State<Arc<Host>>,
    request: Request<Body>,
) -> Response {
    host.dispatch(request).await
}

#[utoipa::path(post, path = "/api/v2/backtest/runs/{run_id}/cancellation", operation_id = "cancel_run_api_v2_backtest_runs__run_id__cancellation_post", tag = "workstation", security(("LocalDeveloperCookie" = [])), params(("run_id" = String, Path),("Idempotency-Key" = String, Header)), responses((status = 501, body = NativeErrorEnvelope)))]
async fn cancel_run_api_v2_backtest_runs_run_id_cancellation_post(
    State(host): State<Arc<Host>>,
    request: Request<Body>,
) -> Response {
    host.dispatch(request).await
}

#[utoipa::path(get, path = "/api/v2/backtest/runs/{run_id}/evidence", operation_id = "get_evidence_api_v2_backtest_runs__run_id__evidence_get", tag = "workstation", security(("LocalDeveloperCookie" = [])), params(("run_id" = String, Path)), responses((status = 501, body = NativeErrorEnvelope)))]
async fn get_evidence_api_v2_backtest_runs_run_id_evidence_get(
    State(host): State<Arc<Host>>,
    request: Request<Body>,
) -> Response {
    host.dispatch(request).await
}

#[utoipa::path(get, path = "/api/v2/backtest/runs/{run_id}/evidence/artifacts/{artifact_name}", operation_id = "get_artifact_api_v2_backtest_runs__run_id__evidence_artifacts__artifact_name__get", tag = "workstation", security(("LocalDeveloperCookie" = [])), params(("run_id" = String, Path),("artifact_name" = String, Path)), responses((status = 501, body = NativeErrorEnvelope)))]
async fn get_artifact_api_v2_backtest_runs_run_id_evidence_artifacts_artifact_name_get(
    State(host): State<Arc<Host>>,
    request: Request<Body>,
) -> Response {
    host.dispatch(request).await
}

#[utoipa::path(get, path = "/api/v2/backtest/runs/{run_id}/result", operation_id = "result_api_v2_backtest_runs__run_id__result_get", tag = "workstation", security(("LocalDeveloperCookie" = [])), params(("run_id" = String, Path)), responses((status = 501, body = NativeErrorEnvelope)))]
async fn result_api_v2_backtest_runs_run_id_result_get(
    State(host): State<Arc<Host>>,
    request: Request<Body>,
) -> Response {
    host.dispatch(request).await
}

#[utoipa::path(get, path = "/api/v2/chart/studies/capabilities", operation_id = "capabilities_api_v2_chart_studies_capabilities_get", tag = "workstation", security(("LocalDeveloperCookie" = [])), responses((status = 200, body = ChartStudyCapabilitiesDto),(status = 400, body = NativeErrorEnvelope),(status = 401, body = NativeErrorEnvelope),(status = 403, body = NativeErrorEnvelope),(status = 404, body = NativeErrorEnvelope),(status = 409, body = NativeErrorEnvelope),(status = 429, body = NativeErrorEnvelope),(status = 500, body = NativeErrorEnvelope),(status = 503, body = NativeErrorEnvelope)))]
async fn capabilities_api_v2_chart_studies_capabilities_get(
    State(host): State<Arc<Host>>,
    request: Request<Body>,
) -> Response {
    let response = host.dispatch(request).await;
    verify::<ChartStudyCapabilitiesDto>(response).await
}

#[utoipa::path(post, path = "/api/v2/chart/studies/evaluate", operation_id = "evaluate_api_v2_chart_studies_evaluate_post", tag = "workstation", security(("LocalDeveloperCookie" = [])), request_body = ChartStudyEvaluateRequestDto, responses((status = 200, body = ChartStudyEvaluateDto),(status = 400, body = NativeErrorEnvelope),(status = 401, body = NativeErrorEnvelope),(status = 403, body = NativeErrorEnvelope),(status = 404, body = NativeErrorEnvelope),(status = 409, body = NativeErrorEnvelope),(status = 429, body = NativeErrorEnvelope),(status = 500, body = NativeErrorEnvelope),(status = 503, body = NativeErrorEnvelope)))]
async fn evaluate_api_v2_chart_studies_evaluate_post(
    State(host): State<Arc<Host>>,
    request: Request<Body>,
) -> Response {
    let response = host.dispatch(request).await;
    verify::<ChartStudyEvaluateDto>(response).await
}

#[utoipa::path(get, path = "/api/v2/integration-types", operation_id = "list_integration_types_api_v2_integration_types_get", tag = "workstation", security(("LocalDeveloperCookie" = [])), params(("category" = Option<String>, Query)), responses((status = 200, body = IntegrationTypeListDto),(status = 400, body = NativeErrorEnvelope),(status = 401, body = NativeErrorEnvelope),(status = 403, body = NativeErrorEnvelope),(status = 404, body = NativeErrorEnvelope),(status = 409, body = NativeErrorEnvelope),(status = 429, body = NativeErrorEnvelope),(status = 500, body = NativeErrorEnvelope),(status = 503, body = NativeErrorEnvelope)))]
async fn list_integration_types_api_v2_integration_types_get(
    State(host): State<Arc<Host>>,
    request: Request<Body>,
) -> Response {
    let response = host.dispatch(request).await;
    verify::<IntegrationTypeListDto>(response).await
}

#[utoipa::path(get, path = "/api/v2/integration-types/{type_id}", operation_id = "get_integration_type_api_v2_integration_types__type_id__get", tag = "workstation", security(("LocalDeveloperCookie" = [])), params(("type_id" = String, Path)), responses((status = 200, body = IntegrationTypeDto),(status = 400, body = NativeErrorEnvelope),(status = 401, body = NativeErrorEnvelope),(status = 403, body = NativeErrorEnvelope),(status = 404, body = NativeErrorEnvelope),(status = 409, body = NativeErrorEnvelope),(status = 429, body = NativeErrorEnvelope),(status = 500, body = NativeErrorEnvelope),(status = 503, body = NativeErrorEnvelope)))]
async fn get_integration_type_api_v2_integration_types_type_id_get(
    State(host): State<Arc<Host>>,
    request: Request<Body>,
) -> Response {
    let response = host.dispatch(request).await;
    verify::<IntegrationTypeDto>(response).await
}

#[utoipa::path(get, path = "/api/v2/integrations", operation_id = "list_integrations_api_v2_integrations_get", tag = "workstation", security(("LocalDeveloperCookie" = [])), params(("type_id" = Option<String>, Query),("lifecycle_state" = Option<String>, Query)), responses((status = 200, body = IntegrationListDto),(status = 400, body = NativeErrorEnvelope),(status = 401, body = NativeErrorEnvelope),(status = 403, body = NativeErrorEnvelope),(status = 404, body = NativeErrorEnvelope),(status = 409, body = NativeErrorEnvelope),(status = 429, body = NativeErrorEnvelope),(status = 500, body = NativeErrorEnvelope),(status = 503, body = NativeErrorEnvelope)))]
async fn list_integrations_api_v2_integrations_get(
    State(host): State<Arc<Host>>,
    request: Request<Body>,
) -> Response {
    let response = host.dispatch(request).await;
    verify::<IntegrationListDto>(response).await
}

#[utoipa::path(post, path = "/api/v2/integrations", operation_id = "create_integration_api_v2_integrations_post", tag = "workstation", security(("LocalDeveloperCookie" = [])), params(("Idempotency-Key" = String, Header)), request_body = IntegrationCreateRequestDto, responses((status = 200, body = IntegrationCommandResponseDto),(status = 400, body = NativeErrorEnvelope),(status = 401, body = NativeErrorEnvelope),(status = 403, body = NativeErrorEnvelope),(status = 404, body = NativeErrorEnvelope),(status = 409, body = NativeErrorEnvelope),(status = 429, body = NativeErrorEnvelope),(status = 500, body = NativeErrorEnvelope),(status = 503, body = NativeErrorEnvelope)))]
async fn create_integration_api_v2_integrations_post(
    State(host): State<Arc<Host>>,
    request: Request<Body>,
) -> Response {
    let response = host.dispatch(request).await;
    verify::<IntegrationCommandResponseDto>(response).await
}

#[utoipa::path(get, path = "/api/v2/integrations/{integration_id}", operation_id = "get_integration_api_v2_integrations__integration_id__get", tag = "workstation", security(("LocalDeveloperCookie" = [])), params(("integration_id" = String, Path)), responses((status = 200, body = IntegrationDto),(status = 400, body = NativeErrorEnvelope),(status = 401, body = NativeErrorEnvelope),(status = 403, body = NativeErrorEnvelope),(status = 404, body = NativeErrorEnvelope),(status = 409, body = NativeErrorEnvelope),(status = 429, body = NativeErrorEnvelope),(status = 500, body = NativeErrorEnvelope),(status = 503, body = NativeErrorEnvelope)))]
async fn get_integration_api_v2_integrations_integration_id_get(
    State(host): State<Arc<Host>>,
    request: Request<Body>,
) -> Response {
    let response = host.dispatch(request).await;
    verify::<IntegrationDto>(response).await
}

#[utoipa::path(get, path = "/api/v2/integrations/{integration_id}/draft", operation_id = "get_integration_draft_api_v2_integrations__integration_id__draft_get", tag = "workstation", security(("LocalDeveloperCookie" = [])), params(("integration_id" = String, Path)), responses((status = 200, body = IntegrationDraftDto),(status = 400, body = NativeErrorEnvelope),(status = 401, body = NativeErrorEnvelope),(status = 403, body = NativeErrorEnvelope),(status = 404, body = NativeErrorEnvelope),(status = 409, body = NativeErrorEnvelope),(status = 429, body = NativeErrorEnvelope),(status = 500, body = NativeErrorEnvelope),(status = 503, body = NativeErrorEnvelope)))]
async fn get_integration_draft_api_v2_integrations_integration_id_draft_get(
    State(host): State<Arc<Host>>,
    request: Request<Body>,
) -> Response {
    let response = host.dispatch(request).await;
    verify::<IntegrationDraftDto>(response).await
}

#[utoipa::path(put, path = "/api/v2/integrations/{integration_id}/draft", operation_id = "update_integration_draft_api_v2_integrations__integration_id__draft_put", tag = "workstation", security(("LocalDeveloperCookie" = [])), params(("integration_id" = String, Path),("Idempotency-Key" = String, Header)), request_body = IntegrationDraftUpdateRequestDto, responses((status = 200, body = IntegrationCommandResponseDto),(status = 400, body = NativeErrorEnvelope),(status = 401, body = NativeErrorEnvelope),(status = 403, body = NativeErrorEnvelope),(status = 404, body = NativeErrorEnvelope),(status = 409, body = NativeErrorEnvelope),(status = 429, body = NativeErrorEnvelope),(status = 500, body = NativeErrorEnvelope),(status = 503, body = NativeErrorEnvelope)))]
async fn update_integration_draft_api_v2_integrations_integration_id_draft_put(
    State(host): State<Arc<Host>>,
    request: Request<Body>,
) -> Response {
    let response = host.dispatch(request).await;
    verify::<IntegrationCommandResponseDto>(response).await
}

#[utoipa::path(post, path = "/api/v2/integrations/{integration_id}/draft/contract-reset", operation_id = "reset_integration_draft_contract_api_v2_integrations__integration_id__draft_contract_reset_post", tag = "workstation", security(("LocalDeveloperCookie" = [])), params(("integration_id" = String, Path),("Idempotency-Key" = String, Header)), request_body = IntegrationDraftContractResetRequestDto, responses((status = 200, body = IntegrationCommandResponseDto),(status = 400, body = NativeErrorEnvelope),(status = 401, body = NativeErrorEnvelope),(status = 403, body = NativeErrorEnvelope),(status = 404, body = NativeErrorEnvelope),(status = 409, body = NativeErrorEnvelope),(status = 429, body = NativeErrorEnvelope),(status = 500, body = NativeErrorEnvelope),(status = 503, body = NativeErrorEnvelope)))]
async fn reset_integration_draft_contract_api_v2_integrations_integration_id_draft_contract_reset_post(
    State(host): State<Arc<Host>>,
    request: Request<Body>,
) -> Response {
    let response = host.dispatch(request).await;
    verify::<IntegrationCommandResponseDto>(response).await
}

#[utoipa::path(delete, path = "/api/v2/integrations/{integration_id}/draft/secrets/{field_id}", operation_id = "clear_integration_secret_api_v2_integrations__integration_id__draft_secrets__field_id__delete", tag = "workstation", security(("LocalDeveloperCookie" = [])), params(("integration_id" = String, Path),("field_id" = String, Path),("expected_draft_version" = i64, Query),("Idempotency-Key" = String, Header)), responses((status = 200, body = IntegrationCommandResponseDto),(status = 400, body = NativeErrorEnvelope),(status = 401, body = NativeErrorEnvelope),(status = 403, body = NativeErrorEnvelope),(status = 404, body = NativeErrorEnvelope),(status = 409, body = NativeErrorEnvelope),(status = 429, body = NativeErrorEnvelope),(status = 500, body = NativeErrorEnvelope),(status = 503, body = NativeErrorEnvelope)))]
async fn clear_integration_secret_api_v2_integrations_integration_id_draft_secrets_field_id_delete(
    State(host): State<Arc<Host>>,
    request: Request<Body>,
) -> Response {
    let response = host.dispatch(request).await;
    verify::<IntegrationCommandResponseDto>(response).await
}

#[utoipa::path(put, path = "/api/v2/integrations/{integration_id}/draft/secrets/{field_id}", operation_id = "set_integration_secret_api_v2_integrations__integration_id__draft_secrets__field_id__put", tag = "workstation", security(("LocalDeveloperCookie" = [])), params(("integration_id" = String, Path),("field_id" = String, Path),("Idempotency-Key" = String, Header)), request_body = IntegrationSecretSetRequestDto, responses((status = 200, body = IntegrationCommandResponseDto),(status = 400, body = NativeErrorEnvelope),(status = 401, body = NativeErrorEnvelope),(status = 403, body = NativeErrorEnvelope),(status = 404, body = NativeErrorEnvelope),(status = 409, body = NativeErrorEnvelope),(status = 429, body = NativeErrorEnvelope),(status = 500, body = NativeErrorEnvelope),(status = 503, body = NativeErrorEnvelope)))]
async fn set_integration_secret_api_v2_integrations_integration_id_draft_secrets_field_id_put(
    State(host): State<Arc<Host>>,
    request: Request<Body>,
) -> Response {
    let response = host.dispatch(request).await;
    verify::<IntegrationCommandResponseDto>(response).await
}

#[utoipa::path(put, path = "/api/v2/integrations/{integration_id}/lifecycle", operation_id = "set_integration_lifecycle_api_v2_integrations__integration_id__lifecycle_put", tag = "workstation", security(("LocalDeveloperCookie" = [])), params(("integration_id" = String, Path),("Idempotency-Key" = String, Header)), request_body = IntegrationLifecycleUpdateRequestDto, responses((status = 200, body = IntegrationCommandResponseDto),(status = 400, body = NativeErrorEnvelope),(status = 401, body = NativeErrorEnvelope),(status = 403, body = NativeErrorEnvelope),(status = 404, body = NativeErrorEnvelope),(status = 409, body = NativeErrorEnvelope),(status = 429, body = NativeErrorEnvelope),(status = 500, body = NativeErrorEnvelope),(status = 503, body = NativeErrorEnvelope)))]
async fn set_integration_lifecycle_api_v2_integrations_integration_id_lifecycle_put(
    State(host): State<Arc<Host>>,
    request: Request<Body>,
) -> Response {
    let response = host.dispatch(request).await;
    verify::<IntegrationCommandResponseDto>(response).await
}

#[utoipa::path(get, path = "/api/v2/integrations/{integration_id}/operational-status", operation_id = "get_integration_operational_status_api_v2_integrations__integration_id__operational_status_get", tag = "workstation", security(("LocalDeveloperCookie" = [])), params(("integration_id" = String, Path)), responses((status = 200, body = IntegrationOperationalStatusDto),(status = 400, body = NativeErrorEnvelope),(status = 401, body = NativeErrorEnvelope),(status = 403, body = NativeErrorEnvelope),(status = 404, body = NativeErrorEnvelope),(status = 409, body = NativeErrorEnvelope),(status = 429, body = NativeErrorEnvelope),(status = 500, body = NativeErrorEnvelope),(status = 503, body = NativeErrorEnvelope)))]
async fn get_integration_operational_status_api_v2_integrations_integration_id_operational_status_get(
    State(host): State<Arc<Host>>,
    request: Request<Body>,
) -> Response {
    let response = host.dispatch(request).await;
    verify::<IntegrationOperationalStatusDto>(response).await
}

#[utoipa::path(post, path = "/api/v2/integrations/{integration_id}/probe", operation_id = "probe_integration_api_v2_integrations__integration_id__probe_post", tag = "workstation", security(("LocalDeveloperCookie" = [])), params(("integration_id" = String, Path)), request_body = IntegrationProbeRequestDto, responses((status = 200, body = IntegrationProbeAttemptDto),(status = 400, body = NativeErrorEnvelope),(status = 401, body = NativeErrorEnvelope),(status = 403, body = NativeErrorEnvelope),(status = 404, body = NativeErrorEnvelope),(status = 409, body = NativeErrorEnvelope),(status = 429, body = NativeErrorEnvelope),(status = 500, body = NativeErrorEnvelope),(status = 503, body = NativeErrorEnvelope)))]
async fn probe_integration_api_v2_integrations_integration_id_probe_post(
    State(host): State<Arc<Host>>,
    request: Request<Body>,
) -> Response {
    let response = host.dispatch(request).await;
    verify::<IntegrationProbeAttemptDto>(response).await
}

#[utoipa::path(get, path = "/api/v2/integrations/{integration_id}/probe-attempts", operation_id = "list_integration_probe_attempts_api_v2_integrations__integration_id__probe_attempts_get", tag = "workstation", security(("LocalDeveloperCookie" = [])), params(("integration_id" = String, Path)), responses((status = 200, body = IntegrationProbeAttemptListDto),(status = 400, body = NativeErrorEnvelope),(status = 401, body = NativeErrorEnvelope),(status = 403, body = NativeErrorEnvelope),(status = 404, body = NativeErrorEnvelope),(status = 409, body = NativeErrorEnvelope),(status = 429, body = NativeErrorEnvelope),(status = 500, body = NativeErrorEnvelope),(status = 503, body = NativeErrorEnvelope)))]
async fn list_integration_probe_attempts_api_v2_integrations_integration_id_probe_attempts_get(
    State(host): State<Arc<Host>>,
    request: Request<Body>,
) -> Response {
    let response = host.dispatch(request).await;
    verify::<IntegrationProbeAttemptListDto>(response).await
}

#[utoipa::path(get, path = "/api/v2/integrations/{integration_id}/probe-attempts/{probe_attempt_id}", operation_id = "get_integration_probe_attempt_api_v2_integrations__integration_id__probe_attempts__probe_attempt_id__get", tag = "workstation", security(("LocalDeveloperCookie" = [])), params(("integration_id" = String, Path),("probe_attempt_id" = String, Path)), responses((status = 200, body = IntegrationProbeAttemptDto),(status = 400, body = NativeErrorEnvelope),(status = 401, body = NativeErrorEnvelope),(status = 403, body = NativeErrorEnvelope),(status = 404, body = NativeErrorEnvelope),(status = 409, body = NativeErrorEnvelope),(status = 429, body = NativeErrorEnvelope),(status = 500, body = NativeErrorEnvelope),(status = 503, body = NativeErrorEnvelope)))]
async fn get_integration_probe_attempt_api_v2_integrations_integration_id_probe_attempts_probe_attempt_id_get(
    State(host): State<Arc<Host>>,
    request: Request<Body>,
) -> Response {
    let response = host.dispatch(request).await;
    verify::<IntegrationProbeAttemptDto>(response).await
}

#[utoipa::path(get, path = "/api/v2/integrations/{integration_id}/revisions", operation_id = "list_integration_revisions_api_v2_integrations__integration_id__revisions_get", tag = "workstation", security(("LocalDeveloperCookie" = [])), params(("integration_id" = String, Path)), responses((status = 200, body = IntegrationRevisionListDto),(status = 400, body = NativeErrorEnvelope),(status = 401, body = NativeErrorEnvelope),(status = 403, body = NativeErrorEnvelope),(status = 404, body = NativeErrorEnvelope),(status = 409, body = NativeErrorEnvelope),(status = 429, body = NativeErrorEnvelope),(status = 500, body = NativeErrorEnvelope),(status = 503, body = NativeErrorEnvelope)))]
async fn list_integration_revisions_api_v2_integrations_integration_id_revisions_get(
    State(host): State<Arc<Host>>,
    request: Request<Body>,
) -> Response {
    let response = host.dispatch(request).await;
    verify::<IntegrationRevisionListDto>(response).await
}

#[utoipa::path(post, path = "/api/v2/integrations/{integration_id}/revisions", operation_id = "publish_integration_revision_api_v2_integrations__integration_id__revisions_post", tag = "workstation", security(("LocalDeveloperCookie" = [])), params(("integration_id" = String, Path),("Idempotency-Key" = String, Header)), request_body = IntegrationPublishRequestDto, responses((status = 200, body = IntegrationCommandResponseDto),(status = 400, body = NativeErrorEnvelope),(status = 401, body = NativeErrorEnvelope),(status = 403, body = NativeErrorEnvelope),(status = 404, body = NativeErrorEnvelope),(status = 409, body = NativeErrorEnvelope),(status = 429, body = NativeErrorEnvelope),(status = 500, body = NativeErrorEnvelope),(status = 503, body = NativeErrorEnvelope)))]
async fn publish_integration_revision_api_v2_integrations_integration_id_revisions_post(
    State(host): State<Arc<Host>>,
    request: Request<Body>,
) -> Response {
    let response = host.dispatch(request).await;
    verify::<IntegrationCommandResponseDto>(response).await
}

#[utoipa::path(get, path = "/api/v2/integrations/{integration_id}/revisions/{revision_fingerprint}", operation_id = "get_integration_revision_api_v2_integrations__integration_id__revisions__revision_fingerprint__get", tag = "workstation", security(("LocalDeveloperCookie" = [])), params(("integration_id" = String, Path),("revision_fingerprint" = String, Path)), responses((status = 200, body = IntegrationRevisionDto),(status = 400, body = NativeErrorEnvelope),(status = 401, body = NativeErrorEnvelope),(status = 403, body = NativeErrorEnvelope),(status = 404, body = NativeErrorEnvelope),(status = 409, body = NativeErrorEnvelope),(status = 429, body = NativeErrorEnvelope),(status = 500, body = NativeErrorEnvelope),(status = 503, body = NativeErrorEnvelope)))]
async fn get_integration_revision_api_v2_integrations_integration_id_revisions_revision_fingerprint_get(
    State(host): State<Arc<Host>>,
    request: Request<Body>,
) -> Response {
    let response = host.dispatch(request).await;
    verify::<IntegrationRevisionDto>(response).await
}

#[utoipa::path(post, path = "/api/v2/market-data/acquisitions", operation_id = "create_acquisition_api_v2_market_data_acquisitions_post", tag = "workstation", security(("LocalDeveloperCookie" = [])), request_body = MarketDataAcquisitionRequestDto, responses((status = 200, body = MarketDataAcquisitionDto),(status = 400, body = NativeErrorEnvelope),(status = 401, body = NativeErrorEnvelope),(status = 403, body = NativeErrorEnvelope),(status = 404, body = NativeErrorEnvelope),(status = 409, body = NativeErrorEnvelope),(status = 429, body = NativeErrorEnvelope),(status = 500, body = NativeErrorEnvelope),(status = 503, body = NativeErrorEnvelope)))]
async fn create_acquisition_api_v2_market_data_acquisitions_post(
    State(host): State<Arc<Host>>,
    request: Request<Body>,
) -> Response {
    let response = host.dispatch(request).await;
    verify::<MarketDataAcquisitionDto>(response).await
}

#[utoipa::path(get, path = "/api/v2/market-data/acquisitions/{acquisition_id}", operation_id = "get_acquisition_api_v2_market_data_acquisitions__acquisition_id__get", tag = "workstation", security(("LocalDeveloperCookie" = [])), params(("acquisition_id" = String, Path),("integration_id" = String, Query),("integration_revision_fingerprint" = String, Query),("expected_type_id" = Option<String>, Query)), responses((status = 200, body = MarketDataAcquisitionDto),(status = 400, body = NativeErrorEnvelope),(status = 401, body = NativeErrorEnvelope),(status = 403, body = NativeErrorEnvelope),(status = 404, body = NativeErrorEnvelope),(status = 409, body = NativeErrorEnvelope),(status = 429, body = NativeErrorEnvelope),(status = 500, body = NativeErrorEnvelope),(status = 503, body = NativeErrorEnvelope)))]
async fn get_acquisition_api_v2_market_data_acquisitions_acquisition_id_get(
    State(host): State<Arc<Host>>,
    request: Request<Body>,
) -> Response {
    let response = host.dispatch(request).await;
    verify::<MarketDataAcquisitionDto>(response).await
}

#[utoipa::path(get, path = "/api/v2/market-data/bars", operation_id = "query_bars_api_v2_market_data_bars_get", tag = "workstation", security(("LocalDeveloperCookie" = [])), params(("integration_id" = String, Query),("integration_revision_fingerprint" = String, Query),("instrument_id" = String, Query),("anchor_kind" = String, Query),("bar_semantic" = String, Query),("target_bar_count" = i64, Query),("before_ns" = Option<String>, Query),("expected_type_id" = Option<String>, Query)), responses((status = 200, body = MarketDataBarWindowDto),(status = 400, body = NativeErrorEnvelope),(status = 401, body = NativeErrorEnvelope),(status = 403, body = NativeErrorEnvelope),(status = 404, body = NativeErrorEnvelope),(status = 409, body = NativeErrorEnvelope),(status = 429, body = NativeErrorEnvelope),(status = 500, body = NativeErrorEnvelope),(status = 503, body = NativeErrorEnvelope)))]
async fn query_bars_api_v2_market_data_bars_get(
    State(host): State<Arc<Host>>,
    request: Request<Body>,
) -> Response {
    let response = host.dispatch(request).await;
    verify::<MarketDataBarWindowDto>(response).await
}

#[utoipa::path(get, path = "/api/v2/chart/market-data/bars", operation_id = "temporary_bars_api_v2_chart_market_data_bars_get", tag = "workstation", security(("LocalDeveloperCookie" = [])), params(("page_id" = String, Query),("integration_id" = String, Query),("integration_revision_fingerprint" = String, Query),("instrument_id" = String, Query),("anchor_kind" = String, Query),("bar_semantic" = String, Query),("target_bar_count" = i64, Query),("before_ns" = Option<String>, Query),("expected_type_id" = Option<String>, Query)), responses((status = 200, body = TemporaryMarketDataWindowDto),(status = 400, body = NativeErrorEnvelope),(status = 401, body = NativeErrorEnvelope),(status = 403, body = NativeErrorEnvelope),(status = 404, body = NativeErrorEnvelope),(status = 409, body = NativeErrorEnvelope),(status = 429, body = NativeErrorEnvelope),(status = 503, body = NativeErrorEnvelope)))]
async fn temporary_bars_api_v2_chart_market_data_bars_get(
    State(host): State<Arc<Host>>,
    request: Request<Body>,
) -> Response {
    verify::<TemporaryMarketDataWindowDto>(host.dispatch(request).await).await
}

#[utoipa::path(get, path = "/api/v2/market-data/latest-bar", operation_id = "latest_bar_api_v2_market_data_latest_bar_get", tag = "workstation", security(("LocalDeveloperCookie" = [])), params(("integration_id" = String, Query),("integration_revision_fingerprint" = String, Query),("instrument_id" = String, Query),("bar_semantic" = String, Query),("expected_type_id" = Option<String>, Query)), responses((status = 200, body = Option<MarketDataBarWindowDto>),(status = 400, body = NativeErrorEnvelope),(status = 401, body = NativeErrorEnvelope),(status = 403, body = NativeErrorEnvelope),(status = 404, body = NativeErrorEnvelope),(status = 409, body = NativeErrorEnvelope),(status = 429, body = NativeErrorEnvelope),(status = 500, body = NativeErrorEnvelope),(status = 503, body = NativeErrorEnvelope)))]
async fn latest_bar_api_v2_market_data_latest_bar_get(
    State(host): State<Arc<Host>>,
    request: Request<Body>,
) -> Response {
    let response = host.dispatch(request).await;
    verify::<Option<MarketDataBarWindowDto>>(response).await
}

#[utoipa::path(get, path = "/api/v2/market-data/quotes", operation_id = "quotes_api_v2_market_data_quotes_get", tag = "workstation", security(("LocalDeveloperCookie" = [])), params(("integration_id" = String, Query),("integration_revision_fingerprint" = String, Query),("instrument_ids" = String, Query),("expected_type_id" = Option<String>, Query)), responses((status = 200, body = MarketDataQuoteListDto),(status = 400, body = NativeErrorEnvelope),(status = 401, body = NativeErrorEnvelope),(status = 403, body = NativeErrorEnvelope),(status = 404, body = NativeErrorEnvelope),(status = 409, body = NativeErrorEnvelope),(status = 429, body = NativeErrorEnvelope),(status = 500, body = NativeErrorEnvelope),(status = 503, body = NativeErrorEnvelope)))]
async fn quotes_api_v2_market_data_quotes_get(
    State(host): State<Arc<Host>>,
    request: Request<Body>,
) -> Response {
    let response = host.dispatch(request).await;
    verify::<MarketDataQuoteListDto>(response).await
}

#[utoipa::path(get, path = "/api/v2/market-data/sources", operation_id = "list_sources_api_v2_market_data_sources_get", tag = "workstation", security(("LocalDeveloperCookie" = [])), responses((status = 200, body = MarketDataSourceListDto),(status = 400, body = NativeErrorEnvelope),(status = 401, body = NativeErrorEnvelope),(status = 403, body = NativeErrorEnvelope),(status = 404, body = NativeErrorEnvelope),(status = 409, body = NativeErrorEnvelope),(status = 429, body = NativeErrorEnvelope),(status = 500, body = NativeErrorEnvelope),(status = 503, body = NativeErrorEnvelope)))]
async fn list_sources_api_v2_market_data_sources_get(
    State(host): State<Arc<Host>>,
    request: Request<Body>,
) -> Response {
    let response = host.dispatch(request).await;
    verify::<MarketDataSourceListDto>(response).await
}

#[utoipa::path(get, path = "/api/v2/market/instruments", operation_id = "list_instruments_api_v2_market_instruments_get", tag = "workstation", security(("LocalDeveloperCookie" = [])), params(("integration_id" = String, Query),("integration_revision_fingerprint" = String, Query),("expected_type_id" = Option<String>, Query),("query" = Option<String>, Query),("limit" = Option<i64>, Query),("instrument_ids" = Option<String>, Query)), responses((status = 200, body = MarketDataInstrumentListDto),(status = 400, body = NativeErrorEnvelope),(status = 401, body = NativeErrorEnvelope),(status = 403, body = NativeErrorEnvelope),(status = 404, body = NativeErrorEnvelope),(status = 409, body = NativeErrorEnvelope),(status = 429, body = NativeErrorEnvelope),(status = 500, body = NativeErrorEnvelope),(status = 503, body = NativeErrorEnvelope)))]
async fn list_instruments_api_v2_market_instruments_get(
    State(host): State<Arc<Host>>,
    request: Request<Body>,
) -> Response {
    let response = host.dispatch(request).await;
    verify::<MarketDataInstrumentListDto>(response).await
}

#[utoipa::path(get, path = "/api/v2/market/instruments/search", operation_id = "search_instruments_api_v2_market_instruments_search_get", tag = "workstation", security(("LocalDeveloperCookie" = [])), params(("query" = String, Query),("asset_class" = Option<String>, Query),("limit" = Option<i64>, Query),("instrument_types" = Option<String>, Query)), responses((status = 200, body = MarketDataSearchDto),(status = 400, body = NativeErrorEnvelope),(status = 401, body = NativeErrorEnvelope),(status = 403, body = NativeErrorEnvelope),(status = 404, body = NativeErrorEnvelope),(status = 409, body = NativeErrorEnvelope),(status = 429, body = NativeErrorEnvelope),(status = 500, body = NativeErrorEnvelope),(status = 503, body = NativeErrorEnvelope)))]
async fn search_instruments_api_v2_market_instruments_search_get(
    State(host): State<Arc<Host>>,
    request: Request<Body>,
) -> Response {
    let response = host.dispatch(request).await;
    verify::<MarketDataSearchDto>(response).await
}

#[utoipa::path(get, path = "/api/v2/private-assets", operation_id = "browse_current_private_assets_v2", tag = "workstation", security(("LocalDeveloperCookie" = [])), responses((status = 200, body = PrivateAssetRegistryDto),(status = 400, body = NativeErrorEnvelope),(status = 401, body = NativeErrorEnvelope),(status = 403, body = NativeErrorEnvelope),(status = 404, body = NativeErrorEnvelope),(status = 409, body = NativeErrorEnvelope),(status = 429, body = NativeErrorEnvelope),(status = 500, body = NativeErrorEnvelope),(status = 503, body = NativeErrorEnvelope)))]
async fn browse_current_private_assets_v2(
    State(host): State<Arc<Host>>,
    request: Request<Body>,
) -> Response {
    let response = host.dispatch(request).await;
    verify::<PrivateAssetRegistryDto>(response).await
}

#[utoipa::path(get, path = "/api/v2/private-assets/factors/{factor_id}/revisions/{revision_fingerprint}", operation_id = "get_exact_private_factor_revision_v2", tag = "workstation", security(("LocalDeveloperCookie" = [])), params(("factor_id" = String, Path),("revision_fingerprint" = String, Path),("content_fingerprint" = String, Query)), responses((status = 200, body = PrivateFactorRevisionDto),(status = 400, body = NativeErrorEnvelope),(status = 401, body = NativeErrorEnvelope),(status = 403, body = NativeErrorEnvelope),(status = 404, body = NativeErrorEnvelope),(status = 409, body = NativeErrorEnvelope),(status = 429, body = NativeErrorEnvelope),(status = 500, body = NativeErrorEnvelope),(status = 503, body = NativeErrorEnvelope)))]
async fn get_exact_private_factor_revision_v2(
    State(host): State<Arc<Host>>,
    request: Request<Body>,
) -> Response {
    let response = host.dispatch(request).await;
    verify::<PrivateFactorRevisionDto>(response).await
}

#[utoipa::path(get, path = "/api/v2/private-assets/search", operation_id = "search_private_assets_v2", tag = "workstation", security(("LocalDeveloperCookie" = [])), params(("text" = Option<String>, Query),("kind" = Option<String>, Query),("category" = Option<String>, Query),("tag" = Option<String>, Query)), responses((status = 501, body = NativeErrorEnvelope)))]
async fn search_private_assets_v2(
    State(host): State<Arc<Host>>,
    request: Request<Body>,
) -> Response {
    host.dispatch(request).await
}

#[utoipa::path(get, path = "/api/v2/private-assets/strategies/{strategy_id}/revisions/{revision_fingerprint}", operation_id = "get_exact_private_strategy_revision_v2", tag = "workstation", security(("LocalDeveloperCookie" = [])), params(("strategy_id" = String, Path),("revision_fingerprint" = String, Path),("content_fingerprint" = String, Query)), responses((status = 501, body = NativeErrorEnvelope)))]
async fn get_exact_private_strategy_revision_v2(
    State(host): State<Arc<Host>>,
    request: Request<Body>,
) -> Response {
    host.dispatch(request).await
}

#[utoipa::path(get, path = "/api/v2/qualification-decisions/{decision_fingerprint}", operation_id = "get_qualification_decision_api_v2_qualification_decisions__decision_fingerprint__get", tag = "workstation", security(("LocalDeveloperCookie" = [])), params(("decision_fingerprint" = String, Path)), responses((status = 501, body = NativeErrorEnvelope)))]
async fn get_qualification_decision_api_v2_qualification_decisions_decision_fingerprint_get(
    State(host): State<Arc<Host>>,
    request: Request<Body>,
) -> Response {
    host.dispatch(request).await
}

#[utoipa::path(get, path = "/api/v2/qualification-policies", operation_id = "list_qualification_policies_api_v2_qualification_policies_get", tag = "workstation", security(("LocalDeveloperCookie" = [])), responses((status = 501, body = NativeErrorEnvelope)))]
async fn list_qualification_policies_api_v2_qualification_policies_get(
    State(host): State<Arc<Host>>,
    request: Request<Body>,
) -> Response {
    host.dispatch(request).await
}

#[utoipa::path(get, path = "/api/v2/qualification-policies/{policy_id}/revisions/{policy_version}", operation_id = "get_qualification_policy_api_v2_qualification_policies__policy_id__revisions__policy_version__get", tag = "workstation", security(("LocalDeveloperCookie" = [])), params(("policy_id" = String, Path),("policy_version" = String, Path)), responses((status = 501, body = NativeErrorEnvelope)))]
async fn get_qualification_policy_api_v2_qualification_policies_policy_id_revisions_policy_version_get(
    State(host): State<Arc<Host>>,
    request: Request<Body>,
) -> Response {
    host.dispatch(request).await
}

#[utoipa::path(get, path = "/api/v2/research/artifacts/{research_result_fingerprint}", operation_id = "artifact_summary_api_v2_research_artifacts__research_result_fingerprint__get", tag = "workstation", security(("LocalDeveloperCookie" = [])), params(("research_result_fingerprint" = String, Path)), responses((status = 501, body = NativeErrorEnvelope)))]
async fn artifact_summary_api_v2_research_artifacts_research_result_fingerprint_get(
    State(host): State<Arc<Host>>,
    request: Request<Body>,
) -> Response {
    host.dispatch(request).await
}

#[utoipa::path(get, path = "/api/v2/research/artifacts/{research_result_fingerprint}/candidates", operation_id = "candidate_catalog_api_v2_research_artifacts__research_result_fingerprint__candidates_get", tag = "workstation", security(("LocalDeveloperCookie" = [])), params(("research_result_fingerprint" = String, Path)), responses((status = 501, body = NativeErrorEnvelope)))]
async fn candidate_catalog_api_v2_research_artifacts_research_result_fingerprint_candidates_get(
    State(host): State<Arc<Host>>,
    request: Request<Body>,
) -> Response {
    host.dispatch(request).await
}

#[utoipa::path(get, path = "/api/v2/research/artifacts/{research_result_fingerprint}/candidates/{candidate_fingerprint}/graph", operation_id = "candidate_graph_api_v2_research_artifacts__research_result_fingerprint__candidates__candidate_fingerprint__graph_get", tag = "workstation", security(("LocalDeveloperCookie" = [])), params(("research_result_fingerprint" = String, Path),("candidate_fingerprint" = String, Path)), responses((status = 501, body = NativeErrorEnvelope)))]
async fn candidate_graph_api_v2_research_artifacts_research_result_fingerprint_candidates_candidate_fingerprint_graph_get(
    State(host): State<Arc<Host>>,
    request: Request<Body>,
) -> Response {
    host.dispatch(request).await
}

#[utoipa::path(get, path = "/api/v2/research/artifacts/{research_result_fingerprint}/market/series", operation_id = "market_series_api_v2_research_artifacts__research_result_fingerprint__market_series_get", tag = "workstation", security(("LocalDeveloperCookie" = [])), params(("research_result_fingerprint" = String, Path),("instrument_id" = String, Query),("from_ts_event_ns" = Option<String>, Query),("to_ts_event_ns" = Option<String>, Query),("after_ts_event_ns" = Option<String>, Query),("limit" = Option<i64>, Query)), responses((status = 501, body = NativeErrorEnvelope)))]
async fn market_series_api_v2_research_artifacts_research_result_fingerprint_market_series_get(
    State(host): State<Arc<Host>>,
    request: Request<Body>,
) -> Response {
    host.dispatch(request).await
}

#[utoipa::path(get, path = "/api/v2/research/artifacts/{research_result_fingerprint}/signals/{candidate_fingerprint}/{role}/series", operation_id = "signal_series_api_v2_research_artifacts__research_result_fingerprint__signals__candidate_fingerprint___role__series_get", tag = "workstation", security(("LocalDeveloperCookie" = [])), params(("research_result_fingerprint" = String, Path),("candidate_fingerprint" = String, Path),("role" = String, Path),("instrument_id" = String, Query),("from_ts_event_ns" = Option<String>, Query),("to_ts_event_ns" = Option<String>, Query),("after_ts_event_ns" = Option<String>, Query),("limit" = Option<i64>, Query)), responses((status = 501, body = NativeErrorEnvelope)))]
async fn signal_series_api_v2_research_artifacts_research_result_fingerprint_signals_candidate_fingerprint_role_series_get(
    State(host): State<Arc<Host>>,
    request: Request<Body>,
) -> Response {
    host.dispatch(request).await
}

#[utoipa::path(get, path = "/api/v2/research/artifacts/{research_result_fingerprint}/statistics", operation_id = "statistics_catalog_api_v2_research_artifacts__research_result_fingerprint__statistics_get", tag = "workstation", security(("LocalDeveloperCookie" = [])), params(("research_result_fingerprint" = String, Path)), responses((status = 501, body = NativeErrorEnvelope)))]
async fn statistics_catalog_api_v2_research_artifacts_research_result_fingerprint_statistics_get(
    State(host): State<Arc<Host>>,
    request: Request<Body>,
) -> Response {
    host.dispatch(request).await
}

#[utoipa::path(get, path = "/api/v2/research/artifacts/{research_result_fingerprint}/statistics/{statistics_fingerprint}/series", operation_id = "statistic_series_api_v2_research_artifacts__research_result_fingerprint__statistics__statistics_fingerprint__series_get", tag = "workstation", security(("LocalDeveloperCookie" = [])), params(("research_result_fingerprint" = String, Path),("statistics_fingerprint" = String, Path),("from_ts_event_ns" = Option<String>, Query),("to_ts_event_ns" = Option<String>, Query),("after_ts_event_ns" = Option<String>, Query),("limit" = Option<i64>, Query)), responses((status = 501, body = NativeErrorEnvelope)))]
async fn statistic_series_api_v2_research_artifacts_research_result_fingerprint_statistics_statistics_fingerprint_series_get(
    State(host): State<Arc<Host>>,
    request: Request<Body>,
) -> Response {
    host.dispatch(request).await
}

#[utoipa::path(get, path = "/api/v2/research/artifacts/{research_result_fingerprint}/variables", operation_id = "variable_catalog_api_v2_research_artifacts__research_result_fingerprint__variables_get", tag = "workstation", security(("LocalDeveloperCookie" = [])), params(("research_result_fingerprint" = String, Path)), responses((status = 501, body = NativeErrorEnvelope)))]
async fn variable_catalog_api_v2_research_artifacts_research_result_fingerprint_variables_get(
    State(host): State<Arc<Host>>,
    request: Request<Body>,
) -> Response {
    host.dispatch(request).await
}

#[utoipa::path(get, path = "/api/v2/research/artifacts/{research_result_fingerprint}/variables/{calculation_fingerprint}/{node_fingerprint}/{output_name}/series", operation_id = "variable_series_api_v2_research_artifacts__research_result_fingerprint__variables__calculation_fingerprint___node_fingerprint___output_name__series_get", tag = "workstation", security(("LocalDeveloperCookie" = [])), params(("research_result_fingerprint" = String, Path),("calculation_fingerprint" = String, Path),("node_fingerprint" = String, Path),("output_name" = String, Path),("instrument_id" = String, Query),("candidate_fingerprint" = Option<String>, Query),("from_ts_event_ns" = Option<String>, Query),("to_ts_event_ns" = Option<String>, Query),("after_ts_event_ns" = Option<String>, Query),("limit" = Option<i64>, Query)), responses((status = 501, body = NativeErrorEnvelope)))]
async fn variable_series_api_v2_research_artifacts_research_result_fingerprint_variables_calculation_fingerprint_node_fingerprint_output_name_series_get(
    State(host): State<Arc<Host>>,
    request: Request<Body>,
) -> Response {
    host.dispatch(request).await
}

#[utoipa::path(get, path = "/api/v2/research/catalog-context/exact/{catalog_generation_fingerprint}", operation_id = "get_complete_exact_catalog_context_v2", tag = "workstation", security(("LocalDeveloperCookie" = [])), params(("catalog_generation_fingerprint" = String, Path)), responses((status = 501, body = NativeErrorEnvelope)))]
async fn get_complete_exact_catalog_context_v2(
    State(host): State<Arc<Host>>,
    request: Request<Body>,
) -> Response {
    host.dispatch(request).await
}

#[utoipa::path(get, path = "/api/v2/research/catalog-context/exact/{catalog_generation_fingerprint}/readiness", operation_id = "get_exact_catalog_readiness_v2", tag = "workstation", security(("LocalDeveloperCookie" = [])), params(("catalog_generation_fingerprint" = String, Path)), responses((status = 501, body = NativeErrorEnvelope)))]
async fn get_exact_catalog_readiness_v2(
    State(host): State<Arc<Host>>,
    request: Request<Body>,
) -> Response {
    host.dispatch(request).await
}

#[utoipa::path(get, path = "/api/v2/research/catalog-context/{catalog_generation_fingerprint}", operation_id = "get_exact_catalog_context_v2", tag = "workstation", security(("LocalDeveloperCookie" = [])), params(("catalog_generation_fingerprint" = String, Path)), responses((status = 501, body = NativeErrorEnvelope)))]
async fn get_exact_catalog_context_v2(
    State(host): State<Arc<Host>>,
    request: Request<Body>,
) -> Response {
    host.dispatch(request).await
}

#[utoipa::path(get, path = "/api/v2/research/catalog/calculations", operation_id = "calculations_api_v2_research_catalog_calculations_get", tag = "workstation", security(("LocalDeveloperCookie" = [])), responses((status = 200, body = ResearchCalculationCatalogDto),(status = 400, body = NativeErrorEnvelope),(status = 401, body = NativeErrorEnvelope),(status = 403, body = NativeErrorEnvelope),(status = 404, body = NativeErrorEnvelope),(status = 409, body = NativeErrorEnvelope),(status = 429, body = NativeErrorEnvelope),(status = 500, body = NativeErrorEnvelope),(status = 503, body = NativeErrorEnvelope)))]
async fn calculations_api_v2_research_catalog_calculations_get(
    State(host): State<Arc<Host>>,
    request: Request<Body>,
) -> Response {
    let response = host.dispatch(request).await;
    verify::<ResearchCalculationCatalogDto>(response).await
}

#[utoipa::path(get, path = "/api/v2/research/catalog/dataset-fields", operation_id = "dataset_fields_api_v2_research_catalog_dataset_fields_get", tag = "workstation", security(("LocalDeveloperCookie" = [])), responses((status = 501, body = NativeErrorEnvelope)))]
async fn dataset_fields_api_v2_research_catalog_dataset_fields_get(
    State(host): State<Arc<Host>>,
    request: Request<Body>,
) -> Response {
    host.dispatch(request).await
}

#[utoipa::path(get, path = "/api/v2/research/catalog/statistics", operation_id = "statistics_api_v2_research_catalog_statistics_get", tag = "workstation", security(("LocalDeveloperCookie" = [])), responses((status = 501, body = NativeErrorEnvelope)))]
async fn statistics_api_v2_research_catalog_statistics_get(
    State(host): State<Arc<Host>>,
    request: Request<Body>,
) -> Response {
    host.dispatch(request).await
}

#[utoipa::path(get, path = "/api/v2/research/catalog/universes", operation_id = "universes_api_v2_research_catalog_universes_get", tag = "workstation", security(("LocalDeveloperCookie" = [])), responses((status = 501, body = NativeErrorEnvelope)))]
async fn universes_api_v2_research_catalog_universes_get(
    State(host): State<Arc<Host>>,
    request: Request<Body>,
) -> Response {
    host.dispatch(request).await
}

#[utoipa::path(get, path = "/api/v2/research/datasets/{snapshot_fingerprint}", operation_id = "get_exact_dataset_snapshot_identity_v2", tag = "workstation", security(("LocalDeveloperCookie" = [])), params(("snapshot_fingerprint" = String, Path)), responses((status = 501, body = NativeErrorEnvelope)))]
async fn get_exact_dataset_snapshot_identity_v2(
    State(host): State<Arc<Host>>,
    request: Request<Body>,
) -> Response {
    host.dispatch(request).await
}

#[utoipa::path(post, path = "/api/v2/research/definitions/resolve", operation_id = "resolve_definition_api_v2_research_definitions_resolve_post", tag = "workstation", security(("LocalDeveloperCookie" = [])), responses((status = 501, body = NativeErrorEnvelope)))]
async fn resolve_definition_api_v2_research_definitions_resolve_post(
    State(host): State<Arc<Host>>,
    request: Request<Body>,
) -> Response {
    host.dispatch(request).await
}

#[utoipa::path(get, path = "/api/v2/research/evaluations/{evaluation_kind}/{evaluation_schema_version}/{evaluation_fingerprint}", operation_id = "get_exact_evaluation_context_identity_v2", tag = "workstation", security(("LocalDeveloperCookie" = [])), params(("evaluation_kind" = String, Path),("evaluation_schema_version" = i64, Path),("evaluation_fingerprint" = String, Path)), responses((status = 501, body = NativeErrorEnvelope)))]
async fn get_exact_evaluation_context_identity_v2(
    State(host): State<Arc<Host>>,
    request: Request<Body>,
) -> Response {
    host.dispatch(request).await
}

#[utoipa::path(get, path = "/api/v2/research/runs", operation_id = "list_runs_api_v2_research_runs_get", tag = "workstation", security(("LocalDeveloperCookie" = [])), params(("limit" = Option<i64>, Query),("cursor" = Option<String>, Query)), responses((status = 501, body = NativeErrorEnvelope)))]
async fn list_runs_api_v2_research_runs_get(
    State(host): State<Arc<Host>>,
    request: Request<Body>,
) -> Response {
    host.dispatch(request).await
}

#[utoipa::path(post, path = "/api/v2/research/runs", operation_id = "submit_run_api_v2_research_runs_post", tag = "workstation", security(("LocalDeveloperCookie" = [])), params(("Idempotency-Key" = Option<String>, Query)), responses((status = 501, body = NativeErrorEnvelope)))]
async fn submit_run_api_v2_research_runs_post(
    State(host): State<Arc<Host>>,
    request: Request<Body>,
) -> Response {
    host.dispatch(request).await
}

#[utoipa::path(post, path = "/api/v2/research/runs/commands", operation_id = "submit_research_run_command_v2", tag = "workstation", security(("LocalDeveloperCookie" = [])), params(("Idempotency-Key" = String, Header)), responses((status = 501, body = NativeErrorEnvelope)))]
async fn submit_research_run_command_v2(
    State(host): State<Arc<Host>>,
    request: Request<Body>,
) -> Response {
    host.dispatch(request).await
}

#[utoipa::path(post, path = "/api/v2/research/runs/private-strategy", operation_id = "submit_private_strategy_research_v2", tag = "workstation", security(("LocalDeveloperCookie" = [])), params(("Idempotency-Key" = String, Header)), responses((status = 501, body = NativeErrorEnvelope)))]
async fn submit_private_strategy_research_v2(
    State(host): State<Arc<Host>>,
    request: Request<Body>,
) -> Response {
    host.dispatch(request).await
}

#[utoipa::path(get, path = "/api/v2/research/runs/{run_id}", operation_id = "get_run_api_v2_research_runs__run_id__get", tag = "workstation", security(("LocalDeveloperCookie" = [])), params(("run_id" = String, Path)), responses((status = 501, body = NativeErrorEnvelope)))]
async fn get_run_api_v2_research_runs_run_id_get(
    State(host): State<Arc<Host>>,
    request: Request<Body>,
) -> Response {
    host.dispatch(request).await
}

#[utoipa::path(post, path = "/api/v2/research/runs/{run_id}/cancellation", operation_id = "cancel_run_api_v2_research_runs__run_id__cancellation_post", tag = "workstation", security(("LocalDeveloperCookie" = [])), params(("run_id" = String, Path),("Idempotency-Key" = Option<String>, Query)), responses((status = 501, body = NativeErrorEnvelope)))]
async fn cancel_run_api_v2_research_runs_run_id_cancellation_post(
    State(host): State<Arc<Host>>,
    request: Request<Body>,
) -> Response {
    host.dispatch(request).await
}

#[utoipa::path(get, path = "/api/v2/research/runs/{run_id}/execution-evidence", operation_id = "get_run_execution_evidence_api_v2_research_runs__run_id__execution_evidence_get", tag = "workstation", security(("LocalDeveloperCookie" = [])), params(("run_id" = String, Path)), responses((status = 501, body = NativeErrorEnvelope)))]
async fn get_run_execution_evidence_api_v2_research_runs_run_id_execution_evidence_get(
    State(host): State<Arc<Host>>,
    request: Request<Body>,
) -> Response {
    host.dispatch(request).await
}

#[utoipa::path(get, path = "/api/v2/research/runtime-generations/active", operation_id = "get_active_runtime_generation_v2", tag = "workstation", security(("LocalDeveloperCookie" = [])), responses((status = 501, body = NativeErrorEnvelope)))]
async fn get_active_runtime_generation_v2(
    State(host): State<Arc<Host>>,
    request: Request<Body>,
) -> Response {
    host.dispatch(request).await
}

#[utoipa::path(get, path = "/api/v2/research/runtime-generations/{runtime_generation_fingerprint}", operation_id = "get_exact_runtime_generation_v2", tag = "workstation", security(("LocalDeveloperCookie" = [])), params(("runtime_generation_fingerprint" = String, Path)), responses((status = 501, body = NativeErrorEnvelope)))]
async fn get_exact_runtime_generation_v2(
    State(host): State<Arc<Host>>,
    request: Request<Body>,
) -> Response {
    host.dispatch(request).await
}

#[utoipa::path(get, path = "/api/v2/research/search/authoring/{reference_kind}/{reference_fingerprint}", operation_id = "get_exact_search_authoring_input_v2", tag = "workstation", security(("LocalDeveloperCookie" = [])), params(("reference_kind" = String, Path),("reference_fingerprint" = String, Path)), responses((status = 501, body = NativeErrorEnvelope)))]
async fn get_exact_search_authoring_input_v2(
    State(host): State<Arc<Host>>,
    request: Request<Body>,
) -> Response {
    host.dispatch(request).await
}

#[utoipa::path(get, path = "/api/v2/research/search/experiments/{experiment_fingerprint}", operation_id = "get_search_experiment_v2", tag = "workstation", security(("LocalDeveloperCookie" = [])), params(("experiment_fingerprint" = String, Path)), responses((status = 501, body = NativeErrorEnvelope)))]
async fn get_search_experiment_v2(
    State(host): State<Arc<Host>>,
    request: Request<Body>,
) -> Response {
    host.dispatch(request).await
}

#[utoipa::path(get, path = "/api/v2/research/search/experiments/{experiment_fingerprint}/ledger", operation_id = "get_search_iteration_ledger_v2", tag = "workstation", security(("LocalDeveloperCookie" = [])), params(("experiment_fingerprint" = String, Path)), responses((status = 501, body = NativeErrorEnvelope)))]
async fn get_search_iteration_ledger_v2(
    State(host): State<Arc<Host>>,
    request: Request<Body>,
) -> Response {
    host.dispatch(request).await
}

#[utoipa::path(get, path = "/api/v2/research/search/experiments/{experiment_fingerprint}/terminal", operation_id = "get_search_terminal_v2", tag = "workstation", security(("LocalDeveloperCookie" = [])), params(("experiment_fingerprint" = String, Path)), responses((status = 501, body = NativeErrorEnvelope)))]
async fn get_search_terminal_v2(State(host): State<Arc<Host>>, request: Request<Body>) -> Response {
    host.dispatch(request).await
}

#[utoipa::path(post, path = "/api/v2/research/search/parameter-experiments", operation_id = "submit_parameter_search_experiment_v2", tag = "workstation", security(("LocalDeveloperCookie" = [])), params(("Idempotency-Key" = String, Header)), responses((status = 501, body = NativeErrorEnvelope)))]
async fn submit_parameter_search_experiment_v2(
    State(host): State<Arc<Host>>,
    request: Request<Body>,
) -> Response {
    host.dispatch(request).await
}

#[utoipa::path(post, path = "/api/v2/research/search/parameter-experiments/advance", operation_id = "advance_parameter_search_experiment_v2", tag = "workstation", security(("LocalDeveloperCookie" = [])), params(("Idempotency-Key" = String, Header)), responses((status = 501, body = NativeErrorEnvelope)))]
async fn advance_parameter_search_experiment_v2(
    State(host): State<Arc<Host>>,
    request: Request<Body>,
) -> Response {
    host.dispatch(request).await
}

#[utoipa::path(post, path = "/api/v2/research/search/symbolic-experiments", operation_id = "submit_symbolic_search_experiment_v2", tag = "workstation", security(("LocalDeveloperCookie" = [])), params(("Idempotency-Key" = String, Header)), responses((status = 501, body = NativeErrorEnvelope)))]
async fn submit_symbolic_search_experiment_v2(
    State(host): State<Arc<Host>>,
    request: Request<Body>,
) -> Response {
    host.dispatch(request).await
}

#[utoipa::path(post, path = "/api/v2/research/search/symbolic-experiments/advance", operation_id = "advance_symbolic_search_experiment_v2", tag = "workstation", security(("LocalDeveloperCookie" = [])), params(("Idempotency-Key" = String, Header)), responses((status = 501, body = NativeErrorEnvelope)))]
async fn advance_symbolic_search_experiment_v2(
    State(host): State<Arc<Host>>,
    request: Request<Body>,
) -> Response {
    host.dispatch(request).await
}

#[utoipa::path(get, path = "/api/v2/research/statistics/{statistics_result_fingerprint}", operation_id = "get_exact_research_statistics_v2", tag = "workstation", security(("LocalDeveloperCookie" = [])), params(("statistics_result_fingerprint" = String, Path)), responses((status = 501, body = NativeErrorEnvelope)))]
async fn get_exact_research_statistics_v2(
    State(host): State<Arc<Host>>,
    request: Request<Body>,
) -> Response {
    host.dispatch(request).await
}

#[utoipa::path(get, path = "/api/v2/strategies/{strategy_fingerprint}", operation_id = "get_strategy_api_v2_strategies__strategy_fingerprint__get", tag = "workstation", security(("LocalDeveloperCookie" = [])), params(("strategy_fingerprint" = String, Path)), responses((status = 501, body = NativeErrorEnvelope)))]
async fn get_strategy_api_v2_strategies_strategy_fingerprint_get(
    State(host): State<Arc<Host>>,
    request: Request<Body>,
) -> Response {
    host.dispatch(request).await
}

#[utoipa::path(post, path = "/api/v2/strategies/{strategy_fingerprint}/promotions", operation_id = "promote_strategy_api_v2_strategies__strategy_fingerprint__promotions_post", tag = "workstation", security(("LocalDeveloperCookie" = [])), params(("strategy_fingerprint" = String, Path),("Idempotency-Key" = String, Header)), responses((status = 501, body = NativeErrorEnvelope)))]
async fn promote_strategy_api_v2_strategies_strategy_fingerprint_promotions_post(
    State(host): State<Arc<Host>>,
    request: Request<Body>,
) -> Response {
    host.dispatch(request).await
}

#[utoipa::path(get, path = "/api/v2/strategies/{strategy_fingerprint}/qualification-decisions", operation_id = "list_qualification_decisions_api_v2_strategies__strategy_fingerprint__qualification_decisions_get", tag = "workstation", security(("LocalDeveloperCookie" = [])), params(("strategy_fingerprint" = String, Path)), responses((status = 501, body = NativeErrorEnvelope)))]
async fn list_qualification_decisions_api_v2_strategies_strategy_fingerprint_qualification_decisions_get(
    State(host): State<Arc<Host>>,
    request: Request<Body>,
) -> Response {
    host.dispatch(request).await
}

#[utoipa::path(post, path = "/api/v2/strategies/{strategy_fingerprint}/qualification-promotions", operation_id = "promote_qualified_strategy_api_v2_strategies__strategy_fingerprint__qualification_promotions_post", tag = "workstation", security(("LocalDeveloperCookie" = [])), params(("strategy_fingerprint" = String, Path),("Idempotency-Key" = String, Header)), responses((status = 501, body = NativeErrorEnvelope)))]
async fn promote_qualified_strategy_api_v2_strategies_strategy_fingerprint_qualification_promotions_post(
    State(host): State<Arc<Host>>,
    request: Request<Body>,
) -> Response {
    host.dispatch(request).await
}

#[utoipa::path(post, path = "/api/v2/strategies/{strategy_fingerprint}/qualifications", operation_id = "evaluate_qualification_api_v2_strategies__strategy_fingerprint__qualifications_post", tag = "workstation", security(("LocalDeveloperCookie" = [])), params(("strategy_fingerprint" = String, Path),("Idempotency-Key" = String, Header)), responses((status = 501, body = NativeErrorEnvelope)))]
async fn evaluate_qualification_api_v2_strategies_strategy_fingerprint_qualifications_post(
    State(host): State<Arc<Host>>,
    request: Request<Body>,
) -> Response {
    host.dispatch(request).await
}

#[utoipa::path(post, path = "/api/v2/strategy-freezes", operation_id = "freeze_strategy_api_v2_strategy_freezes_post", tag = "workstation", security(("LocalDeveloperCookie" = [])), params(("Idempotency-Key" = String, Header)), responses((status = 501, body = NativeErrorEnvelope)))]
async fn freeze_strategy_api_v2_strategy_freezes_post(
    State(host): State<Arc<Host>>,
    request: Request<Body>,
) -> Response {
    host.dispatch(request).await
}

#[utoipa::path(get, path = "/api/v2/watchlists", operation_id = "read_api_v2_watchlists_get", tag = "workstation", security(("LocalDeveloperCookie" = [])), responses((status = 200, body = WatchlistBookDto),(status = 400, body = NativeErrorEnvelope),(status = 401, body = NativeErrorEnvelope),(status = 403, body = NativeErrorEnvelope),(status = 404, body = NativeErrorEnvelope),(status = 409, body = NativeErrorEnvelope),(status = 429, body = NativeErrorEnvelope),(status = 500, body = NativeErrorEnvelope),(status = 503, body = NativeErrorEnvelope)))]
async fn read_api_v2_watchlists_get(
    State(host): State<Arc<Host>>,
    request: Request<Body>,
) -> Response {
    let response = host.dispatch(request).await;
    verify::<WatchlistBookDto>(response).await
}

#[utoipa::path(put, path = "/api/v2/watchlists", operation_id = "save_api_v2_watchlists_put", tag = "workstation", security(("LocalDeveloperCookie" = [])), request_body = SaveWatchlistsDto, responses((status = 200, body = WatchlistBookDto),(status = 400, body = NativeErrorEnvelope),(status = 401, body = NativeErrorEnvelope),(status = 403, body = NativeErrorEnvelope),(status = 404, body = NativeErrorEnvelope),(status = 409, body = NativeErrorEnvelope),(status = 429, body = NativeErrorEnvelope),(status = 500, body = NativeErrorEnvelope),(status = 503, body = NativeErrorEnvelope)))]
async fn save_api_v2_watchlists_put(
    State(host): State<Arc<Host>>,
    request: Request<Body>,
) -> Response {
    let response = host.dispatch(request).await;
    verify::<WatchlistBookDto>(response).await
}

#[utoipa::path(get, path = "/api/v2/watchlists/commands/{command_id}", operation_id = "command_api_v2_watchlists_commands__command_id__get", tag = "workstation", security(("LocalDeveloperCookie" = [])), params(("command_id" = String, Path)), responses((status = 200, body = WatchlistBookDto),(status = 400, body = NativeErrorEnvelope),(status = 401, body = NativeErrorEnvelope),(status = 403, body = NativeErrorEnvelope),(status = 404, body = NativeErrorEnvelope),(status = 409, body = NativeErrorEnvelope),(status = 429, body = NativeErrorEnvelope),(status = 500, body = NativeErrorEnvelope),(status = 503, body = NativeErrorEnvelope)))]
async fn command_api_v2_watchlists_commands_command_id_get(
    State(host): State<Arc<Host>>,
    request: Request<Body>,
) -> Response {
    let response = host.dispatch(request).await;
    verify::<WatchlistBookDto>(response).await
}

#[utoipa::path(get, path = "/api/v2/workspace", operation_id = "read_api_v2_workspace_get", tag = "workstation", security(("LocalDeveloperCookie" = [])), responses((status = 200, body = WorkspaceBookDto),(status = 400, body = NativeErrorEnvelope),(status = 401, body = NativeErrorEnvelope),(status = 403, body = NativeErrorEnvelope),(status = 404, body = NativeErrorEnvelope),(status = 409, body = NativeErrorEnvelope),(status = 429, body = NativeErrorEnvelope),(status = 500, body = NativeErrorEnvelope),(status = 503, body = NativeErrorEnvelope)))]
async fn read_api_v2_workspace_get(
    State(host): State<Arc<Host>>,
    request: Request<Body>,
) -> Response {
    let response = host.dispatch(request).await;
    verify::<WorkspaceBookDto>(response).await
}

#[utoipa::path(put, path = "/api/v2/workspace", operation_id = "save_api_v2_workspace_put", tag = "workstation", security(("LocalDeveloperCookie" = [])), request_body = SaveWorkspaceDto, responses((status = 200, body = WorkspaceBookDto),(status = 400, body = NativeErrorEnvelope),(status = 401, body = NativeErrorEnvelope),(status = 403, body = NativeErrorEnvelope),(status = 404, body = NativeErrorEnvelope),(status = 409, body = NativeErrorEnvelope),(status = 429, body = NativeErrorEnvelope),(status = 500, body = NativeErrorEnvelope),(status = 503, body = NativeErrorEnvelope)))]
async fn save_api_v2_workspace_put(
    State(host): State<Arc<Host>>,
    request: Request<Body>,
) -> Response {
    let response = host.dispatch(request).await;
    verify::<WorkspaceBookDto>(response).await
}

#[utoipa::path(get, path = "/api/v2/workspace/commands/{command_id}", operation_id = "command_api_v2_workspace_commands__command_id__get", tag = "workstation", security(("LocalDeveloperCookie" = [])), params(("command_id" = String, Path)), responses((status = 200, body = WorkspaceBookDto),(status = 400, body = NativeErrorEnvelope),(status = 401, body = NativeErrorEnvelope),(status = 403, body = NativeErrorEnvelope),(status = 404, body = NativeErrorEnvelope),(status = 409, body = NativeErrorEnvelope),(status = 429, body = NativeErrorEnvelope),(status = 500, body = NativeErrorEnvelope),(status = 503, body = NativeErrorEnvelope)))]
async fn command_api_v2_workspace_commands_command_id_get(
    State(host): State<Arc<Host>>,
    request: Request<Body>,
) -> Response {
    let response = host.dispatch(request).await;
    verify::<WorkspaceBookDto>(response).await
}

#[utoipa::path(get, path = "/health/execution", operation_id = "execution_health_execution_get", tag = "workstation", security(("LocalDeveloperCookie" = [])), responses((status = 501, body = NativeErrorEnvelope)))]
async fn execution_health_execution_get(
    State(host): State<Arc<Host>>,
    request: Request<Body>,
) -> Response {
    host.dispatch(request).await
}

#[utoipa::path(get, path = "/health/live", operation_id = "live_health_live_get", tag = "workstation", security(("LocalDeveloperCookie" = [])), responses((status = 200, body = NativeHealthDto),(status = 503, body = NativeErrorEnvelope)))]
async fn live_health_live_get(State(host): State<Arc<Host>>, request: Request<Body>) -> Response {
    host.dispatch(request).await
}

#[utoipa::path(get, path = "/health/ready", operation_id = "ready_health_ready_get", tag = "workstation", security(("LocalDeveloperCookie" = [])), responses((status = 200, body = NativeHealthDto),(status = 503, body = NativeErrorEnvelope)))]
async fn ready_health_ready_get(State(host): State<Arc<Host>>, request: Request<Body>) -> Response {
    host.dispatch(request).await
}

#[utoipa::path(get,path="/api/v2/market-data/stream",operation_id="market_data_stream_upgrade",tag="workstation",security(("LocalDeveloperCookie"=[])),responses((status=101,description="Authenticated native WebSocket; its versioned message schema is separate"),(status=400,body=NativeErrorEnvelope),(status=401,body=NativeErrorEnvelope),(status=403,body=NativeErrorEnvelope)))]
async fn market_data_stream_upgrade(
    State(host): State<Arc<Host>>,
    request: Request<Body>,
) -> Response {
    host.dispatch(request).await
}

#[utoipa::path(get,path="/api/v2/chart/market-data/stream",operation_id="temporary_market_data_stream_upgrade",tag="workstation",security(("LocalDeveloperCookie"=[])),responses((status=101,description="Volatile chart WebSocket; explicit temporary input contract"),(status=400,body=NativeErrorEnvelope),(status=401,body=NativeErrorEnvelope),(status=403,body=NativeErrorEnvelope)))]
async fn temporary_market_data_stream_upgrade(
    State(host): State<Arc<Host>>,
    request: Request<Body>,
) -> Response {
    host.dispatch(request).await
}

#[utoipa::path(post,path="/api/v2/chart/temporary-studies/evaluate",operation_id="temporary_chart_studies_evaluate",tag="workstation",security(("LocalDeveloperCookie"=[])),request_body=TemporaryChartStudyEvaluateRequestDto,responses((status=200,body=TemporaryChartStudyEvaluateDto),(status=400,body=NativeErrorEnvelope),(status=401,body=NativeErrorEnvelope),(status=403,body=NativeErrorEnvelope),(status=404,body=NativeErrorEnvelope),(status=409,body=NativeErrorEnvelope),(status=429,body=NativeErrorEnvelope),(status=503,body=NativeErrorEnvelope)))]
async fn temporary_chart_studies_evaluate(
    State(host): State<Arc<Host>>,
    request: Request<Body>,
) -> Response {
    verify::<TemporaryChartStudyEvaluateDto>(host.dispatch(request).await).await
}

#[utoipa::path(post,path="/api/v2/chart/temporary-studies/evaluate-batch",operation_id="temporary_chart_studies_evaluate_batch",tag="workstation",security(("LocalDeveloperCookie"=[])),request_body=TemporaryChartStudyBatchRequestDto,responses((status=200,body=TemporaryChartStudyBatchDto),(status=400,body=NativeErrorEnvelope),(status=401,body=NativeErrorEnvelope),(status=403,body=NativeErrorEnvelope),(status=404,body=NativeErrorEnvelope),(status=409,body=NativeErrorEnvelope),(status=429,body=NativeErrorEnvelope),(status=503,body=NativeErrorEnvelope)))]
async fn temporary_chart_studies_evaluate_batch(
    State(host): State<Arc<Host>>,
    request: Request<Body>,
) -> Response {
    verify::<TemporaryChartStudyBatchDto>(host.dispatch(request).await).await
}

#[cfg(test)]
mod policy_tests {
    use super::*;
    #[test]
    fn bounded_temporary_batch_is_a_formal_authenticated_query() {
        let (_, document) = declaration();
        let value = serde_json::to_value(document).unwrap();
        let operation = &value["paths"]["/api/v2/chart/temporary-studies/evaluate-batch"]["post"];
        assert_eq!(
            operation["operationId"],
            "temporary_chart_studies_evaluate_batch"
        );
        assert_eq!(
            operation["security"],
            serde_json::json!([{"LocalDeveloperCookie":[]}])
        );
        assert!(operation["responses"].get("409").is_some());
        assert!(operation["responses"].get("503").is_some());
    }
    #[test]
    fn temporary_market_data_is_a_distinct_typed_read_without_durable_proof_fields() {
        assert_eq!(
            operation(&Method::GET, "/api/v2/chart/market-data/stream"),
            Some(Operation::Implemented)
        );
        assert_eq!(
            operation(&Method::POST, "/api/v2/chart/market-data/stream"),
            None
        );
        let stream = crate::transport::stream_wire::document();
        assert!(stream["message_roots"]["temporary_subscribe"].is_string());
        assert!(stream["message_roots"]["temporary_event"].is_string());
        assert_eq!(
            operation(&Method::POST, "/api/v2/chart/temporary-studies/evaluate"),
            Some(Operation::Implemented)
        );
        assert_eq!(
            operation(&Method::GET, "/api/v2/chart/temporary-studies/evaluate"),
            None
        );
        let path = "/api/v2/chart/market-data/bars";
        assert_eq!(operation(&Method::GET, path), Some(Operation::Implemented));
        assert_eq!(operation(&Method::POST, path), None);
        let (_, document) = declaration();
        let value = serde_json::to_value(document).unwrap();
        assert_eq!(
            value["paths"][path]["get"]["responses"]["200"]["content"]["application/json"]["schema"]
                ["$ref"],
            "#/components/schemas/TemporaryMarketDataWindowDto"
        );
        let properties =
            value["components"]["schemas"]["TemporaryMarketDataWindowDto"]["properties"]
                .as_object()
                .unwrap();
        assert!(properties.contains_key("source_kind"));
        assert!(properties.contains_key("window_fingerprint"));
        for key in [
            "revision_evidence",
            "seal_id",
            "history_projection_fingerprint",
        ] {
            assert!(!properties.contains_key(key));
        }
    }
    #[test]
    fn implemented_creation_routes_declare_their_success_bodies() {
        let (_, document) = declaration();
        let value = serde_json::to_value(document).expect("OpenAPI document");
        for (path, expected) in [
            ("/api/v2/integrations", "IntegrationCommandResponseDto"),
            (
                "/api/v2/market-data/acquisitions",
                "MarketDataAcquisitionDto",
            ),
        ] {
            assert_eq!(
                value["paths"][path]["post"]["responses"]["200"]["content"]["application/json"]["schema"]
                    ["$ref"],
                format!("#/components/schemas/{expected}"),
                "successful creation must not be validated as an error: {path}",
            );
        }
    }
    #[test]
    fn actual_declarations_drive_deferred_and_denied_admission() {
        assert_eq!(
            operation(
                &Method::GET,
                "/api/v2/private-assets/strategies/id/revisions/pin"
            ),
            Some(Operation::Deferred)
        );
        assert_eq!(
            operation(&Method::POST, "/api/v2/agent/sessions"),
            Some(Operation::Denied)
        );
        assert_eq!(
            operation(&Method::GET, "/api/v2/private-assets"),
            Some(Operation::Implemented)
        );
        assert_eq!(operation(&Method::GET, "/api/v2/no-such-route"), None);
    }
}

#[cfg(test)]
mod default_workspace_tests {
    use super::*;
    #[test]
    fn default_workspace_routes_are_formal_owner_commands_and_queries() {
        for (method, path) in [
            (Method::GET, "/api/v2/workspace"),
            (Method::PUT, "/api/v2/workspace"),
            (
                Method::GET,
                "/api/v2/workspace/commands/00000000-0000-4000-8000-000000000001",
            ),
        ] {
            assert_eq!(operation(&method, path), Some(Operation::Implemented));
        }
        assert_eq!(operation(&Method::POST, "/api/v2/workspace"), None);
    }
}

#[utoipa::path(get, path = "/api/v2/private-assets/factors", operation_id = "private_factor_authoring_inventory", tag = "private-factor-authoring", security(("LocalDeveloperCookie" = [])), responses((status = 200, body = PrivateFactorAuthoringInventoryDto),(status = 400, body = NativeErrorEnvelope),(status = 401, body = NativeErrorEnvelope),(status = 403, body = NativeErrorEnvelope),(status = 404, body = NativeErrorEnvelope),(status = 409, body = NativeErrorEnvelope),(status = 503, body = NativeErrorEnvelope)))]
async fn private_factor_authoring_inventory(
    State(host): State<Arc<Host>>,
    request: Request<Body>,
) -> Response {
    verify::<PrivateFactorAuthoringInventoryDto>(host.dispatch(request).await).await
}

#[utoipa::path(get, path = "/api/v2/private-assets/factors/{factor_id}", operation_id = "private_factor_authoring_state", tag = "private-factor-authoring", security(("LocalDeveloperCookie" = [])), params(("factor_id" = String, Path)), responses((status = 200, body = PrivateFactorAuthoringStateDto),(status = 400, body = NativeErrorEnvelope),(status = 401, body = NativeErrorEnvelope),(status = 403, body = NativeErrorEnvelope),(status = 404, body = NativeErrorEnvelope),(status = 409, body = NativeErrorEnvelope),(status = 503, body = NativeErrorEnvelope)))]
async fn private_factor_authoring_state(
    State(host): State<Arc<Host>>,
    request: Request<Body>,
) -> Response {
    verify::<PrivateFactorAuthoringStateDto>(host.dispatch(request).await).await
}

#[utoipa::path(put, path = "/api/v2/private-assets/factors/{factor_id}/display", operation_id = "private_factor_display_update", tag = "private-factor-authoring", security(("LocalDeveloperCookie" = [])), params(("factor_id" = String, Path),("Idempotency-Key" = String, Header)), request_body = UpdatePrivateFactorDisplayDto, responses((status = 200, body = PrivateFactorAuthoringReceiptDto),(status = 400, body = NativeErrorEnvelope),(status = 401, body = NativeErrorEnvelope),(status = 403, body = NativeErrorEnvelope),(status = 404, body = NativeErrorEnvelope),(status = 409, body = NativeErrorEnvelope),(status = 503, body = NativeErrorEnvelope)))]
async fn private_factor_display_update(
    State(host): State<Arc<Host>>,
    request: Request<Body>,
) -> Response {
    verify::<PrivateFactorAuthoringReceiptDto>(host.dispatch(request).await).await
}

#[utoipa::path(put, path = "/api/v2/private-assets/factors/{factor_id}/draft", operation_id = "private_factor_draft_save", tag = "private-factor-authoring", security(("LocalDeveloperCookie" = [])), params(("factor_id" = String, Path),("Idempotency-Key" = String, Header)), request_body = SavePrivateFactorDraftDto, responses((status = 200, body = PrivateFactorAuthoringReceiptDto),(status = 400, body = NativeErrorEnvelope),(status = 401, body = NativeErrorEnvelope),(status = 403, body = NativeErrorEnvelope),(status = 404, body = NativeErrorEnvelope),(status = 409, body = NativeErrorEnvelope),(status = 503, body = NativeErrorEnvelope)))]
async fn private_factor_draft_save(
    State(host): State<Arc<Host>>,
    request: Request<Body>,
) -> Response {
    verify::<PrivateFactorAuthoringReceiptDto>(host.dispatch(request).await).await
}

#[utoipa::path(post, path = "/api/v2/private-assets/factors/{factor_id}/revisions", operation_id = "private_factor_revision_publish", tag = "private-factor-authoring", security(("LocalDeveloperCookie" = [])), params(("factor_id" = String, Path),("Idempotency-Key" = String, Header)), request_body = PublishPrivateFactorRevisionDto, responses((status = 200, body = PrivateFactorAuthoringReceiptDto),(status = 400, body = NativeErrorEnvelope),(status = 401, body = NativeErrorEnvelope),(status = 403, body = NativeErrorEnvelope),(status = 404, body = NativeErrorEnvelope),(status = 409, body = NativeErrorEnvelope),(status = 503, body = NativeErrorEnvelope)))]
async fn private_factor_revision_publish(
    State(host): State<Arc<Host>>,
    request: Request<Body>,
) -> Response {
    verify::<PrivateFactorAuthoringReceiptDto>(host.dispatch(request).await).await
}

#[utoipa::path(get, path = "/api/v2/private-assets/factors/{factor_id}/commands/{command_id}", operation_id = "private_factor_authoring_command", tag = "private-factor-authoring", security(("LocalDeveloperCookie" = [])), params(("factor_id" = String, Path),("command_id" = String, Path)), responses((status = 200, body = Option<PrivateFactorAuthoringReceiptDto>),(status = 400, body = NativeErrorEnvelope),(status = 401, body = NativeErrorEnvelope),(status = 403, body = NativeErrorEnvelope),(status = 404, body = NativeErrorEnvelope),(status = 409, body = NativeErrorEnvelope),(status = 503, body = NativeErrorEnvelope)))]
async fn private_factor_authoring_command(
    State(host): State<Arc<Host>>,
    request: Request<Body>,
) -> Response {
    verify::<Option<PrivateFactorAuthoringReceiptDto>>(host.dispatch(request).await).await
}

#[utoipa::path(post,path="/api/v2/factor-proposal-grants",security(("LocalDeveloperCookie"=[])),params(("Idempotency-Key"=String,Header)),request_body=crate::application::factor_proposals::GrantInput,responses((status=200,body=crate::application::factor_proposals::Operation),(status=400,body=NativeErrorEnvelope),(status=401,body=NativeErrorEnvelope),(status=403,body=NativeErrorEnvelope),(status=404,body=NativeErrorEnvelope),(status=409,body=NativeErrorEnvelope),(status=429,body=NativeErrorEnvelope),(status=500,body=NativeErrorEnvelope),(status=503,body=NativeErrorEnvelope)))]
async fn proposal_grant(State(host): State<Arc<Host>>, request: Request<Body>) -> Response {
    verify::<crate::application::factor_proposals::Operation>(host.dispatch(request).await).await
}

#[utoipa::path(post,path="/api/v2/factor-proposal-grants/revocations",security(("LocalDeveloperCookie"=[])),params(("Idempotency-Key"=String,Header)),request_body=crate::application::factor_proposals::RevokeInput,responses((status=200,body=crate::application::factor_proposals::Operation),(status=400,body=NativeErrorEnvelope),(status=401,body=NativeErrorEnvelope),(status=403,body=NativeErrorEnvelope),(status=404,body=NativeErrorEnvelope),(status=409,body=NativeErrorEnvelope),(status=429,body=NativeErrorEnvelope),(status=500,body=NativeErrorEnvelope),(status=503,body=NativeErrorEnvelope)))]
async fn proposal_revoke(State(host): State<Arc<Host>>, request: Request<Body>) -> Response {
    verify::<crate::application::factor_proposals::Operation>(host.dispatch(request).await).await
}

#[utoipa::path(post,path="/api/v2/factor-proposals",security(("AgentProposalBearer"=[])),params(("Idempotency-Key"=String,Header)),request_body=crate::application::factor_proposals::StageInput,responses((status=200,body=crate::application::factor_proposals::Operation),(status=400,body=NativeErrorEnvelope),(status=401,body=NativeErrorEnvelope),(status=403,body=NativeErrorEnvelope),(status=404,body=NativeErrorEnvelope),(status=409,body=NativeErrorEnvelope),(status=429,body=NativeErrorEnvelope),(status=500,body=NativeErrorEnvelope),(status=503,body=NativeErrorEnvelope)))]
async fn proposal_stage(State(host): State<Arc<Host>>, request: Request<Body>) -> Response {
    verify::<crate::application::factor_proposals::Operation>(host.dispatch(request).await).await
}

#[utoipa::path(get,path="/api/v2/factor-proposal-context/{session_id}",security(("AgentProposalBearer"=[])),params(("session_id"=String,Path)),responses((status=200,body=crate::application::factor_proposals::Context),(status=400,body=NativeErrorEnvelope),(status=401,body=NativeErrorEnvelope),(status=403,body=NativeErrorEnvelope),(status=404,body=NativeErrorEnvelope),(status=409,body=NativeErrorEnvelope),(status=429,body=NativeErrorEnvelope),(status=500,body=NativeErrorEnvelope),(status=503,body=NativeErrorEnvelope)))]
async fn proposal_context(State(host): State<Arc<Host>>, request: Request<Body>) -> Response {
    verify::<crate::application::factor_proposals::Context>(host.dispatch(request).await).await
}

#[utoipa::path(get,path="/api/v2/factor-proposals/{fingerprint}",security(("LocalDeveloperCookie"=[]),("AgentProposalBearer"=[])),params(("fingerprint"=String,Path)),responses((status=200,body=crate::application::factor_proposals::ProposalView),(status=400,body=NativeErrorEnvelope),(status=401,body=NativeErrorEnvelope),(status=403,body=NativeErrorEnvelope),(status=404,body=NativeErrorEnvelope),(status=409,body=NativeErrorEnvelope),(status=429,body=NativeErrorEnvelope),(status=500,body=NativeErrorEnvelope),(status=503,body=NativeErrorEnvelope)))]
async fn proposal_read(State(host): State<Arc<Host>>, request: Request<Body>) -> Response {
    verify::<crate::application::factor_proposals::ProposalView>(host.dispatch(request).await).await
}

#[utoipa::path(post,path="/api/v2/factor-proposals/{fingerprint}/confirmation",security(("LocalDeveloperCookie"=[])),params(("fingerprint"=String,Path),("Idempotency-Key"=String,Header)),request_body=crate::application::factor_proposals::ConfirmInput,responses((status=200,body=crate::application::factor_proposals::Operation),(status=400,body=NativeErrorEnvelope),(status=401,body=NativeErrorEnvelope),(status=403,body=NativeErrorEnvelope),(status=404,body=NativeErrorEnvelope),(status=409,body=NativeErrorEnvelope),(status=429,body=NativeErrorEnvelope),(status=500,body=NativeErrorEnvelope),(status=503,body=NativeErrorEnvelope)))]
async fn proposal_confirm(State(host): State<Arc<Host>>, request: Request<Body>) -> Response {
    verify::<crate::application::factor_proposals::Operation>(host.dispatch(request).await).await
}

#[utoipa::path(get,path="/api/v2/factor-proposals/commands/{command_id}",security(("LocalDeveloperCookie"=[]),("AgentProposalBearer"=[])),params(("command_id"=String,Path)),responses((status=200,body=crate::application::factor_proposals::Operation),(status=400,body=NativeErrorEnvelope),(status=401,body=NativeErrorEnvelope),(status=403,body=NativeErrorEnvelope),(status=404,body=NativeErrorEnvelope),(status=409,body=NativeErrorEnvelope),(status=429,body=NativeErrorEnvelope),(status=500,body=NativeErrorEnvelope),(status=503,body=NativeErrorEnvelope)))]
async fn proposal_observe(State(host): State<Arc<Host>>, request: Request<Body>) -> Response {
    verify::<crate::application::factor_proposals::Operation>(host.dispatch(request).await).await
}

#[utoipa::path(post,path="/api/v2/agent-browser-access",security(("LocalDeveloperCookie"=[])),responses((status=200,body=crate::security::agent_browser::AccessView),(status=401,body=NativeErrorEnvelope),(status=403,body=NativeErrorEnvelope),(status=503,body=NativeErrorEnvelope)))]
async fn agent_browser_access(State(host): State<Arc<Host>>, request: Request<Body>) -> Response {
    verify::<crate::security::agent_browser::AccessView>(host.dispatch(request).await).await
}
#[utoipa::path(get,path="/api/v2/agent-connection",security(("LocalDeveloperCookie"=[])),responses((status=200,body=crate::security::agent_browser::ConnectionView),(status=401,body=NativeErrorEnvelope),(status=403,body=NativeErrorEnvelope),(status=503,body=NativeErrorEnvelope)))]
async fn agent_connection(State(host): State<Arc<Host>>, request: Request<Body>) -> Response {
    verify::<crate::security::agent_browser::ConnectionView>(host.dispatch(request).await).await
}

#[utoipa::path(post,path="/api/v2/factor-proposals/{fingerprint}/withdrawal",security(("LocalDeveloperCookie"=[])),params(("fingerprint"=String,Path),("Idempotency-Key"=String,Header)),request_body=crate::application::factor_proposals::ConfirmInput,responses((status=200,body=crate::application::factor_proposals::Operation),(status=400,body=NativeErrorEnvelope),(status=401,body=NativeErrorEnvelope),(status=403,body=NativeErrorEnvelope),(status=404,body=NativeErrorEnvelope),(status=409,body=NativeErrorEnvelope),(status=503,body=NativeErrorEnvelope)))]
async fn proposal_withdraw(State(host): State<Arc<Host>>, request: Request<Body>) -> Response {
    verify::<crate::application::factor_proposals::Operation>(host.dispatch(request).await).await
}
