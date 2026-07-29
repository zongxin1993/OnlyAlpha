# ADR 0043: Historical Store Factory and Runtime State Directory

- Status: Superseded by ADR 0044
- Date: 2026-07-28

This ADR recorded the earlier, transaction-only persistence composition and its limited single-tail restart path. ADR 0044
replaces that design with the unified Runtime Persistence Store, schema version 2, checkpoint participants, exact replay cursor
and multi-transaction tail recovery. No interface or configuration described by this historical ADR remains supported.
