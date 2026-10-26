//! Explicit node-owned cleartext deployment policy. Never inferred from headers.
use std::net::{IpAddr, SocketAddr};
#[derive(Clone, Debug)]
pub enum Transport {
    Loopback {
        port: u16,
    },
    ContainedDevelopment {
        local: IpAddr,
        gateway: IpAddr,
        port: u16,
    },
}
impl Transport {
    /// The canonical dev launcher attests its exact network endpoint/gateway and
    /// host-loopback publication before passing these operational inputs.
    pub fn contained(
        local: IpAddr,
        gateway: IpAddr,
        publication: SocketAddr,
    ) -> Result<Self, &'static str> {
        if publication != SocketAddr::from(([127, 0, 0, 1], 5173))
            || local == gateway
            || local.is_loopback()
            || gateway.is_loopback()
            || local.is_unspecified()
            || gateway.is_unspecified()
            || !matches!((local,gateway),(IpAddr::V4(a),IpAddr::V4(b)) if a.is_private() && b.is_private())
        {
            return Err("DEV_TRANSPORT_ATTESTATION_INVALID");
        }
        Ok(Self::ContainedDevelopment {
            local,
            gateway,
            port: publication.port(),
        })
    }
    pub fn permits(&self, local: SocketAddr, peer: SocketAddr) -> bool {
        match self {
            Self::Loopback { port } => {
                local.ip().is_loopback() && peer.ip().is_loopback() && local.port() == *port
            }
            Self::ContainedDevelopment {
                local: expected,
                gateway,
                port,
            } => {
                local.port() == *port
                    && ((local.ip() == *expected && peer.ip() == *gateway)
                        || (local.ip() == IpAddr::from([127, 0, 0, 1])
                            && peer.ip() == IpAddr::from([127, 0, 0, 1])))
            }
        }
    }
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn contained_exact_endpoints_never_grant_a_subnet_or_private_bearer_exception() {
        let local = "172.20.0.2:5173".parse().unwrap();
        let peer = "172.20.0.1:43210".parse().unwrap();
        let policy = Transport::contained(
            "172.20.0.2".parse().unwrap(),
            "172.20.0.1".parse().unwrap(),
            "127.0.0.1:5173".parse().unwrap(),
        )
        .unwrap();
        assert!(policy.permits(local, peer));
        assert!(policy.permits(
            "127.0.0.1:5173".parse().unwrap(),
            "127.0.0.1:43210".parse().unwrap()
        ));
        assert!(!policy.permits(
            "127.0.0.2:5173".parse().unwrap(),
            "127.0.0.1:43210".parse().unwrap()
        ));
        for (a, b) in [
            ("172.20.0.3:5173", "172.20.0.1:43210"),
            ("172.20.0.2:5174", "172.20.0.1:43210"),
            ("172.20.0.2:5173", "172.20.0.3:43210"),
            ("172.18.0.2:5173", "172.18.0.1:43210"),
        ] {
            assert!(!policy.permits(a.parse().unwrap(), b.parse().unwrap()));
        }
        assert!(!Transport::Loopback { port: 5173 }.permits(local, peer));
        assert!(
            Transport::contained(local.ip(), peer.ip(), "0.0.0.0:5173".parse().unwrap()).is_err()
        );
        assert!(
            Transport::contained(local.ip(), peer.ip(), "127.0.0.1:5174".parse().unwrap()).is_err()
        );
    }
}
