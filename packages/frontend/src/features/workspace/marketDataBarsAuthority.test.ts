import type { MarketDataBars } from "../../api/marketData/model";
import { marketDataBarSemantic } from "../../api/marketData/model";
import { FIXTURE_REFERENCE, marketDataBars } from "../../test/marketDataClient";
import {
    MarketDataBarsAuthorityMismatchError,
    onlyAssertMarketDataBarsAuthority,
    type MarketDataBarsExpectation
} from "./marketDataBarsAuthority";

const expected: MarketDataBarsExpectation = {
    reference: FIXTURE_REFERENCE,
    expectedSourceId: "test.market_data.live",
    instrumentId: "BTCUSDT.TEST",
    barSemantic: marketDataBarSemantic(1),
    anchorKind: "BEFORE_TIME",
    beforeNs: "1767225720000000000",
    targetBarCount: 2
};

it("admits exact responses for all coverage states and both anchors", () => {
    for (const status of ["COMPLETE", "INCOMPLETE", "UNPROVABLE"] as const) {
        const page = marketDataBars();
        page.coverage.status = status;
        if (status !== "COMPLETE") {
            page.bars = [];
            page.history_projection_fingerprint = null;
            page.resume_after_sequence = null;
            page.resume_plan_fingerprint = null;
        }
        expect(() => {
            onlyAssertMarketDataBarsAuthority(expected, page);
        }).not.toThrow();
    }
    expect(() => {
        onlyAssertMarketDataBarsAuthority(
            { ...expected, anchorKind: "LATEST_CLOSED" },
            marketDataBars({ anchor_kind: "LATEST_CLOSED", requested_before_ns: null })
        );
    }).not.toThrow();
    const reference = {
        integration_id: FIXTURE_REFERENCE.integration_id,
        integration_revision_fingerprint: FIXTURE_REFERENCE.integration_revision_fingerprint
    };
    expect(() => {
        onlyAssertMarketDataBarsAuthority({ ...expected, reference }, marketDataBars());
    }).not.toThrow();
});

const mutations: readonly [string, (page: MarketDataBars) => void][] = [
    [
        "preview family",
        (p) => {
            p.closed_only = false;
        }
    ],
    [
        "preview Bar",
        (p) => {
            p.bars = p.bars.map((bar) => ({ ...bar, closed: false }));
        }
    ],
    [
        "integration_id",
        (p) => {
            p.source_selection.integration_id = "other";
        }
    ],
    [
        "integration_revision_fingerprint",
        (p) => {
            p.source_selection.integration_revision_fingerprint = "b".repeat(64);
        }
    ],
    [
        "type_id",
        (p) => {
            p.source_selection.type_id = "other";
        }
    ],
    [
        "source_id",
        (p) => {
            p.source_selection.source_id = "other";
        }
    ],
    [
        "instrument_id",
        (p) => {
            p.instrument_id = "ETHUSDT.TEST";
        }
    ],
    [
        "bar_semantic",
        (p) => {
            p.bar_semantic = marketDataBarSemantic(7);
        }
    ],
    [
        "anchor_kind",
        (p) => {
            p.anchor_kind = "LATEST_CLOSED";
        }
    ],
    [
        "requested_before_ns",
        (p) => {
            p.requested_before_ns = "1767225720000000001";
        }
    ],
    [
        "requested_bar_count",
        (p) => {
            p.requested_bar_count = 240;
        }
    ],
    [
        "malformed start",
        (p) => {
            p.resolved_start_ns = "invalid";
        }
    ],
    [
        "malformed end",
        (p) => {
            p.resolved_end_ns = "-1";
        }
    ],
    [
        "empty window",
        (p) => {
            p.resolved_start_ns = p.resolved_end_ns;
        }
    ],
    [
        "reversed window",
        (p) => {
            p.resolved_start_ns = "1767225780000000000";
        }
    ],
    [
        "end beyond before by one nanosecond",
        (p) => {
            p.resolved_end_ns = "1767225720000000001";
        }
    ],
    [
        "bar before window",
        (p) => {
            p.bars = p.bars.map((bar, index) =>
                index === 0 ? { ...bar, bar_start_ns: "1767225599999999999" } : bar
            );
        }
    ],
    [
        "bar after window",
        (p) => {
            p.bars = p.bars.map((bar, index) =>
                index === 1 ? { ...bar, bar_end_ns: "1767225720000000001" } : bar
            );
        }
    ],
    [
        "bar crossing before",
        (p) => {
            p.bars = p.bars.map((bar, index) =>
                index === 0 ? { ...bar, bar_end_ns: "1767225780000000000" } : bar
            );
        }
    ]
];

it.each(mutations)("rejects %s with the stable mismatch code", (_name, mutate) => {
    const page = structuredClone(marketDataBars());
    mutate(page);
    expect(() => {
        onlyAssertMarketDataBarsAuthority(expected, page);
    }).toThrow(MarketDataBarsAuthorityMismatchError);
    expect(() => {
        onlyAssertMarketDataBarsAuthority(expected, page);
    }).toThrow(/MARKET_DATA_HISTORY_RESPONSE_MISMATCH/);
});

it.each(["source_selection", "instrument_id", "bar_semantic", "bars", "resolved_end_ns"])(
    "fails closed on missing mandatory %s rather than certifying absence",
    (field) => {
        const page = structuredClone(marketDataBars());
        Reflect.deleteProperty(page, field);
        expect(() => {
            onlyAssertMarketDataBarsAuthority(expected, page);
        }).toThrow(MarketDataBarsAuthorityMismatchError);
    }
);
