/** Technical evidence after real Shipping UI operations; never creates a business fact. */
import { execFileSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { expect } from "@playwright/test";
import { z } from "zod";

const fingerprint = z.string().regex(/^[0-9a-f]{64}$/);
const commandId = z.uuid({ version: "v4" });
const preparationProof = z.strictObject({
    commandId,
    studyFingerprint: fingerprint,
    factorFingerprint: fingerprint,
    researchCommandId: commandId,
    runId: commandId.nullable(),
    generation: fingerprint,
    revisionFingerprint: fingerprint,
    activationFingerprint: fingerprint,
    activationDisposition: z.enum(["ACTIVATED", "REUSED_CURRENT"]),
    bindingFingerprint: fingerprint,
    workId: commandId,
    generationActivationCount: z.number().int().nonnegative(),
    bindingCount: z.number().int().nonnegative()
});
export type PreparationProof = z.infer<typeof preparationProof>;
const tupleFault = z.strictObject({
    mutation: z.enum(["dataset-materialization", "future-command"]),
    original_sha: fingerprint,
    changed_sha: fingerprint,
    original_value: z.string().max(256),
    original_prepared_fingerprint: fingerprint.nullable()
});
const fileFault = z.strictObject({ fingerprint });
const decimal = z.string().regex(/^(0|[1-9][0-9]*)$/);
const runtimeFault = z.strictObject({ device: decimal, inode: decimal });
const inventoryFault = z.strictObject({
    inventoryBackendPid: z.number().int().positive(),
    writerBackendPid: z.number().int().positive(),
    hostPid: z.number().int().positive()
});
const restored = z.strictObject({});
const root = fileURLToPath(new URL("../../../../", import.meta.url));
const probe = String.raw`
import hashlib,json,os,sys
from pathlib import Path
import psycopg
from psycopg.conninfo import conninfo_to_dict
request=json.load(sys.stdin)
dsn=os.environ['ONLYALPHA_POSTGRES_DSN']
config=conninfo_to_dict(dsn)
if not config.get('dbname','').endswith('_test') or config.get('host')!='postgres' or config.get('port','5432')!='5432': raise RuntimeError('CANONICAL_TEST_DATABASE_REQUIRED')
if not os.environ.get('ONLYALPHA_BROWSER_HOST_PID','').isdigit(): raise RuntimeError('OWNED_BROWSER_HOST_REQUIRED')
data=Path(request['userDataRoot']).resolve(strict=True)
parent=(Path.cwd()/'test-results/native-web-e2e').resolve(strict=True)
if data.name!='user-data' or not data.is_relative_to(parent): raise RuntimeError('ISOLATED_NATIVE_TEST_ROOT_REQUIRED')
command=request['command']
import uuid
if str(uuid.UUID(command))!=command or uuid.UUID(command).version!=4: raise RuntimeError('EXACT_COMMAND_REQUIRED')
with psycopg.connect(dsn) as db:
 db.execute('SET LOCAL statement_timeout=5000')
 row=db.execute('SELECT owner,accepted_fingerprint,accepted_payload,state,outputs_payload FROM research_preparation WHERE command_id=%s',(command,)).fetchone()
 if row is None: raise RuntimeError('PREPARATION_MISSING')
 owner,pin,accepted_raw,state,outputs_raw=row
 accepted=json.loads(accepted_raw); outputs=json.loads(outputs_raw)
 if hashlib.sha256(accepted_raw.encode()).hexdigest()!=pin: raise RuntimeError('ACCEPTED_IDENTITY_MISMATCH')
 if accepted['command_id']!=command or accepted['owner']!=owner: raise RuntimeError('ACCEPTED_RELATION_MISMATCH')
 receipt=db.execute('SELECT command_kind,outcome_kind,outcome_id FROM product_command_receipt WHERE command_id=%s',(command,)).fetchone()
 if receipt!=('PREPARE_FACTOR_RESEARCH','RESEARCH_PREPARATION_OPERATION',pin): raise RuntimeError('PREPARATION_RECEIPT_MISMATCH')
 future=accepted['input']['research_command_id']
 ready=outputs['ready']; prepared=ready['prepared_study']; inputs=ready['prepared_inputs']; environment=outputs['environment']
 run=db.execute('SELECT outcome_id FROM product_command_receipt WHERE command_id=%s AND command_kind=\'CREATE_RESEARCH_RUN\' AND outcome_kind=\'RESEARCH_RUN\'',(future,)).fetchone()
 if request['action']=='terminate-inventory':
  import ipaddress,socket
  if db.execute("SELECT 1 FROM research_run WHERE specification_schema_version=4 AND state NOT IN ('COMPLETED','FAILED','CANCELLED') LIMIT 1").fetchone() is not None: raise RuntimeError('IDLE_RESEARCH_SERVICE_REQUIRED')
  writer_sql="SELECT DISTINCT pid FROM pg_catalog.pg_locks WHERE locktype='advisory' AND database=(SELECT oid FROM pg_catalog.pg_database WHERE datname=current_database()) AND classid=1329199301::pg_catalog.oid AND objid=5::pg_catalog.oid AND objsubid=2 AND mode='ExclusiveLock' AND granted"
  writers=db.execute(writer_sql).fetchall()
  if len(writers)!=1: raise RuntimeError('UNIQUE_ORIGINAL_WRITER_REQUIRED')
  sessions=db.execute("SELECT pid,host(client_addr),client_port,backend_start FROM pg_catalog.pg_stat_activity WHERE datname=current_database() AND usename=current_user AND application_name='onlyalpha-research-inventory' AND backend_type='client backend'").fetchall()
  if len(sessions)!=1 or sessions[0][0]==writers[0][0]: raise RuntimeError('UNIQUE_READ_INVENTORY_REQUIRED')
  pid,client_addr,client_port,backend_start=sessions[0]
  server_addr,server_port=db.execute('SELECT host(inet_server_addr()),inet_server_port()').fetchone()
  host=Path('/proc')/os.environ['ONLYALPHA_BROWSER_HOST_PID']
  inodes=set()
  for fd in (host/'fd').iterdir():
   try: link=os.readlink(fd)
   except FileNotFoundError: continue
   if link.startswith('socket:[') and link.endswith(']'): inodes.add(link[8:-1])
  def address(raw):
   encoded,port=raw.split(':'); data=bytes.fromhex(encoded)
   decoded=data[::-1] if len(data)==4 else b''.join(data[i:i+4][::-1] for i in range(0,16,4))
   value=ipaddress.ip_address(decoded)
   return str(getattr(value,'ipv4_mapped',None) or value),int(port,16)
  matched=[]
  for name in ('tcp','tcp6'):
   for line in (host/'net'/name).read_text().splitlines()[1:]:
    fields=line.split()
    if fields[9] in inodes and fields[3]=='01' and address(fields[1])==(client_addr,client_port) and address(fields[2])==(server_addr,server_port): matched.append(fields[9])
  if len(matched)!=1: raise RuntimeError('ACTUAL_HOST_INVENTORY_SOCKET_REQUIRED')
  killed=db.execute("SELECT pg_terminate_backend(a.pid) FROM pg_catalog.pg_stat_activity a WHERE a.pid=%s AND a.backend_start=%s AND a.datname=current_database() AND a.application_name='onlyalpha-research-inventory' AND NOT EXISTS(SELECT 1 FROM pg_catalog.pg_locks l WHERE l.pid=a.pid AND l.locktype='advisory' AND l.classid=1329199301::pg_catalog.oid AND l.objid=5::pg_catalog.oid AND l.objsubid=2 AND l.granted)",(pid,backend_start)).fetchone()
  if killed!=(True,) or db.execute(writer_sql).fetchall()!=writers: raise RuntimeError('ORIGINAL_WRITER_MUST_REMAIN_HELD')
  print(json.dumps({'inventoryBackendPid':pid,'writerBackendPid':writers[0][0],'hostPid':int(os.environ['ONLYALPHA_BROWSER_HOST_PID'])}))
 elif request['action'] in ('hide-runtime','restore-runtime'):
  selected=data/'runtime'; held=data.parent/('controlled-missing-runtime-'+command)
  if request['action']=='hide-runtime':
   if run is None or db.execute("SELECT 1 FROM research_run WHERE specification_schema_version=4 AND state NOT IN ('COMPLETED','FAILED','CANCELLED') LIMIT 1").fetchone() is not None: raise RuntimeError('DRAINED_ORIGINAL_RUN_REQUIRED')
   if selected.is_symlink() or not selected.is_dir() or held.exists(): raise RuntimeError('ORIGINAL_RUNTIME_REQUIRED')
   identity=selected.stat();selected.rename(held)
   print(json.dumps({'device':str(identity.st_dev),'inode':str(identity.st_ino)}))
  else:
   identity=held.stat()
   if selected.exists() or held.is_symlink() or str(identity.st_dev)!=request['device'] or str(identity.st_ino)!=request['inode']: raise RuntimeError('EXACT_RUNTIME_RESTORE_REQUIRED')
   held.rename(selected);print('{}')
 elif request['action'] in ('hide-file','restore-file'):
  kind=request['kind']
  if kind=='novelty-group': selected=data/'research/novelty-decision-groups'/future/'group.json'
  elif kind=='installed-proof': selected=data/'runtime/runtime-generation-installed-proof'/environment['runtime_generation_fingerprint']/(environment['installed_proof_fingerprint']+'.json')
  else: raise RuntimeError('UNKNOWN_ORIGINAL_FACT')
  held=data.parent/('controlled-missing-'+command+'-'+kind)
  if request['action']=='hide-file':
   if selected.is_symlink() or not selected.is_file() or held.exists(): raise RuntimeError('ORIGINAL_FACT_REQUIRED')
   digest=hashlib.sha256(selected.read_bytes()).hexdigest()
   selected.rename(held)
   print(json.dumps({'fingerprint':digest}))
  else:
   if selected.exists() or held.is_symlink() or hashlib.sha256(held.read_bytes()).hexdigest()!=request['fingerprint']: raise RuntimeError('EXACT_ORIGINAL_FACT_RESTORE_REQUIRED')
   held.rename(selected)
   print('{}')
 elif request['action']=='inject':
  if state!='READY' or run is not None: raise RuntimeError('QUIESCENT_UNSUBMITTED_READY_REQUIRED')
  # Prove exact reversible serialization before changing this test-owned row.
  canonical=lambda value: json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'))
  sha=lambda raw: hashlib.sha256(raw.encode()).hexdigest()
  if canonical(outputs)!=outputs_raw: raise RuntimeError('EXACT_ORIGINAL_SERIALIZATION_REQUIRED')
  original_sha=sha(outputs_raw); original_prepared_fingerprint=None
  mutation=request['mutation']
  if mutation=='dataset-materialization':
   original_value=inputs['dataset_materialization']['materialization_id']
   inputs['dataset_materialization']['materialization_id']='dataset-materialization:'+'0'*64
  elif mutation=='future-command':
   original_value=prepared['command_id'];original_prepared_fingerprint=ready['prepared_study_fingerprint']
   prepared['command_id']='00000000-0000-4000-8000-000000000001'
   ready['prepared_study_fingerprint']=sha(canonical(prepared))
  else: raise RuntimeError('UNSUPPORTED_CONTROLLED_FAULT')
  changed=canonical(outputs)
  db.execute('SET LOCAL session_replication_role=replica')
  count=db.execute('UPDATE research_preparation SET outputs_payload=%s WHERE command_id=%s AND outputs_payload=%s AND state=\'READY\' AND NOT EXISTS(SELECT 1 FROM product_command_admission WHERE command_id=%s)',(changed,command,outputs_raw,future)).rowcount
  if count!=1: raise RuntimeError('QUIESCENT_READY_CAS_FAILED')
  print(json.dumps({'mutation':mutation,'original_sha':original_sha,'changed_sha':sha(changed),'original_value':original_value,'original_prepared_fingerprint':original_prepared_fingerprint}))
 elif request['action']=='restore':
  if state!='READY' or run is not None: raise RuntimeError('QUIESCENT_UNSUBMITTED_READY_REQUIRED')
  canonical=lambda value: json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'))
  sha=lambda raw: hashlib.sha256(raw.encode()).hexdigest()
  if sha(outputs_raw)!=request['changed_sha']: raise RuntimeError('EXACT_CHANGED_OUTPUTS_REQUIRED')
  if request['mutation']=='dataset-materialization':
   inputs['dataset_materialization']['materialization_id']=request['original_value']
  elif request['mutation']=='future-command':
   prepared['command_id']=request['original_value']
   ready['prepared_study_fingerprint']=request['original_prepared_fingerprint']
  else: raise RuntimeError('UNSUPPORTED_CONTROLLED_FAULT')
  original=canonical(outputs)
  if sha(original)!=request['original_sha']: raise RuntimeError('EXACT_ORIGINAL_OUTPUTS_REQUIRED')
  db.execute('SET LOCAL session_replication_role=replica')
  count=db.execute('UPDATE research_preparation SET outputs_payload=%s WHERE command_id=%s AND outputs_payload=%s AND state=\'READY\' AND NOT EXISTS(SELECT 1 FROM product_command_admission WHERE command_id=%s)',(original,command,outputs_raw,future)).rowcount
  if count!=1: raise RuntimeError('FAULT_RESTORE_REQUIRES_EXACT_UNCHANGED_ROW')
  print('{}')
 elif request['action']=='read':
  events=[json.loads(line) for line in (data/'runtime/generation-events.jsonl').read_text().splitlines()]
  generation=environment['runtime_generation_fingerprint']; activation=environment['activation']; binding=environment['binding']
  if events.count(activation)!=1 or events.count(binding)!=1: raise RuntimeError('ORIGINAL_JOURNAL_FACT_MISSING')
  if inputs['runtime_work_binding']!=binding or ready['preparation_command_id']!=command or prepared['command_id']!=future or ready['study_proposal_fingerprint']!=accepted['input']['study_proposal_fingerprint']: raise RuntimeError('READY_TUPLE_MISMATCH')
  runid=run[0] if run else None
  if runid is not None:
   authorization=db.execute('SELECT payload FROM research_factor_study_authorization WHERE run_id=%s AND command_id=%s',(runid,future)).fetchone()
   if authorization is None: raise RuntimeError('ORIGINAL_RUN_AUTHORIZATION_MISSING')
   auth=json.loads(authorization[0])
   if auth['prepared_inputs']!=inputs or auth['request']!=prepared['request'] or auth['run_id']!=binding['work_id']: raise RuntimeError('ORIGINAL_RUN_RELATION_MISMATCH')
  print(json.dumps({'commandId':command,'studyFingerprint':accepted['input']['study_proposal_fingerprint'],'factorFingerprint':accepted['study']['factor_proposal_fingerprint'],'researchCommandId':future,'runId':runid,'generation':generation,'revisionFingerprint':ready['revision_fingerprint'],'activationFingerprint':activation['event_fingerprint'],'activationDisposition':environment['activation_disposition'],'bindingFingerprint':binding['event_fingerprint'],'workId':binding['work_id'],'generationActivationCount':sum(e['kind']=='GenerationActivated' and e['generation_fingerprint']==generation for e in events),'bindingCount':sum(e['kind']=='RuntimeWorkBound' and e['work_id']==binding['work_id'] for e in events)}))
 else: raise RuntimeError('UNKNOWN_TECHNICAL_ASSERTION')
`;
function inspect(request: Record<string, unknown>): unknown {
    return JSON.parse(
        execFileSync("python3", ["-c", probe], {
            cwd: root,
            input: JSON.stringify(request),
            encoding: "utf8",
            timeout: 10_000,
            // Never expose a DSN or child driver diagnostic in assertion output.
            stdio: ["pipe", "pipe", "pipe"]
        })
    ) as unknown;
}
export function readPreparationProof(commandId: string, userDataRoot: string): PreparationProof {
    return preparationProof.parse(inspect({ action: "read", command: commandId, userDataRoot }));
}
export function assertStudiesReuseGeneration(
    first: PreparationProof,
    second: PreparationProof
): void {
    expect(second.factorFingerprint).toBe(first.factorFingerprint);
    expect(second.studyFingerprint).not.toBe(first.studyFingerprint);
    expect(second.researchCommandId).not.toBe(first.researchCommandId);
    expect(second.runId).not.toBeNull();
    expect(first.runId).not.toBeNull();
    expect(second.runId).not.toBe(first.runId);
    expect(second.generation).toBe(first.generation);
    expect(second.revisionFingerprint).toBe(first.revisionFingerprint);
    expect(first.activationDisposition).toBe("ACTIVATED");
    expect(second.activationDisposition).toBe("REUSED_CURRENT");
    expect(second.activationFingerprint).toBe(first.activationFingerprint);
    expect(second.generationActivationCount).toBe(1);
    expect(first.bindingCount).toBe(1);
    expect(second.bindingCount).toBe(1);
    expect(second.bindingFingerprint).not.toBe(first.bindingFingerprint);
    expect(second.workId).toBe(second.runId);
    expect(first.workId).toBe(first.runId);
}
export async function withCorruptedReadyTuple(
    commandId: string,
    userDataRoot: string,
    mutation: "dataset-materialization" | "future-command",
    observeThroughUI: () => Promise<void>
): Promise<void> {
    const original = tupleFault.parse(
        inspect({ action: "inject", command: commandId, userDataRoot, mutation })
    );
    try {
        await observeThroughUI();
    } finally {
        restored.parse(
            inspect({ action: "restore", command: commandId, userDataRoot, ...original })
        );
    }
}

/** Hide one actual retained fact; the UI must retain the known accepted Run outcome. */
export async function withMissingPreparationFact(
    commandId: string,
    userDataRoot: string,
    kind: "novelty-group" | "installed-proof",
    observeThroughUI: () => Promise<void>
): Promise<void> {
    const original = fileFault.parse(
        inspect({ action: "hide-file", command: commandId, userDataRoot, kind })
    );
    try {
        await observeThroughUI();
    } finally {
        restored.parse(
            inspect({ action: "restore-file", command: commandId, userDataRoot, kind, ...original })
        );
    }
}

/** A lost retained Registry is unavailable, never a fresh namespace. */
export async function withMissingRuntimeRoot(
    commandId: string,
    userDataRoot: string,
    observeThroughUI: () => Promise<void>
): Promise<void> {
    const original = runtimeFault.parse(
        inspect({ action: "hide-runtime", command: commandId, userDataRoot })
    );
    try {
        await observeThroughUI();
    } finally {
        restored.parse(
            inspect({ action: "restore-runtime", command: commandId, userDataRoot, ...original })
        );
    }
}

/** Stop only the existing Host-owned read inventory socket, preserving mutation Authority. */
export function terminateResearchInventory(
    commandId: string,
    userDataRoot: string
): z.infer<typeof inventoryFault> {
    return inventoryFault.parse(
        inspect({ action: "terminate-inventory", command: commandId, userDataRoot })
    );
}
