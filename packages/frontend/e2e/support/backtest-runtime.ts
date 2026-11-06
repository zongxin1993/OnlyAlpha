import { execFile } from "node:child_process";
import { promisify } from "node:util";
import { z } from "zod";

const execute = promisify(execFile);
const fingerprint = z.string().regex(/^[0-9a-f]{64}$/);
const flag = z.union([z.literal(0), z.literal(1)]);
const row = z.strictObject({ sequence: z.number().int().positive(), digest: fingerprint });
export const RuntimePrefixSchema = z.strictObject({
    state: z.literal("OBSERVED"),
    device: z.string().regex(/^[0-9]+$/),
    inode: z.string().regex(/^[0-9]+$/),
    metadata: fingerprint,
    binding: fingerprint,
    execution: z
        .array(row.extend({ delivered: flag }))
        .min(1)
        .max(16),
    replay: z.array(row).min(1).max(16)
});
const observation = z.union([
    RuntimePrefixSchema,
    z.strictObject({ state: z.enum(["MISSING", "BUSY", "UNINITIALIZED", "PENDING"]) })
]);
export type RuntimePrefix = z.infer<typeof RuntimePrefixSchema>;

// Technical interruption precondition only. The browser still submits Commands,
// cancels and reads results through the normal UI. No SQL mutation or admission.
const observe = String.raw`
import hashlib, json, pathlib, sqlite3, stat, sys, uuid
root, identity, strategy = pathlib.Path(sys.argv[1]), sys.argv[2], sys.argv[3]
assert root.is_absolute() and str(uuid.UUID(identity)) == identity
assert uuid.UUID(identity).version == 4
path = root / 'backtest' / 'runtime' / identity / 'runtime.sqlite3'
def sha(value): return hashlib.sha256(value.encode()).hexdigest()
def unique(pairs):
    result = {}
    for key, value in pairs:
        assert key not in result, 'duplicate metadata field'
        result[key] = value
    return result
def document(raw, digest):
    assert type(raw) is str and len(raw) <= 16 * 1024 * 1024
    assert sha(raw) == digest, 'actual payload digest mismatch'
    return json.loads(raw, object_pairs_hook=unique)
def inspect():
    candidate = root
    assert not candidate.is_symlink(), 'symlink runtime root'
    for part in ('backtest', 'runtime', identity):
        candidate = candidate / part
        assert not candidate.is_symlink(), 'symlink runtime directory'
    assert not path.is_symlink(), 'runtime database symlink'
    if not path.exists(): return {'state':'MISSING'}
    before = path.lstat()
    assert stat.S_ISREG(before.st_mode) and before.st_nlink == 1, 'invalid runtime file'
    with sqlite3.connect(path.as_uri() + '?mode=ro', uri=True, timeout=0) as db:
        db.execute('PRAGMA query_only=ON')
        db.execute('BEGIN')
        application = db.execute('PRAGMA application_id').fetchone()[0]
        version = db.execute('PRAGMA user_version').fetchone()[0]
        if application == version == 0:
            assert db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall() == []
            return {'state':'UNINITIALIZED'}
        assert application == 0x4f415250 and version == 4, 'wrong runtime schema'
        metadata = db.execute('SELECT singleton,payload,digest FROM meta LIMIT 2').fetchall()
        assert len(metadata) == 1 and metadata[0][0] == 1, 'invalid runtime metadata'
        meta = document(metadata[0][1], metadata[0][2])
        assert type(meta['schema_version']) is int and meta['schema_version'] == 1 and meta['family'] == 'RUST_EXECUTION_RUNTIME'
        config = meta['configuration']
        assert config['runtime_kind'] == 'BACKTEST' and config['engine'] == 'onlyalpha-backtest'
        assert config['profiles'] and all(p['revision'] == strategy for p in config['profiles'].values()), 'foreign strategy'
        bindings = db.execute('SELECT singleton,payload,digest FROM replay_binding LIMIT 2').fetchall()
        if not bindings: return {'state':'PENDING'}
        assert len(bindings) == 1 and bindings[0][0] == 1
        binding = document(bindings[0][1], bindings[0][2])
        assert type(binding['schema_version']) is int and binding['schema_version'] == 2 and binding['work_id'] == identity, 'foreign Run owner'
        assert binding['kernel_artifact'] == meta['kernel_artifact'], 'foreign runtime artifact'
        def prefix(table, delivered=False):
            columns = 'sequence,payload,digest,ready' + (',delivered' if delivered else '')
            rows = db.execute('SELECT ' + columns + ' FROM ' + table + ' ORDER BY sequence LIMIT 16').fetchall()
            result = []
            pending = False
            for number, item in enumerate(rows, 1):
                assert item[0] == number and type(item[3]) is int and item[3] in (0,1), 'broken prefix'
                if delivered: assert type(item[4]) is int and 0 <= item[4] <= item[3]
                if item[3] == 0: pending = True; continue
                assert not pending, 'Ready row after pending prefix'
                document(item[1], item[2])
                result.append({'sequence':item[0], 'digest':item[2], **({'delivered':item[4]} if delivered else {})})
            return result
        execution, replay = prefix('records', True), prefix('replay_steps')
        if not execution or not replay: return {'state':'PENDING'}
        after = path.lstat()
        assert (before.st_dev,before.st_ino) == (after.st_dev,after.st_ino), 'runtime file replaced'
        return {'state':'OBSERVED', 'device':str(after.st_dev), 'inode':str(after.st_ino),
                'metadata':metadata[0][2], 'binding':bindings[0][2], 'execution':execution, 'replay':replay}
try:
    result = inspect()
except sqlite3.OperationalError as error:
    if getattr(error, 'sqlite_errorcode', None) not in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED): raise
    result = {'state':'BUSY'}
print(json.dumps(result))
`;

export async function observeRuntimePrefix(run: string, strategy: string, deadline: number) {
    const root = process.env.ONLYALPHA_BROWSER_USER_DATA_ROOT;
    if (root === undefined) throw new Error("canonical native user data root required");
    const remaining = deadline - Date.now();
    if (remaining <= 0) throw new Error("运行前缀观察超过本用例预算。");
    const { stdout } = await execute(
        "/workspace/.venv/bin/python",
        ["-I", "-c", observe, root, run, strategy],
        { timeout: Math.min(5_000, remaining), maxBuffer: 32 * 1024, shell: false }
    );
    return observation.parse(JSON.parse(stdout));
}

export function requirePreservedPrefix(before: RuntimePrefix, after: RuntimePrefix) {
    for (const field of ["device", "inode", "metadata", "binding"] as const)
        if (before[field] !== after[field]) throw new Error(`原 Run 的 ${field} 已改变。`);
    if (
        after.replay.length < before.replay.length ||
        after.execution.length < before.execution.length
    )
        throw new Error("原 Ready 前缀丢失。");
    for (const [index, previous] of before.replay.entries())
        if (JSON.stringify(previous) !== JSON.stringify(after.replay[index]))
            throw new Error("原 Ready 回放前缀被改写。");
    for (const [index, previous] of before.execution.entries()) {
        const current = after.execution[index];
        if (
            current.sequence !== previous.sequence ||
            current.digest !== previous.digest ||
            current.delivered < previous.delivered
        )
            throw new Error("原 Ready Execution 前缀被改写或投递状态倒退。");
    }
}
