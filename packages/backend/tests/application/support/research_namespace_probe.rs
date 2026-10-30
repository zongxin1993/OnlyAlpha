//! Deployment/source-history technical proof; never a normal user operation.
use onlyalpha_backend::bootstrap::{deployment,research_namespace};
use serde_json::{Value,json};
use std::path::Path;

pub async fn run(request:&Value,client:&mut tokio_postgres::Client)->Value{
    let result=async{
        let root=Path::new(request["user_data"].as_str().ok_or("root")?);
        let identity=research_namespace::open_existing(root)?;
        deployment::verify_binding(client,&identity).await.map_err(|_|"SEMANTIC_STORE_BINDING_MISMATCH")?;
        research_namespace::novelty(root)?.refresh_projection(client).await
    }.await;
    match result{Ok(pin)=>json!({"projection_fingerprint":pin}),Err(code)=>json!({"error":code})}
}
