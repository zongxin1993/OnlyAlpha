# 私有协议 loopback TLS 测试向量

这组固定公开向量由 Tushare 与 Binance Broker 的离线 HTTPS/WSS 测试共享，保留原 Tushare 内嵌向量的完整字节。

- `ca.pem`：测试 CA 证书。
- `server.pem`：loopback 服务端证书。
- `server-key.pem`：该服务端证书的公开测试私钥。

目录不包含 CA 私钥或实际账户凭据。测试显式加载这组信任材料，运行时不调用 OpenSSL，也不使用开发环境 CA。
