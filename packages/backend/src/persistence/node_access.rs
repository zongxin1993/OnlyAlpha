//! Read-only admission of the actual Node LOGIN. No role creation or grants.
use tokio_postgres::Client;
const POLICY: &str = include_str!("node_access.sql");
const UNAVAILABLE: &str = "NODE_DATABASE_POLICY_UNAVAILABLE";

pub(crate) async fn verify(client: &Client, configured: &str) -> Result<(), &'static str> {
    tokio::time::timeout(std::time::Duration::from_secs(5), async {
        let identity = client.query_one("SELECT session_user::pg_catalog.text,current_user::pg_catalog.text,(pg_catalog.current_schemas(true))[1]::pg_catalog.text", &[]).await.map_err(|_| UNAVAILABLE)?;
        let login: String = identity.try_get(0).map_err(|_| UNAVAILABLE)?;
        if login != configured || identity.try_get::<_,String>(1).map_err(|_| UNAVAILABLE)? != login
            || identity.try_get::<_,String>(2).map_err(|_| UNAVAILABLE)? != "pg_catalog" {
            return Err("NODE_ROLE_IDENTITY_REFUSED");
        }
        let row = client.query_one(POLICY, &[&login]).await.map_err(|_| UNAVAILABLE)?;
        match row.try_get::<_,String>(0).map_err(|_| UNAVAILABLE)?.as_str() {
            "OK" => Ok(()),
            "NODE_CAPABILITY_ROLE_REFUSED" => Err("NODE_CAPABILITY_ROLE_REFUSED"),
            "NODE_ROLE_IDENTITY_REFUSED" => Err("NODE_ROLE_IDENTITY_REFUSED"),
            "NODE_ROLE_MEMBERSHIP_REFUSED" => Err("NODE_ROLE_MEMBERSHIP_REFUSED"),
            "NODE_ROLE_CONFIGURATION_REFUSED" => Err("NODE_ROLE_CONFIGURATION_REFUSED"),
            "NODE_ROLE_DIRECT_AUTHORITY_REFUSED" => Err("NODE_ROLE_DIRECT_AUTHORITY_REFUSED"),
            "NODE_CAPABILITY_PERMISSION_REFUSED" => Err("NODE_CAPABILITY_PERMISSION_REFUSED"),
            _ => Err(UNAVAILABLE),
        }
    }).await.map_err(|_| UNAVAILABLE)?
}
