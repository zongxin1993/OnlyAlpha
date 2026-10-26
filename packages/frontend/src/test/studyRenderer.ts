import { createElement as h, useState } from "react";
import { createRoot } from "react-dom/client";
import { PriceChart } from "../charts/lightweight/PriceChart";
import { studySeriesFixture } from "./studySeries";
import type { ChartStudyInstance } from "../features/workspace/chartStudy";
import "../app/styles/tokens.css";
import "../features/workspace/chartStudy.css";

const { instance, bars: originalBars, evidence } = studySeriesFixture();
const bars = originalBars.map((bar, index) => ({
    ...bar,
    close: index % 3 === 0 ? "101" : index % 3 === 1 ? "99" : "100",
    numeric: { ...bar.numeric, close: index % 3 === 0 ? 101 : index % 3 === 1 ? 99 : 100 }
}));
const initial: readonly ChartStudyInstance[] = Array.from({ length: 4 }, (_, index) => ({
    ...instance,
    instanceId: `controlled-${String(index)}`,
    configuration: {
        ...instance.configuration,
        parameters: {
            ...instance.configuration.parameters,
            period: { type: "INTEGER", value: index === 1 ? 10 : 20 }
        }
    },
    presentation: {
        ...instance.presentation,
        placement: index < 2 ? "PRICE_OVERLAY" : "SEPARATE_PANE",
        color: index % 2 === 0 ? "#c8332a" : "#2f7d47"
    }
}));
function Harness() {
    const firstBar = bars[0];
    if (firstBar === undefined) throw new Error("Missing controlled bar");
    const [studies, setStudies] = useState(initial);
    const [selected, setSelected] = useState<string | null>(null);
    const [context, setContext] = useState(instance.context.key);
    const [mounted, setMounted] = useState(true);
    const [type, setType] = useState<"LINE" | "CANDLESTICK">("CANDLESTICK");
    const [prepend, setPrepend] = useState(false);
    const [tick, setTick] = useState(0);
    const [units, setUnits] = useState(false);
    const lastBar = bars[bars.length - 1];
    if (lastBar === undefined) throw new Error("Missing last controlled Bar");
    const preview =
        tick === 0
            ? null
            : {
                  ...lastBar,
                  closed: false,
                  time: (lastBar.time + 900) as typeof lastBar.time,
                  barStartNs: (BigInt(lastBar.barStartNs) + 900000000000n).toString(),
                  barEndNs: (BigInt(lastBar.barEndNs) + 900000000000n).toString(),
                  close: String(101 + tick / 100),
                  numeric: { ...lastBar.numeric, close: 101 + tick / 100 }
              };
    const allBars = prepend
        ? [
              {
                  ...firstBar,
                  time: (firstBar.time - 900) as typeof firstBar.time,
                  barStartNs: (BigInt(firstBar.barStartNs) - 900000000000n).toString()
              },
              ...bars
          ]
        : bars;
    return h(
        "main",
        null,
        h(
            "h1",
            { style: { fontSize: "1rem", overflowWrap: "anywhere" } },
            "CONTROLLED_TEST_EVIDENCE · no Product Result"
        ),
        h(
            "button",
            {
                onClick: () => {
                    setType((previous) => (previous === "LINE" ? "CANDLESTICK" : "LINE"));
                }
            },
            "chart type"
        ),
        h(
            "button",
            {
                onClick: () => {
                    setPrepend(true);
                }
            },
            "prepend history"
        ),
        h(
            "button",
            {
                onClick: () => {
                    setTick((previous) => previous + 1);
                }
            },
            "preview tick"
        ),
        h(
            "button",
            {
                onClick: () => {
                    setContext("different-context");
                }
            },
            "change context"
        ),
        h(
            "button",
            {
                onClick: () => {
                    setMounted((previous) => !previous);
                }
            },
            "mount / unmount"
        ),
        h(
            "button",
            {
                onClick: () => {
                    setUnits((previous) => !previous);
                }
            },
            "controlled units"
        ),
        ...studies.map((study) =>
            h(
                "div",
                { key: study.instanceId },
                h(
                    "button",
                    {
                        onClick: () => {
                            setSelected(study.instanceId);
                        }
                    },
                    `select ${study.instanceId}`
                ),
                h(
                    "button",
                    {
                        onClick: () => {
                            setStudies((previous) =>
                                previous.map((item) =>
                                    item.instanceId === study.instanceId
                                        ? {
                                              ...item,
                                              presentation: {
                                                  ...item.presentation,
                                                  visible: !item.presentation.visible
                                              }
                                          }
                                        : item
                                )
                            );
                        }
                    },
                    `visibility ${study.instanceId}`
                ),
                h(
                    "button",
                    {
                        onClick: () => {
                            setStudies((previous) =>
                                previous.map((item) =>
                                    item.instanceId === study.instanceId
                                        ? {
                                              ...item,
                                              presentation: {
                                                  ...item.presentation,
                                                  placement:
                                                      item.presentation.placement ===
                                                      "PRICE_OVERLAY"
                                                          ? "SEPARATE_PANE"
                                                          : "PRICE_OVERLAY"
                                              }
                                          }
                                        : item
                                )
                            );
                        }
                    },
                    `placement ${study.instanceId}`
                ),
                h(
                    "button",
                    {
                        onClick: () => {
                            setStudies((previous) =>
                                previous.filter((item) => item.instanceId !== study.instanceId)
                            );
                        }
                    },
                    `remove ${study.instanceId}`
                )
            )
        ),
        h(
            "div",
            { style: { height: 520, position: "relative", minWidth: 0 } },
            mounted
                ? h(PriceChart, {
                      key: context,
                      bars: tick === 0 ? allBars : [...allBars],
                      liveBar: preview,
                      barSemantic: instance.context.barSemantic,
                      contextKey: context,
                      studies,
                      selectedStudyId: selected,
                      incarnationKey: evidence.incarnationKey,
                      chartType: type,
                      studyEvidence: initial.map((item) => ({
                          ...evidence,
                          instanceId: item.instanceId,
                          configurationKey: JSON.stringify(item.configuration),
                          points:
                              item.instanceId === "controlled-1"
                                  ? evidence.points.map((point) => ({
                                        ...point,
                                        value:
                                            point.value === null ? null : "100.500000000000000001"
                                    }))
                                  : evidence.points,
                          outputUnit:
                              units && item.instanceId === "controlled-0"
                                  ? "PERCENT"
                                  : units && item.instanceId === "controlled-1"
                                    ? null
                                    : "PRICE"
                      }))
                  })
                : null
        )
    );
}
const root = document.getElementById("root");
if (root === null) throw new Error("Missing root");
createRoot(root).render(h(Harness));
