# onlyalpha-gateway-protocol

Provider-neutral Protobuf/gRPC bindings and the small infrastructure client for the OnlyAlpha remote Gateway v1 contract.

This package is independently installable. It depends only on `grpcio` and `protobuf`; it does not depend on the OnlyAlpha Kernel,
Product API/client, Strategy, Portfolio, Risk, Research, Runtime, or persistence packages.

The canonical authoring authority is under `contracts/gateway/v1/`. Files in `onlyalpha_gateway_protocol.v1` are generated projections.
Regenerate and verify them through `scripts/gateway_protocol.py`; do not edit generated files directly.

This package does not implement QMT, CTP, order submission, account/position queries, provider reconciliation, or a Product API.
