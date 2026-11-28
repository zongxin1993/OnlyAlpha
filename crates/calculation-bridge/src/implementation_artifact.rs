use serde_json::{Value, json};

/// 宿主核验的可执行工件，以发行目录内的相对路径和实际字节摘要标识。
#[derive(Clone, Debug)]
pub struct ImplementationArtifact {
    relative_path: String,
    byte_sha256: String,
}

impl ImplementationArtifact {
    pub fn new(relative_path: &str, byte_sha256: &str) -> Result<Self, &'static str> {
        let path = relative_path.as_bytes();
        let drive_prefix = path.get(1) == Some(&b':') && path[0].is_ascii_alphabetic();
        if drive_prefix
            || relative_path.contains('\\')
            || relative_path.chars().any(char::is_control)
            || relative_path
                .split('/')
                .any(|part| matches!(part, "" | "." | ".."))
            || !crate::process::sha(byte_sha256)
        {
            return Err("IMPLEMENTATION_ARTIFACT_INVALID");
        }
        Ok(Self {
            relative_path: relative_path.to_owned(),
            byte_sha256: byte_sha256.to_owned(),
        })
    }

    pub(crate) fn manifest_resources(&self) -> (Value, String) {
        let resources =
            json!([{"relative_path": self.relative_path, "byte_sha256": self.byte_sha256}]);
        let fingerprint = onlyalpha_strategy::record_fingerprint(&json!({
            "domain": "onlyalpha.calculation.implementation-bundle", "schema_version": 1, "resources": resources
        }));
        (resources, fingerprint)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn artifact_requires_canonical_relative_path_and_lowercase_sha256() {
        let digest = "f".repeat(64);
        for path in [
            "",
            "/image",
            "./image",
            "dir/../image",
            "dir//image",
            "dir/",
            "dir\\image",
            "C:/image",
            "C:image",
            "image\0",
        ] {
            assert!(
                ImplementationArtifact::new(path, &digest).is_err(),
                "{path:?}"
            );
        }
        for invalid in [
            "F".repeat(64),
            "g".repeat(64),
            "0".repeat(63),
            "0".repeat(65),
        ] {
            assert!(ImplementationArtifact::new("bin/runner", &invalid).is_err());
        }
        let artifact = ImplementationArtifact::new("bin/runner", &digest).unwrap();
        assert_eq!(
            artifact.manifest_resources().0,
            json!([{"relative_path":"bin/runner", "byte_sha256":digest}])
        );
    }
}
