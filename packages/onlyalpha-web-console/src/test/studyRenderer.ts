import { createElement as h, useState } from "react";
import { createRoot } from "react-dom/client";
import { PriceChart } from "../charts/lightweight/PriceChart";
import { studySeriesFixture } from "./studySeries";
import type { ChartStudyInstance } from "../features/workspace/chartStudy";
import "../app/styles/tokens.css";
import "../features/workspace/chartStudy.css";

const { instance, bars, evidence } = studySeriesFixture();
const initial: readonly ChartStudyInstance[] = Array.from({ length: 4 }, (_, index) => ({
    ...instance,
    instanceId: `controlled-${String(index)}`,
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
                      bars: allBars,
                      barSemantic: instance.context.barSemantic,
                      contextKey: context,
                      studies,
                      selectedStudyId: selected,
                      incarnationKey: evidence.incarnationKey,
                      chartType: type,
                      studyEvidence: initial.map((item) => ({
                          ...evidence,
                          instanceId: item.instanceId
                      }))
                  })
                : null
        )
    );
}
const root = document.getElementById("root");
if (root === null) throw new Error("Missing root");
createRoot(root).render(h(Harness));
