"""Report writers: turn a scan (engine.run_scan() result) into files on disk.

Isolated from scoring logic -- these modules only format/write, they never
compute an indicator or a backtest stat themselves.
"""
