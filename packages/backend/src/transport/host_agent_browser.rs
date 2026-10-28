//! Human session exchange and proposal-connection discovery, not Agent orchestration.
use crate::{
    persistence::factor_proposals::Proposals,
    security::{
        agent_browser::ConnectionView,
        human_access,
        ingress::{self, Release},
    },
    transport::host::{Failure, Host, now},
};
use axum::{
    Json,
    body::Body,
    response::{IntoResponse, Response},
};
use http::Request;
impl Host {
    pub(crate) async fn agent_browser(
        &self,
        request: Request<Body>,
        human: human_access::Session,
    ) -> Result<Response, Failure> {
        let issuer = self
            .agent_browser
            .as_ref()
            .ok_or(Failure::unavailable("AGENT_BROWSER_NOT_CONFIGURED"))?;
        let owner = human.subject_id()?;
        let response = if request.uri().path() == "/api/v2/agent-browser-access" {
            let at = std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .map_err(|_| Failure::unavailable("CLOCK_UNAVAILABLE"))?
                .as_secs();
            Json(issuer.access(owner, at).map_err(Failure::unavailable)?).into_response()
        } else {
            let mut writer = self.writer.lock().await;
            let client = writer
                .as_mut()
                .ok_or(Failure::unavailable("PRODUCT_AUTHORITY_UNAVAILABLE"))?
                .client_mut()
                .await
                .map_err(|_| Failure::unavailable("PRODUCT_AUTHORITY_UNAVAILABLE"))?;
            let grant_state = Proposals::new(client)
                .grant_state(&issuer.connection, owner, &now()?.to_string())
                .await
                .map_err(Failure::unavailable)?;
            // Serialize only public connection metadata. The assertion key never has a JSON representation.
            let connection = issuer.connection.clone();
            Json(ConnectionView {
                schema_version: 1,
                connection,
                grant_state,
            })
            .into_response()
        };
        let mut response = ingress::attach(response, Release::Generation(human.metadata_session()));
        response
            .headers_mut()
            .insert("cache-control", http::HeaderValue::from_static("no-store"));
        Ok(response)
    }
}
