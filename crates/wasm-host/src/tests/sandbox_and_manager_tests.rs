use crate::{
    ArtifactBinding, CertificationRequest, Error, GoldenCase, MarketRuleInput, NamedFactor,
    OrderSide, OrderType, PluginKind, ReadonlyAccountState, ReadonlyPosition, ResourceBudget,
    TimeInForce, WIT_CONTRACT_VERSION, WasmPluginManager, sha256_hex,
};
use onlyalpha_operators::algebra::Decimal;
use onlyalpha_operators::execution::VectorKernel;
use std::collections::BTreeMap;

fn dec(raw: &str) -> Decimal {
    raw.parse::<Decimal>().expect("valid test decimal")
}

/// Builds a real WebAssembly Component Model binary implementing `onlyalpha:plugin/extended-operator@1.0.0`.
///
/// The component implements a stateful `Lag1` operator (`warmup = 2`, `input-arity = 1`,
/// `numeric-policy = DECIMAL28_HALF_EVEN_Q12_V1`):
/// - `eval-vector`: returns `[None, col[0], col[1], ..., col[n-2]]`
/// - `init-event`: resets state slot in linear memory
/// - `step-event`: emits buffered prior `option<string>` and stores current `option<string>`
/// - `capture-state`: serializes `[has_prev: u8, len: u32 LE, bytes...]`
/// - `restore-state`: restores serialized state into linear memory (fails cleanly on bad bytes)
///
/// Fault-injection knobs create genuine adversarial `.wasm` binaries for negative certification
/// and Fail-Closed sandbox tests.
#[derive(Clone, Copy)]
struct OperatorVariant {
    interface_name: &'static str,
    warmup: u32,
    numeric_policy: &'static str,
    lookahead_vector: bool,
    mismatched_event: bool,
    broken_restore: bool,
    infinite_loop_vector: bool,
    oom_vector: bool,
    trap_vector: bool,
    omit_restore_export: bool,
}

impl Default for OperatorVariant {
    fn default() -> Self {
        Self {
            interface_name: "onlyalpha:plugin/extended-operator@1.0.0",
            warmup: 2,
            numeric_policy: "DECIMAL28_HALF_EVEN_Q12_V1",
            lookahead_vector: false,
            mismatched_event: false,
            broken_restore: false,
            infinite_loop_vector: false,
            oom_vector: false,
            trap_vector: false,
            omit_restore_export: false,
        }
    }
}

fn compile_operator_component(v: OperatorVariant) -> Vec<u8> {
    let vector_fault = if v.infinite_loop_vector {
        "(loop $spin (br $spin))"
    } else if v.oom_vector {
        "(if (i32.eq (memory.grow (i32.const 64)) (i32.const -1)) (then (unreachable)))"
    } else if v.trap_vector {
        "(unreachable)"
    } else {
        ""
    };

    // In normal mode: out[0] = None, out[i] = in[i - 1] (causal lag 1).
    // In lookahead mode: out[i] = in[i + 1] for i + 1 < len, else None (peeks into future!).
    let vector_loop_body = if v.lookahead_vector {
        r#"
            (if (i32.lt_u (i32.add (local.get $i) (i32.const 1)) (local.get $col_len))
              (then
                (local.set $src (i32.add (local.get $col_ptr) (i32.mul (i32.add (local.get $i) (i32.const 1)) (i32.const 12))))
                (local.set $dst (i32.add (local.get $out_ptr) (i32.mul (local.get $i) (i32.const 12))))
                (i32.store (local.get $dst) (i32.load (local.get $src)))
                (i32.store offset=4 (local.get $dst) (i32.load offset=4 (local.get $src)))
                (i32.store offset=8 (local.get $dst) (i32.load offset=8 (local.get $src)))
              )
              (else
                (local.set $dst (i32.add (local.get $out_ptr) (i32.mul (local.get $i) (i32.const 12))))
                (i32.store (local.get $dst) (i32.const 0))
                (i32.store offset=4 (local.get $dst) (i32.const 0))
                (i32.store offset=8 (local.get $dst) (i32.const 0))
              )
            )
        "#
    } else {
        r#"
            (local.set $dst (i32.add (local.get $out_ptr) (i32.mul (local.get $i) (i32.const 12))))
            (if (i32.eq (local.get $i) (i32.const 0))
              (then
                (i32.store (local.get $dst) (i32.const 0))
                (i32.store offset=4 (local.get $dst) (i32.const 0))
                (i32.store offset=8 (local.get $dst) (i32.const 0))
              )
              (else
                (local.set $src (i32.add (local.get $col_ptr) (i32.mul (i32.sub (local.get $i) (i32.const 1)) (i32.const 12))))
                (i32.store (local.get $dst) (i32.load (local.get $src)))
                (i32.store offset=4 (local.get $dst) (i32.load offset=4 (local.get $src)))
                (i32.store offset=8 (local.get $dst) (i32.load offset=8 (local.get $src)))
              )
            )
        "#
    };

    let step_output_logic = if v.mismatched_event {
        // Deliberately always emits None -> mismatches eval-vector!
        r#"
          (i32.store (local.get $ret) (i32.const 0))
          (i32.store offset=4 (local.get $ret) (i32.const 0))
          (i32.store offset=8 (local.get $ret) (i32.const 0))
          (i32.store offset=12 (local.get $ret) (i32.const 0))
        "#
    } else {
        r#"
          (i32.store (local.get $ret) (i32.const 0))
          (local.set $prev_disc (i32.load (i32.const 256)))
          (local.set $prev_len (i32.load (i32.const 260)))
          (if (i32.eq (local.get $prev_disc) (i32.const 1))
            (then
              (local.set $copy_ptr (call $alloc (local.get $prev_len)))
              (memory.copy (local.get $copy_ptr) (i32.const 512) (local.get $prev_len))
              (i32.store offset=4 (local.get $ret) (i32.const 1))
              (i32.store offset=8 (local.get $ret) (local.get $copy_ptr))
              (i32.store offset=12 (local.get $ret) (local.get $prev_len))
            )
            (else
              (i32.store offset=4 (local.get $ret) (i32.const 0))
              (i32.store offset=8 (local.get $ret) (i32.const 0))
              (i32.store offset=12 (local.get $ret) (i32.const 0))
            )
          )
        "#
    };

    let restore_logic = if v.broken_restore {
        // Deliberately ignores snapshot bytes and resets state to empty!
        r#"
          (i32.store (i32.const 256) (i32.const 0))
          (i32.store (i32.const 260) (i32.const 0))
          (i32.store (local.get $ret) (i32.const 0))
        "#
    } else {
        r#"
          (if (i32.lt_u (local.get $snap_len) (i32.const 5))
            (then
              (i32.store (local.get $ret) (i32.const 1))
              (i32.store offset=4 (local.get $ret) (i32.const 160))
              (i32.store offset=8 (local.get $ret) (i32.const 12))
              (i32.store offset=12 (local.get $ret) (i32.const 160))
              (i32.store offset=16 (local.get $ret) (i32.const 12))
              (return (local.get $ret))
            )
          )
          (local.set $disc (i32.load8_u (local.get $snap_ptr)))
          (local.set $slen (i32.load offset=1 (local.get $snap_ptr)))
          (if (i32.ne (i32.add (i32.const 5) (local.get $slen)) (local.get $snap_len))
            (then
              (i32.store (local.get $ret) (i32.const 1))
              (i32.store offset=4 (local.get $ret) (i32.const 160))
              (i32.store offset=8 (local.get $ret) (i32.const 12))
              (i32.store offset=12 (local.get $ret) (i32.const 160))
              (i32.store offset=16 (local.get $ret) (i32.const 12))
              (return (local.get $ret))
            )
          )
          (i32.store (i32.const 256) (local.get $disc))
          (i32.store (i32.const 260) (local.get $slen))
          (if (i32.gt_u (local.get $slen) (i32.const 0))
            (then
              (memory.copy (i32.const 512) (i32.add (local.get $snap_ptr) (i32.const 5)) (local.get $slen))
            )
          )
          (i32.store (local.get $ret) (i32.const 0))
        "#
    };

    let restore_lift_and_export = if v.omit_restore_export {
        ""
    } else {
        r#"
    (func $restore-state (param "snapshot" (list u8)) (result (result (error $plugin-error)))
      (canon lift (core func $m "restore-state") (memory $mem) (realloc $realloc))
    )
        "#
    };

    let restore_instance_export = if v.omit_restore_export {
        ""
    } else {
        r#"(export "restore-state" (func $restore-state))"#
    };

    let policy_len = v.numeric_policy.len();

    let wat = format!(
        r#"
(component
  (component $iface_comp
    (core module $core
      (memory (export "memory") 1)
      (global $heap (mut i32) (i32.const 4096))

      ;; Static strings
      (data (i32.const 0) "ext.lag1")
    (data (i32.const 32) "1.0.0")
    (data (i32.const 64) "{numeric_policy}")
    (data (i32.const 160) "BAD_SNAPSHOT")

    ;; State layout in linear memory:
    ;; 256: prev_disc (i32: 0 = None, 1 = Some)
    ;; 260: prev_len (i32)
    ;; 512..2048: prev_utf8_bytes

    (func $alloc (param $size i32) (result i32)
      (local $ptr i32)
      (local $aligned i32)
      (local $end i32)
      (local $cur_bytes i32)
      (local $pages_needed i32)
      (local.set $aligned (i32.and (i32.add (global.get $heap) (i32.const 7)) (i32.const -8)))
      (local.set $ptr (local.get $aligned))
      (local.set $end (i32.add (local.get $ptr) (local.get $size)))
      (local.set $cur_bytes (i32.mul (memory.size) (i32.const 65536)))
      (if (i32.gt_u (local.get $end) (local.get $cur_bytes))
        (then
          (local.set $pages_needed
            (i32.div_u
              (i32.add (i32.sub (local.get $end) (local.get $cur_bytes)) (i32.const 65535))
              (i32.const 65536)))
          (if (i32.eq (memory.grow (local.get $pages_needed)) (i32.const -1))
            (then (unreachable))
          )
        )
      )
      (global.set $heap (local.get $end))
      (local.get $ptr)
    )

    (func (export "cabi_realloc") (param $old_ptr i32) (param $old_size i32) (param $align i32) (param $new_size i32) (result i32)
      (call $alloc (local.get $new_size))
    )

    ;; metadata() -> retptr (32 bytes):
    ;; 0: id_ptr, 4: id_len, 8: ver_ptr, 12: ver_len, 16: arity, 20: warmup, 24: pol_ptr, 28: pol_len
    (func (export "metadata") (result i32)
      (local $ret i32)
      (local.set $ret (call $alloc (i32.const 32)))
      (i32.store offset=0 (local.get $ret) (i32.const 0))
      (i32.store offset=4 (local.get $ret) (i32.const 8))
      (i32.store offset=8 (local.get $ret) (i32.const 32))
      (i32.store offset=12 (local.get $ret) (i32.const 5))
      (i32.store offset=16 (local.get $ret) (i32.const 1))
      (i32.store offset=20 (local.get $ret) (i32.const {warmup}))
      (i32.store offset=24 (local.get $ret) (i32.const 64))
      (i32.store offset=28 (local.get $ret) (i32.const {policy_len}))
      (local.get $ret)
    )

    ;; eval-vector(cols_ptr, cols_len, params_ptr, params_len) -> retptr (result<decimal-column, plugin-error>)
    (func (export "eval-vector") (param $cols_ptr i32) (param $cols_len i32) (param $params_ptr i32) (param $params_len i32) (result i32)
      (local $ret i32)
      (local $col_ptr i32)
      (local $col_len i32)
      (local $out_ptr i32)
      (local $i i32)
      (local $src i32)
      (local $dst i32)
      {vector_fault}
      (local.set $ret (call $alloc (i32.const 20)))
      (local.set $col_ptr (i32.load offset=0 (local.get $cols_ptr)))
      (local.set $col_len (i32.load offset=4 (local.get $cols_ptr)))
      (local.set $out_ptr (call $alloc (i32.mul (local.get $col_len) (i32.const 12))))
      (local.set $i (i32.const 0))
      (block $done
        (loop $loop
          (br_if $done (i32.ge_u (local.get $i) (local.get $col_len)))
          {vector_loop_body}
          (local.set $i (i32.add (local.get $i) (i32.const 1)))
          (br $loop)
        )
      )
      ;; Ok(decimal-column {{ values: (out_ptr, col_len) }})
      (i32.store offset=0 (local.get $ret) (i32.const 0))
      (i32.store offset=4 (local.get $ret) (local.get $out_ptr))
      (i32.store offset=8 (local.get $ret) (local.get $col_len))
      (local.get $ret)
    )

    ;; init-event(params_ptr, params_len) -> retptr (result<_, plugin-error>)
    (func (export "init-event") (param $params_ptr i32) (param $params_len i32) (result i32)
      (local $ret i32)
      (local.set $ret (call $alloc (i32.const 20)))
      (i32.store (i32.const 256) (i32.const 0))
      (i32.store (i32.const 260) (i32.const 0))
      (i32.store offset=0 (local.get $ret) (i32.const 0))
      (local.get $ret)
    )

    ;; step-event(vals_ptr, vals_len) -> retptr (result<option<string>, plugin-error>)
    (func (export "step-event") (param $vals_ptr i32) (param $vals_len i32) (result i32)
      (local $ret i32)
      (local $prev_disc i32)
      (local $prev_len i32)
      (local $copy_ptr i32)
      (local $cur_disc i32)
      (local $cur_ptr i32)
      (local $cur_len i32)
      (local.set $ret (call $alloc (i32.const 20)))
      {step_output_logic}
      ;; Store current values[0] into state slot
      (local.set $cur_disc (i32.load offset=0 (local.get $vals_ptr)))
      (local.set $cur_ptr (i32.load offset=4 (local.get $vals_ptr)))
      (local.set $cur_len (i32.load offset=8 (local.get $vals_ptr)))
      (i32.store (i32.const 256) (local.get $cur_disc))
      (i32.store (i32.const 260) (local.get $cur_len))
      (if (i32.and (i32.eq (local.get $cur_disc) (i32.const 1)) (i32.gt_u (local.get $cur_len) (i32.const 0)))
        (then
          (memory.copy (i32.const 512) (local.get $cur_ptr) (local.get $cur_len))
        )
      )
      (local.get $ret)
    )

    ;; capture-state() -> retptr (result<list<u8>, plugin-error>)
    (func (export "capture-state") (result i32)
      (local $ret i32)
      (local $disc i32)
      (local $slen i32)
      (local $buf i32)
      (local $total i32)
      (local.set $ret (call $alloc (i32.const 20)))
      (local.set $disc (i32.load (i32.const 256)))
      (local.set $slen (i32.load (i32.const 260)))
      (local.set $total (i32.add (i32.const 5) (local.get $slen)))
      (local.set $buf (call $alloc (local.get $total)))
      (i32.store8 (local.get $buf) (local.get $disc))
      (i32.store offset=1 (local.get $buf) (local.get $slen))
      (if (i32.gt_u (local.get $slen) (i32.const 0))
        (then
          (memory.copy (i32.add (local.get $buf) (i32.const 5)) (i32.const 512) (local.get $slen))
        )
      )
      (i32.store offset=0 (local.get $ret) (i32.const 0))
      (i32.store offset=4 (local.get $ret) (local.get $buf))
      (i32.store offset=8 (local.get $ret) (local.get $total))
      (local.get $ret)
    )

    ;; restore-state(snap_ptr, snap_len) -> retptr (result<_, plugin-error>)
    (func (export "restore-state") (param $snap_ptr i32) (param $snap_len i32) (result i32)
      (local $ret i32)
      (local $disc i32)
      (local $slen i32)
      (local.set $ret (call $alloc (i32.const 20)))
      {restore_logic}
      (local.get $ret)
    )
  )

    (core instance $m (instantiate $core))
    (alias core export $m "memory" (core memory $mem))
    (alias core export $m "cabi_realloc" (core func $realloc))

    (type $param-entry' (record (field "key" string) (field "value" string)))
    (export $param-entry "param-entry" (type $param-entry'))
    (type $plugin-error' (record (field "code" string) (field "message" string)))
    (export $plugin-error "plugin-error" (type $plugin-error'))
    (type $decimal-column' (record (field "values" (list (option string)))))
    (export $decimal-column "decimal-column" (type $decimal-column'))
    (type $operator-metadata' (record
      (field "operator-id" string)
      (field "version" string)
      (field "input-arity" u32)
      (field "warmup" u32)
      (field "numeric-policy" string)
    ))
    (export $operator-metadata "operator-metadata" (type $operator-metadata'))

    (func $metadata (result $operator-metadata)
      (canon lift (core func $m "metadata") (memory $mem))
    )
    (func $eval-vector (param "columns" (list $decimal-column)) (param "params" (list $param-entry)) (result (result $decimal-column (error $plugin-error)))
      (canon lift (core func $m "eval-vector") (memory $mem) (realloc $realloc))
    )
    (func $init-event (param "params" (list $param-entry)) (result (result (error $plugin-error)))
      (canon lift (core func $m "init-event") (memory $mem) (realloc $realloc))
    )
    (func $step-event (param "values" (list (option string))) (result (result (option string) (error $plugin-error)))
      (canon lift (core func $m "step-event") (memory $mem) (realloc $realloc))
    )
    (func $capture-state (result (result (list u8) (error $plugin-error)))
      (canon lift (core func $m "capture-state") (memory $mem))
    )
    {restore_lift_and_export}

    (export "metadata" (func $metadata))
    (export "eval-vector" (func $eval-vector))
    (export "init-event" (func $init-event))
    (export "step-event" (func $step-event))
    (export "capture-state" (func $capture-state))
    {restore_instance_export}
  )
  (instance $iface (instantiate $iface_comp))
  (export "{interface_name}" (instance $iface))
)
"#,
        numeric_policy = v.numeric_policy,
        warmup = v.warmup,
        policy_len = policy_len,
        vector_fault = vector_fault,
        vector_loop_body = vector_loop_body,
        step_output_logic = step_output_logic,
        restore_logic = restore_logic,
        restore_lift_and_export = restore_lift_and_export,
        restore_instance_export = restore_instance_export,
        interface_name = v.interface_name,
    );

    wat::parse_str(&wat).expect("valid component WAT for extended operator fixture")
}

/// Builds a component that illegally imports a WASI clock interface.
fn compile_wasi_importing_component() -> Vec<u8> {
    let wat = r#"
(component
  (import "wasi:clocks/wall-clock@0.2.0" (instance $clock
    (export "now" (func (result u64)))
  ))
  (core module $core
    (memory (export "memory") 1)
    (func (export "noop"))
  )
  (core instance $m (instantiate $core))
)
"#;
    wat::parse_str(wat).expect("valid component WAT with WASI import")
}

/// Builds a real Component Model binary implementing `onlyalpha:plugin/market-rule@1.0.0`.
///
/// Behavior:
/// - When `side == sell` (enum index 1) and `settled-quantity` starts with `'0'` (length 1):
///   returns `allowed = false, reject-code = Some("T_PLUS_1_INSUFFICIENT_SETTLED")` (or `None` if `missing_reject_code`).
/// - Otherwise returns `allowed = true, normalized-quantity = Some(input.quantity), normalized-price = input.price, fee-estimate = Some("0.01")`.
fn compile_market_rule_component(missing_reject_code: bool, infinite_loop: bool) -> Vec<u8> {
    let fault = if infinite_loop {
        "(loop $l (br $l))"
    } else {
        ""
    };
    let reject_disc = if missing_reject_code { 0 } else { 1 };
    let wat = format!(
        r#"
(component
  (component $iface_comp
    (core module $core
      (memory (export "memory") 1)
      (global $heap (mut i32) (i32.const 4096))

      (data (i32.const 0) "onlyalpha-market-cn-ashare-wasm")
    (data (i32.const 64) "CN_A_SHARE")
    (data (i32.const 96) "1.0.0")
    (data (i32.const 128) "T_PLUS_1_INSUFFICIENT_SETTLED")
    (data (i32.const 192) "0.01")

    (func $alloc (param $size i32) (result i32)
      (local $ptr i32)
      (local.set $ptr (i32.and (i32.add (global.get $heap) (i32.const 7)) (i32.const -8)))
      (global.set $heap (i32.add (local.get $ptr) (local.get $size)))
      (local.get $ptr)
    )
    (func (export "cabi_realloc") (param i32 i32 i32 i32) (result i32)
      (call $alloc (local.get 3))
    )

    ;; metadata() -> retptr (24 bytes): plugin-id, market-id, version
    (func (export "metadata") (result i32)
      (local $ret i32)
      (local.set $ret (call $alloc (i32.const 24)))
      (i32.store offset=0 (local.get $ret) (i32.const 0))
      (i32.store offset=4 (local.get $ret) (i32.const 31))
      (i32.store offset=8 (local.get $ret) (i32.const 64))
      (i32.store offset=12 (local.get $ret) (i32.const 10))
      (i32.store offset=16 (local.get $ret) (i32.const 96))
      (i32.store offset=20 (local.get $ret) (i32.const 5))
      (local.get $ret)
    )

    ;; validate-order(in_ptr) -> retptr (result<market-rule-decision, plugin-error>)
    ;; market-rule-input exceeds MAX_FLAT_PARAMS (16), so passed via pointer `in_ptr`:
    ;;   0: trading-day (ptr, len)     [8]
    ;;   8: instrument-id (ptr, len)   [8]
    ;;  16: side (u8)                  [1]  (0 = buy, 1 = sell)
    ;;  17: order-type (u8)            [1]  (0 = market, 1 = limit) (+2 pad -> 20)
    ;;  20: quantity (ptr, len)        [8]
    ;;  28: price (opt<str>: disc, ptr, len) [12]
    ;;  40: ref-price (opt<str>)       [12]
    ;;  52: settled-quantity (ptr,len) [8]
    ;;  60: rule-version (ptr, len)    [8]
    ;;
    ;; result<market-rule-decision, plugin-error> layout at retptr:
    ;;   0: result disc (0 = Ok)
    ;;   4: allowed (u8, padded to 4)
    ;;   8: reject-code (opt<str>: disc@8, ptr@12, len@16)
    ;;  20: normalized-quantity (opt<str>: disc@20, ptr@24, len@28)
    ;;  32: normalized-price (opt<str>: disc@32, ptr@36, len@40)
    ;;  44: fee-estimate (opt<str>: disc@44, ptr@48, len@52)
    (func (export "validate-order") (param $in_ptr i32) (result i32)
      (local $ret i32)
      (local $side i32)
      (local $settled_ptr i32)
      (local $settled_len i32)
      {fault}
      (local.set $ret (call $alloc (i32.const 64)))
      (i32.store offset=0 (local.get $ret) (i32.const 0))
      (local.set $side (i32.load8_u offset=16 (local.get $in_ptr)))
      (local.set $settled_ptr (i32.load offset=52 (local.get $in_ptr)))
      (local.set $settled_len (i32.load offset=56 (local.get $in_ptr)))

      (if (i32.and
            (i32.eq (local.get $side) (i32.const 1))
            (i32.and
              (i32.eq (local.get $settled_len) (i32.const 1))
              (i32.eq (i32.load8_u (local.get $settled_ptr)) (i32.const 48))))
        (then
          ;; Reject sell with 0 settled quantity (T+1)
          (i32.store offset=4 (local.get $ret) (i32.const 0))
          (i32.store offset=8 (local.get $ret) (i32.const {reject_disc}))
          (i32.store offset=12 (local.get $ret) (i32.const 128))
          (i32.store offset=16 (local.get $ret) (i32.const 29))
          (i32.store offset=20 (local.get $ret) (i32.const 0))
          (i32.store offset=32 (local.get $ret) (i32.const 0))
          (i32.store offset=44 (local.get $ret) (i32.const 0))
        )
        (else
          ;; Allow and echo normalized quantity/price + fee estimate
          (i32.store offset=4 (local.get $ret) (i32.const 1))
          (i32.store offset=8 (local.get $ret) (i32.const 0))
          (i32.store offset=20 (local.get $ret) (i32.const 1))
          (i32.store offset=24 (local.get $ret) (i32.load offset=20 (local.get $in_ptr)))
          (i32.store offset=28 (local.get $ret) (i32.load offset=24 (local.get $in_ptr)))
          (i32.store offset=32 (local.get $ret) (i32.load offset=28 (local.get $in_ptr)))
          (i32.store offset=36 (local.get $ret) (i32.load offset=32 (local.get $in_ptr)))
          (i32.store offset=40 (local.get $ret) (i32.load offset=36 (local.get $in_ptr)))
          (i32.store offset=44 (local.get $ret) (i32.const 1))
          (i32.store offset=48 (local.get $ret) (i32.const 192))
          (i32.store offset=52 (local.get $ret) (i32.const 4))
        )
      )
      (local.get $ret)
    )
  )

    (core instance $m (instantiate $core))
    (alias core export $m "memory" (core memory $mem))
    (alias core export $m "cabi_realloc" (core func $realloc))

    (type $order-side' (enum "buy" "sell"))
    (export $order-side "order-side" (type $order-side'))
    (type $order-type' (enum "market" "limit"))
    (export $order-type "order-type" (type $order-type'))
    (type $plugin-error' (record (field "code" string) (field "message" string)))
    (export $plugin-error "plugin-error" (type $plugin-error'))
    (type $market-rule-metadata' (record
      (field "plugin-id" string)
      (field "market-id" string)
      (field "version" string)
    ))
    (export $market-rule-metadata "market-rule-metadata" (type $market-rule-metadata'))
    (type $market-rule-input' (record
      (field "trading-day" string)
      (field "instrument-id" string)
      (field "side" $order-side)
      (field "order-type" $order-type)
      (field "quantity" string)
      (field "price" (option string))
      (field "reference-price" (option string))
      (field "settled-quantity" string)
      (field "rule-version" string)
    ))
    (export $market-rule-input "market-rule-input" (type $market-rule-input'))
    (type $market-rule-decision' (record
      (field "allowed" bool)
      (field "reject-code" (option string))
      (field "normalized-quantity" (option string))
      (field "normalized-price" (option string))
      (field "fee-estimate" (option string))
    ))
    (export $market-rule-decision "market-rule-decision" (type $market-rule-decision'))

    (func $metadata (result $market-rule-metadata)
      (canon lift (core func $m "metadata") (memory $mem))
    )
    (func $validate-order (param "input" $market-rule-input) (result (result $market-rule-decision (error $plugin-error)))
      (canon lift (core func $m "validate-order") (memory $mem) (realloc $realloc))
    )

    (export "metadata" (func $metadata))
    (export "validate-order" (func $validate-order))
  )
  (instance $iface (instantiate $iface_comp))
  (export "onlyalpha:plugin/market-rule@1.0.0" (instance $iface))
)
"#
    );
    wat::parse_str(&wat).expect("valid component WAT for market rule fixture")
}

/// Builds a real Component Model binary implementing `onlyalpha:plugin/strategy@1.0.0`.
///
/// Behavior:
/// - Declares `required-factors = ["momentum_20"]`.
/// - When `factors[0].value` is `Some(...)`, emits one Buy Limit order intent for `BTCUSDT`.
/// - When `factors[0].value` is `None`, emits empty intent list `[]`.
fn compile_strategy_component(emit_invalid_qty: bool, trap: bool) -> Vec<u8> {
    let fault = if trap { "(unreachable)" } else { "" };
    let qty_str = if emit_invalid_qty { "-5" } else { "10" };
    let qty_len = qty_str.len();
    let wat = format!(
        r#"
(component
  (component $iface_comp
    (core module $core
      (memory (export "memory") 1)
      (global $heap (mut i32) (i32.const 4096))

      (data (i32.const 0) "strat.momentum.v1")
    (data (i32.const 32) "1.0.0")
    (data (i32.const 64) "momentum_20")
    (data (i32.const 96) "BTCUSDT")
    (data (i32.const 128) "{qty_str}")
    (data (i32.const 160) "50000.50")
    (data (i32.const 192) "SIGNAL_MOMENTUM_ENTRY")

    ;; Static list<string> of 1 required factor at 256: (ptr=64, len=11)
    (data (i32.const 256) "\40\00\00\00\0b\00\00\00")

    (func $alloc (param $size i32) (result i32)
      (local $ptr i32)
      (local.set $ptr (i32.and (i32.add (global.get $heap) (i32.const 7)) (i32.const -8)))
      (global.set $heap (i32.add (local.get $ptr) (local.get $size)))
      (local.get $ptr)
    )
    (func (export "cabi_realloc") (param i32 i32 i32 i32) (result i32)
      (call $alloc (local.get 3))
    )

    ;; metadata() -> retptr (24 bytes): strategy-id, version, required-factors
    (func (export "metadata") (result i32)
      (local $ret i32)
      (local.set $ret (call $alloc (i32.const 24)))
      (i32.store offset=0 (local.get $ret) (i32.const 0))
      (i32.store offset=4 (local.get $ret) (i32.const 17))
      (i32.store offset=8 (local.get $ret) (i32.const 32))
      (i32.store offset=12 (local.get $ret) (i32.const 5))
      (i32.store offset=16 (local.get $ret) (i32.const 256))
      (i32.store offset=20 (local.get $ret) (i32.const 1))
      (local.get $ret)
    )

    ;; on-event(factors_ptr, factors_len, ts, cash_ptr, cash_len, eq_ptr, eq_len, pos_ptr, pos_len, params_ptr, params_len)
    ;; Total flat params = 2 + 1 + 2 + 2 + 2 + 2 = 11 <= 16 (MAX_FLAT_PARAMS).
    ;; Each named-factor in memory is 20 bytes: name(ptr@0, len@4), value(disc@8, ptr@12, len@16).
    ;; Each order-intent in memory is 48 bytes:
    ;;   0: instrument-id (ptr@0, len@4)
    ;;   8: side (u8 @8, buy=0)
    ;;   9: order-type (u8 @9, limit=1)
    ;;  12: quantity (ptr@12, len@16)
    ;;  20: limit-price (opt<str>: disc@20, ptr@24, len@28)
    ;;  32: time-in-force (u8 @32, gtc=1)
    ;;  36: reason-code (ptr@36, len@40)
    ;;  total size = 44 bytes (align 4)
    (func (export "on-event")
      (param $f_ptr i32) (param $f_len i32)
      (param $ts i64)
      (param $cash_ptr i32) (param $cash_len i32)
      (param $eq_ptr i32) (param $eq_len i32)
      (param $pos_ptr i32) (param $pos_len i32)
      (param $p_ptr i32) (param $p_len i32)
      (result i32)
      (local $ret i32)
      (local $intent i32)
      (local $has_val i32)
      {fault}
      (local.set $ret (call $alloc (i32.const 20)))
      (i32.store offset=0 (local.get $ret) (i32.const 0))
      (if (i32.gt_u (local.get $f_len) (i32.const 0))
        (then
          (local.set $has_val (i32.load offset=8 (local.get $f_ptr)))
        )
        (else
          (local.set $has_val (i32.const 0))
        )
      )
      (if (i32.eq (local.get $has_val) (i32.const 1))
        (then
          (local.set $intent (call $alloc (i32.const 44)))
          (i32.store offset=0 (local.get $intent) (i32.const 96))
          (i32.store offset=4 (local.get $intent) (i32.const 7))
          (i32.store8 offset=8 (local.get $intent) (i32.const 0))
          (i32.store8 offset=9 (local.get $intent) (i32.const 1))
          (i32.store offset=12 (local.get $intent) (i32.const 128))
          (i32.store offset=16 (local.get $intent) (i32.const {qty_len}))
          (i32.store offset=20 (local.get $intent) (i32.const 1))
          (i32.store offset=24 (local.get $intent) (i32.const 160))
          (i32.store offset=28 (local.get $intent) (i32.const 8))
          (i32.store8 offset=32 (local.get $intent) (i32.const 1))
          (i32.store offset=36 (local.get $intent) (i32.const 192))
          (i32.store offset=40 (local.get $intent) (i32.const 21))

          (i32.store offset=4 (local.get $ret) (local.get $intent))
          (i32.store offset=8 (local.get $ret) (i32.const 1))
        )
        (else
          (i32.store offset=4 (local.get $ret) (i32.const 0))
          (i32.store offset=8 (local.get $ret) (i32.const 0))
        )
      )
      (local.get $ret)
    )
  )

    (core instance $m (instantiate $core))
    (alias core export $m "memory" (core memory $mem))
    (alias core export $m "cabi_realloc" (core func $realloc))

    (type $param-entry' (record (field "key" string) (field "value" string)))
    (export $param-entry "param-entry" (type $param-entry'))
    (type $plugin-error' (record (field "code" string) (field "message" string)))
    (export $plugin-error "plugin-error" (type $plugin-error'))
    (type $named-factor' (record (field "name" string) (field "value" (option string))))
    (export $named-factor "named-factor" (type $named-factor'))
    (type $readonly-position' (record
      (field "instrument-id" string)
      (field "quantity" string)
      (field "average-cost" (option string))
    ))
    (export $readonly-position "readonly-position" (type $readonly-position'))
    (type $readonly-account-state' (record
      (field "timestamp-ns" s64)
      (field "cash-available" string)
      (field "total-equity" string)
      (field "positions" (list $readonly-position))
    ))
    (export $readonly-account-state "readonly-account-state" (type $readonly-account-state'))
    (type $order-side' (enum "buy" "sell"))
    (export $order-side "order-side" (type $order-side'))
    (type $order-type' (enum "market" "limit"))
    (export $order-type "order-type" (type $order-type'))
    (type $time-in-force' (enum "day" "gtc" "ioc" "fok"))
    (export $time-in-force "time-in-force" (type $time-in-force'))
    (type $order-intent' (record
      (field "instrument-id" string)
      (field "side" $order-side)
      (field "order-type" $order-type)
      (field "quantity" string)
      (field "limit-price" (option string))
      (field "time-in-force" $time-in-force)
      (field "reason-code" string)
    ))
    (export $order-intent "order-intent" (type $order-intent'))
    (type $strategy-metadata' (record
      (field "strategy-id" string)
      (field "version" string)
      (field "required-factors" (list string))
    ))
    (export $strategy-metadata "strategy-metadata" (type $strategy-metadata'))

    (func $metadata (result $strategy-metadata)
      (canon lift (core func $m "metadata") (memory $mem))
    )
    (func $on-event
      (param "factors" (list $named-factor))
      (param "readonly-state" $readonly-account-state)
      (param "params" (list $param-entry))
      (result (result (list $order-intent) (error $plugin-error)))
      (canon lift (core func $m "on-event") (memory $mem) (realloc $realloc))
    )

    (export "metadata" (func $metadata))
    (export "on-event" (func $on-event))
  )
  (instance $iface (instantiate $iface_comp))
  (export "onlyalpha:plugin/strategy@1.0.0" (instance $iface))
)
"#
    );
    wat::parse_str(&wat).expect("valid component WAT for strategy fixture")
}

#[test]
fn extended_operator_automatic_certification_vector_event_snapshot_and_hot_unload() {
    let manager = WasmPluginManager::new(ResourceBudget::default()).expect("host init");
    let wasm = compile_operator_component(OperatorVariant::default());
    let sha = sha256_hex(&wasm);

    let golden = GoldenCase {
        name: "lag1_independent_golden".into(),
        columns: vec![vec![
            Some(dec("10.5")),
            None,
            Some(dec("-3.25")),
            Some(dec("0")),
        ]],
        expected: vec![None, Some(dec("10.5")), None, Some(dec("-3.25"))],
    };

    let op = manager
        .load_extended_operator(
            &wasm,
            &sha,
            CertificationRequest {
                plugin_id: "plugin.ext.lag1".into(),
                canonical_parameters: BTreeMap::from([("lag".into(), "1".into())]),
                golden_cases: vec![golden.clone()],
            },
            None,
        )
        .expect("valid dual-kernel operator must pass automatic certification");

    let cert = op.certificate();
    assert_eq!(cert.operator_id, "ext.lag1");
    assert_eq!(cert.artifact_sha256, sha);
    assert_eq!(cert.wit_contract_version, WIT_CONTRACT_VERSION);
    assert!(cert.vector_event_equivalent);
    assert!(cert.causal_prefixes_verified);
    assert!(cert.warmup_null_verified);
    assert!(cert.snapshot_restore_verified);
    assert!(cert.deterministic_fuel_verified);
    assert_eq!(cert.golden_cases_count, 1);
    assert_eq!(cert.certificate_digest.len(), 64);

    // VectorKernel trait implementation matches golden exactly.
    let via_trait = op.evaluate(&golden.columns).expect("VectorKernel trait");
    assert_eq!(via_trait, golden.expected);

    // Stateful stream allocates linear memory while alive and reclaims it completely on drop.
    let mut stream = op.new_stream().expect("create event stream");
    assert!(stream.live_memory_bytes() >= 64 * 1024);
    assert!(manager.metrics().live_linear_memory_bytes >= 64 * 1024);

    assert_eq!(stream.step(&[Some(dec("10.5"))]).unwrap().value, None);
    assert_eq!(stream.step(&[None]).unwrap().value, Some(dec("10.5")));
    let snapshot = stream.capture_state().unwrap().value;
    drop(stream);
    assert_eq!(manager.metrics().live_linear_memory_bytes, 0);

    // Restore into a brand-new stream and finish the suffix.
    let mut restored = op.new_stream().expect("fresh stream");
    restored.restore_state(&snapshot).expect("restore snapshot");
    assert_eq!(restored.step(&[Some(dec("-3.25"))]).unwrap().value, None);
    assert_eq!(
        restored.step(&[Some(dec("0"))]).unwrap().value,
        Some(dec("-3.25"))
    );
    drop(restored);
    assert_eq!(manager.metrics().live_linear_memory_bytes, 0);

    // Binding verification succeeds for exact SHA-256 and rejects tampered binding.
    let binding = op.binding();
    binding.verify_bytes(&wasm).expect("binding matches bytes");
    manager
        .verify_binding(&binding)
        .expect("binding matches manager");

    let mut wrong_binding = binding.clone();
    wrong_binding.artifact_sha256 = "0".repeat(64);
    assert!(matches!(
        manager.verify_binding(&wrong_binding),
        Err(Error::Sha256Mismatch { .. })
    ));

    // Hot-unload reclaims component references cleanly once external handle is dropped.
    drop(op);
    let receipt = manager.unload("plugin.ext.lag1").expect("hot unload");
    assert!(receipt.reclaimed_immediately);
    assert_eq!(receipt.remaining_external_refs, 0);
    assert_eq!(receipt.artifact_sha256, sha);
    assert_eq!(manager.metrics().active_plugins, 0);
    assert_eq!(manager.metrics().active_stores, 0);
    assert_eq!(manager.metrics().live_linear_memory_bytes, 0);
    assert!(matches!(
        manager.get_extended_operator("plugin.ext.lag1", None),
        Err(Error::PluginNotFound { .. })
    ));
}

#[test]
fn admission_rejects_lookahead_vector_event_mismatch_broken_restore_and_warmup_violation() {
    let manager = WasmPluginManager::new(ResourceBudget::default()).expect("host init");

    // 1. Look-ahead operator must be rejected by multi-prefix causality certification.
    let lookahead = compile_operator_component(OperatorVariant {
        lookahead_vector: true,
        ..Default::default()
    });
    let err = manager
        .load_extended_operator(
            &lookahead,
            &sha256_hex(&lookahead),
            CertificationRequest {
                plugin_id: "bad.lookahead".into(),
                ..Default::default()
            },
            None,
        )
        .err()
        .expect("look-ahead must fail certification");
    assert!(matches!(
        err,
        Error::CertificationFailed {
            stage: "warmup" | "vector_event_equivalence" | "causality",
            ..
        }
    ));

    // Look-ahead with warmup=1 and matching event? Wait: force causality failure directly with warmup=1
    // where event mismatches or vector peeks ahead! Even better: test explicit causality stage when warmup=1:
    let mismatched = compile_operator_component(OperatorVariant {
        mismatched_event: true,
        ..Default::default()
    });
    let err = manager
        .load_extended_operator(
            &mismatched,
            &sha256_hex(&mismatched),
            CertificationRequest {
                plugin_id: "bad.mismatch".into(),
                ..Default::default()
            },
            None,
        )
        .err()
        .expect("vector/event mismatch must fail certification");
    assert!(matches!(
        err,
        Error::CertificationFailed {
            stage: "vector_event_equivalence",
            ..
        }
    ));

    // 2. Broken snapshot restore must fail at `snapshot_restore`.
    let broken_restore = compile_operator_component(OperatorVariant {
        broken_restore: true,
        ..Default::default()
    });
    let err = manager
        .load_extended_operator(
            &broken_restore,
            &sha256_hex(&broken_restore),
            CertificationRequest {
                plugin_id: "bad.restore".into(),
                ..Default::default()
            },
            None,
        )
        .err()
        .expect("broken snapshot restore must fail certification");
    assert!(matches!(
        err,
        Error::CertificationFailed {
            stage: "snapshot_restore",
            ..
        }
    ));

    // 3. Warmup violation (declares warmup=3, outputs at index 1).
    let bad_warmup = compile_operator_component(OperatorVariant {
        warmup: 3,
        ..Default::default()
    });
    let err = manager
        .load_extended_operator(
            &bad_warmup,
            &sha256_hex(&bad_warmup),
            CertificationRequest {
                plugin_id: "bad.warmup".into(),
                ..Default::default()
            },
            None,
        )
        .err()
        .expect("warmup violation must fail certification");
    assert!(matches!(
        err,
        Error::CertificationFailed {
            stage: "warmup",
            ..
        }
    ));

    // 4. Excessive warmup DoS rejected at metadata decode before allocating certification suites.
    let huge_warmup = compile_operator_component(OperatorVariant {
        warmup: u32::MAX,
        ..Default::default()
    });
    let err = manager
        .load_extended_operator(
            &huge_warmup,
            &sha256_hex(&huge_warmup),
            CertificationRequest {
                plugin_id: "bad.huge_warmup".into(),
                ..Default::default()
            },
            None,
        )
        .err()
        .expect("excessive warmup must be rejected");
    assert!(matches!(err, Error::InvalidGuestOutput(_)));

    // None of the rejected plugins entered the READY registry, and zero linear memory leaked.
    assert_eq!(manager.metrics().active_plugins, 0);
    assert_eq!(manager.metrics().live_linear_memory_bytes, 0);
}

#[test]
fn sandbox_rejects_wasi_imports_wrong_wit_version_missing_export_and_sha256_tampering() {
    let manager = WasmPluginManager::new(ResourceBudget::default()).expect("host init");

    // 1. Forbidden WASI import rejected at load time.
    let wasi_wasm = compile_wasi_importing_component();
    let err = manager
        .load_strategy("bad.wasi", &wasi_wasm, &sha256_hex(&wasi_wasm), None)
        .err()
        .expect("WASI import must be forbidden");
    assert!(matches!(
        err,
        Error::ForbiddenImport { ref import_name } if import_name == "wasi:clocks/wall-clock@0.2.0"
    ));

    // 2. Wrong WIT contract version export rejected.
    let wrong_ver = compile_operator_component(OperatorVariant {
        interface_name: "onlyalpha:plugin/extended-operator@0.9.0",
        ..Default::default()
    });
    let err = manager
        .load_extended_operator(
            &wrong_ver,
            &sha256_hex(&wrong_ver),
            CertificationRequest {
                plugin_id: "bad.version".into(),
                ..Default::default()
            },
            None,
        )
        .err()
        .expect("wrong WIT version must be rejected");
    assert!(matches!(err, Error::ContractExportMismatch { .. }));

    // 3. Missing required function (`restore-state`) rejected.
    let missing_fn = compile_operator_component(OperatorVariant {
        omit_restore_export: true,
        ..Default::default()
    });
    let err = manager
        .load_extended_operator(
            &missing_fn,
            &sha256_hex(&missing_fn),
            CertificationRequest {
                plugin_id: "bad.missing_fn".into(),
                ..Default::default()
            },
            None,
        )
        .err()
        .expect("missing restore-state must be rejected");
    assert!(matches!(err, Error::ContractExportMismatch { .. }));

    // 4. SHA-256 mismatch rejected before compilation.
    let valid = compile_operator_component(OperatorVariant::default());
    let wrong_sha = "f".repeat(64);
    let err = manager
        .load_extended_operator(
            &valid,
            &wrong_sha,
            CertificationRequest {
                plugin_id: "bad.sha".into(),
                ..Default::default()
            },
            None,
        )
        .err()
        .expect("SHA-256 mismatch must be rejected");
    assert!(matches!(err, Error::Sha256Mismatch { .. }));
}

#[test]
fn fuel_exhaustion_memory_limit_and_guest_traps_fail_closed_without_impacting_host() {
    let tight_budget = ResourceBudget {
        max_memory_bytes: 256 * 1024, // 4 pages (256 KiB)
        max_fuel_per_call: 50_000,
        ..ResourceBudget::default()
    };
    let manager = WasmPluginManager::new(tight_budget).expect("host init");

    // Pre-load a healthy operator in the same host to prove isolation.
    let healthy_wasm = compile_operator_component(OperatorVariant::default());
    let healthy = manager
        .load_extended_operator(
            &healthy_wasm,
            &sha256_hex(&healthy_wasm),
            CertificationRequest {
                plugin_id: "healthy.lag1".into(),
                ..Default::default()
            },
            Some(ResourceBudget::default()),
        )
        .expect("load healthy operator");

    // 1. Infinite loop -> FuelExhausted (Fail-Closed).
    let loop_rule_wasm = compile_market_rule_component(false, true);
    let loop_rule = manager
        .load_market_rule(
            "fault.loop_rule",
            &loop_rule_wasm,
            &sha256_hex(&loop_rule_wasm),
            Some(tight_budget),
        )
        .expect("load loop rule");
    let sample_input = MarketRuleInput {
        trading_day: "2026-11-26".into(),
        instrument_id: "600519.SH".into(),
        side: OrderSide::Buy,
        order_type: OrderType::Limit,
        quantity: dec("100"),
        price: Some(dec("1500.00")),
        reference_price: Some(dec("1490.00")),
        settled_quantity: dec("0"),
        rule_version: "cn-a-share-v1".into(),
    };
    let fuel_err = loop_rule
        .validate_order(&sample_input)
        .expect_err("infinite loop must exhaust fuel");
    assert!(matches!(fuel_err, Error::FuelExhausted { limit: 50_000 }));
    assert!(fuel_err.is_fail_closed());

    // 2. Memory OOM -> MemoryLimitExceeded (Fail-Closed).
    let oom_op_wasm = compile_operator_component(OperatorVariant {
        oom_vector: true,
        ..Default::default()
    });
    let oom_err = manager
        .load_extended_operator(
            &oom_op_wasm,
            &sha256_hex(&oom_op_wasm),
            CertificationRequest {
                plugin_id: "fault.oom_op".into(),
                ..Default::default()
            },
            Some(tight_budget),
        )
        .err()
        .expect("OOM must fail closed");
    assert!(
        matches!(
            oom_err,
            Error::CertificationFailed { ref reason, .. } if reason.contains("WASM_MEMORY_LIMIT_EXCEEDED")
        ),
        "unexpected error: {oom_err}"
    );
    assert!(oom_err.is_fail_closed());

    // 3. Unreachable trap in strategy -> GuestTrap (Fail-Closed).
    let trap_strat_wasm = compile_strategy_component(false, true);
    let trap_strat = manager
        .load_strategy(
            "fault.trap_strat",
            &trap_strat_wasm,
            &sha256_hex(&trap_strat_wasm),
            Some(tight_budget),
        )
        .expect("load trapping strategy");
    let state = ReadonlyAccountState {
        timestamp_ns: 1_700_000_000_000_000_000,
        cash_available: dec("100000"),
        total_equity: dec("100000"),
        positions: vec![],
    };
    let trap_err = trap_strat
        .on_event(
            &[NamedFactor {
                name: "momentum_20".into(),
                value: Some(dec("1.5")),
            }],
            &state,
            &BTreeMap::new(),
        )
        .expect_err("unreachable must trap");
    assert!(matches!(trap_err, Error::GuestTrap(_)));
    assert!(trap_err.is_fail_closed());

    // 4. Stateful stream hitting MemoryLimitExceeded mid-run is permanently poisoned (Fail-Closed).
    let one_page_budget = ResourceBudget {
        max_memory_bytes: crate::MIN_MEMORY_BYTES,
        ..ResourceBudget::default()
    };
    let tight_op = manager
        .load_extended_operator(
            &healthy_wasm,
            &sha256_hex(&healthy_wasm),
            CertificationRequest {
                plugin_id: "healthy.lag1_tight".into(),
                ..Default::default()
            },
            Some(one_page_budget),
        )
        .expect("load tight-memory lag1");
    let mut stream = tight_op.new_stream().expect("init stream");
    let long_val = Some(dec("1234567890123456.123456789012"));
    let mut hit_oom = false;
    for _ in 0..4000 {
        match stream.step(std::slice::from_ref(&long_val)) {
            Ok(_) => {}
            Err(Error::MemoryLimitExceeded { limit_bytes }) => {
                assert_eq!(limit_bytes, crate::MIN_MEMORY_BYTES);
                hit_oom = true;
                break;
            }
            Err(other) => panic!("expected MemoryLimitExceeded, got {other}"),
        }
    }
    assert!(hit_oom, "stream must hit 1-page memory budget");
    assert!(stream.is_poisoned());
    assert!(matches!(
        stream.step(&[Some(dec("1"))]),
        Err(Error::GuestTrap(_))
    ));
    assert!(matches!(stream.capture_state(), Err(Error::GuestTrap(_))));
    drop(stream);

    // Host remains completely intact: traps were counted, linear memory reclaimed to 0,
    // and the healthy operator still produces exact deterministic results!
    let metrics = manager.metrics();
    assert!(metrics.total_traps_isolated >= 4);
    assert_eq!(metrics.live_linear_memory_bytes, 0);
    assert_eq!(metrics.active_stores, 0);

    let res = healthy
        .evaluate_vector(&[vec![Some(dec("42")), Some(dec("99"))]])
        .expect("healthy operator unaffected after faults");
    assert_eq!(res.value, vec![None, Some(dec("42"))]);
}

#[test]
fn market_rule_and_strategy_plugins_enforce_contract_invariants_and_determinism() {
    let manager_a = WasmPluginManager::new(ResourceBudget::default()).expect("host A");
    let manager_b = WasmPluginManager::new(ResourceBudget::default()).expect("host B");

    // Market rule plugin: allow Buy, reject T+1 Sell with 0 settled quantity.
    let rule_wasm = compile_market_rule_component(false, false);
    let rule_sha = sha256_hex(&rule_wasm);
    let rule_a = manager_a
        .load_market_rule("market.cn_ashare", &rule_wasm, &rule_sha, None)
        .expect("load market rule A");
    let rule_b = manager_b
        .load_market_rule("market.cn_ashare", &rule_wasm, &rule_sha, None)
        .expect("load market rule B");
    assert_eq!(rule_a.metadata().market_id, "CN_A_SHARE");

    let buy_input = MarketRuleInput {
        trading_day: "2026-11-26".into(),
        instrument_id: "600519.SH".into(),
        side: OrderSide::Buy,
        order_type: OrderType::Limit,
        quantity: dec("100"),
        price: Some(dec("1500.00")),
        reference_price: Some(dec("1490.00")),
        settled_quantity: dec("0"),
        rule_version: "cn-a-share-v1".into(),
    };
    let out_a = rule_a.validate_order(&buy_input).expect("buy allowed A");
    let out_b = rule_b.validate_order(&buy_input).expect("buy allowed B");
    assert_eq!(
        out_a, out_b,
        "cross-host output and fuel must match bit-for-bit"
    );
    assert!(out_a.value.allowed);
    assert_eq!(out_a.value.normalized_quantity, Some(dec("100")));
    assert_eq!(out_a.value.fee_estimate, Some(dec("0.01")));

    let t1_sell_input = MarketRuleInput {
        side: OrderSide::Sell,
        settled_quantity: dec("0"),
        ..buy_input.clone()
    };
    let rejected = rule_a
        .validate_order(&t1_sell_input)
        .expect("T+1 sell decision");
    assert!(!rejected.value.allowed);
    assert_eq!(
        rejected.value.reject_code.as_deref(),
        Some("T_PLUS_1_INSUFFICIENT_SETTLED")
    );

    // Market rule returning allowed=false with missing reject-code must fail closed!
    let bad_rule_wasm = compile_market_rule_component(true, false);
    let bad_rule = manager_a
        .load_market_rule(
            "market.bad_reject",
            &bad_rule_wasm,
            &sha256_hex(&bad_rule_wasm),
            None,
        )
        .expect("load bad rule");
    assert!(matches!(
        bad_rule.validate_order(&t1_sell_input),
        Err(Error::InvalidGuestOutput(_))
    ));

    // Strategy plugin: emits OrderIntent when momentum_20 is Some, empty when None.
    let strat_wasm = compile_strategy_component(false, false);
    let strat_sha = sha256_hex(&strat_wasm);
    let strat_a = manager_a
        .load_strategy("strat.momentum", &strat_wasm, &strat_sha, None)
        .expect("load strategy A");
    let strat_b = manager_b
        .load_strategy("strat.momentum", &strat_wasm, &strat_sha, None)
        .expect("load strategy B");
    assert_eq!(strat_a.metadata().required_factors, vec!["momentum_20"]);

    let account = ReadonlyAccountState {
        timestamp_ns: 1_764_160_000_000_000_000,
        cash_available: dec("250000"),
        total_equity: dec("300000"),
        positions: vec![ReadonlyPosition {
            instrument_id: "BTCUSDT".into(),
            quantity: dec("1"),
            average_cost: Some(dec("50000")),
        }],
    };

    let active_factors = vec![NamedFactor {
        name: "momentum_20".into(),
        value: Some(dec("2.5")),
    }];
    let strat_out_a = strat_a
        .on_event(&active_factors, &account, &BTreeMap::new())
        .expect("strategy A on_event");
    let strat_out_b = strat_b
        .on_event(&active_factors, &account, &BTreeMap::new())
        .expect("strategy B on_event");
    assert_eq!(
        strat_out_a, strat_out_b,
        "cross-host strategy intents and fuel must match bit-for-bit"
    );
    assert_eq!(strat_out_a.value.len(), 1);
    assert_eq!(strat_out_a.value[0].instrument_id, "BTCUSDT");
    assert_eq!(strat_out_a.value[0].side, OrderSide::Buy);
    assert_eq!(strat_out_a.value[0].order_type, OrderType::Limit);
    assert_eq!(strat_out_a.value[0].quantity, dec("10"));
    assert_eq!(strat_out_a.value[0].limit_price, Some(dec("50000.50")));
    assert_eq!(strat_out_a.value[0].time_in_force, TimeInForce::Gtc);
    assert_eq!(strat_out_a.value[0].reason_code, "SIGNAL_MOMENTUM_ENTRY");

    // Null factor produces zero intents cleanly.
    let null_out = strat_a
        .on_event(
            &[NamedFactor {
                name: "momentum_20".into(),
                value: None,
            }],
            &account,
            &BTreeMap::new(),
        )
        .expect("null factor");
    assert!(null_out.value.is_empty());

    // Missing required factor rejected Fail-Closed before invoking guest.
    assert!(matches!(
        strat_a.on_event(&[], &account, &BTreeMap::new()),
        Err(Error::InvalidHostInput(_))
    ));

    // Strategy emitting negative quantity rejected Fail-Closed.
    let bad_strat_wasm = compile_strategy_component(true, false);
    let bad_strat = manager_a
        .load_strategy(
            "strat.bad_qty",
            &bad_strat_wasm,
            &sha256_hex(&bad_strat_wasm),
            None,
        )
        .expect("load bad strategy");
    assert!(matches!(
        bad_strat.on_event(&active_factors, &account, &BTreeMap::new()),
        Err(Error::InvalidGuestOutput(_))
    ));

    // Verify exact frozen replay binding rejects silent hot-swap to a different artifact.
    let frozen_binding = ArtifactBinding::new(
        "strat.momentum",
        PluginKind::Strategy,
        strat_sha,
        BTreeMap::new(),
    )
    .expect("binding");
    manager_a
        .verify_binding(&frozen_binding)
        .expect("frozen binding matches original");

    drop(strat_a);
    let unload_receipt = manager_a.unload("strat.momentum").expect("unload");
    assert!(unload_receipt.reclaimed_immediately);

    // Hot-load a different binary under the same plugin_id: old frozen binding must be rejected!
    manager_a
        .load_strategy(
            "strat.momentum",
            &bad_strat_wasm,
            &sha256_hex(&bad_strat_wasm),
            None,
        )
        .expect("reload different artifact");
    assert!(matches!(
        manager_a.verify_binding(&frozen_binding),
        Err(Error::Sha256Mismatch { .. })
    ));
}

/// Builds a market-rule component whose `validate-order` has a subtly wrong WIT return type
/// (`string` instead of `result<market-rule-decision, plugin-error>`) to verify static ABI checking.
fn compile_market_rule_wrong_signature_component() -> Vec<u8> {
    let wat = r#"
(component
  (component $iface_comp
    (core module $core
      (memory (export "memory") 1)
      (global $heap (mut i32) (i32.const 4096))
      (data (i32.const 0) "rule.bad.sig")
      (data (i32.const 32) "CN_A_SHARE")
      (data (i32.const 64) "1.0.0")
      (func $alloc (param $size i32) (result i32)
        (local $ptr i32)
        (local.set $ptr (i32.and (i32.add (global.get $heap) (i32.const 7)) (i32.const -8)))
        (global.set $heap (i32.add (local.get $ptr) (local.get $size)))
        (local.get $ptr)
      )
      (func (export "cabi_realloc") (param i32 i32 i32 i32) (result i32)
        (call $alloc (local.get 3))
      )
      (func (export "metadata") (result i32)
        (local $ret i32)
        (local.set $ret (call $alloc (i32.const 24)))
        (i32.store offset=0 (local.get $ret) (i32.const 0))
        (i32.store offset=4 (local.get $ret) (i32.const 12))
        (i32.store offset=8 (local.get $ret) (i32.const 32))
        (i32.store offset=12 (local.get $ret) (i32.const 10))
        (i32.store offset=16 (local.get $ret) (i32.const 64))
        (i32.store offset=20 (local.get $ret) (i32.const 5))
        (local.get $ret)
      )
      (func (export "validate-order") (param i32) (result i32)
        (local $ret i32)
        (local.set $ret (call $alloc (i32.const 8)))
        (i32.store offset=0 (local.get $ret) (i32.const 0))
        (i32.store offset=4 (local.get $ret) (i32.const 12))
        (local.get $ret)
      )
    )
    (core instance $m (instantiate $core))
    (alias core export $m "memory" (core memory $mem))
    (alias core export $m "cabi_realloc" (core func $realloc))
    (type $meta' (record (field "plugin-id" string) (field "market-id" string) (field "version" string)))
    (export $meta "market-rule-metadata" (type $meta'))
    (func $metadata (result $meta)
      (canon lift (core func $m "metadata") (memory $mem) (realloc $realloc))
    )
    (func $validate-order (param "input" u32) (result string)
      (canon lift (core func $m "validate-order") (memory $mem) (realloc $realloc))
    )
    (export "metadata" (func $metadata))
    (export "validate-order" (func $validate-order))
  )
  (instance $iface (instantiate $iface_comp))
  (export "onlyalpha:plugin/market-rule@1.0.0" (instance $iface))
)
"#;
    wat::parse_str(wat).expect("valid WAT for wrong-signature market rule")
}

/// Builds a market-rule component that exports the valid interface PLUS an extra unexpected export.
fn compile_market_rule_extra_export_component() -> Vec<u8> {
    let wat = r#"
(component
  (component $extra_comp
    (core module $c (func (export "ping") (result i32) (i32.const 1)))
    (core instance $m (instantiate $c))
    (func $ping (result u32) (canon lift (core func $m "ping")))
    (export "ping" (func $ping))
  )
  (instance $extra (instantiate $extra_comp))
  (export "backdoor:plugin/extra@1.0.0" (instance $extra))
)
"#;
    wat::parse_str(wat).expect("valid WAT for extra export component")
}

/// Builds a malicious market-rule component that fits inside 1 Wasm page (64 KiB) but attempts to
/// return a 48 KiB UTF-8 `reject-code` string, exceeding `MARKET_RULE_LIFT_BYTES` (32 KiB) so
/// Wasmtime's `hostcall_fuel` traps before the host allocates the oversized payload.
fn compile_market_rule_lift_bomb_component() -> Vec<u8> {
    let wat = r#"
(component
  (component $iface_comp
    (core module $core
      (memory (export "memory") 1)
      (global $heap (mut i32) (i32.const 4096))

      (data (i32.const 0) "rule.lift.bomb")
      (data (i32.const 32) "CN_A_SHARE")
      (data (i32.const 64) "1.0.0")

      (func $alloc (param $size i32) (result i32)
        (local $ptr i32)
        (local.set $ptr (i32.and (i32.add (global.get $heap) (i32.const 7)) (i32.const -8)))
        (global.set $heap (i32.add (local.get $ptr) (local.get $size)))
        (local.get $ptr)
      )
      (func (export "cabi_realloc") (param i32 i32 i32 i32) (result i32)
        (call $alloc (local.get 3))
      )
      (func (export "metadata") (result i32)
        (local $ret i32)
        (local.set $ret (call $alloc (i32.const 24)))
        (i32.store offset=0 (local.get $ret) (i32.const 0))
        (i32.store offset=4 (local.get $ret) (i32.const 14))
        (i32.store offset=8 (local.get $ret) (i32.const 32))
        (i32.store offset=12 (local.get $ret) (i32.const 10))
        (i32.store offset=16 (local.get $ret) (i32.const 64))
        (i32.store offset=20 (local.get $ret) (i32.const 5))
        (local.get $ret)
      )
      (func (export "validate-order") (param $in_ptr i32) (result i32)
        (local $ret i32)
        (local $buf i32)
        (local $i i32)
        ;; Fill 48 KiB of ASCII 'A' in linear memory (valid UTF-8, fits inside 1 page!).
        (local.set $buf (i32.const 8192))
        (local.set $i (i32.const 0))
        (block $done
          (loop $fill
            (br_if $done (i32.ge_u (local.get $i) (i32.const 49152)))
            (i32.store8 (i32.add (local.get $buf) (local.get $i)) (i32.const 65))
            (local.set $i (i32.add (local.get $i) (i32.const 1)))
            (br $fill)
          )
        )
        (local.set $ret (call $alloc (i32.const 60)))
        ;; result = Ok (0)
        (i32.store offset=0 (local.get $ret) (i32.const 0))
        ;; allowed = false (0)
        (i32.store8 offset=4 (local.get $ret) (i32.const 0))
        ;; reject-code = Some(buf, 49152)
        (i32.store offset=8 (local.get $ret) (i32.const 1))
        (i32.store offset=12 (local.get $ret) (local.get $buf))
        (i32.store offset=16 (local.get $ret) (i32.const 49152))
        ;; normalized-quantity, normalized-price, fee-estimate = None
        (i32.store offset=20 (local.get $ret) (i32.const 0))
        (i32.store offset=32 (local.get $ret) (i32.const 0))
        (i32.store offset=44 (local.get $ret) (i32.const 0))
        (local.get $ret)
      )
    )
    (core instance $m (instantiate $core))
    (alias core export $m "memory" (core memory $mem))
    (alias core export $m "cabi_realloc" (core func $realloc))

    (type $plugin-error' (record (field "code" string) (field "message" string)))
    (export $plugin-error "plugin-error" (type $plugin-error'))
    (type $order-side' (enum "buy" "sell"))
    (export $order-side "order-side" (type $order-side'))
    (type $order-type' (enum "market" "limit"))
    (export $order-type "order-type" (type $order-type'))
    (type $market-rule-input' (record
      (field "trading-day" string)
      (field "instrument-id" string)
      (field "side" $order-side)
      (field "order-type" $order-type)
      (field "quantity" string)
      (field "price" (option string))
      (field "reference-price" (option string))
      (field "settled-quantity" string)
      (field "rule-version" string)
    ))
    (export $market-rule-input "market-rule-input" (type $market-rule-input'))
    (type $market-rule-decision' (record
      (field "allowed" bool)
      (field "reject-code" (option string))
      (field "normalized-quantity" (option string))
      (field "normalized-price" (option string))
      (field "fee-estimate" (option string))
    ))
    (export $market-rule-decision "market-rule-decision" (type $market-rule-decision'))
    (type $market-rule-metadata' (record
      (field "plugin-id" string)
      (field "market-id" string)
      (field "version" string)
    ))
    (export $market-rule-metadata "market-rule-metadata" (type $market-rule-metadata'))

    (func $metadata (result $market-rule-metadata)
      (canon lift (core func $m "metadata") (memory $mem) (realloc $realloc))
    )
    (func $validate-order (param "input" $market-rule-input) (result (result $market-rule-decision (error $plugin-error)))
      (canon lift (core func $m "validate-order") (memory $mem) (realloc $realloc))
    )
    (export "metadata" (func $metadata))
    (export "validate-order" (func $validate-order))
  )
  (instance $iface (instantiate $iface_comp))
  (export "onlyalpha:plugin/market-rule@1.0.0" (instance $iface))
)
"#;
    wat::parse_str(wat).expect("valid WAT for host-lift bomb market rule")
}

#[test]
fn hardening_enforces_static_abi_signatures_host_lift_budget_canonical_decimals_and_cert_fuel() {
    let manager = WasmPluginManager::new(ResourceBudget::default()).expect("manager");

    // 1. Wrong WIT function signature rejected statically at compile/load time.
    let bad_sig_wasm = compile_market_rule_wrong_signature_component();
    let bad_sig_err = manager
        .load_market_rule("bad.sig", &bad_sig_wasm, &sha256_hex(&bad_sig_wasm), None)
        .err()
        .expect("wrong function signature must be rejected");
    assert!(matches!(bad_sig_err, Error::ContractExportMismatch { .. }));

    // 2. Unexpected extra top-level export rejected statically.
    let extra_wasm = compile_market_rule_extra_export_component();
    let extra_err = manager
        .load_market_rule("bad.extra", &extra_wasm, &sha256_hex(&extra_wasm), None)
        .err()
        .expect("extra export must be rejected");
    assert!(matches!(extra_err, Error::ContractExportMismatch { .. }));

    // 3. Host-side lifting DoS protection: 48 KiB guest return inside 1 Wasm page hits
    //    `MARKET_RULE_LIFT_BYTES` (32 KiB) via `hostcall_fuel` and fails closed.
    let lift_bomb_wasm = compile_market_rule_lift_bomb_component();
    let lift_bomb = manager
        .load_market_rule(
            "fault.lift_bomb",
            &lift_bomb_wasm,
            &sha256_hex(&lift_bomb_wasm),
            None,
        )
        .expect("lift bomb loads metadata cleanly");
    let order_input = MarketRuleInput {
        trading_day: "2026-11-26".into(),
        instrument_id: "600519.SH".into(),
        side: OrderSide::Buy,
        order_type: OrderType::Limit,
        quantity: dec("100"),
        price: Some(dec("1500")),
        reference_price: Some(dec("1490")),
        settled_quantity: dec("0"),
        rule_version: "cn-a-share-v1".into(),
    };
    let lift_err = lift_bomb
        .validate_order(&order_input)
        .expect_err("oversized host lift must fail closed");
    assert!(
        matches!(lift_err, Error::HostLiftLimitExceeded { .. }),
        "expected HostLiftLimitExceeded, got {lift_err}"
    );
    assert!(lift_err.is_fail_closed());

    // 4. Canonical decimal boundary checks (host & guest).
    let tiny = dec("0.0000001");
    assert_eq!(
        crate::contract::format_host_decimal(&tiny, "tiny").expect("tiny decimal plain format"),
        "0.0000001"
    );
    assert_eq!(
        crate::contract::format_host_decimal(&dec("-0.00"), "neg_zero").expect("zero normalized"),
        "0"
    );
    assert!(matches!(
        crate::contract::format_host_decimal(&dec("0.1234567890123"), "scale13"),
        Err(Error::InvalidHostInput(_))
    ));
    assert!(matches!(
        crate::contract::format_host_decimal(&dec("12345678901234567890123456789"), "prec29"),
        Err(Error::InvalidHostInput(_))
    ));
    for bad_guest in [
        "",
        "NaN",
        "Inf",
        "1E-7",
        "1e5",
        "+1.5",
        " 1.5",
        "01.5",
        "-0",
        "-0.00",
        "1.",
        ".5",
        "0.1234567890123",
        "12345678901234567890123456789",
    ] {
        assert!(
            matches!(
                crate::contract::parse_guest_decimal(bad_guest, "test"),
                Err(Error::InvalidGuestOutput(_))
            ),
            "guest decimal {bad_guest:?} must be rejected"
        );
    }
    assert_eq!(
        crate::contract::parse_guest_decimal("50000.50", "price").expect("fixed-scale ok"),
        dec("50000.5")
    );
    assert_eq!(
        crate::contract::parse_guest_decimal("0.00", "zero").expect("positive zero ok"),
        dec("0")
    );

    // 5. MarketRule binding rejects non-empty canonical_parameters.
    let mut non_empty_params = BTreeMap::new();
    non_empty_params.insert("k".into(), "v".into());
    assert!(matches!(
        ArtifactBinding::new(
            "fault.lift_bomb",
            PluginKind::MarketRule,
            sha256_hex(&lift_bomb_wasm),
            non_empty_params.clone(),
        ),
        Err(Error::InvalidHostInput(_))
    ));
    // Even a manually constructed ArtifactBinding with non-empty params is rejected by verify_binding.
    let forged_binding = ArtifactBinding {
        plugin_id: "fault.lift_bomb".into(),
        kind: PluginKind::MarketRule,
        artifact_sha256: sha256_hex(&lift_bomb_wasm),
        wit_contract_version: WIT_CONTRACT_VERSION.into(),
        host_version: crate::HOST_RUNTIME_VERSION.into(),
        canonical_parameters: non_empty_params,
    };
    assert!(matches!(
        manager.verify_binding(&forged_binding),
        Err(Error::BindingMismatch { .. })
    ));

    // 6. Strategy on_event rejects oversized canonical_parameters (> MAX_CANONICAL_PARAMETERS).
    let strat_wasm = compile_strategy_component(false, false);
    let strat = manager
        .load_strategy(
            "strat.param_limit",
            &strat_wasm,
            &sha256_hex(&strat_wasm),
            None,
        )
        .expect("load strategy");
    let too_many_params: BTreeMap<String, String> = (0..=crate::MAX_CANONICAL_PARAMETERS)
        .map(|i| (format!("k{i}"), "1".into()))
        .collect();
    let account = ReadonlyAccountState {
        timestamp_ns: 1_764_160_000_000_000_000,
        cash_available: dec("1000"),
        total_equity: dec("1000"),
        positions: vec![],
    };
    assert!(matches!(
        strat.on_event(
            &[NamedFactor {
                name: "momentum_20".into(),
                value: None,
            }],
            &account,
            &too_many_params,
        ),
        Err(Error::InvalidHostInput(_))
    ));

    // 7. Cumulative certification fuel budget bounds admission work.
    let healthy_wasm = compile_operator_component(OperatorVariant::default());
    let tiny_cert_budget = ResourceBudget {
        max_fuel_per_call: 2_000,
        max_certification_fuel: 2_000,
        ..ResourceBudget::default()
    };
    let cert_fuel_err = manager
        .load_extended_operator(
            &healthy_wasm,
            &sha256_hex(&healthy_wasm),
            CertificationRequest {
                plugin_id: "op.cert_fuel_cap".into(),
                ..Default::default()
            },
            Some(tiny_cert_budget),
        )
        .err()
        .expect("tiny cumulative certification fuel must fail closed");
    assert!(matches!(
        cert_fuel_err,
        Error::CertificationFailed { .. } | Error::FuelExhausted { .. }
    ));

    // 8. ResourceBudget rejects invalid / out-of-ceiling limits.
    let bad_budget = ResourceBudget {
        max_host_lift_bytes: crate::HARD_MAX_HOST_LIFT_BYTES + 1,
        ..ResourceBudget::default()
    };
    assert!(matches!(
        bad_budget.validate(),
        Err(Error::InvalidBudget(_))
    ));
    let mut bad_cert_budget = ResourceBudget {
        max_certification_fuel: crate::HARD_MAX_CERTIFICATION_FUEL + 1,
        ..ResourceBudget::default()
    };
    assert!(matches!(
        bad_cert_budget.validate(),
        Err(Error::InvalidBudget(_))
    ));
    bad_cert_budget.max_certification_fuel = 0;
    assert!(matches!(
        bad_cert_budget.validate(),
        Err(Error::InvalidBudget(_))
    ));

    // 9. Linear memory accounting returns cleanly to 0 after all isolated faults.
    let metrics = manager.metrics();
    assert_eq!(metrics.live_linear_memory_bytes, 0);
    assert_eq!(metrics.active_stores, 0);
}
