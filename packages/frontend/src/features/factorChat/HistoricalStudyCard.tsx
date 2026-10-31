import { useRef, useState } from "react";
import { Alert, Button, Card } from "antd";
import { request, studySchema, type Conversation, type Study } from "./api";
import { ResearchStudyPanel, type ResearchStudyActions } from "./ResearchStudyPanel";

type Turn = Conversation["turns"][number];
export function HistoricalStudyCard({
    sessionId,
    head,
    reference,
    advice
}: {
    readonly sessionId: string;
    readonly head: string;
    readonly reference: Turn["study_reference"];
    readonly advice: NonNullable<Turn["study"]>;
}) {
    const [original, setOriginal] = useState<Study | null>(null);
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState("");
    // Historical observation must never replace the composer's current confirmation target.
    const historicalActions = useRef<ResearchStudyActions>(null);
    async function observe() {
        if (reference?.fingerprint == null || reference.head !== head || busy) return;
        setBusy(true);
        setError("");
        try {
            const view = await request(
                `/api/v2/factor-studies/${reference.fingerprint}`,
                studySchema
            );
            if (
                view.fingerprint !== reference.fingerprint ||
                view.snapshot.origin.session_id !== sessionId ||
                view.snapshot.origin.event_fingerprint !== head
            )
                throw new Error("historical study binding mismatch");
            setOriginal(view);
        } catch {
            setError("原研究记录暂时无法核对，请稍后重新查看；不会创建新的研究。");
        } finally {
            setBusy(false);
        }
    }
    return (
        <Card size="small" className="factor-preview-card factor-preview-history">
            <section aria-label="历史研究建议">
                <h3>历史研究条件</h3>
                <p>
                    {advice.source.instrument_id} · {advice.timeframe_minutes} 分钟K线 · 预测未来{" "}
                    {advice.horizon_bars} 根
                </p>
                <p>{advice.rationale}</p>
                {reference?.fingerprint != null && original === null && (
                    <Button
                        loading={busy}
                        onClick={() => {
                            void observe();
                        }}
                    >
                        查看研究记录
                    </Button>
                )}
                {error !== "" && <Alert role="alert" type="warning" title={error} />}
                {original !== null && (
                    <ResearchStudyPanel
                        key={original.fingerprint}
                        study={original}
                        newWorkBlocked
                        actionRef={historicalActions}
                    />
                )}
            </section>
        </Card>
    );
}
