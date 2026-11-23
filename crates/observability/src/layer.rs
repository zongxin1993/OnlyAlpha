use crate::{
    Mode,
    output::{Counters, nanos, wall_time},
};
use serde_json::{Map, Value, json};
use std::{
    io::Write,
    sync::{
        Arc,
        atomic::{AtomicU64, Ordering},
    },
    time::Instant,
};
use tracing::{
    Event, Subscriber,
    field::{Field, Visit},
    span::{Attributes, Id},
};
use tracing_appender::non_blocking::NonBlocking;
use tracing_subscriber::{Layer, layer::Context, registry::LookupSpan};
pub(crate) struct ObservationLayer {
    pub mode: Mode,
    pub process_instance_id: String,
    pub origin: Instant,
    pub writer: NonBlocking,
    pub counters: Arc<Counters>,
    pub next_operation_id: AtomicU64,
}
#[derive(Clone)]
struct OperationData {
    fields: Map<String, Value>,
    start: Option<u64>,
}
/// 动态 Debug 一律忽略，不调用用户对象的格式化实现。
#[derive(Default)]
struct Fields(Map<String, Value>);
fn admitted(name: &str) -> bool {
    matches!(
        name,
        "event_kind"
            | "request_id"
            | "command_id"
            | "run_id"
            | "attempt"
            | "links"
            | "module"
            | "operation"
            | "outcome"
            | "work_items"
            | "bytes"
            | "error_code"
            | "lock_type"
            | "device"
            | "inode"
            | "errno"
            | "file_path"
            | "expected_value"
            | "actual_value"
    )
}
impl Visit for Fields {
    fn record_str(&mut self, field: &Field, value: &str) {
        let limit = if field.name() == "file_path" {
            4096
        } else {
            256
        };
        if admitted(field.name()) && !value.is_empty() && value.len() <= limit {
            self.0.insert(field.name().into(), json!(value));
        }
    }
    fn record_u64(&mut self, field: &Field, value: u64) {
        if admitted(field.name()) {
            self.0.insert(field.name().into(), json!(value));
        }
    }
    fn record_i64(&mut self, field: &Field, value: i64) {
        if admitted(field.name()) {
            self.0.insert(field.name().into(), json!(value));
        }
    }
    fn record_bool(&mut self, field: &Field, value: bool) {
        if admitted(field.name()) {
            self.0.insert(field.name().into(), json!(value));
        }
    }
    fn record_debug(&mut self, _field: &Field, _value: &dyn std::fmt::Debug) {}
}
impl ObservationLayer {
    pub(crate) fn emit(&self, mut row: Value) {
        row["schema_version"] = json!(1);
        row["process_instance_id"] = json!(self.process_instance_id);
        row["pid"] = json!(std::process::id());
        if row.get("mono_ns").is_none() {
            row["mono_ns"] = json!(nanos(self.origin.elapsed().as_nanos()));
        }
        row["wall_time_unix_ns"] = json!(wall_time());
        if let Ok(mut bytes) = serde_json::to_vec(&row) {
            bytes.push(b'\n');
            self.counters.submitted.fetch_add(1, Ordering::Release);
            // 入的是有界队列；底层 I/O 错误由 CheckedWriter 统计。
            let _ = self.writer.clone().write_all(&bytes);
        }
    }
}
impl<S: Subscriber + for<'a> LookupSpan<'a>> Layer<S> for ObservationLayer {
    fn on_record(&self, id: &Id, values: &tracing::span::Record<'_>, ctx: Context<'_, S>) {
        let mut fields = Fields::default();
        values.record(&mut fields);
        fields
            .0
            .retain(|key, _| matches!(key.as_str(), "lock_type" | "device" | "inode" | "errno"));
        if let Some(span) = ctx.span(id)
            && let Some(data) = span.extensions_mut().get_mut::<OperationData>()
        {
            data.fields.extend(fields.0);
        }
    }
    fn on_new_span(&self, attrs: &Attributes<'_>, id: &Id, ctx: Context<'_, S>) {
        if attrs.metadata().target() != "onlyalpha.observability" {
            return;
        }
        let mut fields = Fields::default();
        attrs.record(&mut fields);
        // Registry 的槽位与 generation 会循环使用，不能充当进程内诊断身份。
        let operation_id = self
            .next_operation_id
            .fetch_add(1, Ordering::Relaxed)
            .to_string();
        let parent = attrs.parent().and_then(|id| ctx.span(id)).or_else(|| {
            attrs
                .is_contextual()
                .then(|| ctx.lookup_current())
                .flatten()
        });
        let mut inherited = Map::new();
        if let Some(parent) = parent
            && let Some(data) = parent.extensions().get::<OperationData>()
        {
            for key in ["trace_id", "request_id", "command_id", "run_id", "attempt"] {
                if let Some(value) = data.fields.get(key) {
                    inherited.insert(key.into(), value.clone());
                }
            }
            inherited.insert("parent_span_id".into(), data.fields["span_id"].clone());
        }
        inherited.extend(fields.0);
        inherited
            .entry("trace_id")
            .or_insert_with(|| json!(format!("{}:{}", self.process_instance_id, operation_id)));
        inherited.insert("span_id".into(), json!(operation_id));
        if let Some(span) = ctx.span(id) {
            span.extensions_mut().insert(OperationData {
                fields: inherited,
                start: None,
            });
        }
    }
    fn on_event(&self, event: &Event<'_>, ctx: Context<'_, S>) {
        if event.metadata().target() != "onlyalpha.observability" {
            return;
        }
        let mut fields = Fields::default();
        event.record(&mut fields);
        let kind = fields
            .0
            .get("event_kind")
            .and_then(Value::as_str)
            .unwrap_or("")
            .to_owned();
        let now = nanos(self.origin.elapsed().as_nanos());
        let mut row = Map::new();
        if let Some(span) = ctx.event_span(event) {
            let mut extensions = span.extensions_mut();
            if let Some(data) = extensions.get_mut::<OperationData>() {
                row.extend(data.fields.clone());
                if kind == "operation_start" {
                    data.start = Some(now);
                }
                if kind == "operation_end"
                    && let Some(start) = data.start
                {
                    row.extend([
                        ("start_mono_ns".into(), json!(start)),
                        ("end_mono_ns".into(), json!(now)),
                        ("duration_ns".into(), json!(now.saturating_sub(start))),
                    ]);
                }
            }
        }
        row.extend(fields.0);
        if self.mode == Mode::Basic
            && kind != "summary"
            && !matches!(
                row.get("outcome").and_then(Value::as_str),
                Some("failed" | "incomplete" | "dropped")
            )
        {
            return;
        }
        row.insert("mono_ns".into(), json!(now));
        self.emit(Value::Object(row));
    }
}

pub(crate) fn linked_current() -> crate::Correlation {
    tracing::Span::current()
        .with_subscriber(|(id, dispatch)| {
            let registry = dispatch.downcast_ref::<tracing_subscriber::Registry>()?;
            let span = registry.span(id)?;
            let extensions = span.extensions();
            let data = extensions.get::<OperationData>()?;
            let text = |key| {
                data.fields
                    .get(key)
                    .and_then(Value::as_str)
                    .map(str::to_owned)
            };
            Some(crate::Correlation {
                request_id: text("request_id"),
                command_id: text("command_id"),
                run_id: text("run_id"),
                attempt: data.fields.get("attempt").and_then(Value::as_u64),
                links: Some(format!("{}/{}", text("trace_id")?, text("span_id")?)),
            })
        })
        .flatten()
        .unwrap_or_default()
}
