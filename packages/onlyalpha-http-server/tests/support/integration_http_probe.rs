#[path = "http.rs"]
mod http_support;
// Technical native HTTP/PG probe, never a business acceptance entry.
use axum::body::{Body, to_bytes};
use http::Request;
use hyper_util::rt::TokioIo;
use onlyalpha_http_server::{human_access::Access, ingress::LocalIngress, integrations};
use serde_json::{Value, json};
use std::{
    error::Error,
    io::{self, BufRead, Read, Write},
    time::Duration,
};
use tokio::net::{TcpListener, TcpStream};
fn main() -> Result<(), Box<dyn Error>> {
    let runtime = tokio::runtime::Builder::new_current_thread()
        .enable_all()
        .build()?;
    runtime.block_on(run())
}
async fn run() -> Result<(), Box<dyn Error>> {
    let mut raw = String::new();
    io::stdin().lock().take(131073).read_line(&mut raw)?;
    if raw.len() > 131072 {
        return Err("frame too large".into());
    }
    let input: Value = serde_json::from_str(&raw)?;
    if input["op"] == "web-assets" {
        println!("{}", web_assets_probe(&input).await?);
        return Ok(());
    }

    let mut config: tokio_postgres::Config = std::env::var("ONLYALPHA_POSTGRES_DSN")?.parse()?;
    if !config.get_dbname().is_some_and(|s| s.ends_with("_test")) {
        return Err("test database required".into());
    }
    config
        .connect_timeout(Duration::from_secs(5))
        .ssl_mode(tokio_postgres::config::SslMode::Disable)
        .options("-c timezone=UTC -c statement_timeout=5000ms -c lock_timeout=2000ms");
    let (client, connection) = config.connect(tokio_postgres::NoTls).await?;
    let (physical_closed, driver_stopped, driver) = if input["action"] == "cancel-close" {
        let (closed_tx, closed_rx) = tokio::sync::oneshot::channel();
        let (stopped_tx, stopped_rx) = tokio::sync::oneshot::channel();
        let driver = tokio::spawn(async move {
            let _stopped = DriverStopped(Some(stopped_tx));
            let result = connection.await;
            let _ = closed_tx.send(());
            // Controlled completion stall after the actual socket has closed.
            // Cancellation must retain ownership of this physical driver task.
            std::future::pending::<()>().await;
            result
        });
        (Some(closed_rx), Some(stopped_rx), driver)
    } else {
        (None, None, tokio::spawn(connection))
    };
    if input["op"] == "node-authority" {
        let output =
            node_authority_probe(&input, client, driver, physical_closed, driver_stopped).await?;
        println!("{}", output);
        return Ok(());
    }

    if input["op"] == "startup-storage" {
        if input["lost_connection"] == true {
            driver.abort();
        }
        let mut output = startup_storage_probe(&input, client).await?;
        if !matches!(driver.await, Ok(Ok(()))) && output["verified"] == true {
            output = json!({"error":"RESEARCH_RUN_STORE_UNAVAILABLE"});
        }
        println!("{}", output);
        return Ok(());
    }
    if std::env::args().any(|arg| arg == "--pid-barrier") {
        let pid: i32 = client
            .query_one("SELECT pg_backend_pid()", &[])
            .await?
            .get(0);
        println!("{}", json!({"backend_pid":pid}));
        io::stdout().flush()?;
    }
    if let Some(missing) = input["missing_relation"].as_str() {
        let tables = [
            "integration",
            "integration_draft",
            "integration_draft_secret_binding",
            "integration_revision",
            "integration_revision_secret_binding",
        ];
        if !tables.contains(&missing) {
            return Err("unknown controlled relation fault".into());
        }
        for table in tables {
            client
                .batch_execute(&format!(
                    "CREATE TEMP TABLE {table} (LIKE public.{table} INCLUDING ALL)"
                ))
                .await?;
            if input["copy_shadow"] != false {
                client
                    .batch_execute(&format!(
                        "INSERT INTO pg_temp.{table} SELECT * FROM public.{table}"
                    ))
                    .await?;
            }
        }
        client
            .batch_execute(&format!(
                "ALTER TABLE public.{missing} RENAME TO retained_relation_fault"
            ))
            .await?;
    } else if input["shadow"] == true {
        client.batch_execute("CREATE TEMP TABLE integration(LIKE public.integration INCLUDING ALL); SET search_path=pg_temp,public").await?;
    }
    let router = integrations::query_router(
        client,
        input["rows"].as_u64().ok_or("rows")? as usize,
        input["work"].as_u64().ok_or("work")? as usize,
    )
    .await?;
    let ingress = LocalIngress::new_developer(Access::new(&"a".repeat(64))?, router);
    let listener = TcpListener::bind("127.0.0.1:5173").await?;
    let mut results = vec![];
    for item in input["requests"].as_array().ok_or("requests")? {
        let stream = TcpStream::connect(listener.local_addr()?).await?;
        let (socket, _) = listener.accept().await?;
        let owned = ingress.clone();
        let server = tokio::spawn(async move { owned.serve_connection(socket).await });
        let (mut sender, connection) =
            hyper::client::conn::http1::handshake(TokioIo::new(stream)).await?;
        let transport = tokio::spawn(connection);
        let mut request = Request::builder()
            .method(item["method"].as_str().unwrap_or("GET"))
            .uri(item["path"].as_str().ok_or("path")?)
            .header("host", "127.0.0.1:5173")
            .header("origin", "http://127.0.0.1:5173");
        if item["authenticated"] != false {
            request = request.header(
                "cookie",
                format!("onlyalpha_dev_session={}", "a".repeat(64)),
            );
        }
        let response = sender.send_request(request.body(Body::empty())?).await?;
        let status = response.status().as_u16();
        let headers = response
            .headers()
            .iter()
            .map(|(k, v)| (k.to_string(), v.to_str().unwrap_or("").to_owned()))
            .collect::<std::collections::BTreeMap<_, _>>();
        let bytes = to_bytes(Body::new(response.into_body()), 4 * 1024 * 1024).await?;
        results.push(
            json!({"status":status,"headers":headers,"raw":String::from_utf8(bytes.to_vec())?}),
        );
        drop(sender);
        server.await??;
        transport.await??;
    }
    drop(ingress);
    driver.await??;
    println!("{}", json!({"responses":results}));
    Ok(())
}

async fn node_authority_probe(
    input: &Value,
    client: tokio_postgres::Client,
    driver: tokio::task::JoinHandle<Result<(), tokio_postgres::Error>>,
    physical_closed: Option<tokio::sync::oneshot::Receiver<()>>,
    driver_stopped: Option<tokio::sync::oneshot::Receiver<()>>,
) -> Result<Value, Box<dyn Error>> {
    use onlyalpha_product_runtime::authority_session::AuthoritySession;
    use std::io::BufRead;
    let pid: i32 = client
        .query_one("SELECT pg_catalog.pg_backend_pid()", &[])
        .await?
        .get(0);
    match input["preheld"].as_str() {
        Some("two-key") => {
            client
                .batch_execute("SELECT pg_catalog.pg_advisory_lock(1329199301,5)")
                .await?;
        }
        Some("shared-two-key") => {
            client
                .batch_execute("SELECT pg_catalog.pg_advisory_lock_shared(1329199301,5)")
                .await?;
        }
        Some("single-key") => {
            client
                .batch_execute(
                    "SELECT pg_catalog.pg_advisory_lock((1329199301::bigint << 32) | 5::bigint)",
                )
                .await?;
        }
        None => {}
        _ => return Err("unknown controlled lock setup".into()),
    }
    if input["shadow_catalog"] == true {
        client.batch_execute("CREATE TEMP TABLE pg_locks AS SELECT * FROM pg_catalog.pg_locks WHERE false; CREATE TEMP TABLE pg_database AS SELECT * FROM pg_catalog.pg_database WHERE false; CREATE FUNCTION public.pg_backend_pid() RETURNS int4 LANGUAGE SQL AS 'SELECT 0'; CREATE FUNCTION public.pg_try_advisory_lock(int4,int4) RETURNS boolean LANGUAGE SQL AS 'SELECT true'; CREATE FUNCTION public.pg_advisory_unlock(int4,int4) RETURNS boolean LANGUAGE SQL AS 'SELECT false'; CREATE FUNCTION public.wrong_oid_equality(oid,oid) RETURNS boolean LANGUAGE SQL AS 'SELECT false'; CREATE OPERATOR public.= (FUNCTION=public.wrong_oid_equality, LEFTARG=oid, RIGHTARG=oid); SET search_path=pg_temp,public,pg_catalog").await?;
    }
    let abort = driver.abort_handle();
    let mut session = match AuthoritySession::acquire(client, driver).await {
        Ok(session) => session,
        Err(error) => return Ok(json!({"error":error.code(),"backend_pid":pid})),
    };
    let action = input["action"].as_str().unwrap_or("cycle");
    if action == "frozen-reconcile" {
        use onlyalpha_product_runtime::{
            deployment::SemanticStoreId, frozen_strategy::FrozenStore, protected_files,
        };
        use std::os::fd::AsFd;
        let root = protected_files::open_directory(std::path::Path::new(
            input["root"].as_str().ok_or("missing controlled root")?,
        ))
        .map_err(|_| "controlled root unavailable")?;
        let store = FrozenStore::open(root.as_fd())?;
        let namespace = SemanticStoreId::new(
            input["namespace"]
                .as_str()
                .ok_or("missing controlled namespace")?,
        )?;
        let at = input["audit_at"]
            .as_str()
            .unwrap_or("2026-10-22T00:00:00+00:00");
        let rows = input["max_rows"].as_u64().unwrap_or(1000) as usize;
        let work = input["max_work"].as_u64().unwrap_or(67108864) as usize;
        if input["cancel_reconcile"] == true || input["cancel_reconcile"] == "blocked" {
            {
                use std::future::Future;
                let work = store.reconcile(&mut session, &namespace, at, rows, work);
                tokio::pin!(work);
                if input["cancel_reconcile"] == "blocked" {
                    use std::io::Write;
                    println!("{}", json!({"barrier_pid":pid}));
                    std::io::stdout().flush()?;
                    let (sender, receiver) = tokio::sync::oneshot::channel();
                    let reader = std::thread::spawn(move || {
                        let mut line = String::new();
                        let accepted = std::io::stdin().read_line(&mut line).is_ok()
                            && line.trim() == "cancel";
                        let _ = sender.send(accepted);
                    });
                    let accepted = tokio::select! {
                        _ = &mut work => return Err("reconciliation ended before cancellation barrier".into()),
                        accepted=receiver => accepted?,
                    };
                    reader
                        .join()
                        .map_err(|_| "controlled cancellation reader failed")?;
                    if !accepted {
                        return Err("invalid controlled cancellation".into());
                    }
                } else {
                    let pending = std::future::poll_fn(|cx| {
                        std::task::Poll::Ready(work.as_mut().poll(cx).is_pending())
                    })
                    .await;
                    if !pending {
                        return Err("reconciliation did not reach pending barrier".into());
                    }
                }
            }
            let session_error = session.verify().await.err().map(|e| e.code());
            return Ok(json!({"cancelled":true,"session_error":session_error,"backend_pid":pid}));
        }
        if input["shadow_projection"] == true {
            session.client_mut().await?.batch_execute("CREATE TEMP TABLE strategy_catalog AS SELECT * FROM public.strategy_catalog WHERE false; CREATE TEMP TABLE strategy_freeze_record AS SELECT * FROM public.strategy_freeze_record WHERE false; CREATE TEMP TABLE research_deployment_semantic_store_binding AS SELECT * FROM public.research_deployment_semantic_store_binding WHERE false; CREATE FUNCTION public.octet_length(text) RETURNS int4 LANGUAGE SQL AS 'SELECT 0'; SET search_path=pg_temp,public,pg_catalog").await?;
        }
        let result = store
            .reconcile(&mut session, &namespace, at, rows, work)
            .await;
        let error = result.err().map(|e| e.code());
        let session_error = session.verify().await.err().map(|e| e.code());
        if session_error.is_none() {
            session.close().await?;
        }
        return Ok(
            json!({"reconciled":error.is_none(),"error":error,"session_error":session_error,"backend_pid":pid}),
        );
    }
    if action == "qualification-admit" {
        use onlyalpha_product_runtime::{
            deployment::SemanticStoreId,
            protected_files,
            qualification_policy::{Policy, Store},
        };
        use std::os::fd::AsFd;
        let root = protected_files::open_directory(std::path::Path::new(
            input["root"].as_str().ok_or("controlled root")?,
        ))
        .map_err(|_| "controlled root unavailable")?;
        let store = Store::open(root.as_fd())?;
        let namespace =
            SemanticStoreId::new(input["namespace"].as_str().ok_or("controlled namespace")?)?;
        let policies: Result<Vec<_>, _> = input["policies"]
            .as_array()
            .ok_or("controlled policies")?
            .iter()
            .map(|v| {
                let mut value = v.clone();
                if let Some(bytes) = input["large_policy_metric_bytes"].as_u64() {
                    if bytes > 16 * 1024 * 1024 {
                        return Err(
                            onlyalpha_product_runtime::qualification_policy::Error::Unavailable,
                        );
                    }
                    value["criteria"][0]["metric"] = json!("x".repeat(bytes as usize));
                    let mut semantic = value.clone();
                    let fields = semantic
                        .as_object_mut()
                        .ok_or(onlyalpha_product_runtime::qualification_policy::Error::Conflict)?;
                    fields.remove("policy_fingerprint");
                    fields.insert(
                        "domain".into(),
                        json!("onlyalpha.strategy.qualification-policy"),
                    );
                    value["policy_fingerprint"] = json!(
                        <sha2::Sha256 as sha2::Digest>::digest(semantic.to_string().as_bytes())
                            .iter()
                            .map(|b| format!("{b:02x}"))
                            .collect::<String>()
                    );
                }
                Policy::from_json(
                    &value.to_string(),
                    input["policy_model_work"]
                        .as_u64()
                        .unwrap_or(8 * 1024 * 1024) as usize,
                )
            })
            .collect();
        let policies = match policies {
            Ok(v) => v,
            Err(e) => return Ok(json!({"error":e.code()})),
        };
        if input["lose_guard"] == true {
            session
                .client_mut()
                .await?
                .batch_execute("SELECT pg_catalog.pg_advisory_unlock(1329199301,5)")
                .await?;
        }
        if input["cancel_admission"] == true {
            use std::future::Future;
            {
                let future = store.admit(&mut session, &namespace, &policies, 67108864);
                tokio::pin!(future);
                let pending = std::future::poll_fn(|cx| {
                    std::task::Poll::Ready(future.as_mut().poll(cx).is_pending())
                })
                .await;
                if !pending {
                    return Err("admission did not reach actual pending barrier".into());
                }
            }
            let session_error = session.verify().await.err().map(|e| e.code());
            return Ok(json!({"cancelled":true,"session_error":session_error,"backend_pid":pid}));
        }
        let result = store
            .admit(
                &mut session,
                &namespace,
                &policies,
                input["max_work"].as_u64().unwrap_or(67108864) as usize,
            )
            .await;
        let session_error = session.verify().await.err().map(|e| e.code());
        if session_error.is_none() {
            session.close().await?;
        }
        return Ok(match result {
            Ok(v) => {
                json!({"policies":v.iter().map(Policy::to_record).collect::<Vec<_>>(),"error":null,"session_error":session_error})
            }
            Err(e) => json!({"error":e.code(),"session_error":session_error}),
        });
    }
    if action == "frozen-inventory" {
        use onlyalpha_product_runtime::{frozen_strategy::FrozenStore, protected_files};
        use std::os::fd::AsFd;
        let root = protected_files::open_directory(std::path::Path::new(
            input["root"].as_str().ok_or("missing controlled root")?,
        ))
        .map_err(|_| "controlled root unavailable")?;
        let store = FrozenStore::open(root.as_fd())?;
        if input["lose_guard"] == true {
            session
                .client_mut()
                .await?
                .batch_execute("SELECT pg_catalog.pg_advisory_unlock(1329199301,5)")
                .await?;
        }
        let result = match store
            .inventory(
                &mut session,
                input["max_work"].as_u64().unwrap_or(67108864) as usize,
            )
            .await
        {
            Ok(v) => {
                json!({"revisions":v.revisions().keys().collect::<Vec<_>>(),"relations":v.relations().keys().collect::<Vec<_>>(),"revision_tree_present":v.revision_tree_present(),"relation_tree_present":v.relation_tree_present()})
            }
            Err(e) => json!({"error":e.code()}),
        };
        if input["lose_guard"] != true {
            session.close().await?;
        }
        return Ok(result);
    }

    if action == "cancel-verify" {
        {
            use std::future::Future;
            let proof = session.verify();
            tokio::pin!(proof);
            // Poll the actual query once; the current-thread driver cannot
            // produce a response until this synchronous poll returns Pending.
            let pending = std::future::poll_fn(|cx| {
                std::task::Poll::Ready(proof.as_mut().poll(cx).is_pending())
            })
            .await;
            if !pending {
                return Err("verification did not reach pending barrier".into());
            }
        }
        let error = session.verify().await.err().map(|error| error.code());
        drop(session);
        return Ok(json!({"cancelled":true,"error":error,"backend_pid":pid}));
    }
    if action == "cancel-close" {
        {
            let close = session.close();
            tokio::pin!(close);
            tokio::select! {
                _ = physical_closed.ok_or("missing socket barrier")? => {},
                _ = &mut close => return Err("close completed before driver barrier".into()),
            }
        }
        tokio::time::timeout(
            Duration::from_secs(5),
            driver_stopped.ok_or("missing driver barrier")?,
        )
        .await??;
        return Ok(json!({"cancelled":true,"driver_stopped":true,"backend_pid":pid}));
    }

    if action == "hold" {
        println!("{}", json!({"guard_held":true,"backend_pid":pid}));
        io::stdout().flush()?;
        let mut ack = String::new();
        io::stdin().lock().take(16).read_line(&mut ack)?;
        if ack != "release\n" {
            return Err("test barrier acknowledgement".into());
        }
    }
    match action {
        "cycle" | "hold" => {}
        "replace-one-key" => {
            session.client_mut().await?.batch_execute("SELECT pg_catalog.pg_advisory_unlock(1329199301,5); SELECT pg_catalog.pg_advisory_lock((1329199301::bigint << 32) | 5::bigint)").await?;
        }
        "repeat-held" => {
            session
                .client_mut()
                .await?
                .batch_execute("SELECT pg_catalog.pg_advisory_lock(1329199301,5)")
                .await?;
        }
        "abort-driver" => {
            abort.abort();
        }
        "drop" => {
            drop(session);
            return Ok(json!({"dropped":true,"backend_pid":pid}));
        }
        _ => return Err("unknown controlled guard action".into()),
    }
    if action == "replace-one-key" || action == "abort-driver" {
        let first = session.verify().await.err().map(|e| e.code());
        let second = session.verify().await.err().map(|e| e.code());
        return Ok(json!({"error":first,"second_error":second,"backend_pid":pid}));
    }
    match session.close().await {
        Ok(()) => Ok(json!({"closed":true,"backend_pid":pid})),
        Err(error) => Ok(json!({"error":error.code(),"backend_pid":pid})),
    }
}

struct DriverStopped(Option<tokio::sync::oneshot::Sender<()>>);
impl Drop for DriverStopped {
    fn drop(&mut self) {
        if let Some(stopped) = self.0.take() {
            let _ = stopped.send(());
        }
    }
}

async fn web_assets_probe(input: &Value) -> Result<Value, Box<dyn Error>> {
    use onlyalpha_http_server::web_assets::Assets;
    use sha2::{Digest, Sha256};
    let root = std::path::Path::new(input["root"].as_str().ok_or("build root")?);
    let app = Assets::load(root, 64 * 1024 * 1024)?.router();
    let ingress = LocalIngress::new_developer(Access::new(&"a".repeat(64))?, app);
    let listener = TcpListener::bind("127.0.0.1:5173").await?;
    let mut cookie = String::new();
    let mut responses = vec![];
    for path in input["paths"].as_array().ok_or("asset paths")? {
        let path = path.as_str().ok_or("asset path")?;
        let navigation = [
            ("sec-fetch-mode", "navigate"),
            ("sec-fetch-dest", "document"),
            ("sec-fetch-site", "none"),
        ];
        let authenticated = [("cookie", cookie.as_str())];
        let headers = if path == "/" {
            &navigation[..]
        } else {
            &authenticated[..]
        };
        let (status, headers, bytes) =
            http_support::request(&ingress, &listener, "GET", path, headers, "").await;
        let bootstrap = if path == "/" {
            cookie = headers
                .get("set-cookie")
                .ok_or("missing bootstrap")?
                .to_str()?
                .split(';')
                .next()
                .ok_or("cookie")?
                .to_owned();
            true
        } else {
            false
        };
        let headers = headers
            .iter()
            .map(|(key, value)| (key.to_string(), value.to_str().unwrap_or("").to_owned()))
            .collect::<std::collections::BTreeMap<_, _>>();
        responses.push(json!({"path":path,"status":status.as_u16(),"headers":headers,"size":bytes.len(),"sha256":Sha256::digest(&bytes).iter().map(|byte| format!("{byte:02x}")).collect::<String>(),"bootstrap_cookie":bootstrap}));
    }
    Ok(json!({"responses":responses}))
}

async fn startup_storage_probe(
    input: &Value,
    mut client: tokio_postgres::Client,
) -> Result<Value, Box<dyn Error>> {
    use onlyalpha_http_server::startup::{StorageInputs, StorageRoots};
    let root = std::path::Path::new(input["root"].as_str().ok_or("root")?);
    let roots = match StorageRoots::open(root) {
        Ok(roots) => roots,
        Err(error) => return Ok(json!({"error":error.code()})),
    };
    if input["storage_barrier"] == true {
        println!("{}", json!({"storage_selected":true}));
        io::stdout().flush()?;
        let mut ack = String::new();
        io::stdin().lock().take(16).read_line(&mut ack)?;
        if ack != "verify\n" {
            return Err("storage test barrier acknowledgement".into());
        }
    }
    let source = std::path::Path::new(input["schema_source"].as_str().ok_or("schema source")?);
    let inputs = match StorageInputs::load(
        roots,
        source,
        input["work"].as_u64().ok_or("work")? as usize,
    ) {
        Ok(inputs) => inputs,
        Err(error) => return Ok(json!({"error":error.code()})),
    };
    let rows = input["rows"].as_u64().ok_or("rows")? as usize;
    if input["cancel_verify"] == true {
        {
            use std::future::Future;
            let verify = inputs.verify(&mut client, rows);
            tokio::pin!(verify);
            let pending = std::future::poll_fn(|cx| {
                std::task::Poll::Ready(verify.as_mut().poll(cx).is_pending())
            })
            .await;
            if !pending {
                return Err("storage verification did not reach pending barrier".into());
            }
        }
        return Ok(json!({"cancelled":true}));
    }
    match inputs.verify(&mut client, rows).await {
        Ok(()) => Ok(json!({"verified":true,"namespace":inputs.namespace().value()})),
        Err(error) => Ok(json!({"error":error.code()})),
    }
}
