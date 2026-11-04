import { z } from "zod";

export class ProductRequestError extends Error {}

export async function request<T>(
    path: string,
    schema: z.ZodType<T>,
    body?: object,
    command?: string
): Promise<T> {
    const r = await fetch(path, {
        method: body === undefined ? "GET" : "POST",
        credentials: "same-origin",
        cache: "no-store",
        headers: {
            "Content-Type": "application/json",
            ...(command === undefined ? {} : { "Idempotency-Key": command })
        },
        ...(body === undefined ? {} : { body: JSON.stringify(body) })
    });
    const data: unknown = await r.json();
    if (!r.ok) {
        const code = z
            .union([
                z.object({ error: z.object({ code: z.string() }) }).transform((v) => v.error.code),
                z.object({ error: z.string() }).transform((v) => v.error),
                z.object({ detail: z.string() }).transform((v) => v.detail)
            ])
            .safeParse(data);
        throw new ProductRequestError(code.success ? code.data : "服务响应不可用，请核对原操作");
    }
    return schema.parse(data);
}
