export type DecimalText = string & { readonly __decimalText: unique symbol };
const DECIMAL = /^-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?$/;

export function parseDecimalText(value: string): DecimalText {
    if (!DECIMAL.test(value)) throw new Error("Decimal must be canonical fixed decimal text");
    return value as DecimalText;
}
