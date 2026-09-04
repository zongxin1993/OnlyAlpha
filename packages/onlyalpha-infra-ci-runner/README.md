# OnlyAlpha CI Runner Toolchain

This independently versioned Infrastructure component builds the shared container used by
OnlyAlpha repository test runners. It contains Python 3.12, a pinned `uv`, pinned validation
tools, and a pre-warmed `uv` cache. It contains no OnlyAlpha source, private asset, repository
credential, Research Evidence, release artifact, or runtime authority.

The default Python index is the Alibaba Cloud mirror. Operators may override
`PYPI_INDEX_URL` at image build time. Runtime workflows keep `UV_PYTHON_DOWNLOADS=never` and
may select another explicitly configured mirror without changing package identities.

Build and verify locally from the repository root:

```bash
docker buildx build \
  --platform linux/amd64 \
  --load \
  --file packages/onlyalpha-infra-ci-runner/Dockerfile \
  --tag onlyalpha-ci-runner:2026.9.4.1 \
  packages/onlyalpha-infra-ci-runner

docker run --rm onlyalpha-ci-runner:2026.9.4.1 onlyalpha-ci-verify
```

Publishing is a separate operator action. After publishing, configure the Gitea `act_runner`
label to resolve an operator-chosen label such as `onlyalpha-ci` to the image by immutable
digest, then set each private repository's `PRIVATE_ASSET_RUNNER_LABEL` variable to that label.
Do not put registry credentials or image digests into the private asset semantic/provider
identity.

The image removes repeated third-party toolchain downloads. Admission workflows must still
check out exact source, execute tests, and build candidate wheels on every pull request; the
cached environment never substitutes for those source-bound gates.
