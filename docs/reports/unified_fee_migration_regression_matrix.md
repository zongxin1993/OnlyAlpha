# Unified Fee Migration Regression Matrix

| Baseline failures | Old assumption | Authoritative behavior | Treatment |
| --- | --- | --- | --- |
| Scenario/CLI/Conformance (3) | Fractional order can use an unquantized fee input | Fee request notional is quantized to its currency before `OnlyMoney` construction | A: production fix |
| Engine resource conflict (1) | Broker fixed commission is resource configuration | Typed broker fee configuration participates in resource identity | C: new fee configuration assertion |
| MACD product golden (1) | Two fixed 1.00 commissions | Market schedule produces 21.99 of immutable fee facts | C: golden migration |
| Integration scenario 008 and dependent vertical-slice parametrizations (32) | Fixed fee and Broker/local cash equality | Runtime applies market fee facts; Broker snapshot has no reported local fee | C: invariant migration |

The 32 dependent parametrizations share the same scenario assertion and are
not independent production failures. Their migrated invariant compares the
explicit Runtime fee total to the Broker/Runtime difference.
