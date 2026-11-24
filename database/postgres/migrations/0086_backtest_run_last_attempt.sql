ALTER TABLE public.backtest_run ADD COLUMN last_attempt_number integer NOT NULL DEFAULT 0
    CHECK (last_attempt_number >= 0);
GRANT UPDATE (last_attempt_number) ON public.backtest_run TO onlyalpha_node_control;
