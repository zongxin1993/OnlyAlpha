-- Read-only validation of the approved Node database profile. This creates no
-- role, grant, business fact, claim or readiness capability. One bound LOGIN;
-- Rust additionally binds the actual authenticated session and configured user.
WITH
requested AS (SELECT $1::text AS login),
capabilities(role_name, inherit_option, set_option) AS (VALUES
  ('onlyalpha_node_control'::text,true,false),
  ('onlyalpha_job_reader',false,true),
  ('onlyalpha_job_publisher',false,true)),
login AS (SELECT r.* FROM pg_catalog.pg_roles r,requested q WHERE r.rolname=q.login),
groups AS (SELECT r.* FROM pg_catalog.pg_roles r JOIN capabilities c ON c.role_name=r.rolname),
checked AS (SELECT oid,rolname FROM login UNION SELECT oid,rolname FROM groups),
database_id AS (SELECT oid FROM pg_catalog.pg_database WHERE datname=pg_catalog.current_database()),
acl AS (
  SELECT a.* FROM pg_catalog.pg_class c CROSS JOIN LATERAL pg_catalog.aclexplode(c.relacl) a
  UNION ALL SELECT x.* FROM pg_catalog.pg_attribute a CROSS JOIN LATERAL pg_catalog.aclexplode(a.attacl) x
  UNION ALL SELECT a.* FROM pg_catalog.pg_namespace n CROSS JOIN LATERAL pg_catalog.aclexplode(n.nspacl) a
  UNION ALL SELECT a.* FROM pg_catalog.pg_proc p CROSS JOIN LATERAL pg_catalog.aclexplode(p.proacl) a
  UNION ALL SELECT a.* FROM pg_catalog.pg_database d CROSS JOIN LATERAL pg_catalog.aclexplode(d.datacl) a WHERE d.oid=(SELECT oid FROM database_id)),
objects AS (SELECT c.oid,c.relname FROM pg_catalog.pg_class c
  JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
  WHERE n.nspname='public' AND c.relkind IN ('r','p','v','m','f')),
columns AS (SELECT c.oid,c.relname,a.attnum,a.attname FROM objects c
  JOIN pg_catalog.pg_attribute a ON a.attrelid=c.oid WHERE a.attnum>0 AND NOT a.attisdropped),
read_tables(table_name) AS (VALUES
  ('research_deployment_semantic_store_binding'::text),('factor_built_program'),
  ('factor_parameter_certificate'),('job_frozen_binding'),('job_result_member'),
  ('job_publication'),('research_run'),('research_run_attempt'),('backtest_run'),('backtest_run_attempt')),
publisher_updates(table_name,column_name) AS (VALUES
  ('research_run'::text,'revision'::text),('research_run','state'),('research_run','finished_at'),
  ('research_run','research_result_fingerprint'),('research_run','artifact_content_fingerprint'),
  ('research_run','calculation_execution_evidence_fingerprints'),
  ('backtest_run','revision'),('backtest_run','state'),('backtest_run','finished_at'),
  ('backtest_run','evidence_fingerprint'),('backtest_run','result_fingerprint'),('backtest_run','determinism_fingerprint'),
  ('research_run_attempt','state'),('research_run_attempt','finished_at'),
  ('backtest_run_attempt','state'),('backtest_run_attempt','finished_at')),
control_forbidden(table_name) AS (VALUES
  ('job_frozen_binding'::text),('job_result_member'),('job_publication'),
  ('factor_built_program'),('factor_parameter_certificate'),('factor_build_request'),('calculation_build_proof')),
result_columns(table_name,column_name,privileges) AS (VALUES
  ('research_run'::text,'research_result_fingerprint'::text,'INSERT,UPDATE'::text),
  ('research_run','artifact_content_fingerprint','INSERT,UPDATE'),
  ('research_run','calculation_execution_evidence_fingerprints','UPDATE'),
  ('backtest_run','evidence_fingerprint','INSERT,UPDATE'),
  ('backtest_run','result_fingerprint','INSERT,UPDATE'),
  ('backtest_run','determinism_fingerprint','INSERT,UPDATE')),
closed_functions(signature) AS (VALUES
  ('public.chart_native_context_v1(uuid,uuid,text,text,text)'::text),
  ('public.chart_native_claim_v1(integer,uuid,uuid,bigint,text,text,text,uuid,uuid,interval,integer,timestamptz)'),
  ('public.chart_native_heartbeat_v1(integer,uuid,uuid,bigint,text,text,text,uuid,uuid,integer,interval)')),
violations(priority,code) AS (
  SELECT 10,'NODE_CAPABILITY_ROLE_REFUSED'::text WHERE
    (SELECT count(*) FROM groups)<>3 OR EXISTS(SELECT 1 FROM groups g WHERE
      g.rolcanlogin OR g.rolsuper OR g.rolcreatedb OR g.rolcreaterole OR g.rolreplication OR g.rolbypassrls OR g.rolinherit
      OR EXISTS(SELECT 1 FROM pg_catalog.pg_auth_members m WHERE m.member=g.oid))
  UNION ALL SELECT 20,'NODE_ROLE_IDENTITY_REFUSED' WHERE
    (SELECT count(*) FROM login)<>1 OR EXISTS(SELECT 1 FROM login l WHERE NOT l.rolcanlogin OR NOT l.rolinherit
      OR l.rolsuper OR l.rolcreatedb OR l.rolcreaterole OR l.rolreplication OR l.rolbypassrls
      OR l.rolconnlimit<>-1 OR (l.rolvaliduntil IS NOT NULL AND l.rolvaliduntil<>'infinity'::timestamptz))
  UNION ALL SELECT 30,'NODE_ROLE_MEMBERSHIP_REFUSED' WHERE
    (SELECT count(*) FROM pg_catalog.pg_auth_members m JOIN login l ON l.oid=m.member)<>3
    OR EXISTS(SELECT 1 FROM pg_catalog.pg_auth_members m JOIN login l ON l.oid=m.member
      JOIN pg_catalog.pg_roles parent ON parent.oid=m.roleid LEFT JOIN capabilities c ON c.role_name=parent.rolname
      WHERE c.role_name IS NULL OR m.admin_option OR m.inherit_option IS DISTINCT FROM c.inherit_option
        OR m.set_option IS DISTINCT FROM c.set_option)
  UNION ALL SELECT 40,'NODE_ROLE_CONFIGURATION_REFUSED' WHERE EXISTS(
    SELECT 1 FROM pg_catalog.pg_db_role_setting s JOIN checked r ON r.oid=s.setrole
    WHERE s.setconfig IS NOT NULL AND (s.setdatabase=0 OR s.setdatabase=(SELECT oid FROM database_id)))
  UNION ALL SELECT 50,'NODE_ROLE_DIRECT_AUTHORITY_REFUSED' WHERE
    EXISTS(SELECT 1 FROM pg_catalog.pg_shdepend d JOIN checked r ON r.oid=d.refobjid
      WHERE d.refclassid='pg_catalog.pg_authid'::regclass AND d.deptype='o'
        AND (d.dbid=0 OR d.dbid=(SELECT oid FROM database_id)))
    OR EXISTS(SELECT 1 FROM acl JOIN login l ON l.oid=acl.grantee)
  UNION ALL SELECT 60,'NODE_CAPABILITY_PERMISSION_REFUSED' WHERE
    EXISTS(SELECT 1 FROM checked r WHERE pg_catalog.has_schema_privilege(r.oid,'public','CREATE')
      OR pg_catalog.has_database_privilege(r.oid,pg_catalog.current_database(),'CREATE'))
    OR EXISTS(SELECT 1 FROM checked r CROSS JOIN closed_functions f WHERE
      pg_catalog.has_function_privilege(r.oid,pg_catalog.to_regprocedure(f.signature),'EXECUTE') IS DISTINCT FROM false)
    OR EXISTS(SELECT 1 FROM acl WHERE is_grantable AND (grantee=0 OR grantee IN (SELECT oid FROM checked)))
    OR EXISTS(SELECT 1 FROM groups r CROSS JOIN control_forbidden f WHERE r.rolname='onlyalpha_node_control' AND (
      pg_catalog.has_table_privilege(r.oid,'public.'||f.table_name,'SELECT,INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER,MAINTAIN')
      OR pg_catalog.has_any_column_privilege(r.oid,'public.'||f.table_name,'SELECT,INSERT,UPDATE,REFERENCES')))
    OR EXISTS(SELECT 1 FROM groups r CROSS JOIN result_columns f WHERE r.rolname='onlyalpha_node_control'
      AND pg_catalog.has_column_privilege(r.oid,'public.'||f.table_name,f.column_name,f.privileges))
    OR EXISTS(SELECT 1 FROM groups r CROSS JOIN columns c WHERE r.rolname IN ('onlyalpha_job_reader','onlyalpha_job_publisher')
      AND pg_catalog.has_column_privilege(r.oid,c.oid,c.attnum,'SELECT')
      AND NOT (c.relname IN (SELECT table_name FROM read_tables)
        OR (r.rolname='onlyalpha_job_reader' AND c.relname IN ('factor_build_request','calculation_build_proof'))
        OR (c.relname='private_factor_revision' AND (c.attname IN ('revision_fingerprint','source_sha256')
          OR (r.rolname='onlyalpha_job_reader' AND c.attname='factor_id')))))
    OR EXISTS(SELECT 1 FROM groups r CROSS JOIN objects c WHERE r.rolname IN ('onlyalpha_job_reader','onlyalpha_job_publisher') AND (
      pg_catalog.has_table_privilege(r.oid,c.oid,'UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER,MAINTAIN')
      OR pg_catalog.has_any_column_privilege(r.oid,c.oid,'REFERENCES')
      OR (pg_catalog.has_any_column_privilege(r.oid,c.oid,'INSERT') AND NOT (
        r.rolname='onlyalpha_job_publisher' AND c.relname IN ('job_frozen_binding','job_result_member','job_publication')))))
    OR EXISTS(SELECT 1 FROM groups r CROSS JOIN columns c WHERE r.rolname IN ('onlyalpha_job_reader','onlyalpha_job_publisher')
      AND pg_catalog.has_column_privilege(r.oid,c.oid,c.attnum,'UPDATE') AND NOT (
        r.rolname='onlyalpha_job_publisher' AND EXISTS(SELECT 1 FROM publisher_updates u WHERE u.table_name=c.relname AND u.column_name=c.attname)))
)
SELECT COALESCE((SELECT code FROM violations ORDER BY priority LIMIT 1),'OK') AS result;
