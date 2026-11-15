-- Exact controlled graph certification is a build fact, never a Run/dispatch grant.
CREATE TABLE public.calculation_build_proof (
 build_key text PRIMARY KEY CHECK(build_key ~ '^[0-9a-f]{64}$'),
 proof_fingerprint text NOT NULL UNIQUE CHECK(proof_fingerprint ~ '^[0-9a-f]{64}$'),
 payload text NOT NULL CHECK(octet_length(payload)<=8388608 AND jsonb_typeof(payload::jsonb)='object'),
 CHECK(payload::jsonb->>'build_key'=build_key),
 CHECK(encode(sha256(convert_to(payload,'UTF8')),'hex')=proof_fingerprint)
);
CREATE TRIGGER calculation_build_proof_immutable BEFORE UPDATE OR DELETE ON public.calculation_build_proof
FOR EACH ROW EXECUTE FUNCTION public.job_content_immutable();
CREATE TRIGGER calculation_build_proof_no_truncate BEFORE TRUNCATE ON public.calculation_build_proof
FOR EACH STATEMENT EXECUTE FUNCTION public.job_content_immutable();
REVOKE ALL ON public.calculation_build_proof FROM PUBLIC;
GRANT SELECT ON public.calculation_build_proof TO onlyalpha_factor_builder,onlyalpha_job_reader;
GRANT INSERT ON public.calculation_build_proof TO onlyalpha_factor_builder;
