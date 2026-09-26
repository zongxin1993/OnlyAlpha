import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { IntegrationType } from "../../../api/integrations/model";
import { IntegrationConfigurationForm } from "./IntegrationConfigurationForm";

const type: IntegrationType = {
    schema_version: 1,
    type_id: "test.market_data",
    category: "DATA_SOURCE",
    display_name: "Test market data",
    description: "Schema-driven fixture",
    provider_id: "test",
    implementation_id: "test",
    implementation_version: "1",
    public_api_version: "1.1",
    capabilities: ["HISTORICAL_BARS"],
    fingerprint: "a".repeat(64),
    configuration_contract: {
        schema_version: 1,
        fingerprint: "b".repeat(64),
        fields: [
            field("text", "STRING"),
            field("path", "PATH"),
            { ...field("choice", "ENUM"), enum_values: ["one", "two"] },
            field("enabled", "BOOLEAN"),
            field("count", "INTEGER"),
            field("ratio", "NUMBER"),
            field("timeout", "DURATION"),
            field("mapping", "STRING_INTEGER_MAP"),
            { ...field("token", "STRING"), secret: true },
            { ...field("advanced_value", "STRING"), advanced: true }
        ]
    },
    probe_contract: null
};

function field(
    field_id: string,
    value_kind: IntegrationType["configuration_contract"]["fields"][number]["value_kind"]
) {
    return {
        field_id,
        display_name: field_id.replace("_", " "),
        description: `${field_id} description`,
        value_kind,
        required: false,
        secret: false,
        advanced: false,
        default: null,
        enum_values: [],
        minimum: null,
        maximum: null,
        exclusive_minimum: false
    };
}

it("renders every current contract kind generically and groups advanced fields", () => {
    render(
        <IntegrationConfigurationForm
            descriptor={type}
            values={{}}
            secretStatuses={[{ field_id: "token", configured: true, generation: 3 }]}
            readOnly={false}
            onChange={() => undefined}
            onReplaceSecret={() => undefined}
            onClearSecret={() => undefined}
        />
    );
    expect(screen.getByLabelText("text")).toHaveAttribute("type", "text");
    expect(screen.getByLabelText("path")).toHaveAttribute("type", "text");
    expect(screen.getByRole("combobox", { name: "choice" })).toBeInTheDocument();
    expect(screen.getByRole("checkbox", { name: "enabled" })).toBeInTheDocument();
    expect(screen.getByLabelText("count")).toHaveAttribute("step", "1");
    expect(screen.getByLabelText("ratio")).toHaveAttribute("step", "any");
    expect(screen.getByLabelText("timeout")).toHaveAccessibleDescription("秒");
    expect(screen.getByRole("table", { name: "mapping" })).toBeInTheDocument();
    expect(
        within(screen.getByRole("group", { name: "高级设置" })).getByLabelText("advanced value")
    ).toBeInTheDocument();
    expect(screen.getByText("已配置 · generation 3")).toBeInTheDocument();
    expect(screen.queryByDisplayValue(/secret/i)).not.toBeInTheDocument();
});

it("keeps a replacement secret transient and clears the input after submission", async () => {
    const replace = vi.fn();
    render(
        <IntegrationConfigurationForm
            descriptor={type}
            values={{}}
            secretStatuses={[{ field_id: "token", configured: false, generation: null }]}
            readOnly={false}
            onChange={() => undefined}
            onReplaceSecret={replace}
            onClearSecret={() => undefined}
        />
    );
    const user = userEvent.setup();
    const secret = screen.getByLabelText("更换 token");
    await user.type(secret, "memory-only-value");
    await user.click(screen.getByRole("button", { name: "更换凭据" }));
    expect(replace).toHaveBeenCalledWith("token", "memory-only-value");
    expect(secret).toHaveValue("");
    expect(JSON.stringify(type)).not.toContain("memory-only-value");
});

it("disables all mutation controls for an archived Integration", () => {
    render(
        <IntegrationConfigurationForm
            descriptor={type}
            values={{}}
            secretStatuses={[{ field_id: "token", configured: true, generation: 1 }]}
            readOnly
            onChange={() => undefined}
            onReplaceSecret={() => undefined}
            onClearSecret={() => undefined}
        />
    );
    for (const control of document.querySelectorAll("input, select, button")) {
        expect(control).toBeDisabled();
    }
});

it("renders Binance market environment and endpoint profile through the generic enum form", async () => {
    const onChange = vi.fn();
    const binance = {
        ...type,
        type_id: "binance.spot.market_data",
        configuration_contract: {
            ...type.configuration_contract,
            fields: [
                {
                    ...field("environment", "ENUM"),
                    display_name: "Market Environment",
                    default: "GLOBAL",
                    enum_values: ["GLOBAL", "US", "SPOT_TESTNET"]
                },
                {
                    ...field("endpoint_profile", "ENUM"),
                    display_name: "Endpoint Profile",
                    default: "PUBLIC_MARKET_DATA",
                    enum_values: [
                        "DEFAULT",
                        "PUBLIC_MARKET_DATA",
                        "STANDARD",
                        "GCP",
                        "API1",
                        "API2",
                        "API3",
                        "API4"
                    ]
                }
            ]
        }
    } satisfies IntegrationType;
    render(
        <IntegrationConfigurationForm
            descriptor={binance}
            values={{ environment: "US", endpoint_profile: "DEFAULT" }}
            secretStatuses={[]}
            readOnly={false}
            onChange={onChange}
            onReplaceSecret={() => undefined}
            onClearSecret={() => undefined}
        />
    );

    expect(screen.getByRole("combobox", { name: "Market Environment" })).toHaveValue("US");
    expect(screen.getByRole("combobox", { name: "Endpoint Profile" })).toHaveValue("DEFAULT");
    await userEvent.selectOptions(
        screen.getByRole("combobox", { name: "Endpoint Profile" }),
        "PUBLIC_MARKET_DATA"
    );
    expect(onChange).toHaveBeenCalledWith("endpoint_profile", "PUBLIC_MARKET_DATA");
});
