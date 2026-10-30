//! Deterministic PostgreSQL fault at the actual operational completion boundary.
//! The owning probe supplies a genuine accepted Work and the original Node session.
use onlyalpha_backend::workers::research::{SharedAuthority, Work, run_owned};
use onlyalpha_domain::time::OnlyUtcDateTime;
use tokio_postgres::Client;

pub async fn node_socket_loss_during_finalization_cannot_commit_on_another_socket(
    writer: SharedAuthority,
    work: Work,
    shadow: &mut Client,
    at: OnlyUtcDateTime,
) {
    let run = work.run.run_id().to_owned();
    let (pid, database) = {
        let mut held = writer.lock().await;
        let row = held
            .as_mut()
            .unwrap()
            .client_mut()
            .await
            .unwrap()
            .query_one("SELECT pg_backend_pid(),current_database()", &[])
            .await
            .unwrap();
        (row.get::<_, i32>(0), row.get::<_, String>(1))
    };
    assert!(database.ends_with("_test"));
    assert_eq!(
        shadow
            .query_one("SELECT current_database()", &[])
            .await
            .unwrap()
            .get::<_, String>(0),
        database
    );
    // If finalization ever uses an independent write socket after a one-time PID
    // check, this trigger kills the Node guard but that other transaction commits.
    // On the required original physical socket it kills its own transaction,
    // rolling both Attempt and Run updates back together.
    shadow.batch_execute(&format!("CREATE FUNCTION research_test_terminate_guard() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN PERFORM pg_terminate_backend({pid}); RETURN NEW; END $$; CREATE TRIGGER research_test_finalization_guard BEFORE UPDATE ON research_run FOR EACH ROW WHEN (NEW.state='COMPLETED') EXECUTE FUNCTION research_test_terminate_guard()" )).await.unwrap();
    let result = run_owned(&writer, work, || Ok(at)).await;
    shadow.batch_execute("DROP TRIGGER research_test_finalization_guard ON research_run; DROP FUNCTION research_test_terminate_guard()").await.unwrap();
    assert!(result.is_err());
    assert_eq!(
        shadow
            .query_one("SELECT 1::integer", &[])
            .await
            .unwrap()
            .get::<_, i32>(0),
        1
    );
    let row = shadow
        .query_one(
            "SELECT state,revision FROM research_run WHERE run_id=$1::text::uuid",
            &[&run],
        )
        .await
        .unwrap();
    assert_eq!(row.get::<_, String>(0), "RUNNING");
    assert_eq!(row.get::<_, i64>(1), 1);
    let row=shadow.query_one("SELECT state FROM research_run_attempt WHERE run_id=$1::text::uuid AND attempt_number=1",&[&run]).await.unwrap();
    assert_eq!(row.get::<_, String>(0), "ACTIVE");
    assert!(
        writer
            .lock()
            .await
            .as_mut()
            .unwrap()
            .client_mut()
            .await
            .is_err()
    );
}
