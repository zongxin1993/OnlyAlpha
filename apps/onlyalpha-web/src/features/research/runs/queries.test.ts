import { shouldPollRunState } from "./queries";

it.each(["QUEUED", "RUNNING", "CANCEL_REQUESTED"])("polls non-terminal %s", (state) => {
    expect(shouldPollRunState(state)).toBe(true);
});

it.each(["COMPLETED", "FAILED", "CANCELLED"])("stops polling terminal %s", (state) => {
    expect(shouldPollRunState(state)).toBe(false);
});
