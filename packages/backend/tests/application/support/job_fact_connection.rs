//! Technical fixture principals for controlled metadata/construction setup.
//! These operator-backed fixtures are not ordinary-Node permission evidence;
//! the actual Host uses Database's separately validated owning connections.
pub(crate) struct Connection {
    pub(crate) client: tokio_postgres::Client,
    driver: tokio::task::JoinHandle<Result<(),tokio_postgres::Error>>,
}
impl Drop for Connection { fn drop(&mut self) { self.driver.abort(); } }
impl Connection {
    pub(crate) async fn operator() -> Result<Self,Box<dyn std::error::Error>> {
        let config = Self::controlled_config()?;
        let (client,driver)=config.connect(tokio_postgres::NoTls).await?;
        Ok(Self {client,driver:tokio::spawn(driver)})
    }
    pub(crate) async fn reader() -> Result<Self,Box<dyn std::error::Error>> {
        Self::open("onlyalpha_job_reader", true).await
    }
    pub(crate) async fn builder() -> Result<Self,Box<dyn std::error::Error>> {
        Self::open("onlyalpha_factor_builder", false).await
    }
    #[allow(dead_code)]
    pub(crate) async fn publisher() -> Result<Self,Box<dyn std::error::Error>> {
        Self::open("onlyalpha_job_publisher", false).await
    }
    pub(super) fn controlled_config() -> Result<tokio_postgres::Config, Box<dyn std::error::Error>> {
        let config: tokio_postgres::Config = std::env::var("ONLYALPHA_POSTGRES_DSN")?.parse()?;
        if config.get_dbname() != Some("onlyalpha_dev_validation_test") {
            return Err("controlled test database required".into());
        }
        Ok(config)
    }
    async fn open(role: &'static str, readonly: bool) -> Result<Self,Box<dyn std::error::Error>> {
        let mut config:tokio_postgres::Config = std::env::var("ONLYALPHA_POSTGRES_DSN")?.parse()?;
        if config.get_dbname()!=Some("onlyalpha_dev_validation_test") { return Err("controlled test database required".into()); }
        if role != "onlyalpha_factor_builder" {
            if readonly { prepare_node_fixture()?; }
            config.user("onlyalpha_node_test");
        }
        config.options(if readonly {"-c default_transaction_read_only=on -c search_path=pg_catalog,public,pg_temp"} else {"-c search_path=pg_catalog,public,pg_temp"});
        let (client,driver) = config.connect(tokio_postgres::NoTls).await?;
        let connection = Self {client,driver:tokio::spawn(driver)};
        connection.client.batch_execute(&format!("SET ROLE {role}")).await?;
        Ok(connection)
    }
}

pub(crate) fn prepare_node_fixture() -> Result<(),Box<dyn std::error::Error>> {
    let prepared=std::process::Command::new("python3").args(["-m","scripts.node_database","--test"]).output()?;
    if !prepared.status.success() {return Err("controlled Node preparation refused".into());}
    Ok(())
}
