//! Technical cold worker fixture: actual startup Infrastructure, no background scan.
use super::*;
pub(crate) async fn open(
    config: &Configuration,
    namespace: &crate::bootstrap::deployment::SemanticStoreId,
) -> Result<
    (
        ResearchConnection,
        crate::workers::research::SharedAuthority,
    ),
    Failure,
> {
    let database = Database::from(config);
    let inputs = StorageInputs::load(
        StorageRoots::open(&config.user_data).map_err(|e| Failure::unavailable(e.code()))?,
        &config.schema,
        WORK,
    )
    .map_err(|e| Failure::unavailable(e.code()))?;
    if inputs.namespace() != namespace {
        return Err(Failure::unavailable("RESEARCH_SEMANTIC_STORE_MISMATCH"));
    }
    let mut socket = connect(&database, false).await?;
    let live = socket.alive.clone();
    let mut writer =
        AuthoritySession::acquire(socket.client.take().unwrap(), socket.driver.take().unwrap())
            .await
            .map_err(|e| Failure::unavailable(e.code()))?;
    inputs
        .verify(
            writer
                .client_mut()
                .await
                .map_err(|e| Failure::unavailable(e.code()))?,
            ROWS,
        )
        .await
        .map_err(|e| Failure::unavailable(e.code()))?;
    writer
        .verify()
        .await
        .map_err(|e| Failure::unavailable(e.code()))?;
    if crate::bootstrap::research_namespace::open_manual_backtest_existing(&config.user_data)
        .map_err(Failure::unavailable)?
        != *namespace
    {
        return Err(Failure::unavailable("RESEARCH_SEMANTIC_STORE_MISMATCH"));
    }
    crate::persistence::research_runtime::Registry::open_existing(
        &config.user_data.join("runtime"),
    )
    .map_err(Failure::unavailable)?;
    let pid = writer
        .client_mut()
        .await
        .map_err(|e| Failure::unavailable(e.code()))?
        .query_one("SELECT pg_catalog.pg_backend_pid()", &[])
        .await
        .map_err(|_| Failure::unavailable("POSTGRES_UNAVAILABLE"))?
        .get(0);
    println!("BACKTEST_OWNER_PID {pid}");
    let connection = database.research_connection(namespace, pid, live).await?;
    Ok((connection, Arc::new(Mutex::new(Some(writer)))))
}
