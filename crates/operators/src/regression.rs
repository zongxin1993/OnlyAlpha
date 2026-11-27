use super::{Cell, Decimal, Result, div, q};
use bigdecimal::Zero;
use std::array;
use std::ops::RangeInclusive;

fn determinant([[a, b, c], [d, e, f], [g, h, i]]: &[[Decimal; 3]; 3]) -> Decimal {
    a * (e * i - f * h) - b * (d * i - f * g) + c * (d * h - e * g)
}

pub(super) fn regression_residual3(
    columns: &[Vec<Cell>],
    window: RangeInclusive<usize>,
) -> Result<Cell> {
    let last = *window.end();
    if window.is_empty() || last - *window.start() < 4 {
        return Ok(None);
    }
    let [response, x1, x2, x3] = columns else {
        return Err(super::Error::InvalidInputs);
    };
    let (Some(y0), Some(a0), Some(b0), Some(c0)) =
        (&response[last], &x1[last], &x2[last], &x3[last])
    else {
        return Ok(None);
    };
    let count = Decimal::from((last - *window.start() + 1) as u64);
    let mut sums: [Decimal; 4] = array::from_fn(|_| Decimal::zero());
    let mut products: [[Decimal; 4]; 3] = array::from_fn(|_| array::from_fn(|_| Decimal::zero()));
    for i in window {
        let (Some(y), Some(a), Some(b), Some(c)) = (&response[i], &x1[i], &x2[i], &x3[i]) else {
            return Ok(None);
        };
        let row = [a - a0, b - b0, c - c0, y - y0];
        for (sum, value) in sums.iter_mut().zip(&row) {
            *sum += value;
        }
        for k in 0..3 {
            for j in k..4 {
                products[k][j] += &row[k] * &row[j];
            }
        }
    }
    // Centered normal equations scaled by n keep all rank decisions exact.
    let centered =
        |i: usize, j: usize| &count * &products[i.min(j)][i.max(j)] - &sums[i] * &sums[j];
    let gram = array::from_fn(|i| array::from_fn(|j| centered(i, j)));
    let det = determinant(&gram);
    if det.is_zero() {
        return Ok(None);
    }
    let rhs: [Decimal; 3] = array::from_fn(|i| centered(i, 3));
    // The last row is the translation origin, so its residual is minus the fitted intercept.
    let mut residual = -(&sums[3] * &det);
    for k in 0..3 {
        let mut replaced = gram.clone();
        for i in 0..3 {
            replaced[i][k] = rhs[i].clone();
        }
        residual += &sums[k] * determinant(&replaced);
    }
    q(div(&residual, &(&count * det))?).map(Some)
}

pub(super) fn conditional_beta(
    columns: &[Vec<Cell>],
    window: RangeInclusive<usize>,
) -> Result<Cell> {
    let [response, predictor, condition] = columns else {
        return Err(super::Error::InvalidInputs);
    };
    let one = Decimal::from(1);
    let mut pairs = window.filter_map(|i| {
        if condition[i].as_ref() == Some(&one) {
            predictor[i].as_ref().zip(response[i].as_ref())
        } else {
            None
        }
    });
    let Some((x0, y0)) = pairs.next() else {
        return Ok(None);
    };
    let mut count = 1u64;
    let (mut sx, mut sy) = (Decimal::zero(), Decimal::zero());
    let (mut sxx, mut sxy) = (Decimal::zero(), Decimal::zero());
    for (x, y) in pairs {
        let (x, y) = (x - x0, y - y0);
        sxx += &x * &x;
        sxy += &x * &y;
        sx += x;
        sy += y;
        count += 1;
    }
    if count < 2 {
        return Ok(None);
    }
    let n = Decimal::from(count);
    let xx = &n * sxx - &sx * &sx;
    if xx.is_zero() {
        return Ok(None);
    }
    q(div(&(&n * sxy - sx * sy), &xx)?).map(Some)
}

#[cfg(test)]
#[path = "tests/regression_tests.rs"]
mod tests;
