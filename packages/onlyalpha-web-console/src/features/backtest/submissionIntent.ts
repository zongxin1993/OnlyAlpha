import { z } from "zod";
import { backtestCreateSchema, type BacktestCreateTransport } from "../../api/research/schemas";
import { createUuidV4 } from "../../api/integrations/submissionIntent";

const pendingSchema = z.strictObject({
    commandId: z.uuid(),
    request: backtestCreateSchema,
    uncertain: z.boolean()
});
export type PendingBacktest = z.infer<typeof pendingSchema>;
const key = "onlyalpha.backtest.creation-intent/1";
// This is pending user intent, never a Run, execution state or result authority.
export function readPendingBacktest(): PendingBacktest | null {
    const raw = sessionStorage.getItem(key);
    return raw === null ? null : pendingSchema.parse(JSON.parse(raw));
}
export function persistBacktestIntent(value: PendingBacktest | null): void {
    if (value === null) sessionStorage.removeItem(key);
    else sessionStorage.setItem(key, JSON.stringify(pendingSchema.parse(value)));
}
export function newBacktestIntent(request: BacktestCreateTransport): PendingBacktest {
    return {
        commandId: createUuidV4(),
        request: backtestCreateSchema.parse(request),
        uncertain: false
    };
}
