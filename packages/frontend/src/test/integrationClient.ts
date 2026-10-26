import type { IntegrationApiClient } from "../api/integrations/client";
import type {
    IntegrationOperationalStatus,
    IntegrationSummary,
    IntegrationType
} from "../api/integrations/model";

const unused = (): Promise<never> => Promise.reject(new Error("unused Integration API method"));

export function dataSourceType(overrides: Partial<IntegrationType> = {}): IntegrationType {
    return {
        schema_version: 1,
        type_id: "test.market_data",
        category: "DATA_SOURCE",
        display_name: "Test Source",
        description: "Fixture",
        provider_id: "test",
        implementation_id: "test",
        implementation_version: "1",
        public_api_version: "1.1",
        capabilities: ["HISTORICAL_BARS"],
        fingerprint: "b".repeat(64),
        configuration_contract: { schema_version: 1, fingerprint: "c".repeat(64), fields: [] },
        probe_contract: null,
        ...overrides
    };
}

export function dataSourceSummary(overrides: Partial<IntegrationSummary> = {}): IntegrationSummary {
    return {
        schema_version: 1,
        integration_id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
        type_id: "test.market_data",
        display_name: "Fixture Source",
        lifecycle_state: "ACTIVE",
        current_revision_fingerprint: "a".repeat(64),
        created_at: "2026-09-21T00:00:00Z",
        updated_at: "2026-09-21T00:00:00Z",
        category: "DATA_SOURCE",
        draft_version: 1,
        pinned_type_descriptor_fingerprint: "b".repeat(64),
        ...overrides
    };
}

export function operationalStatus(
    overrides: Partial<IntegrationOperationalStatus> = {}
): IntegrationOperationalStatus {
    return {
        schema_version: 1,
        integration_id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
        revision_fingerprint: "a".repeat(64),
        status: "READY",
        probe_attempt_id: null,
        checked_at: "2026-09-21T09:42:16Z",
        probe_supported: true,
        ...overrides
    };
}

export function integrationClient(
    overrides: Partial<IntegrationApiClient> = {}
): IntegrationApiClient {
    return {
        listTypes: () => Promise.resolve([]),
        listDataSources: () => Promise.resolve([]),
        createIntegration: unused,
        getIntegration: unused,
        getDraft: unused,
        updateDraft: unused,
        setSecret: unused,
        clearSecret: unused,
        resetDraftContract: unused,
        publish: unused,
        setLifecycle: unused,
        getOperationalStatus: () => Promise.resolve(operationalStatus()),
        probe: unused,
        listProbeAttempts: () => Promise.resolve([]),
        getProbeAttempt: unused,
        listRevisions: () => Promise.resolve([]),
        ...overrides
    };
}
