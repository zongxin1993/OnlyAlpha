-- Finite recomputation exhaustion is an operational control outcome, not a
-- result publication. Keep these three failure columns separate from result pins.
GRANT UPDATE(failure_phase,failure_code,failure_detail)
  ON public.backtest_run TO onlyalpha_node_control;
