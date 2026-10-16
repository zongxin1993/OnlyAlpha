const { test } = require("node:test");
const assert = require("node:assert/strict");
const publish = require("../../scripts/publish_github_release.cjs");

const sha = "a".repeat(40);
const item = {
    previous_version: "0.9.12",
    version: "0.9.13",
    tag: "v0.9.13",
    sha,
};
const missing = () => Object.assign(new Error("Not found"), { status: 404 });
function fixture() {
    const state = { tag: null, release: null, creates: 0, releaseCreates: 0 };
    const git = {
        getRef: async () => {
            if (!state.tag) throw missing();
            return { data: { object: state.tag } };
        },
        createRef: async ({ sha }) => {
            state.creates++;
            state.tag = { type: "commit", sha };
        },
        getTag: async () => ({ data: { object: { type: "commit", sha } } }),
    };
    const repos = {
        getReleaseByTag: async () => {
            if (!state.release) throw missing();
            return { data: state.release };
        },
        createRelease: async (args) => {
            state.releaseCreates++;
            assert.equal(args.target_commitish, sha);
            assert.equal(args.generate_release_notes, true);
            assert.equal(args.draft, false);
            assert.equal(args.prerelease, false);
            state.release = {
                tag_name: args.tag_name,
                draft: false,
                prerelease: false,
                published_at: "2026-10-16T00:00:00Z",
                html_url: "https://example.invalid/release",
            };
            return { data: state.release };
        },
    };
    return {
        state,
        git,
        repos,
        run: () =>
            publish({
                github: { rest: { git, repos } },
                context: { repo: { owner: "owner", repo: "repo" } },
                core: { notice: () => {} },
                plan: [item],
            }),
    };
}

test("creates exact tag and release; repeats are read only", async () => {
    const f = fixture();
    await f.run();
    await f.run();
    assert.equal(f.state.creates, 1);
    assert.equal(f.state.releaseCreates, 1);
});
test("accepts an annotated tag only after exact commit peeling", async () => {
    const f = fixture();
    f.state.tag = { type: "tag", sha: "b".repeat(40) };
    await f.run();
    assert.equal(f.state.creates, 0);
});
test("wrong existing tag never creates a release", async () => {
    const f = fixture();
    f.state.tag = { type: "commit", sha: "b".repeat(40) };
    await assert.rejects(f.run(), /commit/);
    assert.equal(f.state.releaseCreates, 0);
});
test("draft and prerelease releases are not silently republished", async () => {
    for (const field of ["draft", "prerelease"]) {
        const f = fixture();
        await f.run();
        f.state.release[field] = true;
        await assert.rejects(f.run(), /published/);
        assert.equal(f.state.releaseCreates, 1);
    }
});
test("403 is not treated as absence", async () => {
    const f = fixture();
    f.git.getRef = async () => {
        throw Object.assign(new Error("denied"), { status: 403 });
    };
    await assert.rejects(f.run(), /denied/);
    assert.equal(f.state.creates, 0);
});
test("recovers a tag-only partial publication on rerun", async () => {
    const f = fixture();
    const create = f.repos.createRelease;
    f.repos.createRelease = async () => {
        throw Object.assign(new Error("denied"), { status: 403 });
    };
    await assert.rejects(f.run(), /denied/);
    f.repos.createRelease = create;
    await f.run();
    assert.equal(f.state.creates, 1);
    assert.equal(f.state.releaseCreates, 1);
});
test("reconciles 422 tag and release races without overwriting", async () => {
    const f = fixture();
    const create = f.repos.createRelease;
    f.git.createRef = async () => {
        f.state.tag = { type: "commit", sha };
        throw Object.assign(new Error("exists"), { status: 422 });
    };
    f.repos.createRelease = async (args) => {
        await create(args);
        throw Object.assign(new Error("exists"), { status: 422 });
    };
    await f.run();
    assert.equal(f.state.releaseCreates, 1);
});
test("tag race to another commit is rejected", async () => {
    const f = fixture();
    f.git.createRef = async () => {
        f.state.tag = { type: "commit", sha: "c".repeat(40) };
        throw Object.assign(new Error("exists"), { status: 422 });
    };
    await assert.rejects(f.run(), /commit/);
    assert.equal(f.state.releaseCreates, 0);
});
test("tag mutation after publishing is detected", async () => {
    const f = fixture();
    const create = f.repos.createRelease;
    f.repos.createRelease = async (args) => {
        const result = await create(args);
        f.state.tag = { type: "commit", sha: "c".repeat(40) };
        return result;
    };
    await assert.rejects(f.run(), /commit/);
});
test("malformed plan does not write to GitHub", async () => {
    const f = fixture();
    await assert.rejects(
        publish({
            github: { rest: { git: f.git, repos: f.repos } },
            context: { repo: {} },
            core: { notice: () => {} },
            plan: [{ ...item, tag: "master" }],
        }),
        /plan/,
    );
    assert.equal(f.state.creates, 0);
});
