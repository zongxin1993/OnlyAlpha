import { z } from "zod";
import { request } from "../productRequest";

// /health/live 与 /health/ready 是 product-api v2 正式契约端点（NativeHealthDto）。
// /health/execution 恒 501，不接入。此处只读，不新增依赖。
const healthSchema = z.object({ status: z.enum(["LIVE", "READY"]) });

export type HealthStatus = z.infer<typeof healthSchema>["status"];

export function getLiveHealth(): Promise<HealthStatus> {
    return request("/health/live", healthSchema).then((value) => value.status);
}

export function getReadyHealth(): Promise<HealthStatus> {
    return request("/health/ready", healthSchema).then((value) => value.status);
}
