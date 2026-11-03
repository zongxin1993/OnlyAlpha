# Account comparison data

Literal balances are independently specified from cash conservation. Native Account lifecycle tests apply each explicit reservation/fill and compare cash, remaining reservation, fees, realized PnL and equity against every expected row, including fresh restoration after each fill. The output checker uses the same literals without importing a Python Manager or Execution reducer. Common economics do not certify old reader parity, Runtime activation or deployment/history migration.

The rebate-exceeds-buy case retains an authoritative rebate greater than purchase cost and its negative net fee. The older Python direct AccountTradeCashFlow DTO could not represent that input; removing the old comparison path does not remove this case or weaken the native signed-fee contract.
