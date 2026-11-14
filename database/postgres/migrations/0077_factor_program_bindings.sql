-- Forward-only storage primitives. No compiler/certifier is enabled here.
-- Roles are backend service capabilities, not a public authoring API.
DO $$
DECLARE r text;
BEGIN
  FOREACH r IN ARRAY ARRAY['onlyalpha_factor_builder','onlyalpha_job_reader','onlyalpha_job_publisher'] LOOP
    IF NOT EXISTS (SELECT 1 FROM pg_catalog.pg_roles WHERE rolname=r) THEN
      EXECUTE format('CREATE ROLE %I NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS NOINHERIT',r);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_catalog.pg_authid WHERE rolname=r AND NOT rolcanlogin AND NOT rolsuper
      AND NOT rolcreatedb AND NOT rolcreaterole AND NOT rolreplication AND NOT rolbypassrls AND NOT rolinherit
      AND rolpassword IS NULL AND rolconnlimit=-1 AND (rolvaliduntil IS NULL OR rolvaliduntil='infinity'::timestamptz))
      OR EXISTS (SELECT 1 FROM pg_catalog.pg_auth_members m JOIN pg_catalog.pg_roles p ON p.oid=m.member WHERE p.rolname=r)
      OR EXISTS (SELECT 1 FROM pg_catalog.pg_shdepend d JOIN pg_catalog.pg_roles p ON p.oid=d.refobjid
        WHERE d.refclassid='pg_catalog.pg_authid'::regclass AND p.rolname=r
          AND (d.dbid=0 OR d.dbid=(SELECT oid FROM pg_catalog.pg_database WHERE datname=current_database()))) THEN
      RAISE EXCEPTION 'JOB_DATABASE_ROLE_UNSAFE';
    END IF;
  END LOOP;
END $$;

CREATE FUNCTION public.job_content_immutable() RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $$
BEGIN RAISE EXCEPTION 'JOB_CONTENT_IMMUTABLE'; END $$;
REVOKE ALL ON FUNCTION public.job_content_immutable() FROM PUBLIC;

CREATE TABLE public.factor_built_program (
  program_fingerprint text PRIMARY KEY CHECK (program_fingerprint ~ '^[0-9a-f]{64}$'),
  source_sha256 text NOT NULL CHECK (source_sha256 ~ '^[0-9a-f]{64}$'),
  payload text NOT NULL CHECK (octet_length(payload)<=8388608),
  CHECK (encode(sha256(convert_to(payload,'UTF8')),'hex')=program_fingerprint),
  CHECK (payload::jsonb->>'contract' IS NOT DISTINCT FROM 'FACTOR_PROGRAM_CONTAINER_V1'),
  CHECK (payload::jsonb->>'source_sha256' IS NOT DISTINCT FROM source_sha256),
  CHECK (payload::jsonb->>'numeric_policy' IS NOT DISTINCT FROM 'DECIMAL28_HALF_EVEN_Q12_V1'),
  UNIQUE(program_fingerprint,source_sha256)
);
ALTER TABLE public.private_factor_revision ADD CONSTRAINT private_factor_revision_source_identity
  UNIQUE(revision_fingerprint,source_sha256);
CREATE TABLE public.factor_parameter_certificate (
  certificate_fingerprint text PRIMARY KEY CHECK (certificate_fingerprint ~ '^[0-9a-f]{64}$'),
  revision_fingerprint text NOT NULL,
  program_fingerprint text NOT NULL,
  source_sha256 text NOT NULL,
  parameters_fingerprint text NOT NULL CHECK (parameters_fingerprint ~ '^[0-9a-f]{64}$'),
  parameters_payload text NOT NULL CHECK(octet_length(parameters_payload)<=262144),
  payload text NOT NULL CHECK(octet_length(payload)<=8388608),
  FOREIGN KEY(revision_fingerprint,source_sha256) REFERENCES public.private_factor_revision(revision_fingerprint,source_sha256),
  FOREIGN KEY(program_fingerprint,source_sha256) REFERENCES public.factor_built_program(program_fingerprint,source_sha256),
  CHECK (encode(sha256(convert_to(parameters_payload,'UTF8')),'hex')=parameters_fingerprint),
  CHECK (encode(sha256(convert_to(payload,'UTF8')),'hex')=certificate_fingerprint),
  CHECK (payload::jsonb->>'contract' IS NOT DISTINCT FROM 'FACTOR_PARAMETER_CERTIFICATE_V1'),
  CHECK (payload::jsonb->>'revision_fingerprint' IS NOT DISTINCT FROM revision_fingerprint),
  CHECK (payload::jsonb->>'program_fingerprint' IS NOT DISTINCT FROM program_fingerprint),
  CHECK (payload::jsonb->>'parameters_fingerprint' IS NOT DISTINCT FROM parameters_fingerprint),
  CHECK (payload::jsonb->>'numeric_policy' IS NOT DISTINCT FROM 'DECIMAL28_HALF_EVEN_Q12_V1')
);
CREATE TRIGGER factor_built_program_immutable BEFORE UPDATE OR DELETE OR TRUNCATE ON public.factor_built_program
  FOR EACH STATEMENT EXECUTE FUNCTION public.job_content_immutable();
CREATE TRIGGER factor_parameter_certificate_immutable BEFORE UPDATE OR DELETE OR TRUNCATE ON public.factor_parameter_certificate
  FOR EACH STATEMENT EXECUTE FUNCTION public.job_content_immutable();
REVOKE ALL ON public.factor_built_program,public.factor_parameter_certificate FROM PUBLIC;
GRANT USAGE ON SCHEMA public TO onlyalpha_factor_builder,onlyalpha_job_reader,onlyalpha_job_publisher;
GRANT SELECT ON public.research_deployment_semantic_store_binding TO onlyalpha_factor_builder,onlyalpha_job_reader,onlyalpha_job_publisher;
GRANT SELECT(revision_fingerprint,source_sha256) ON public.private_factor_revision TO onlyalpha_factor_builder,onlyalpha_job_reader,onlyalpha_job_publisher;
GRANT SELECT ON public.factor_built_program,public.factor_parameter_certificate TO onlyalpha_factor_builder,onlyalpha_job_reader,onlyalpha_job_publisher;
GRANT INSERT ON public.factor_built_program,public.factor_parameter_certificate TO onlyalpha_factor_builder;
