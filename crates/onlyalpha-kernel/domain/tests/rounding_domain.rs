use onlyalpha_domain::numeric::{
    OnlyDecimal, OnlyRoundingMode, only_increment, only_quantize_with_rounding,
};
#[test]
fn business_rounding_uses_the_explicit_mode_once() {
    for row in include_str!("../../../../test-data/domain/rounding-v1.tsv")
        .lines()
        .filter(|line| !line.starts_with('#'))
    {
        let fields: Vec<_> = row.split('\t').collect();
        let mode: OnlyRoundingMode = fields[1].parse().unwrap();
        let value: OnlyDecimal = fields[2].parse().unwrap();
        let quantum: OnlyDecimal = fields[3].parse().unwrap();
        let result = match fields[0] {
            "quantize" => only_quantize_with_rounding(&value, &quantum, mode),
            "increment" => only_increment(&value, &quantum, mode),
            _ => panic!("unknown shared operation"),
        }
        .unwrap();
        assert_eq!(result.to_string(), fields[4], "{row}");
    }
}
