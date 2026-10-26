// Trusted master-push publisher. Tags and published releases are never rewritten.
module.exports = async function publish({ github, context, core, plan }) {
    const repo = context.repo;
    for (const item of plan) {
        if (
            !/^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$/.test(
                item.version,
            ) ||
            !/^(libs|backend|frontend|plugin-[a-z0-9]+(?:-[a-z0-9]+)*)$/.test(item.unit) ||
            item.tag !== `${item.unit}-v${item.version}` ||
            !/^[0-9a-f]{40}$/.test(item.sha) ||
            item.sha === "0".repeat(40)
        ) {
            throw new Error("Invalid release plan");
        }
    }
    async function optional(operation) {
        try {
            return (await operation()).data;
        } catch (error) {
            if (error.status === 404) return null;
            throw error;
        }
    }
    async function verifyTag(item) {
        const ref = await optional(() =>
            github.rest.git.getRef({ ...repo, ref: `tags/${item.tag}` }),
        );
        if (ref === null) return false;
        let object = ref.object;
        for (let depth = 0; object.type === "tag" && depth < 10; depth++) {
            object = (
                await github.rest.git.getTag({ ...repo, tag_sha: object.sha })
            ).data.object;
        }
        if (object.type !== "commit" || object.sha !== item.sha) {
            throw new Error(
                `Release tag ${item.tag} differs from the exact release commit`,
            );
        }
        return true;
    }
    for (const item of plan) {
        if (!(await verifyTag(item))) {
            try {
                await github.rest.git.createRef({
                    ...repo,
                    ref: `refs/tags/${item.tag}`,
                    sha: item.sha,
                });
            } catch (error) {
                if (error.status !== 422) throw error;
            }
            if (!(await verifyTag(item)))
                throw new Error("Release tag creation unproven");
        }
        let release = await optional(() =>
            github.rest.repos.getReleaseByTag({ ...repo, tag: item.tag }),
        );
        if (release === null) {
            try {
                release = (
                    await github.rest.repos.createRelease({
                        ...repo,
                        tag_name: item.tag,
                        target_commitish: item.sha,
                        name: `OnlyAlpha ${item.unit} ${item.version}`,
                        body: `OnlyAlpha ${item.unit}: ${item.previous_version} → ${item.version}`,
                        generate_release_notes: true,
                        draft: false,
                        prerelease: false,
                        make_latest: "legacy",
                    })
                ).data;
            } catch (error) {
                if (error.status !== 422) throw error;
                release = await optional(() =>
                    github.rest.repos.getReleaseByTag({
                        ...repo,
                        tag: item.tag,
                    }),
                );
            }
        }
        if (
            release === null ||
            release.tag_name !== item.tag ||
            release.draft ||
            release.prerelease ||
            !release.published_at
        ) {
            throw new Error(
                `Release ${item.tag} is not an exact published release`,
            );
        }
        if (!(await verifyTag(item)))
            throw new Error("Published release tag missing");
        core.notice(release.html_url);
    }
};
