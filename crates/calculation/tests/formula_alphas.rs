use onlyalpha_calculation::factor_expr::{FactorExpr, PanelDagState};
use onlyalpha_operators::algebra::Decimal;
use serde_json::Value;
use sha2::{Digest, Sha256};
use std::collections::{BTreeMap, BTreeSet};

const WORLDQUANT: [&str; 101] = [
    include_str!("../../../examples/factor/worldquant/alpha101/ALPHA001.json"),
    include_str!("../../../examples/factor/worldquant/alpha101/ALPHA002.json"),
    include_str!("../../../examples/factor/worldquant/alpha101/ALPHA003.json"),
    include_str!("../../../examples/factor/worldquant/alpha101/ALPHA004.json"),
    include_str!("../../../examples/factor/worldquant/alpha101/ALPHA005.json"),
    include_str!("../../../examples/factor/worldquant/alpha101/ALPHA006.json"),
    include_str!("../../../examples/factor/worldquant/alpha101/ALPHA007.json"),
    include_str!("../../../examples/factor/worldquant/alpha101/ALPHA008.json"),
    include_str!("../../../examples/factor/worldquant/alpha101/ALPHA009.json"),
    include_str!("../../../examples/factor/worldquant/alpha101/ALPHA010.json"),
    include_str!("../../../examples/factor/worldquant/alpha101/ALPHA011.json"),
    include_str!("../../../examples/factor/worldquant/alpha101/ALPHA012.json"),
    include_str!("../../../examples/factor/worldquant/alpha101/ALPHA013.json"),
    include_str!("../../../examples/factor/worldquant/alpha101/ALPHA014.json"),
    include_str!("../../../examples/factor/worldquant/alpha101/ALPHA015.json"),
    include_str!("../../../examples/factor/worldquant/alpha101/ALPHA016.json"),
    include_str!("../../../examples/factor/worldquant/alpha101/ALPHA017.json"),
    include_str!("../../../examples/factor/worldquant/alpha101/ALPHA018.json"),
    include_str!("../../../examples/factor/worldquant/alpha101/ALPHA019.json"),
    include_str!("../../../examples/factor/worldquant/alpha101/ALPHA020.json"),
    include_str!("../../../examples/factor/worldquant/alpha101/ALPHA021.json"),
    include_str!("../../../examples/factor/worldquant/alpha101/ALPHA022.json"),
    include_str!("../../../examples/factor/worldquant/alpha101/ALPHA023.json"),
    include_str!("../../../examples/factor/worldquant/alpha101/ALPHA024.json"),
    include_str!("../../../examples/factor/worldquant/alpha101/ALPHA025.json"),
    include_str!("../../../examples/factor/worldquant/alpha101/ALPHA026.json"),
    include_str!("../../../examples/factor/worldquant/alpha101/ALPHA027.json"),
    include_str!("../../../examples/factor/worldquant/alpha101/ALPHA028.json"),
    include_str!("../../../examples/factor/worldquant/alpha101/ALPHA029.json"),
    include_str!("../../../examples/factor/worldquant/alpha101/ALPHA030.json"),
    include_str!("../../../examples/factor/worldquant/alpha101/ALPHA031.json"),
    include_str!("../../../examples/factor/worldquant/alpha101/ALPHA032.json"),
    include_str!("../../../examples/factor/worldquant/alpha101/ALPHA033.json"),
    include_str!("../../../examples/factor/worldquant/alpha101/ALPHA034.json"),
    include_str!("../../../examples/factor/worldquant/alpha101/ALPHA035.json"),
    include_str!("../../../examples/factor/worldquant/alpha101/ALPHA036.json"),
    include_str!("../../../examples/factor/worldquant/alpha101/ALPHA037.json"),
    include_str!("../../../examples/factor/worldquant/alpha101/ALPHA038.json"),
    include_str!("../../../examples/factor/worldquant/alpha101/ALPHA039.json"),
    include_str!("../../../examples/factor/worldquant/alpha101/ALPHA040.json"),
    include_str!("../../../examples/factor/worldquant/alpha101/ALPHA041.json"),
    include_str!("../../../examples/factor/worldquant/alpha101/ALPHA042.json"),
    include_str!("../../../examples/factor/worldquant/alpha101/ALPHA043.json"),
    include_str!("../../../examples/factor/worldquant/alpha101/ALPHA044.json"),
    include_str!("../../../examples/factor/worldquant/alpha101/ALPHA045.json"),
    include_str!("../../../examples/factor/worldquant/alpha101/ALPHA046.json"),
    include_str!("../../../examples/factor/worldquant/alpha101/ALPHA047.json"),
    include_str!("../../../examples/factor/worldquant/alpha101/ALPHA048.json"),
    include_str!("../../../examples/factor/worldquant/alpha101/ALPHA049.json"),
    include_str!("../../../examples/factor/worldquant/alpha101/ALPHA050.json"),
    include_str!("../../../examples/factor/worldquant/alpha101/ALPHA051.json"),
    include_str!("../../../examples/factor/worldquant/alpha101/ALPHA052.json"),
    include_str!("../../../examples/factor/worldquant/alpha101/ALPHA053.json"),
    include_str!("../../../examples/factor/worldquant/alpha101/ALPHA054.json"),
    include_str!("../../../examples/factor/worldquant/alpha101/ALPHA055.json"),
    include_str!("../../../examples/factor/worldquant/alpha101/ALPHA056.json"),
    include_str!("../../../examples/factor/worldquant/alpha101/ALPHA057.json"),
    include_str!("../../../examples/factor/worldquant/alpha101/ALPHA058.json"),
    include_str!("../../../examples/factor/worldquant/alpha101/ALPHA059.json"),
    include_str!("../../../examples/factor/worldquant/alpha101/ALPHA060.json"),
    include_str!("../../../examples/factor/worldquant/alpha101/ALPHA061.json"),
    include_str!("../../../examples/factor/worldquant/alpha101/ALPHA062.json"),
    include_str!("../../../examples/factor/worldquant/alpha101/ALPHA063.json"),
    include_str!("../../../examples/factor/worldquant/alpha101/ALPHA064.json"),
    include_str!("../../../examples/factor/worldquant/alpha101/ALPHA065.json"),
    include_str!("../../../examples/factor/worldquant/alpha101/ALPHA066.json"),
    include_str!("../../../examples/factor/worldquant/alpha101/ALPHA067.json"),
    include_str!("../../../examples/factor/worldquant/alpha101/ALPHA068.json"),
    include_str!("../../../examples/factor/worldquant/alpha101/ALPHA069.json"),
    include_str!("../../../examples/factor/worldquant/alpha101/ALPHA070.json"),
    include_str!("../../../examples/factor/worldquant/alpha101/ALPHA071.json"),
    include_str!("../../../examples/factor/worldquant/alpha101/ALPHA072.json"),
    include_str!("../../../examples/factor/worldquant/alpha101/ALPHA073.json"),
    include_str!("../../../examples/factor/worldquant/alpha101/ALPHA074.json"),
    include_str!("../../../examples/factor/worldquant/alpha101/ALPHA075.json"),
    include_str!("../../../examples/factor/worldquant/alpha101/ALPHA076.json"),
    include_str!("../../../examples/factor/worldquant/alpha101/ALPHA077.json"),
    include_str!("../../../examples/factor/worldquant/alpha101/ALPHA078.json"),
    include_str!("../../../examples/factor/worldquant/alpha101/ALPHA079.json"),
    include_str!("../../../examples/factor/worldquant/alpha101/ALPHA080.json"),
    include_str!("../../../examples/factor/worldquant/alpha101/ALPHA081.json"),
    include_str!("../../../examples/factor/worldquant/alpha101/ALPHA082.json"),
    include_str!("../../../examples/factor/worldquant/alpha101/ALPHA083.json"),
    include_str!("../../../examples/factor/worldquant/alpha101/ALPHA084.json"),
    include_str!("../../../examples/factor/worldquant/alpha101/ALPHA085.json"),
    include_str!("../../../examples/factor/worldquant/alpha101/ALPHA086.json"),
    include_str!("../../../examples/factor/worldquant/alpha101/ALPHA087.json"),
    include_str!("../../../examples/factor/worldquant/alpha101/ALPHA088.json"),
    include_str!("../../../examples/factor/worldquant/alpha101/ALPHA089.json"),
    include_str!("../../../examples/factor/worldquant/alpha101/ALPHA090.json"),
    include_str!("../../../examples/factor/worldquant/alpha101/ALPHA091.json"),
    include_str!("../../../examples/factor/worldquant/alpha101/ALPHA092.json"),
    include_str!("../../../examples/factor/worldquant/alpha101/ALPHA093.json"),
    include_str!("../../../examples/factor/worldquant/alpha101/ALPHA094.json"),
    include_str!("../../../examples/factor/worldquant/alpha101/ALPHA095.json"),
    include_str!("../../../examples/factor/worldquant/alpha101/ALPHA096.json"),
    include_str!("../../../examples/factor/worldquant/alpha101/ALPHA097.json"),
    include_str!("../../../examples/factor/worldquant/alpha101/ALPHA098.json"),
    include_str!("../../../examples/factor/worldquant/alpha101/ALPHA099.json"),
    include_str!("../../../examples/factor/worldquant/alpha101/ALPHA100.json"),
    include_str!("../../../examples/factor/worldquant/alpha101/ALPHA101.json"),
];
const GTJA: [&str; 191] = [
    include_str!("../../../examples/factor/gtja/alpha191/Alpha1.json"),
    include_str!("../../../examples/factor/gtja/alpha191/Alpha2.json"),
    include_str!("../../../examples/factor/gtja/alpha191/Alpha3.json"),
    include_str!("../../../examples/factor/gtja/alpha191/Alpha4.json"),
    include_str!("../../../examples/factor/gtja/alpha191/Alpha5.json"),
    include_str!("../../../examples/factor/gtja/alpha191/Alpha6.json"),
    include_str!("../../../examples/factor/gtja/alpha191/Alpha7.json"),
    include_str!("../../../examples/factor/gtja/alpha191/Alpha8.json"),
    include_str!("../../../examples/factor/gtja/alpha191/Alpha9.json"),
    include_str!("../../../examples/factor/gtja/alpha191/Alpha10.json"),
    include_str!("../../../examples/factor/gtja/alpha191/Alpha11.json"),
    include_str!("../../../examples/factor/gtja/alpha191/Alpha12.json"),
    include_str!("../../../examples/factor/gtja/alpha191/Alpha13.json"),
    include_str!("../../../examples/factor/gtja/alpha191/Alpha14.json"),
    include_str!("../../../examples/factor/gtja/alpha191/Alpha15.json"),
    include_str!("../../../examples/factor/gtja/alpha191/Alpha16.json"),
    include_str!("../../../examples/factor/gtja/alpha191/Alpha17.json"),
    include_str!("../../../examples/factor/gtja/alpha191/Alpha18.json"),
    include_str!("../../../examples/factor/gtja/alpha191/Alpha19.json"),
    include_str!("../../../examples/factor/gtja/alpha191/Alpha20.json"),
    include_str!("../../../examples/factor/gtja/alpha191/Alpha21.json"),
    include_str!("../../../examples/factor/gtja/alpha191/Alpha22.json"),
    include_str!("../../../examples/factor/gtja/alpha191/Alpha23.json"),
    include_str!("../../../examples/factor/gtja/alpha191/Alpha24.json"),
    include_str!("../../../examples/factor/gtja/alpha191/Alpha25.json"),
    include_str!("../../../examples/factor/gtja/alpha191/Alpha26.json"),
    include_str!("../../../examples/factor/gtja/alpha191/Alpha27.json"),
    include_str!("../../../examples/factor/gtja/alpha191/Alpha28.json"),
    include_str!("../../../examples/factor/gtja/alpha191/Alpha29.json"),
    include_str!("../../../examples/factor/gtja/alpha191/Alpha30.json"),
    include_str!("../../../examples/factor/gtja/alpha191/Alpha31.json"),
    include_str!("../../../examples/factor/gtja/alpha191/Alpha32.json"),
    include_str!("../../../examples/factor/gtja/alpha191/Alpha33.json"),
    include_str!("../../../examples/factor/gtja/alpha191/Alpha34.json"),
    include_str!("../../../examples/factor/gtja/alpha191/Alpha35.json"),
    include_str!("../../../examples/factor/gtja/alpha191/Alpha36.json"),
    include_str!("../../../examples/factor/gtja/alpha191/Alpha37.json"),
    include_str!("../../../examples/factor/gtja/alpha191/Alpha38.json"),
    include_str!("../../../examples/factor/gtja/alpha191/Alpha39.json"),
    include_str!("../../../examples/factor/gtja/alpha191/Alpha40.json"),
    include_str!("../../../examples/factor/gtja/alpha191/Alpha41.json"),
    include_str!("../../../examples/factor/gtja/alpha191/Alpha42.json"),
    include_str!("../../../examples/factor/gtja/alpha191/Alpha43.json"),
    include_str!("../../../examples/factor/gtja/alpha191/Alpha44.json"),
    include_str!("../../../examples/factor/gtja/alpha191/Alpha45.json"),
    include_str!("../../../examples/factor/gtja/alpha191/Alpha46.json"),
    include_str!("../../../examples/factor/gtja/alpha191/Alpha47.json"),
    include_str!("../../../examples/factor/gtja/alpha191/Alpha48.json"),
    include_str!("../../../examples/factor/gtja/alpha191/Alpha49.json"),
    include_str!("../../../examples/factor/gtja/alpha191/Alpha50.json"),
    include_str!("../../../examples/factor/gtja/alpha191/Alpha51.json"),
    include_str!("../../../examples/factor/gtja/alpha191/Alpha52.json"),
    include_str!("../../../examples/factor/gtja/alpha191/Alpha53.json"),
    include_str!("../../../examples/factor/gtja/alpha191/Alpha54.json"),
    include_str!("../../../examples/factor/gtja/alpha191/Alpha55.json"),
    include_str!("../../../examples/factor/gtja/alpha191/Alpha56.json"),
    include_str!("../../../examples/factor/gtja/alpha191/Alpha57.json"),
    include_str!("../../../examples/factor/gtja/alpha191/Alpha58.json"),
    include_str!("../../../examples/factor/gtja/alpha191/Alpha59.json"),
    include_str!("../../../examples/factor/gtja/alpha191/Alpha60.json"),
    include_str!("../../../examples/factor/gtja/alpha191/Alpha61.json"),
    include_str!("../../../examples/factor/gtja/alpha191/Alpha62.json"),
    include_str!("../../../examples/factor/gtja/alpha191/Alpha63.json"),
    include_str!("../../../examples/factor/gtja/alpha191/Alpha64.json"),
    include_str!("../../../examples/factor/gtja/alpha191/Alpha65.json"),
    include_str!("../../../examples/factor/gtja/alpha191/Alpha66.json"),
    include_str!("../../../examples/factor/gtja/alpha191/Alpha67.json"),
    include_str!("../../../examples/factor/gtja/alpha191/Alpha68.json"),
    include_str!("../../../examples/factor/gtja/alpha191/Alpha69.json"),
    include_str!("../../../examples/factor/gtja/alpha191/Alpha70.json"),
    include_str!("../../../examples/factor/gtja/alpha191/Alpha71.json"),
    include_str!("../../../examples/factor/gtja/alpha191/Alpha72.json"),
    include_str!("../../../examples/factor/gtja/alpha191/Alpha73.json"),
    include_str!("../../../examples/factor/gtja/alpha191/Alpha74.json"),
    include_str!("../../../examples/factor/gtja/alpha191/Alpha75.json"),
    include_str!("../../../examples/factor/gtja/alpha191/Alpha76.json"),
    include_str!("../../../examples/factor/gtja/alpha191/Alpha77.json"),
    include_str!("../../../examples/factor/gtja/alpha191/Alpha78.json"),
    include_str!("../../../examples/factor/gtja/alpha191/Alpha79.json"),
    include_str!("../../../examples/factor/gtja/alpha191/Alpha80.json"),
    include_str!("../../../examples/factor/gtja/alpha191/Alpha81.json"),
    include_str!("../../../examples/factor/gtja/alpha191/Alpha82.json"),
    include_str!("../../../examples/factor/gtja/alpha191/Alpha83.json"),
    include_str!("../../../examples/factor/gtja/alpha191/Alpha84.json"),
    include_str!("../../../examples/factor/gtja/alpha191/Alpha85.json"),
    include_str!("../../../examples/factor/gtja/alpha191/Alpha86.json"),
    include_str!("../../../examples/factor/gtja/alpha191/Alpha87.json"),
    include_str!("../../../examples/factor/gtja/alpha191/Alpha88.json"),
    include_str!("../../../examples/factor/gtja/alpha191/Alpha89.json"),
    include_str!("../../../examples/factor/gtja/alpha191/Alpha90.json"),
    include_str!("../../../examples/factor/gtja/alpha191/Alpha91.json"),
    include_str!("../../../examples/factor/gtja/alpha191/Alpha92.json"),
    include_str!("../../../examples/factor/gtja/alpha191/Alpha93.json"),
    include_str!("../../../examples/factor/gtja/alpha191/Alpha94.json"),
    include_str!("../../../examples/factor/gtja/alpha191/Alpha95.json"),
    include_str!("../../../examples/factor/gtja/alpha191/Alpha96.json"),
    include_str!("../../../examples/factor/gtja/alpha191/Alpha97.json"),
    include_str!("../../../examples/factor/gtja/alpha191/Alpha98.json"),
    include_str!("../../../examples/factor/gtja/alpha191/Alpha99.json"),
    include_str!("../../../examples/factor/gtja/alpha191/Alpha100.json"),
    include_str!("../../../examples/factor/gtja/alpha191/Alpha101.json"),
    include_str!("../../../examples/factor/gtja/alpha191/Alpha102.json"),
    include_str!("../../../examples/factor/gtja/alpha191/Alpha103.json"),
    include_str!("../../../examples/factor/gtja/alpha191/Alpha104.json"),
    include_str!("../../../examples/factor/gtja/alpha191/Alpha105.json"),
    include_str!("../../../examples/factor/gtja/alpha191/Alpha106.json"),
    include_str!("../../../examples/factor/gtja/alpha191/Alpha107.json"),
    include_str!("../../../examples/factor/gtja/alpha191/Alpha108.json"),
    include_str!("../../../examples/factor/gtja/alpha191/Alpha109.json"),
    include_str!("../../../examples/factor/gtja/alpha191/Alpha110.json"),
    include_str!("../../../examples/factor/gtja/alpha191/Alpha111.json"),
    include_str!("../../../examples/factor/gtja/alpha191/Alpha112.json"),
    include_str!("../../../examples/factor/gtja/alpha191/Alpha113.json"),
    include_str!("../../../examples/factor/gtja/alpha191/Alpha114.json"),
    include_str!("../../../examples/factor/gtja/alpha191/Alpha115.json"),
    include_str!("../../../examples/factor/gtja/alpha191/Alpha116.json"),
    include_str!("../../../examples/factor/gtja/alpha191/Alpha117.json"),
    include_str!("../../../examples/factor/gtja/alpha191/Alpha118.json"),
    include_str!("../../../examples/factor/gtja/alpha191/Alpha119.json"),
    include_str!("../../../examples/factor/gtja/alpha191/Alpha120.json"),
    include_str!("../../../examples/factor/gtja/alpha191/Alpha121.json"),
    include_str!("../../../examples/factor/gtja/alpha191/Alpha122.json"),
    include_str!("../../../examples/factor/gtja/alpha191/Alpha123.json"),
    include_str!("../../../examples/factor/gtja/alpha191/Alpha124.json"),
    include_str!("../../../examples/factor/gtja/alpha191/Alpha125.json"),
    include_str!("../../../examples/factor/gtja/alpha191/Alpha126.json"),
    include_str!("../../../examples/factor/gtja/alpha191/Alpha127.json"),
    include_str!("../../../examples/factor/gtja/alpha191/Alpha128.json"),
    include_str!("../../../examples/factor/gtja/alpha191/Alpha129.json"),
    include_str!("../../../examples/factor/gtja/alpha191/Alpha130.json"),
    include_str!("../../../examples/factor/gtja/alpha191/Alpha131.json"),
    include_str!("../../../examples/factor/gtja/alpha191/Alpha132.json"),
    include_str!("../../../examples/factor/gtja/alpha191/Alpha133.json"),
    include_str!("../../../examples/factor/gtja/alpha191/Alpha134.json"),
    include_str!("../../../examples/factor/gtja/alpha191/Alpha135.json"),
    include_str!("../../../examples/factor/gtja/alpha191/Alpha136.json"),
    include_str!("../../../examples/factor/gtja/alpha191/Alpha137.json"),
    include_str!("../../../examples/factor/gtja/alpha191/Alpha138.json"),
    include_str!("../../../examples/factor/gtja/alpha191/Alpha139.json"),
    include_str!("../../../examples/factor/gtja/alpha191/Alpha140.json"),
    include_str!("../../../examples/factor/gtja/alpha191/Alpha141.json"),
    include_str!("../../../examples/factor/gtja/alpha191/Alpha142.json"),
    include_str!("../../../examples/factor/gtja/alpha191/Alpha143.json"),
    include_str!("../../../examples/factor/gtja/alpha191/Alpha144.json"),
    include_str!("../../../examples/factor/gtja/alpha191/Alpha145.json"),
    include_str!("../../../examples/factor/gtja/alpha191/Alpha146.json"),
    include_str!("../../../examples/factor/gtja/alpha191/Alpha147.json"),
    include_str!("../../../examples/factor/gtja/alpha191/Alpha148.json"),
    include_str!("../../../examples/factor/gtja/alpha191/Alpha149.json"),
    include_str!("../../../examples/factor/gtja/alpha191/Alpha150.json"),
    include_str!("../../../examples/factor/gtja/alpha191/Alpha151.json"),
    include_str!("../../../examples/factor/gtja/alpha191/Alpha152.json"),
    include_str!("../../../examples/factor/gtja/alpha191/Alpha153.json"),
    include_str!("../../../examples/factor/gtja/alpha191/Alpha154.json"),
    include_str!("../../../examples/factor/gtja/alpha191/Alpha155.json"),
    include_str!("../../../examples/factor/gtja/alpha191/Alpha156.json"),
    include_str!("../../../examples/factor/gtja/alpha191/Alpha157.json"),
    include_str!("../../../examples/factor/gtja/alpha191/Alpha158.json"),
    include_str!("../../../examples/factor/gtja/alpha191/Alpha159.json"),
    include_str!("../../../examples/factor/gtja/alpha191/Alpha160.json"),
    include_str!("../../../examples/factor/gtja/alpha191/Alpha161.json"),
    include_str!("../../../examples/factor/gtja/alpha191/Alpha162.json"),
    include_str!("../../../examples/factor/gtja/alpha191/Alpha163.json"),
    include_str!("../../../examples/factor/gtja/alpha191/Alpha164.json"),
    include_str!("../../../examples/factor/gtja/alpha191/Alpha165.json"),
    include_str!("../../../examples/factor/gtja/alpha191/Alpha166.json"),
    include_str!("../../../examples/factor/gtja/alpha191/Alpha167.json"),
    include_str!("../../../examples/factor/gtja/alpha191/Alpha168.json"),
    include_str!("../../../examples/factor/gtja/alpha191/Alpha169.json"),
    include_str!("../../../examples/factor/gtja/alpha191/Alpha170.json"),
    include_str!("../../../examples/factor/gtja/alpha191/Alpha171.json"),
    include_str!("../../../examples/factor/gtja/alpha191/Alpha172.json"),
    include_str!("../../../examples/factor/gtja/alpha191/Alpha173.json"),
    include_str!("../../../examples/factor/gtja/alpha191/Alpha174.json"),
    include_str!("../../../examples/factor/gtja/alpha191/Alpha175.json"),
    include_str!("../../../examples/factor/gtja/alpha191/Alpha176.json"),
    include_str!("../../../examples/factor/gtja/alpha191/Alpha177.json"),
    include_str!("../../../examples/factor/gtja/alpha191/Alpha178.json"),
    include_str!("../../../examples/factor/gtja/alpha191/Alpha179.json"),
    include_str!("../../../examples/factor/gtja/alpha191/Alpha180.json"),
    include_str!("../../../examples/factor/gtja/alpha191/Alpha181.json"),
    include_str!("../../../examples/factor/gtja/alpha191/Alpha182.json"),
    include_str!("../../../examples/factor/gtja/alpha191/Alpha183.json"),
    include_str!("../../../examples/factor/gtja/alpha191/Alpha184.json"),
    include_str!("../../../examples/factor/gtja/alpha191/Alpha185.json"),
    include_str!("../../../examples/factor/gtja/alpha191/Alpha186.json"),
    include_str!("../../../examples/factor/gtja/alpha191/Alpha187.json"),
    include_str!("../../../examples/factor/gtja/alpha191/Alpha188.json"),
    include_str!("../../../examples/factor/gtja/alpha191/Alpha189.json"),
    include_str!("../../../examples/factor/gtja/alpha191/Alpha190.json"),
    include_str!("../../../examples/factor/gtja/alpha191/Alpha191.json"),
];
const PERIODS: usize = 320;
const INSTRUMENTS: usize = 6;
const SAMPLE_TIMES: [usize; 6] = [0, 15, 63, 255, 316, 319];
type Cell = Option<Decimal>;
type Panel = Vec<BTreeMap<String, Vec<Cell>>>;
type Event = Vec<BTreeMap<String, Cell>>;

fn load_panel(header: &Value) -> Panel {
    assert_eq!(header["periods"], PERIODS);
    assert_eq!(header["sample_times"], serde_json::json!(SAMPLE_TIMES));
    let raw = header["panel"].as_array().unwrap();
    assert_eq!(raw.len(), INSTRUMENTS);
    let panel: Panel = raw
        .iter()
        .map(|instrument| {
            instrument
                .as_object()
                .unwrap()
                .iter()
                .map(|(field, cells)| {
                    let cells = cells.as_array().unwrap();
                    assert_eq!(cells.len(), PERIODS, "{field} length");
                    let values = cells
                        .iter()
                        .map(|cell| match cell {
                            Value::Null => None,
                            Value::String(value) => Some(value.parse::<Decimal>().unwrap()),
                            _ => panic!("{field} contains invalid decimal {cell}"),
                        })
                        .collect();
                    (field.clone(), values)
                })
                .collect()
        })
        .collect();
    assert!(!panel[0].is_empty());
    assert!(panel.iter().all(|row| row.keys().eq(panel[0].keys())));
    panel
}

fn hex_digest(bytes: &[u8]) -> String {
    bytes.iter().map(|b| format!("{b:02x}")).collect()
}

fn check_reference(name: &str, record: &Value, batch: &[Vec<Cell>]) {
    assert_eq!(batch.len(), INSTRUMENTS, "{name} instrument count");
    let samples = record["samples"].as_array().unwrap();
    assert_eq!(samples.len(), INSTRUMENTS, "{name} sample rows");
    let mut digest = Sha256::new();
    let mut defined = 0u64;
    for (i, values) in batch.iter().enumerate() {
        assert_eq!(values.len(), PERIODS, "{name} instrument {i} length");
        let expected = samples[i].as_array().unwrap();
        assert_eq!(expected.len(), SAMPLE_TIMES.len(), "{name} sample times");
        for (t, cell) in values.iter().enumerate() {
            let text = cell.as_ref().map(|value| {
                defined += 1;
                let scaled = value.with_scale(12);
                assert_eq!(value, &scaled, "{name} i={i} t={t} violates Q12");
                scaled.to_plain_string()
            });
            digest.update(text.as_deref().unwrap_or("null").as_bytes());
            digest.update(b"\n");
            if let Ok(sample) = SAMPLE_TIMES.binary_search(&t) {
                assert_eq!(
                    serde_json::json!(text),
                    expected[sample],
                    "{name} i={i} t={t}"
                );
            }
        }
    }
    assert!(defined > 0, "{name} has no defined reference cells");
    assert_eq!(
        Some(defined),
        record["defined"].as_u64(),
        "{name} defined cells"
    );
    assert_eq!(
        record["sha256"],
        hex_digest(&digest.finalize()),
        "{name} matrix SHA-256"
    );
}

fn check_events(name: &str, expr: &FactorExpr, events: &[Event], batch: &[Vec<Cell>]) {
    let mut live = expr.panel_event_executor(INSTRUMENTS).unwrap();
    let mut resumed = None;
    for (t, event) in events.iter().enumerate() {
        if t == 257 {
            let record = live.capture_state().to_record();
            let state = PanelDagState::from_record(&record)
                .unwrap_or_else(|e| panic!("{name} checkpoint: {e}"));
            let mut fresh = expr.panel_event_executor(INSTRUMENTS).unwrap();
            fresh
                .restore_state(state)
                .unwrap_or_else(|e| panic!("{name} restore: {e}"));
            resumed = Some(fresh);
        }
        for (mode, executor) in Some(("event", &mut live))
            .into_iter()
            .chain(resumed.as_mut().map(|fresh| ("restored", fresh)))
        {
            let actual = executor
                .step(event)
                .unwrap_or_else(|e| panic!("{name} {mode} t={t}: {e}"));
            assert_eq!(actual.len(), INSTRUMENTS, "{name} {mode} t={t}");
            for (i, cell) in actual.iter().enumerate() {
                assert_eq!(cell, &batch[i][t], "{name} {mode} i={i} t={t}");
            }
        }
    }
}

#[test]
fn published_formula_alphas_match_independent_panel_results() {
    let mut records = include_str!("fixtures/formula_alphas/expected.jsonl")
        .lines()
        .map(|line| serde_json::from_str::<Value>(line).unwrap());
    let panel = load_panel(&records.next().expect("missing panel header"));
    let fields: BTreeSet<_> = panel[0].keys().cloned().collect();
    let events: Vec<Event> = (0..PERIODS)
        .map(|t| {
            panel
                .iter()
                .map(|row| {
                    row.iter()
                        .map(|(key, col)| (key.clone(), col[t].clone()))
                        .collect()
                })
                .collect()
        })
        .collect();
    let prefixes = [16, 256, 317].map(|len| {
        let prefix: Panel = panel
            .iter()
            .map(|row| {
                row.iter()
                    .map(|(key, values)| (key.clone(), values[..len].to_vec()))
                    .collect()
            })
            .collect();
        (len, prefix)
    });
    for (set, manifest, definitions) in [
        (
            "onlyalpha.alpha101",
            include_str!("../../../examples/factor/worldquant/alpha101/manifest.json"),
            WORLDQUANT.as_slice(),
        ),
        (
            "onlyalpha.alpha191",
            include_str!("../../../examples/factor/gtja/alpha191/manifest.json"),
            GTJA.as_slice(),
        ),
    ] {
        let manifest: Value = serde_json::from_str(manifest).unwrap();
        assert_eq!(manifest["factor_set"], set);
        assert_eq!(manifest["factor_set_version"], "1");
        assert_eq!(manifest["expression_language"], "factor_expr");
        let features = manifest["features"].as_array().unwrap();
        assert_eq!(features.len(), definitions.len());
        for (index, (feature, definition)) in features.iter().zip(definitions).enumerate() {
            let number = index + 1;
            let name = if set == "onlyalpha.alpha101" {
                format!("ALPHA{number:03}")
            } else {
                format!("Alpha{number}")
            };
            let record = records
                .next()
                .unwrap_or_else(|| panic!("{name} missing reference"));
            assert_eq!(record["factor_set"], set, "{name} reference set");
            assert_eq!(record["name"], name, "{name} reference order");
            assert_eq!(feature["file"], format!("{name}.json"));
            assert_eq!(
                feature["sha256"],
                hex_digest(&Sha256::digest(definition.as_bytes())),
                "{name} definition SHA-256"
            );
            let asset: Value = serde_json::from_str(definition).unwrap();
            assert_eq!(asset["name"], name);
            assert_eq!(asset["factor_set"], set, "{name}");
            assert_eq!(
                asset["factor_set_version"], manifest["factor_set_version"],
                "{name}"
            );
            let expr = FactorExpr::compile_with_allowed_fields(
                asset["expression"].as_str().unwrap(),
                &fields,
            )
            .unwrap_or_else(|e| panic!("{name} compile: {e}"));
            let batch = expr
                .evaluate_panel(&panel)
                .unwrap_or_else(|e| panic!("{name} batch: {e}"));
            check_reference(&name, &record, &batch);
            for (len, prefix) in &prefixes {
                let actual = expr
                    .evaluate_panel(prefix)
                    .unwrap_or_else(|e| panic!("{name} prefix {len}: {e}"));
                assert_eq!(actual.len(), INSTRUMENTS, "{name} prefix {len}");
                for (i, row) in actual.iter().enumerate() {
                    assert_eq!(row, &batch[i][..*len], "{name} prefix {len} i={i}");
                }
            }
            check_events(&name, &expr, &events, &batch);
        }
    }
    assert!(
        records.next().is_none(),
        "unexpected trailing reference record"
    );
}
