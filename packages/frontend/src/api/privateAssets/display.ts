import { z } from "zod";
export const displayFieldsSchema = z.strictObject({
    display_name: z.string().min(1),
    usage_summary: z.string().min(1)
});
export const factorDisplaySchema = displayFieldsSchema.extend({
    schema_version: z.literal(1),
    factor_id: z.string(),
    edit_number: z.number().int().min(1).max(Number.MAX_SAFE_INTEGER)
});
