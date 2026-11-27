use super::*;

fn column(values: &[i64]) -> Vec<Cell> {
    values.iter().map(|&v| Some(Decimal::from(v))).collect()
}

fn design() -> Vec<Vec<Cell>> {
    vec![
        column(&[10, 12, 7, 15, 22]),
        column(&[0, 1, 0, 0, 1]),
        column(&[0, 0, 1, 0, 1]),
        column(&[0, 0, 0, 1, 1]),
    ]
}

#[test]
fn last_residual_uses_three_predictors_and_intercept() {
    let mut columns = design();
    assert_eq!(regression_residual3(&columns, 0..=3), Ok(None));
    // [2, -1, -1, -1, 1] spans the residual space and has squared norm 8.
    assert_eq!(
        regression_residual3(&columns, 0..=4),
        Ok(Some(Decimal::from(1)))
    );
    columns[0][4] = Some(Decimal::from(14));
    assert_eq!(
        regression_residual3(&columns, 0..=4),
        Ok(Some(Decimal::zero()))
    );
    columns[0][4] = Some(Decimal::from(6));
    assert_eq!(
        regression_residual3(&columns, 0..=4),
        Ok(Some(Decimal::from(-1)))
    );
}

#[test]
fn residual_missing_and_affine_dependence() {
    let mut columns = design();
    for missing in 0..4 {
        let first = columns[missing][0].take();
        assert_eq!(regression_residual3(&columns, 0..=4), Ok(None));
        columns[missing][0] = first;
    }
    columns[3] = column(&[4, 6, 1, 4, 3]);
    assert_eq!(regression_residual3(&columns, 0..=4), Ok(None));
    *columns[3][3].as_mut().unwrap() += "1e-100".parse::<Decimal>().unwrap();
    assert_eq!(
        regression_residual3(&columns, 0..=4),
        Ok(Some("3.25".parse().unwrap()))
    );
}

#[test]
fn beta_filters_inside_the_selected_calendar_window() {
    let mut columns = vec![
        column(&[-999, 7, 100, 13, 999, 0, 19, -300]),
        column(&[999, 1, 5, 3, 0, 8, 5, 22]),
        column(&[1, 1, 2, 1, 1, 1, 1, 1]),
    ];
    columns[0][5] = None;
    columns[1][4] = None;
    columns[2][7] = None;
    assert_eq!(
        conditional_beta(&columns, 1..=7),
        Ok(Some(Decimal::from(3)))
    );
    assert_eq!(conditional_beta(&columns, 4..=7), Ok(None));
    columns[1][3] = Some(Decimal::from(1));
    assert_eq!(conditional_beta(&columns, 1..=5), Ok(None));
}

#[test]
fn beta_centers_decimal_pairs_and_rounds_half_even() {
    let origin: Decimal = "1e100".parse().unwrap();
    let x = vec![Some(origin.clone()), Some(&origin + Decimal::from(2))];
    for (delta, expected) in [(1, "0"), (3, "0.000000000002"), (-3, "-0.000000000002")] {
        let change = Decimal::new(delta.into(), 12);
        let y = vec![Some(origin.clone()), Some(&origin + change)];
        let columns = vec![y, x.clone(), column(&[1, 1])];
        assert_eq!(
            conditional_beta(&columns, 0..=1),
            Ok(Some(expected.parse().unwrap()))
        );
    }
}
