//! Pure immutable transition data reuse. Actual SQL source and every retained
//! checkpoint remain fresh observations; no successful source proof is cached.
use super::*;
impl SqliteStore {
    fn restore_data_prefix(
        &self,
        records: &[Record],
        count: usize,
    ) -> Result<(Components, Replay), Error> {
        let prefix = records
            .get(..count)
            .ok_or_else(|| error("CHECKPOINT_AHEAD"))?;
        let configuration = self.identity["configuration"].clone();
        let checkpoint = if count == 0 {
            Components::new(configuration.clone())?.checkpoint()?
        } else {
            let prepared = prefix
                .last()
                .ok_or_else(|| error("CHECKPOINT_SEQUENCE"))?
                .prepared();
            let projections = prepared.value()["projections"]
                .as_array()
                .filter(|rows| rows.len() == 6)
                .ok_or_else(|| error("PROJECTION_HASH"))?;
            json!({"schema_version":1,"config":configuration,"sequence":count,"pending":null,"components":projections.iter().map(|projection|projection["result"].clone()).collect::<Vec<_>>()})
        };
        let mut exact = Components::new(self.identity["configuration"].clone())?;
        // The original owning readers still validate this complete original
        // checkpoint. It is derived from actual source, never a stored CP seed.
        exact.restore(&checkpoint, &hash(&checkpoint))?;
        let view = Replay {
            rows: prefix.to_vec(),
        };
        // Full aggregate and Trade/Fee checks are independent of body validity.
        // MISMATCHED remains its original diagnostic, not a synthesized MATCHED.
        view.compare(&exact)?;
        Ok((exact, view))
    }
    pub(super) fn data_checkpoint_prefix(
        &self,
        records: &[Record],
    ) -> Result<Option<(Components, Replay)>, Error> {
        if records
            .iter()
            .any(|record| !record.ready() || !record.prepared().has_validated_transition_data())
        {
            // Unsupported data eligibility takes the original complete cold
            // genesis replay; a malformed checkpoint below never falls back.
            return Ok(None);
        }
        let mut statement = sql(self
            .connection
            .prepare("SELECT sequence,payload,digest FROM checkpoints ORDER BY sequence"))?;
        let mut rows = sql(statement.query([]))?;
        let mut last = None;
        while let Some(row) = sql(rows.next())? {
            let count = usize::try_from(sql(row.get::<_, i64>(0))?)
                .map_err(|_| error("CHECKPOINT_SEQUENCE"))?;
            let value = decoded(text_column(row, 1)?, text_column(row, 2)?)?;
            let (exact, view) = self.restore_data_prefix(records, count)?;
            if value != self.checkpoint_value(&exact, view.records())? {
                return Err(error("CHECKPOINT_SOURCE_OR_COMPONENTS"));
            }
            last = Some((exact, view));
        }
        drop(rows);
        drop(statement);
        if last
            .as_ref()
            .is_some_and(|(_, view)| view.rows.len() == records.len())
        {
            return Ok(last);
        }
        self.restore_data_prefix(records, records.len()).map(Some)
    }
}
