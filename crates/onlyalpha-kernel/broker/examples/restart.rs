//! Test-only file adapter: separate processes reopen durable evidence at every dispatch cut.
use onlyalpha_broker::*;
use serde_json::{Value, json};
use std::{
    fs::{self, File, OpenOptions},
    io::Write,
    path::{Path, PathBuf},
};
struct Files {
    root: PathBuf,
    cut: usize,
}
fn io_error(_: impl std::fmt::Display) -> Error {
    Error::new("TEST_DRIVER_IO")
}
impl Journal for Files {
    fn records(&self) -> Result<Vec<Record>, Error> {
        let path = self.root.join("journal.json");
        if !path.exists() {
            return Ok(vec![]);
        }
        let rows: Vec<Value> =
            serde_json::from_slice(&fs::read(path).map_err(io_error)?).map_err(io_error)?;
        rows.iter().map(Record::decode).collect()
    }
    fn append(&mut self, intent: &AppendIntent) -> Result<(), Error> {
        let mut rows = self.records()?;
        let next = Record::new(intent);
        if next.record()["sequence"] != rows.len() + 1 {
            return Err(Error::new("TEST_DRIVER_SEQUENCE"));
        }
        rows.push(next);
        let data = serde_json::to_vec(&rows.iter().map(Record::record).collect::<Vec<_>>())
            .map_err(io_error)?;
        let temp = self.root.join("journal.next");
        let mut file = File::create(&temp).map_err(io_error)?;
        file.write_all(&data).map_err(io_error)?;
        file.sync_all().map_err(io_error)?;
        fs::rename(temp, self.root.join("journal.json")).map_err(io_error)?;
        File::open(&self.root)
            .map_err(io_error)?
            .sync_all()
            .map_err(io_error)?;
        if rows.len() == self.cut {
            std::process::exit(77)
        }
        Ok(())
    }
}
struct Runtime;
impl RuntimeReader for Runtime {
    fn ready_intent(&self, c: &BrokerCommand) -> Result<ReadyIntent, Error> {
        ReadyIntent::new(c.clone(), "ready-tx".into(), "b".repeat(64))
    }
    fn application_receipt(&self, _: &Fact) -> Result<Option<ApplicationReceipt>, Error> {
        Ok(None)
    }
    fn order_view(&self, _: &BrokerCommand) -> Result<Option<OrderView>, Error> {
        Ok(None)
    }
}
struct External {
    root: PathBuf,
    cut: bool,
}
impl TradingPort for External {
    fn capabilities(&self) -> Capabilities {
        Capabilities::new(&["SUBMIT_ORDER", "LIMIT_ORDER"]).unwrap()
    }
    fn dispatch(&mut self, c: &BrokerCommand) -> Result<DispatchResult, Error> {
        let mut file = OpenOptions::new()
            .create(true)
            .append(true)
            .open(self.root.join("external-calls"))
            .map_err(io_error)?;
        writeln!(file, "{}", c.record()).map_err(io_error)?;
        file.sync_all().map_err(io_error)?;
        if self.cut {
            std::process::exit(77)
        }
        Ok(DispatchResult::Unknown)
    }
}
fn main() {
    let args = std::env::args().collect::<Vec<_>>();
    let root = Path::new(&args[1]);
    fs::create_dir_all(root).unwrap();
    let cut = args[2].parse::<usize>().unwrap();
    let request: Value = serde_json::from_slice(&fs::read(&args[3]).unwrap()).unwrap();
    let scope=Scope::decode(&json!({"engine":"engine","runtime":"runtime","gateway":"gateway","account":"account","generation":"a".repeat(64),"runtime_kind":"BACKTEST"})).unwrap();
    let c=BrokerCommand::decode(&json!({"schema_version":1,"scope":scope.record(),"operation":"SUBMIT","command_id":"submit","order":"order","client":"client","request":request["request"]})).unwrap();
    let mut journal = Files {
        root: root.to_path_buf(),
        cut,
    };
    let mut broker = Broker::recover(scope, &journal, 8).unwrap();
    broker.set_connection(Connection::Ready);
    broker.set_health(true, true, true);
    let mut external = External {
        root: root.to_path_buf(),
        cut: cut == 4,
    };
    let state = broker
        .dispatch(&mut journal, &Runtime, &mut external, &c)
        .unwrap();
    assert_eq!(state, CommandState::Unknown);
    println!("UNKNOWN");
}
