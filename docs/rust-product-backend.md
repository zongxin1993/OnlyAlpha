# Rust Product backend construction

ADR 0141 selects Rust services/business logic and isolated Python Factor/Indicator execution. The Constitution and existing owning Contracts define semantics. A library build does not admit a Product writer or certify a migrated Web flow.

## Dependency map

1. **Product identity and persistence:** complete global Command Admission/Receipt, strict DTO/identity/error semantics, transaction participation, existing PostgreSQL facts, exact readers and bounded I/O. Reuse ADR 0104/0124; no second receipt store.
2. **Product ingress and node lifecycle:** native HTTP/WebSocket service, owner authentication, Source grants/revocation, local-session security, existing versioned wire Contracts, configuration, health, shutdown and recovery. A reverse proxy to Python does not satisfy this boundary.
3. **Integration and market inputs:** Integration types/Drafts/secrets/revisions/lifecycle/probes and native provider adapters; immutable acquisition, physical proofs, history/range/latest/quote reads, live continuity and stream backpressure. Preserve the normal configure-source and chart journeys.
4. **Workspace and calculations:** owning watchlist revisions/global receipts, chart catalog/readiness and transient chart studies. Native orchestration consumes bounded isolated Python algorithm workers; DISPLAY_ONLY remains distinct from Research Evidence.
5. **Research and private assets:** DB-native Factor authoring and stable Python API validation, Calculation catalog/Definition resolution, immutable Dataset, Research Run/Attempt fencing/cancel/recovery, outputs/statistics/artifacts, Qualification and Search/Agent API clients. Python workers own algorithms only; Rust owns admission, scheduling, stores and publication.
6. **Strategy and Runtime Generation:** exact frozen Strategy source/identity, promotion, artifacts/distributions, builds/installation, binding/draining/new-work activation, historical exact readers and worker lifecycle. Preserve ADR 0117 and existing Python-authored Factor assets.
7. **Trading Product composition:** existing Rust Kernel/Replay Driver plus native Product Backtest admission/worker/reconciliation/result reads and SIM/LIVE continuous drivers. Preserve shared semantics, UNKNOWN, cancellation, risk reduction, durable history and explicit human LIVE authority.
8. **Maintained Python backend retirement:** remove each replaced implementation's full current caller/build/deployment closure. Extract only the minimal Python algorithm SDK/worker closure. Validate the whole existing Web workflow set without Python business services, then complete applicable migration/upgrade and milestone gates.

Each complete capability carries its own Task Contract, independent expected behavior, fault/structural mutation tests, affected canonical lanes and bounded independent review. These dependencies do not waive current behavior, authorize placeholder implementations or grant a fallback path. The admitted Product Slice determines which API operations are available during the migration. Operations outside that slice are explicitly unimplemented in both the native API and Shipping Web; no capability is called migrated until its Rust owner actually serves the normal Product flow.

## First native Shipping slice

The 0.11.0 slice is the existing chart workstation: Source management and
watchlists needed by charts, historical and realtime K-lines, transient chart
indicators, and the registered/public/private Factor metadata board. Research,
Data, Strategy, Backtest and System standalone pages show an explicit
unimplemented state. Their broader API commands are not enabled by the
existence of native libraries. This sequencing does not reduce the permanent
product goals.

The serving executable and business orchestration are Rust. Python is admitted
only in the exact isolated Factor/Indicator algorithm installation. Build,
validation and explicitly retained reference tooling are separate from the
maintained runtime; they do not provide a Python service fallback. Historical
facts, keys, original identities and owning readers remain required through
upgrades, without old-version execution or schema fallbacks.

## Placement

`packages/onlyalpha-metadata-json/` owns the shared pure metadata identity codec. `packages/onlyalpha-integration-contract/` owns provider-neutral public Type/Field/Probe declarations. Concrete plugins and Product depend on these pure libraries; neither library depends on Product, HTTP, PostgreSQL or provider implementations. They add no service or store.

`packages/onlyalpha-product-runtime/` contains transport-neutral Rust Product Application/worker composition and owning PostgreSQL adapters. It depends on canonical Rust libraries and explicit plugin/algorithm boundaries; it has no Product HTTP server or ingress dependency. Its owning ClickHouse persistence uses an explicitly bounded HTTP client. `packages/onlyalpha-http-server/` owns the native HTTP/WebSocket adapter and startup composition. Concrete provider/market/Broker implementations remain under `plugs/`. Library modules, process boundaries and storage owners remain separate even when linked into one node.

## Permanent verification obligations

Commands preserve canonical global IDs, immutable intent, accepted outcomes, conflict/reuse and admitted-without-outcome uncertainty. Transaction-scoped operations participate in the same owning business transaction. Readers distinguish absent facts from unavailable/corrupt proofs. Test concurrent same/different-intent commands, orphan/mismatched receipt relations, rollback, commit acknowledgement loss and fresh process reads against the existing schema and exact namespace.

Web acceptance uses the Shipping UI for every business step, real canonical owners and isolated controlled external inputs. Record supported/deferred environment evidence separately. A diagnostic hash, stub response or latest projection does not prove the immutable relation/history. Preserve history and keys through real service restart and applicable upgrades; do not use an empty database as upgrade proof.


## Product PostgreSQL dependency boundary

The Product Command owner uses `tokio-postgres =0.7.18` with default features disabled and only `runtime`; its local pure dependencies are Domain, shared metadata JSON identity and Integration public contracts. The existing canonical PostgreSQL schema and same-transaction business effects require a real PostgreSQL protocol/authentication/transaction implementation. The standard library and existing SQLite driver cannot provide it. A handwritten wire/authentication implementation or Python proxy would add complexity and violate the chosen boundary. The public Rust API exposes `Client`, `Transaction` and `Row` decoding; replacing the driver requires changing that bounded persistence integration, not Kernel semantics.

Direct `tokio =1.54.1` (`rt`, `sync`, `time`, `macros`) supports the production Authority Session driver and bounded Policy admission; the technical probe also uses it. Effective transitive Tokio features also include `net` and `io-util`; no `full`, `process` or `rt-multi-thread` is enabled; the native HTTP consumer separately requires `macros`. Upstream requires `socket2/all`. PostgreSQL authentication entails RustCrypto HMAC/SHA/MD5, stringprep and random nonce generation (`rand`/`getrandom`/`chacha20`); these must never generate canonical trading identity or implicit deterministic inputs.

The locked Linux closure includes socket/entropy/libc FFI and RustCrypto CPU/assembly paths. `getrandom` and `parking_lot_core` build scripts inspect sanitizer configuration; `async-trait` is a compile-time proc macro. This adds no libpq, OpenSSL or native TLS build dependency, but is not a claim of no native/unsafe surface. Apple Objective-C, Redox, WASI/WASM and UEFI lock branches are target-conditional; Linux validation does not certify them. In particular, inactive WASM build branches include compiler/git probing and archive generation and remain subject to their target-specific validation before use.

The rust-postgres/Steven Fackler, Tokio Contributors, RustCrypto, rust-random and futures-rs projects maintain this closure. Permissive license options are available; distributions must retain the chosen license texts and notices, including `unicode-normalization`'s additional `Unicode-3.0` notice. `r-efi` offers LGPL as an OR alternative rather than a mandatory chosen license. Existing locked versions and checksums remain pinned; feature unification adds edges to existing `digest`, and the two `fallible-iterator` versions require explicit lock disambiguation.

Known upstream fixes inform the pins: `tokio-postgres 0.7.18` addresses [DataRow bounds panic RUSTSEC-2026-0178](https://rustsec.org/advisories/RUSTSEC-2026-0178.html); `postgres-protocol 0.6.12` addresses [SCRAM CPU exhaustion RUSTSEC-2026-0179](https://rustsec.org/advisories/RUSTSEC-2026-0179.html) and [hstore panic RUSTSEC-2026-0180](https://rustsec.org/advisories/RUSTSEC-2026-0180.html). Tokio includes the [broadcast soundness fix RUSTSEC-2025-0023](https://rustsec.org/advisories/RUSTSEC-2025-0023.html). These pins and the exact registry fingerprint are not a claim that unknown vulnerabilities cannot exist.

The persistence library borrows a caller-provided client. Production node composition must explicitly validate user, database, endpoint/store binding and TLS policy: upstream defaults (`whoami` username, username-derived database and SSL `Prefer`) cannot select Product authority implicitly. `NoTls` is admitted by the canonical `_test` technical probes and the explicitly selected contained DEVELOPMENT_ONLY Host composition. The latter requires `SslMode::Disable` (never fallback from Prefer/Require), the exact `postgres` endpoint/port/user/database, an independently supplied private TCP peer and the original semantic-store binding. The sole-dev launcher attests the actual container, fixed image, source/artifact inputs, internal database network and exact host-loopback publication before exec. Public/production plaintext and LIVE deployment are not admitted by this development policy. Commands cap transaction statement/lock timeouts without relaxing a stricter caller budget. Connection establishment and driver lifecycle remain node-owned.


## Source read credentials and sessions

Native Source read authentication preserves the existing exact `Bearer [0-9a-f]{64}` grammar. SHA-256 hashes the 64 ASCII credential characters, not hex-decoded bytes. Product directly uses the already pinned `sha2 0.11.1` and `subtle 2.6.1` with default features disabled, comparing fixed-length lowercase hexdigests through `ConstantTimeEq`; neither the trading Kernel nor a handwritten comparison owns credential cryptography. The raw secret, expected digest and session issuance state are not serialized or exposed through Debug.

`subtle` (Dalek, BSD-3-Clause) has no normal/build dependency or native build step with these features. Retain its copyright, license and disclaimer when distributing. Its upstream [README](https://raw.githubusercontent.com/dalek-cryptography/subtle/2.6.1/README.md) describes best-effort side-channel resistance and intended release use: debug assertions can contain secret-dependent branches. Debug tests establish semantics, not timing assurance; release Linux validation does not certify every CPU/compiler/OS. `ctutils 0.4.3`, already needed transitively for PostgreSQL authentication, is marked experimental/unaudited by its maintainers, who currently recommend `subtle`; it is not added as a direct Product credential dependency merely because it is locked.

Relevant fixed histories include [SHA-256 AVX2 multi-block correctness](https://rustsec.org/advisories/RUSTSEC-2021-0100.html), [`block-buffer` panic recovery](https://github.com/RustCrypto/utils/security/advisories/GHSA-qwgh-2vcv-g2f7), [`cmov` ARM32 code generation](https://rustsec.org/advisories/RUSTSEC-2026-0003.html) and [`cmov` aarch64 register handling](https://github.com/RustCrypto/utils/security/advisories/GHSA-3rjw-m598-pq24). The selected SHA-256, `block-buffer 0.12.1` and PostgreSQL-transitive `cmov 0.5.4` include those fixes. Known fixes, pinned archives and semantic vectors do not establish absence of unknown vulnerabilities or a cryptographic audit.

A Source session belongs to its exact issuing composition, immutable grants and irreversible active/withdrawn state. Same configuration in a different authority does not issue the original composition's session. An absent grant grants nothing; incomplete selection proof differs from a complete forbidden selection. Source grants never confer Product Command or LIVE permission. Ingress additionally owns exact Host/Origin and cookie policy, bounded work, outward-response fencing, stream wakeup and cleanup. Logical authority withdrawal alone does not prove transport drain or Web flow completion.

## Protected HTTP startup configuration

The HTTP component owns secure local configuration loading and reuses Product's Source authority. It never grants Product mutation or LIVE permission. Files are opened relative to held directory descriptors using safe `rustix 1.1.5` (`std`, `fs`, `process`, no defaults): root/effective-user ownership, trusted ancestors, no symlink traversal, a single-link private regular file and bounded 32 KiB input. A root-owned sticky shared directory is allowed, but every descendant is independently checked. `NONBLOCK` prevents opening a FIFO from waiting for a writer; `CLOEXEC` and owned descriptors prevent descriptor escape. The loaded authority is an immutable snapshot, not a configuration watcher.

Strict private Serde DTOs reject missing, duplicate and unknown fields. A map-only deserialization wrapper additionally rejects positional arrays at both root and grant levels without converting to `Value` and losing duplicate keys. Integer schema version, UTF-8, grant bounds and Product value validation remain mandatory. Excluded gateway credentials are hashed as arbitrary UTF-8 strings, not reinterpreted as Source bearer tokens.

`http 1.5.0` (`std`, no defaults; MIT OR Apache-2.0) supplies the maintained URI grammar with only already pinned `bytes` and `itoa` dependencies. It adds no HTTP server, TLS or network executor. Parsing does not itself authorize an Origin: explicit policy rejects userinfo, path/query/fragment, whitespace, non-loopback hosts and invalid/empty ports, retaining the original accepted Host/Origin bytes. The standard library does not offer this URI parser; a handwritten parser or a larger URL dependency would add unnecessary surface.

Serde `1.0.229` (`std`, `derive`, no defaults) and Serde JSON `1.0.154` reuse the existing parser and derive closure. Enabling derive adds the `serde_derive` edge; it does not change locked versions or checksums. The parser's recursion limit remains enabled. Rustix's safe interface wraps Linux `linux_raw` assembly syscalls on the validated target; other target backends may use libc. Its build script probes rustc capabilities. Serde/Serde JSON build scripts and the Serde derive proc macro remain explicit compile-time inputs; they do not authorize ambient configuration, network or new native compilation.

Relevant upstream histories include HTTP's [HeaderMap Drain](https://rustsec.org/advisories/RUSTSEC-2019-0034.html) and [reserve](https://rustsec.org/advisories/RUSTSEC-2019-0033.html) fixes and Rustix's [directory iterator allocation](https://github.com/bytecodealliance/rustix/security/advisories/GHSA-c827-hfw6-qwvm) fix. The pinned versions include those fixes; this loader does not consume the directory iterator. Retain upstream license notices, including Rustix's selectable Apache-2.0 WITH LLVM-exception / Apache-2.0 / MIT terms. Semantic and filesystem tests on Linux do not certify timing, other operating systems or the eventual HTTP ingress shutdown/send fence.


## Native REST framework dependency boundary

The private REST adapter uses Axum `0.8.9` (`json` only), Hyper `1.12.0` (`http1`, `server`) and hyper-util `0.1.21` (`tokio`, `service`) with defaults disabled. Axum owns routing/JSON responses and its bounded body collector; Hyper owns the HTTP protocol and connection. Tokio `1.54.1` supplies the actual single-thread async runtime, networking, I/O, synchronization, deadlines and selection macros. No handwritten HTTP parser, Python proxy or duplicate Product implementation is admitted. Hyper client and Tokio test-util are test consumers, not production server features.

The exact reviewed closure adds 19 registry packages without changing any prior registry version/source/checksum. Tokio gains its macro edge. Axum JSON requires Serde JSON `raw_value` and serde_path_to_error; effective smallvec features include const_generics/const_new. Existing async-trait already enables syn's full feature. There is no h2, TLS, WebSocket, tower-http, reqwest or axum-macros dependency in this closure. Hyper's dev client adds want/try-lock, which are absent from the production server-only feature closure.

New packages are MIT or MIT/Apache-2.0 except sync_wrapper (Apache-2.0) and matchit (**MIT AND BSD-3-Clause**, both notices required). Retain atomic-waker's LICENSE-THIRD-PARTY. httparse is the only new build script: it queries rustc and target/SIMD configuration, without network download or native C compilation. tokio-macros is the only new proc macro. The http-body registry archive reports dirty VCS metadata; review binds its exact archive checksum rather than claiming Git-tree equivalence.

Known fixed histories include Hyper's [parser unsoundness](https://rustsec.org/advisories/RUSTSEC-2022-0022.html), [request smuggling](https://github.com/advisories/GHSA-6hfq-h8hq-87mf) and Axum's [body limit](https://rustsec.org/advisories/RUSTSEC-2022-0055.html). Targeted advisory review and pins do not certify absence of unknown vulnerabilities. The h2 empty DATA advisory is outside the selected closure.

The already pinned percent-encoding `2.3.2` (`std`, MIT OR Apache-2.0, no dependencies/build script) owns percent decoding. Its decoder preserves malformed escapes. The private route grammar therefore rejects residual percent signs after one strict UTF-8 decode and accepts only closed ASCII static paths/acquisition identifiers. Only a path satisfying that grammar may be forwarded as a normalized path; Axum cannot change it on another decode because no percent sign remains. The original query is preserved. This rule does not authorize generic dev/static path normalization or Origin rewriting.

Isolated validation lets Cargo resolve feature contraction offline, then checks that the resulting lock only removes packages/edges from the admitted projection. Workspace members, lock header and every retained package's version/source/checksum and other metadata remain exact; any new package/edge, ambiguity or failure restores the original bytes and fails before frozen tests. Root Cargo.lock is never rewritten by isolation.


Hyper merges identical Content-Length fields before exposing HeaderMap. The adapter therefore directly uses the already locked httparse `1.10.1` (`std`, no defaults) for a bounded raw-header preflight, adding no registry package or effective feature. The same cumulative header deadline, 64 KiB cap and header-count bound apply; a fresh parser is used for each partial read. All original bytes, including any body prefix, are replayed unchanged into Hyper. Raw multiplicity failure is an internal service flag, not a client extension. Hyper remains responsible for protocol/framing validity; malformed HTTP can close or receive a standard protocol error instead of Product JSON.


A private request pins its exact issuing Source session. Withdrawal and ordinary/vectored writes, flush and shutdown share one short mutex: the server-side cutoff excludes any bytes newly accepted by the underlying transport afterward, while OS bytes accepted before it cannot be retracted. Every actual write also enforces its send deadline. These guarantees are distinct from client receipt or a fully drained node. Private withdrawal leaves unauthenticated health/error paths available; node shutdown refuses all connections and writes.

Four read permits cover actual owned work and pending responses. The work task and connection each retain an Arc to the same permit; only their joint completion releases capacity. Caller disconnect, timeout, panic, a closed result receiver or late work cannot infer the other owner's completion. Poisoned connection cleanup only releases its resources; admission and writes remain fail closed. Work counts and retained permits expose distinct states.

`LocalIngress::shutdown_and_drain` closes its admission/write gate before waiting for registered connections, retained handlers and response permits. It also wakes partial-header readers; connection cleanup and actual worker completion notify the waiter. Cancelling the waiter leaves shutdown closed and does not certify completion. A poisoned gate fails closed. The concrete Host still owns listener/task completion, query-driver shutdown and guard release; this ingress operation alone does not certify node STOPPED or READY.

Chart queries pin their ten-second budget at ingress entry. A timely captured response uses the earlier of that original deadline and five seconds from response readiness, including result-channel/Hyper queueing. A locally selected timeout error gets a separate five-second delivery budget; a late worker cannot replace that error or rewrite its deadline. Clear HTTP on this adapter is limited to verified loopback sockets and explicitly rejects HTTPS configuration. TLS, broader node composition, WebSocket and the actual Product handlers require their own concrete integrations; this library does not provide them by forwarding to Python.

## Native Watchlist persistence boundary

The Product component's Watchlist owner reuses `watchlist_head`, immutable `watchlist_revision` and global Command Admission/Receipt; there is no Rust-specific store or parallel current head. Namespace comes from the node's verified semantic-store binding. The library borrows a native Client, accepts explicit operational receipt time and does not connect sockets, choose TLS, infer the namespace or authorize a human.

Read-only current queries use a repeatable-read transaction. A single head/history query distinguishes empty namespaces from dangling/missing/stale heads and proves positive contiguous version metadata. The selected revision must bind its exact original fingerprint and global Command lineage. Historical representation 1 is selected only by its existing explicit metadata: its original payload hash and original intent/receipt are verified before member projection. Original rows and receipts are never rewritten. Outcome-less old empty lists lack reconstructible Source proof and cannot be guessed into an accepted new effect.

Writes explicitly use read-committed transactions and acquire the global Command lock before the namespace lock. The current head is observed after acquiring that namespace lock. New Admission, revision, head and Receipt share one commit; failed version checks or Receipt inserts roll back all provisional facts. A lost COMMIT acknowledgement stays unavailable until an exact Command query resolves the durable result. Exact replay returns the original revision even after later edits.

Serde JSON `1.0.154` (`std`, `arbitrary_precision`, no defaults), already pinned and used by Domain, is a direct production consumer for strict Watchlist records and their original canonical hashes. This changes no registry package/version/checksum or effective feature. The record family contains validated integer/string fields, arrays and sorted objects; this is not a generic financial-float canonicalization service. PostgreSQL JSON travels through explicitly cast text, without enabling the driver's optional type ecosystem. Application admission must separately prove Owner access and new exact Source/member references before the persistence port is exposed through HTTP.

## Product metadata document identity boundary

Integration metadata identity follows the existing canonical contract: integers remain integers, finite binary64 values become Python `str(float)` JSON strings, object keys sort by Unicode scalar order, and arrays retain order. Financial Decimal fields keep their separate Domain contract. Native parsing uses the pinned Serde raw JSON parser and a decoded-key-checking map visitor. Serde's private number/raw-value marker strings remain ordinary object keys; they are never evidence of a different JSON primitive.

The pinned JSON library's maintained shortest float formatter supplies digits. The Integration encoder only converts scientific thresholds and exponent spelling to the existing identity representation. Standard Rust Debug formatting is not that contract. Negative floating zero remains distinct from integer zero; overflowing floating input is invalid and arbitrary precision integer text is preserved.

Parsing and canonical emission use an explicit work stack rather than recursive application calls, so a deep document does not silently inherit a reset per-child parser depth limit or overflow the application stack. The caller supplies an operational raw-byte traversal budget, including rescanned subtrees. Exhaustion is unavailable, not malformed history, absence, permission or authority to rewrite a fingerprint. Owning Integration admission and historical readers must select the appropriate bounded operational policy and verify their exact immutable relations; this codec alone admits no Revision or Source.

The Watchlist historical reader also proves the full original JSON preimage equals the decoded record before validating the book fingerprint, intent and projection. This prevents a private raw-value marker from laundering names, Source references or other nested fields. Valid Watchlist representations have a fixed shallow shape and no floating fields; their traversal budget scales with the original byte length. An exhausted proof is unavailable and never an empty book or permission to rewrite history.

## Native Integration metadata persistence boundary

Integration metadata queries borrow the node-owned canonical PostgreSQL connection. Complete owner views use one read-only repeatable-read transaction for the Integration, Draft, published history and Secret bindings. Original JSON columns are read as text and restored through the exact metadata identity codec before cross-checking owner, frozen type, current Revision and Draft base references. Resource exhaustion or unavailable queries cannot become an empty configuration or truncated history.

The Product list query retains its metadata-only purpose: exact optional Type/lifecycle filters and deterministic creation-time/UUID order. It does not require an installed provider or resolve history to display metadata. Source/runtime readiness separately requires exact owning Revision, implementation, current credential generation and authorization proofs. Historical Secret bindings remain readable after credential rotation; reading their original generation never grants current runtime admission.

## Public Integration numeric declaration boundary

The pure Integration contract uses the existing pinned `bigdecimal 0.4.11` (`std`, defaults disabled) directly for arbitrary integer bounds and exact binary64 comparisons. Its [maintained `TryFrom<f64>` conversion](https://docs.rs/bigdecimal/0.4.11/bigdecimal/struct.BigDecimal.html#impl-TryFrom%3Cf64%3E-for-BigDecimal) preserves the float value; shortest decimal text belongs to metadata identity and cannot replace numeric comparison. The public contract does not apply Trading Domain arithmetic/rounding policy or depend on Trading Domain. Product retains its own actual Domain dependencies.

This adds a local dependency edge to the already admitted BigDecimal/num-bigint closure, without changing registry versions, checksums or features. No rounding context, arithmetic defaults, native compilation or new cryptographic implementation is used for these comparisons. Keep the existing BigDecimal license notices and the exact lock/build inputs. The standard library lacks arbitrary integer comparison with an exact binary64 decimal representation; reusing the pinned maintained conversion avoids a custom numeric algorithm. Semantic tests remain required; a fixed version is not an assertion of absence of unknown vulnerabilities.

## Integration authoring command identity and persistence

Draft edit intent retains the existing compact JSON **string** fields for public/probe configuration. The shared JSON encoder has two concrete entry points: metadata identity retains its original floating-number string policy, while command-document normalization turns integral binary64 values into their exact integers and leaves other floats as Python-spelled JSON numbers. Both use the same iterative parser traversal. The command-document entry also caps emitted bytes; this does not change the metadata entry's existing traversal-work budget.

Integration authoring writes borrow the node-owned canonical connection and commit Admission, the owning head/Draft effect and Receipt in one read-committed transaction. Command and SourceHistory/frontier locks precede head/Draft locks. Draft editing preserves its original base and secret bindings; contract reset clears only mutable Draft bindings and selects the exact current Revision as its base. Neither operation deletes credentials or immutable published history. Bounded readers validate the selected base/current references rather than scanning all history on every edit.

Receipt replay is independent of installed providers and later valid authoring state. An Admission without a proved outcome stays UNKNOWN, and loss of COMMIT acknowledgement remains unavailable until exact replay resolves it. The owning command transaction selects the exact compiled authoring registration after replay and locks. Its locked Draft reader strictly parses the actual stored declaration and proves its owner/pin relation before new authoring or post-write certification. Metadata fingerprints alone do not prove JSON scalar kinds; malformed stored declarations fail as persistence conflicts, including Reset, while resource exhaustion stays unavailable. Historical metadata, accepted replay and lifecycle safety paths remain independent of current authoring validation. Update validates its normalized public candidate; Publish validates the same resolved/default-filled public candidate it materializes. Missing installation is `INTEGRATION_TYPE_UNAVAILABLE`; a compiled validator returning a Type/Probe contract error is `INTEGRATION_TYPE_CONTRACT_INVALID`, distinct from invalid user configuration and operational unavailability. These ports do not prove Owner permission, node mutation admission or Source readiness; HTTP/node composition must enforce those boundaries before exposing the existing Product API.


Secret unlinking removes only the selected mutable Draft binding and validates every remaining binding against its exact current credential slot and generation. Publication takes share locks on current credentials until the owning commit. Reusing an already published semantic Revision preserves its original sequence, creation time and bytes; only a new semantic fingerprint consumes a new sequence. A full sequence range therefore refuses a new Revision while allowing exact reuse. Neither operation rewrites encrypted credentials or immutable published bindings. New reuse admission parses the actual stored declaration and validates its actual configuration, probe and bindings through that declaration before accepting normalized component identities. Metadata identity alone cannot prove JSON value kinds; historical runtime fingerprints remain opaque and neither historical reads nor accepted replay are reinterpreted.

## Native credential encryption boundary

Credential encryption retains the original AES-256-GCM envelope (`nonce[12] || ciphertext || tag[16]`) and exact six-field canonical AAD. The original master key and version remain required to read historical records; Rust migration never resets keys, re-encrypts history or translates slot/generation identity. Integration secret intent uses the original HKDF Extract+Expand SHA-256 domain and HMAC-SHA256, rather than storing plaintext or an unkeyed low-entropy digest.

RustCrypto owns AES-GCM and HKDF; the standard library and existing graph supply no equivalent AEAD/HKDF API. `aes-gcm 0.11.1` enables only `aes`, `alloc`, `zeroize`; `hkdf 0.13.0` uses no optional KDF interface; the existing `hmac 0.13.0` and `sha2 0.11.1` enable zeroization. `zeroize 1.9.1` enables `alloc` without derives/Serde; existing `getrandom 0.4.3` obtains OS randomness, separately from AEAD features. No handwritten cryptography, external crypto process, new algorithm/envelope family or Python proxy is used. Replacement requires historical byte/AAD/commitment equivalence, not merely a different authenticated cipher.

The [AES-GCM security notes](https://docs.rs/aes-gcm/0.11.1/aes_gcm/) describe a historical audit and portable constant-time multiplication assumptions, not certification of this complete dependency closure or every CPU. The [historical unauthenticated-plaintext advisory](https://github.com/RustCrypto/AEADs/security/advisories/GHSA-423w-p2w9-r7vq) affected versions through 0.10.2; the selected implementation authenticates before releasing plaintext. Invalid tag, key, context or UTF-8 returns no secret. Explicit owned secret/key buffers and enabled internal member drops wipe their storage; [compiler-generated temporary copies remain outside a complete erasure guarantee](https://github.com/RustCrypto/block-ciphers/issues/385).

This AEAD uses the already locked experimental `ctutils 0.4.3` for tag comparison. Its prior PostgreSQL use is not evidence of independent AEAD audit. The existing `cmov 0.5.4` is outside the affected range of the [ARM32 conditional-move advisory](https://rustsec.org/advisories/RUSTSEC-2026-0003.html); Linux ARM64 validation does not certify ARM32. Keep these upstream limitations visible when upgrading or selecting deployment targets. Keys/plaintext have no Product DTO, Debug or diagnostic display surface. Cryptographic nonce/credential UUID randomness is recorded in the envelope/identity and cannot change exact accepted Command replay.

The exact credential closure adds twelve MIT/Apache-2.0 archives: aead 0.6.1, aes 0.9.3, aes-gcm 0.11.1, cipher 0.5.2, cpubits 0.1.1, ctr 0.10.1, ghash 0.6.0, hkdf 0.13.0, inout 0.2.5, polyval 0.7.3, universal-hash 0.6.1 and zeroize 1.9.1. These archives declare no build scripts or procedural macros. Existing registry versions/sources/checksums remain pinned; block-buffer and digest gain their required zeroize edges. Preserve each archive's license notices. cpubits uses compile-time word-size selection, not a native compiler probe. AES/POLYVAL dispatch to maintained hardware or software implementations; AES 0.9.3 actually detects VAES256/512 at runtime despite older wording in its library documentation. Ambient compiler flags cannot silently choose a different validation backend.

Zeroization does not cover all upstream HKDF PRK/expand intermediate/output arrays or AEAD tag-mask/keystream temporaries, as well as compiler-created copies. This is a bounded storage-erasure measure, not a guarantee that process memory contains no remnants. Do not replace maintained cryptography with handwritten HKDF/CTR in an attempt to claim complete erasure.


## Existing runtime master key

Native node startup loads the existing master key through the same descriptor-relative protected-file boundary as Source configuration. It accepts exactly 32 raw bytes, snapshots the key once, and never creates, repairs, replaces or watches the file. Missing or untrusted key material refuses startup; it cannot select a new namespace or authorize an empty store. Loading a key does not itself prove a historical ciphertext, semantic-store binding or node readiness.

The HTTP component directly reuses the already admitted `zeroize 1.9.1` with only `alloc` and disabled default features for its owned file-read buffer. This changes a local dependency edge, not the registry closure or features. Successful and failed reads drop the protected buffer; this retains the documented limits on temporary copies and complete process-memory erasure. Key paths and bytes are never included in errors, DTOs or logs.

## Compiled Source authoring boundary

The native Binance and Tushare plugins live under their existing `plugs/onlyalpha-plugin-*/` boundaries. Their authoring registrations pair an exact Integration descriptor with an independent plugin projection and an executable public-configuration validator. The projection checks category, implementation identity/version, public API requirement and capabilities. It confers no runtime factory, Probe, Source grant or READY permission. Current installation absence must not change historical metadata reads or accepted Command replay.

Partial editing validates supplied public fields. Publication must first fill canonical defaults and then validate the exact candidate committed under the owning Draft version. For Spot, an omitted endpoint profile may be acceptable when editing a US/Testnet configuration while the descriptor's static `PUBLIC_MARKET_DATA` default is incompatible at publication; validation cannot silently rewrite that candidate. Endpoint combinations and reconnect relationships belong to the Binance plugin, not Product or Kernel.

USD-M and Tushare previously lacked the public validation hook; native validation makes that admission check explicit. USD-M uses the already pinned `http 1.5.0` URI parser (`std`, defaults disabled), requires a complete HTTPS authority with a valid nonzero explicit port, rejects user information, query and fragment, and preserves path prefixes. Parser size exhaustion is unavailable. This is syntax/configuration validation, not a network reachability or provider certification claim. Tushare validates only daily public settings and never resolves environment credentials, decrypts tokens or loads its SDK for authoring. Required secret completeness remains a separate publication proof.

Tushare authoring depends on Integration contracts, metadata JSON and the pinned JSON implementation. Binance additionally depends on Domain/Construction and the explicit maintained Source transport closure below. Both isolated builds exclude Python source and Product/HTTP/database implementations. Dev environment admission includes native plugin Cargo manifests, while source-only validation reuses the same fixed dev tools.


Existing deployment namespace admission follows ADR 0096: the node loads the existing
`research/.onlyalpha-semantic-store.json` and compares its typed UUID4 with the
PostgreSQL singleton binding through a read-only transaction. Neither loader creates,
adopts, repairs or rebinds deployment state. Namespace identity is distinct from paths,
Research identities and immutable object integrity. Strict integer schema parsing rejects
boolean/float spellings accepted accidentally by Python equality. Ordinary nonsecret
metadata permissions and atomic-publication hardlinks remain readable; credential files
retain the separate private, single-link policy. The node must freeze the startup verdict
and bind subsequent work to that deployment; a standalone compatibility check grants no
readiness, Source or execution authority.


## Existing schema startup compatibility

Expected schema history is a snapshot of the explicit canonical SQL directory, using
ordered migration identities and SHA-256 of original UTF-8 file bytes. The native loader
holds directory descriptors while opening selected files, refuses symlinks and untrusted
permissions, and bounds individual files and aggregate traversal work. It does not search
another directory, normalize SQL, generate a second manifest, initialize storage or run
migrations. Empty SQL files remain valid source inputs; secret files retain their existing
nonempty, private, single-link policy.

The node-owned PostgreSQL connection reads the canonical public migration ledger in one
bounded read-only repeatable-read transaction. PostgreSQL major 18 support is checked
separately from connection success. Missing ledger, ahead, checksum mismatch, divergent
history, behind and compatible retain their existing meanings. Malformed evidence and
resource exhaustion cannot become compatible. Schema compatibility and semantic-store
binding are separate startup proofs; neither alone grants node readiness or command
permission. Application startup must bind this snapshot to its immutable deployment
source and compose the remaining owning readiness checks.


## Integration Type Product metadata

The existing Integration Type list and exact-read Product routes project the same immutable
authoring catalog used by the owning commands. They preserve original descriptor fields,
configuration/probe fingerprints and the descriptor fingerprint. Raw JSON fragments retain
number kinds and ordinary marker keys; HTTP projection never redefines metadata identity.
Category filtering is exact, while absent or inexact type identities retain the existing
not-found response. The routes execute no public validator, provider Probe or credential
read, and confer no Source or Runtime permission. Node composition must mount them behind
the explicit Human admission boundary; a reusable router is not a second public control
surface or proof of runtime installation.

The HTTP component directly declares its existing Integration Contract dependency and
Serde JSON `raw_value` feature for this projection. Both are already in its transitive
package/feature closure; no registry archive, alternate serializer or generated DTO manifest
is introduced. Isolated component builds retain this exact local dependency closure.


## Local human request identity

The native local-developer admission model retains the existing fixed Shipping origin
and host-only HttpOnly/SameSiteStrict cookie. Guarded root navigation can bootstrap the
cookie; health and navigation do not produce a human command session. Header cardinality,
Origin, Fetch metadata and forwarded-identity checks precede those anonymous branches.
Mutation and the formal stream GET require exact Origin, even without an Upgrade header.
Path checks decode once and reject encoded, absolute-form, dot/backslash/control bypasses;
Agent execution/control boundaries are distinct from Agent Provider management paths.

The private credential verifier reuses existing authentication, exact issuer membership
and permanent revocation with zero Source grants. The separate human Session has no
external constructor, deserializer or Source-session conversion. It proves identity only;
every actual command still needs its explicit operation policy and owning admission.
It grants no Source or LIVE permission. Node composition must mint a fresh, separate
CSPRNG credential, bind the real deployment and enforce the physical response-write fence
and Source generations. Logical request admission or withdrawal alone proves neither
transport cutoff nor node readiness. Credentials and sessions have no DTO or Debug surface;
owned copied credential buffers are zeroized, subject to the existing temporary/wire-buffer
limitations.


## Local Human HTTP release boundary

`Access::generate` obtains 32 bytes from OS entropy through the already locked `getrandom 0.4.3` (defaults disabled), encodes 64 lowercase hexadecimal characters and reuses the existing issuer, cookie, authentication and withdrawal checks. Entropy and encoded credential buffers are zeroizing; entropy failure returns `LOCAL_READ_PROOF_UNAVAILABLE` before any issuer is created, with no fallback. This adds only a direct HTTP dependency edge, no registry package/version/feature. It is operational session issuance, never a canonical trading identity or Source/Command/LIVE grant; constructing this value alone does not wire a Shipping Host.

Private Source REST and local-developer reads use the same HTTP/1 driver, bounded capture,
retained-work capacity and physical outbound gate. Each admitted response binds its exact
Source issuer, Human issuer or anonymous developer-bootstrap proof to the connection.
Bootstrap is not a command identity. Withdrawal serializes with every underlying write,
vectored write, flush and shutdown; it cannot retract bytes already accepted by the OS.
A permit remains owned until both the actual task and connection finish, including caller
disconnect and late work.

The developer composition has an explicit read-only operation policy for implemented
Integration Type metadata, guarded root/assets and health. Identity alone cannot authorize
POST, Source, Chart or WebSocket operations. Extending that policy requires the actual owning
capability and its permission proofs. Only successful guarded root capture can attach the
session cookie; other responses cannot issue it. Developer responses retain no-store and
frame denial. Private Source health and its existing Chart deadline remain separate from
Human revocation policy. Both modes enforce actual loopback socket addresses and the
configured port; the developer constructor provides no bridge or remote-network exception.
Docker containment, static-file ownership, Source generations and full node composition
remain distinct deployment and permission boundaries.


## Integration historical Product queries

The native Integration query adapter projects the existing owning snapshots into the
unchanged list, head, Draft and Revision Product DTOs. A list reads all selected
owner/Draft/history relationships in one read-only repeatable-read transaction with a
shared total row budget. Resource exhaustion and corrupt relationships cannot become
empty lists, missing resources or partial results. Type filtering remains arbitrary
exact string filtering, separate from current authoring admission.

Historical descriptor projection validates the transport shape while retaining raw
JSON scalar kinds, original descriptor pins, opaque runtime fingerprints and historical
secret-binding generations. It does not execute current authoring validation or read
current credential ciphertext. Only configured binding metadata is exposed; credential
identities and secret bytes are excluded. Complete absence retains each existing
resource's response semantics, including an empty Revision history.

Node startup hands off an owned PostgreSQL session and retains its driver/lifecycle
responsibility. The adapter fixes canonical relation lookup to pg_catalog, public and
explicitly last pg_temp before encapsulating that session. Owning read relations are
also explicitly public-qualified: session search order alone cannot prove canonical
absence when a public relation is missing. No temporary same-name table may substitute
for an owning relation. Neither measure is a namespace, schema or readiness proof by itself. Human identity is required behind the common ingress;
these read operations grant no Integration mutation, Source, Probe or Runtime permission.
The direct tokio-postgres dependency uses the already admitted pinned version/features.


## Product node lifecycle and mutation session

Node Infrastructure models the existing CREATED, BOOTING, VERIFYING, RECOVERING,
READY, DRAINING, STOPPED and FAILED lifecycle. Legal transitions and failure phases
remain explicit. The model does not establish production readiness: startup must
verify the deployment namespace, schema, protected roots, installed registries,
qualification policies and durable inventory, then perform Strategy projection
reconciliation before opening Product mutation admission.

The PostgreSQL singleton guard owns one Client and its connection driver. That
same physical session serves its owning transactions; a second business socket
cannot survive independently after guard loss. Before lending the session, the
guard proves the frozen two-key advisory lock against pg_catalog with the exact
current database, backend PID, key tuple, lock family, granted state and exclusive
mode. Existing same-session locks are rejected to prevent reentrant acquisition.
System relations, functions, types and equality operators use qualified names.

Failure, timeout or cancellation revokes the original session without reconnecting.
Graceful close unlocks once, checks for residual locks and awaits the owned driver.
Drop/cancellation aborts it without claiming successful drain or business rollback.
The actual owning Host must close admission and drain retained work before release;
lock ownership alone grants neither Product READY nor Source or LIVE permission.
Independent observation, fills, cancellation and reconciliation retain their own
required safety lifecycles.


## Native startup storage inputs

Storage startup selects one explicit protected user-data root and retains the
actual directory descriptors for Research, Secrets, artifacts, Backtest evidence,
datasets and economic bindings. Required directories must be readable and
searchable by the effective process identity; writable access is not required.
Key and namespace files are read relative to the selected descriptors. Replacing
the original absolute path cannot rebind those selected inputs or the capabilities
handed to subsequent owning readers. Missing or unsafe inputs fail without
creating, repairing or selecting a replacement store.

The complete input object retains the original private 32-byte key, typed deployment
namespace and expected schema history from the actual deployed SQL source bytes.
Verification uses the caller's existing PostgreSQL session: the owning schema
reader must establish COMPATIBLE before the owning deployment reader compares the
exact namespace. These are two bounded read-only startup observations, not one
atomic database snapshot. Errors, cancellation and lost COMMIT acknowledgements
produce no success or cached readiness. The Host owns failed-startup connection
cleanup and controlled restart/revalidation after deployment changes.

This storage prerequisite does not certify contained durable history or replace
registry admission, qualification policy admission, Strategy reconciliation, the
physical mutation guard or retained-work drain. It grants no Node READY, Source,
Product mutation or LIVE permission.


## Shipping Web build delivery

The native static adapter serves the existing built Web workbench. Startup selects
an explicit protected build directory and snapshots index.html plus its assets tree
through trusted descriptors. It retains the selected bytes instead of reopening
arbitrary paths per request. Unsafe ownership/permissions, symlinks, asset hardlinks,
nonregular entries, unsupported file types and exhausted byte/tree limits refuse
construction rather than produce a partial service. Existing key, namespace and
schema readers retain their distinct file policies and limits.

Root navigation and asset requests pass through the common local Human ingress.
Only successful normal root navigation issues the session cookie; assets require
Human identity and use the same physical release fence. Explicit media types,
nosniff, no-store and HEAD semantics apply to the selected bytes. There is no source
mount, arbitrary-file lookup or fallback page. The build snapshot is Presentation
input, not immutable Research history or proof of an atomic multi-file publication.
Serving these bytes does not establish Product API availability or Node READY.


## Current Calculation Product value readers

Calculation owns pure readers for the current Product Definition2 and Graph1
serialized values, separately from the internal Definition3 execution component.
The readers retain original semantic fingerprints and typed records. Decimal
fixed-point scale, trailing zeros and signed zero remain original Product
identity; no internal numeric normalization may replace them. Existing untagged
Definition2 fingerprint semantics are preserved, not replaced by schema3 hashes.

Public names, dimensions, aliases, warmup and precision use the owning Product
value rules rather than current execution restrictions. Serialized decimal values
are finite ASCII numeric strings; fixed-point output from the canonical writer
is always readable. Supported ASCII exponent notation normalizes to that same
fixed-point output. Python parser conveniences such as whitespace, underscores or
Unicode numeric spelling are not a serialized history format. Noncanonical input
spelling is not an alternative immutable identity.

The isolated algorithm SDK exports one actual type's public descriptor with a
private lossless parameter-value declaration. Defaults, bounds and enum entries
retain scalar categories; Decimal values retain their original string exponent,
scale and sign. Fixed-point public projection alone cannot recover these SDK
values: a STRING default of Decimal `2E+1` normalizes differently from Decimal
`20`, although their public projections agree. The native reader verifies every
projection, original schema constraints and complete bounded structure before
retaining the declaration. It preserves parameter and enum ordering and duplicate
enum entries; it does not substitute the component parameter schema. This private
record has no additional Product fingerprint. Parsed declarations do not prove an
installed factory, normalize caller inputs, resolve a Definition, select a
Generation or establish a ready Host. Installation must bind the same exact
factory and implementation to the full lossless declaration, including across
backends; public descriptor equality alone is insufficient.

Pure candidate validation checks the original exact type reference, complete
Definition2 and every resolved parameter's declared scalar type, inclusive bounds
and enum. Numeric enum equality preserves Decimal/integer/boolean comparisons,
while strings remain distinct. Traversal and repeated comparisons share one
budget, charged using verified fixed-point sizes for scientific decimals. This
check neither proves SDK uppercase/default/coercion normalization nor an algorithm's derived warmup,
bindings, dynamic fields or extensions. Those require the selected immutable
resolver and its vectors. Owning Chart, Research and Strategy callers retain
their additional input, graph, expected-identity and authorization constraints.

The current private Strategy resolver response carries a schema2 envelope with
Product Definition2, the lossless type declaration and the existing component
NodeDescriptor1. Rust independently checks the requested exact type, candidate
parameter contract, original Product fingerprint and complete typed component
projection before returning a descriptor. A malformed or substituted response
poisons the owned worker; no automatic retry follows. The SDK projects both
public records through the existing canonical JSON writer and bounded private
decoder, so StrEnum values cannot escape as non-JSON runtime objects. This changes
neither persisted NodeDescriptor1 nor original Product identities. Current private
consumers evolve together; accepting this response is not an installed-origin
proof, Runtime admission or proof that retained historical worker artifacts have
passed service restart/upgrade verification.

The SDK checks cumulative Decimal fixed-point expansion against the existing
private frame budget before invoking the public descriptor formatter. The typed
Decimal positions—defaults, bounds, enum values and numeric quantum—share this
preflight; nonfinite values are refused. This is not a generic resource sandbox
for malformed Python objects in other typed fields; the installed-factory boundary
must still reject invalid declarations before admitting an implementation. The ordinary private decoder/encoder still checks final JSON size,
depth and leaves. Large positive-exponent zero retains its lossless SDK spelling
but fixed-point output needs only the signed zero, so neither producer nor native
reader charges or allocates fictitious zero padding. Negative exponents and
nonzero coefficients retain their real expansion cost.

One explicit budget bounds input traversal and aggregate decimal expansion;
exhaustion is unavailable rather than corrupt, missing or partial. Both graph
wire readers reuse port compatibility and iterative stable dependency ordering.
Ports are indexed once per node so wide public graphs do not repeatedly scan
every port for each edge. Original Definition2 node identities drive Product
ordering and graph fingerprints; aliases do not enter the fingerprint.

Source consistency grants no implementation, Freeze, physical publication,
Runtime or Node READY authority. Strategy source validation must still resolve
its own universe, market contract, implementation and signal-role relationships;
executable materialization must separately verify actual installed descriptors.


## Strategy source consistency and executable materialization

The Strategy source reader validates the existing Product Revision1 value using
Calculation's current Definition2 and Graph1 reader. It preserves the original
Strategy, graph and node identities, verifies exact universe/market recipe,
complete ordered implementation bindings and the three BOOLEAN signal roles.
Reading source requires no fabricated descriptors or current provider instances.
Historical source validity does not inherit execution component limits on universe
size, graph size, RAW input or port names.

The public JSON entry bounds input bytes before standard depth-limited parsing.
A shared private value checker also serves executable materialization, without
stringifying or deeply copying unchecked caller values. JSON parsing establishes
a self-consistent model only. The owning frozen reader must still verify original
canonical bytes, manifest/path identity, immutable Freeze relations and physical
publication; model parsing does not establish unambiguous original file bytes.

Materialization retains the original source wrapper, including existing legal
presentation ordering, for component checkpoint round trips. It separately
requires actual resolved descriptors, an injective original-to-component node
map, Product2 definition pins with upstream references remapped to component
nodes, implementation pins, typed component projections and all existing execution
limits. Original source node identities remain independently bound by the source
graph, implementation bindings and mapping. Internal normalization cannot replace
the original Product identity. A successful source read grants neither
Freeze, provider execution, Runtime permission nor Node READY.


### Immutable Frozen Strategy reads

ProductRuntime owns descriptor-relative immutable Strategy history reads beneath the selected Research directory. It reuses the existing protected-file implementation, shared with HTTP configuration, startup and static assets. Secret and static asset link policies remain unchanged; immutable history documents allow trusted hard links and an 8 MiB document cap. Public relative operations accept one normal component. A selected directory is validated and duplicated with atomic close-on-exec; later absolute-path replacement cannot select another root.

The reader verifies original canonical manifest bytes, exact wrapper fields, SHA256 prefixes and leaf identities, exact entries, current SourceRevision1 semantics and current FreezeRelation1 identity. Revision history requires a matching relation. Valid relation-first orphan history is retained without manufacturing a Revision. Unexpected published or leftover staging entries fail closed; readers never repair, publish, initialize or obtain missing semantic truth from PostgreSQL.

Complete inventory runs while exclusively borrowing the actual Product AuthoritySession, with physical guard verification before and after the synchronous scan. Startup/upgrade must keep mutation admission closed across this operation and reconciliation. Missing tree observations remain explicit. Exact reads and inventory grant neither Node READY nor Trading admission. Projection reconciliation must still prove every existing projection has corresponding immutable history.

The explicit scan work budget includes bounded directory entries and reserves the full 8 MiB parse/expansion allowance for each document; exceeding it reports unavailable rather than returning partial history. A bounded scan may therefore need substantially more work budget than the total manifest byte count. Runtime uses the existing canonical Strategy source library; only local dependency edges change, with no new registry crate. The physical singleton session implementation resides with ProductRuntime and retains its existing cancellation, driver ownership and lock-proof semantics.


### Frozen Strategy projection reconciliation

The concrete FrozenStore operation rebuilds catalog and audit projections from a fresh verified physical inventory. It reads namespace metadata through the same held Research directory, compares the startup-selected namespace and the transaction's canonical deployment binding, and rejects missing or conflicting immutable history. It does not publish a new Freeze relation or reconstruct semantic truth from PostgreSQL. Existing catalogs must have schema 1; existing audit rows must satisfy the current schema 4 owning reader. Historical SQL acceptance alone does not authorize interpretation of another schema.

The operation transfers the actual Client and driver before its first await, leaving the caller's original AuthoritySession empty. It restores that session only after acknowledged commit, exact readback and post-commit guard proof. Failure or cancellation drops the owned physical driver. A lost COMMIT acknowledgement reports an unknown projection outcome; a fresh process re-observes durable facts and preserves existing audit metadata. This is controlled startup/upgrade reconciliation, not Node READY or Runtime execution admission.

All catalog/audit projections are checked in both directions within one Serializable transaction. Valid orphan relations remain unprojected; contradictory relation triples fail before effects. Missing projections use the existing relation identity, explicit UTC audit input with microsecond precision, and the semantic reconciler actor/comment. Existing creation times, actor/comment and display metadata remain unchanged. Deferred constraints run before final exact readback and namespace proof, so a deferred mutation cannot silently invalidate that proof at COMMIT.

Each history scan and projection phase retains its explicit work cap; metadata reads have their existing fixed cap. PostgreSQL row observations have a cumulative row cap. Count/length preflight in the same transaction bounds cumulative string/array payloads before bulk transfer, and the owning decoder checks and charges them again. Wire framing and fixed-size metadata are additionally bounded by the row/reference counts. Budget exhaustion reports unavailable without a partial successful reconciliation. The shared namespace file and transaction readers live in ProductRuntime deployment; HTTP/startup consumers call those implementations directly.


## Immutable Qualification Policy startup

ProductRuntime reads the current Policy1 representation under the selected Research directory. Exact policy ID, original version spelling, sorted criteria, canonical decimal text and the existing fingerprint remain immutable. Reading unknown nonblank comparison or metric names does not authorize evaluation; the evaluator must still reject unsupported semantics. No Policy read or startup admission grants a Decision, Promotion, Runtime or LIVE right.

Explicit operator configuration uses the same physical mutation session and selected namespace. The complete existing inventory and all inputs are validated before publication begins. Individual put-once publications preserve existing content, sync new ancestors and the staged document, use atomic no-replace publication, and sync the target parent. A multi-policy admission is not a filesystem transaction: a later failure retains earlier published facts. A possible post-publication error never deletes a target or claims rollback; a new process must observe exact durable history. Unpublished stages fail closed and are not automatically ignored or removed.

History manifests retain the shared trusted-hardlink policy and 8 MiB bound. Private Policy construction enforces the same raw and canonical document bound before any filesystem write. Each scan and input reservation also has a cumulative work cap and a per-directory entry cap. Errors and cancellation revoke the original session; only complete readback and the final physical guard proof restore it. This is an operator startup primitive, not proof of Node READY, a Policy administration API or Shipping business acceptance.


## Durable market-data storage

ProductRuntime owns the existing PostgreSQL catalog and ClickHouse physical facts through the native `market_data` module. Application remains transport-neutral; ClickHouse persistence reuses pinned reqwest 0.13.5 with defaults disabled and Rustls, without automatic retry, redirects or proxy discovery. Host supplies the exact endpoint, database, credentials and finite time/byte/row budgets. HTTPS requires explicit PEM trust roots, with native/built-in roots and environment key logging disabled; trusted-network HTTP requires an explicit HTTP endpoint and no TLS roots. No protocol fallback is attempted. PostgreSQL connections and TLS remain Host-owned. An immutable expected four-partition proof is derived from the retained OAMD WAL before physical publication, stored put-once in PostgreSQL, and rechecked against every physical column for exact historical reads. Missing historical proofs remain unprovable.

Before a first ClickHouse insert, a put-once `market_recovery_event` with outcome `STORE_SUBMISSION_STARTED`, boundary `C3`, null pre-publication Segment FK and deterministic per-Segment event identity binds original Segment metadata and all four expected partition proofs. Only the acknowledged transaction that creates this witness owns one dispatch. An existing witness or lost PostgreSQL commit acknowledgement never grants another dispatch. Unknown ClickHouse acknowledgement plus an ABSENT observation remains unknown, including across restart; late completion can reconcile only through exact all-column proof. Partial/conflicting physical content retains WAL and fails closed. This operational witness does not establish durability, Coverage or Revision authority.

Source/session/Segment and expected physical proofs publish atomically after exact verification. Coverage, Manifest, Revision and Seal retain their existing canonical identities and ordered occurrence relations. Latest remains the existing immutable-history `DISTINCT ON(scope)` view, ordered by sealed time then Revision ID. Exact range reads compose only facts owned by current verified Revision occurrences. Filesystem collection follows physical proof plus applicable catalog/coverage publication; collection of raw-only or incomplete durable data never grants complete coverage. Normal drain enumerates only published seals; exclusive startup alone resolves interrupted/open WAL.


## Native chart Source and MarketData Application

The Integration contract owns a transport-neutral executable Source SPI with finite remaining budgets, explicit clock observations and immutable Host-selected PEM trust. Binance owns endpoint profiles, eight native bar intervals, provider normalization, bounded gzip REST, maintained WebSocket transport, Probe checks and contiguous baseline/suffix recovery. Other supported chart durations reuse Construction's existing 1m TIME_BAR plan and identity. Current native authoring advertises only executable capabilities; it does not claim Tick support or translate retired descriptors.

Product's installed registry binds each actual factory to the Host-qualified executable artifact. The qualified implementation includes that artifact fingerprint. Exact ACTIVE Integration Revision/configuration/descriptor relations and original Source grants remain required; neither latest-head substitution nor a global READY-Probe prerequisite is implicit. Canonical market identity stays independent of native build bytes, while every accepted capture retains the actual qualified producer provenance.

Acquisition admission retains an operation-specific Host Human policy separately from Source permission. It persists the original intent before provider effects, refreshes proven gaps under the actual execution lease, and stages capture without borrowing the business Client during network waits. Publication retains earlier valid pages, proves exact own subranges and reuses an already complete exact seal. Interrupted or unacknowledged work remains unknown. History/status/latest reads do not acquire data.

Stream construction consumes the original authorized instrument occurrence and actual WAL writer. The concrete Source constructs its actor locally; network connection/baseline work starts in the worker, after the business borrow returns. Each accepted observation appends and syncs one raw-plus-facts bundle and seals its own checked occurrence before delivery. Product limits eight sessions, 256 reliable events and one coalesced preview. Loss, overflow, closure and withdrawal invalidate existing send/preview fences. Closing awaits the actual worker and writer; cancellation of close is not proof of completed drain.

`ProductStream::next` returns an opaque pending occurrence without borrowing storage while waiting. Host then calls `release` with its original business Client-backed Storage; release verifies existing canonical identity and drains physical evidence before authorizing market data or READY. Host must retain the resulting original send fence through physical transmission. A different Resource cannot take over that proof. Source withdrawal blocks disclosure and new provider work but does not prevent Host from preserving already accepted facts.

Real-time background drain and exclusive startup recovery use the same public `drain_market_capture` identity/proof boundary, whose publication reason is `REALTIME_STREAM`. It reads only exact selected authoritative evidence and rejects conflicting canonical values, retaining original WAL and uncertainty. Host must not bypass this protection with bare Storage drain on realtime candidates. Historical acquisition recovery remains an actual Host composition handoff: preserve the original Segment/Intent's `REST_BACKFILL` reason and reuse the same canonical comparison protection; the realtime entry is not a publication-reason converter. WAL's existing exclusive open-segment recovery remains its own prerequisite; no live-open scanning or parallel quarantine authority is introduced.

### Outbound transport dependency inputs

Binance reuses reqwest 0.13.5 and Rustls 0.23.46 with defaults disabled and explicit roots, no proxy discovery, redirects or transparent retries. Maintained tokio-tungstenite/tungstenite 0.30.0 supplies WebSocket framing, fragmentation and controls; `connect` and `__rustls-tls` do not enable native or WebPKI root loaders. Source supplies finite handshake/message deadlines and explicit frame/read/write bounds. SHA-1 is used by the maintained WebSocket handshake as required by that protocol, never for OnlyAlpha canonical identity.

Flate2 1.1.10 uses its Rust backend with defaults disabled. Compressed and complete decoded JSON have independent limits; corrupt/truncated gzip does not publish partial decoded observations. The nine added registry archives are adler2 2.0.1, crc32fast 1.5.3, data-encoding 2.11.1, flate2 1.1.10, miniz_oxide 0.9.1, sha1 0.11.0, simd-adler32 0.3.10 and the two WebSocket crates. Retain their permissive license texts and notices. CRC32fast's sole added build script invokes Cargo's selected rustc for supported intrinsic configuration; pinned compiler and ambient-wrapper guards still apply. No new native C compiler, TLS implementation or system compression library is selected.

The [RustSec tungstenite advisory](https://rustsec.org/advisories/RUSTSEC-2023-0065.html) is patched from 0.20.1; selected 0.30.0 retains bounded handshake parsing. Upstream [issue 557](https://github.com/snapview/tungstenite-rs/issues/557) concerns custom zero-write streams and manually inconsistent httparse requests; this Source supplies maintained Tokio TCP/Rustls streams and compiled valid request URLs. These bounded observations do not assert absence of unknown vulnerabilities or certify unvalidated targets.


## Native workstation route and signal dependencies

The native HTTP boundary uses `utoipa =6.0.0` with only `macros` and
`utoipa-axum =0.3.0` without defaults. The same actual typed route/DTO declaration
registers handlers and exports OpenAPI3.1 independently of startup state.
The bridge selects maintained `pastey 0.2.3`; `utoipa-gen 6.0.1` is the compile-time
schema macro. No schema dependency enters the Kernel. Export does not construct
DB, filesystem, Source or algorithm resources. Tool-only Python and Node retain
canonicalization, immutable-baseline classification and generated projections.

These exact archives declare MIT OR Apache-2.0; retain the selected licenses and
notices. Neither the five new archives nor Tokio1.54.1 declares a build script.
Utoipa-gen and pastey are procedural macros. The actual selected closure adds
indexmap's Serde edge and syn3 full/extra-traits; it does not enable YAML/config,
Axum extras, Swagger UI or another framework. Safe Tokio Unix signals use
`signal-hook-registry 1.4.8` plus the already pinned libc/errno/mio closure.
Signal delivery is operational input; it never grants trading authority.

Tokio1.54.1 is the minimal selected published patch for
[GHSA-5wjr-9356-4wc8](https://github.com/tokio-rs/tokio/security/advisories/GHSA-5wjr-9356-4wc8).
The advisory requires Interval on a multithread runtime; the selected Host
closure remains current-thread and excludes full, rt-multi-thread and process.
This is not a claim that the previous single-thread consumer was affected.
Exact archive checksums and features remain under the canonical lock/guard.
Known upstream schema requiredness/enum limitations require strict named wire
DTOs and actual deserialization/output conformance; schema overrides cannot
mask an unimplemented runtime constraint. Published fixes and bounded advisory
review do not establish absence of unknown vulnerabilities or certify other OSes.

The native workstation owns the retained mutation session, separate readonly driver, bounded HTTP/WS tasks, exact SDK installation, Source/Storage recovery and graceful signal drain. Schema/route export executes before operational configuration and starts none of these resources. The contained Human transport admits only its attested gateway-facing socket and exact 127.0.0.1 health socket on the fixed port; other interfaces, peers, forwarded headers and arbitrary private subnets grant nothing. Private bearer ingress remains loopback-only. Native source runs use the explicit `--user-data-root` path and existing layout; normal startup never initializes, migrates or rebinds stores.

The first native Shipping workstation exposes WebSocket subscriptions only after the same verified local developer cookie/Origin admission as its HTTP session. The generated WS contract declares SUBSCRIBE_BAR and actual server events; AUTH/AUTHENTICATED bearer negotiation is not implemented or advertised. Current Web clients reject bearer WS explicitly. Existing loopback-only private read primitives retain their separate technical policy and do not grant workstation management Authority. This is an explicit development-unfrozen wire evolution under ADR 0130/0141, with all current consumers updated together.
