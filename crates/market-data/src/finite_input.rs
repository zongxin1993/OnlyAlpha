//! 有限闭合 Bar 切片的行情轴规则；不证明来源、内容摘要或读取权限。
use onlyalpha_domain::{market::OnlyBar, time::OnlyTimestamp};

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum InputError {
    InvalidAxis,
    AxisMismatch,
}

/// 按 Bar 结束事件排列的半开区间。构造时验证计数，逐行检查缺口和重复。
#[derive(Clone, Copy, Debug)]
pub struct Axis {
    start: i64,
    end: i64,
    stride: i64,
    rows: usize,
}
impl Axis {
    pub fn new(start: i64, end: i64, stride: i64, rows: usize) -> Result<Self, InputError> {
        let width = i128::from(end) - i128::from(start);
        if stride <= 0
            || width <= 0
            || width % i128::from(stride) != 0
            || usize::try_from(width / i128::from(stride)).ok() != Some(rows)
        {
            return Err(InputError::InvalidAxis);
        }
        Ok(Self {
            start,
            end,
            stride,
            rows,
        })
    }
    pub fn rows(&self) -> usize {
        self.rows
    }
    pub fn check(&self, index: usize, bar: &OnlyBar) -> Result<(), InputError> {
        let expected = i128::from(self.start)
            + i128::try_from(index).map_err(|_| InputError::AxisMismatch)?
                * i128::from(self.stride);
        let actual = OnlyTimestamp::from_datetime(*bar.bar_end());
        if index >= self.rows
            || expected >= i128::from(self.end)
            || actual.unix_nanos() != &expected.into()
            || !bar.is_closed()
        {
            return Err(InputError::AxisMismatch);
        }
        Ok(())
    }
}
