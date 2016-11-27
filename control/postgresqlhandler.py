# Adapted from https://gist.github.com/danielrichman/2951265dfedee2cb4c10

import logging
import traceback
import psycopg2

class PostgreSQLHandler(logging.Handler):
    """
    A :class:`logging.Handler` that logs to the `log` PostgreSQL table.

    Does not use :class:`PostgreSQL`, keeping its own connection, in autocommit
    mode.

    .. DANGER:

        Beware explicit or automatic locks taken out in the main requests'
        transaction could deadlock with this INSERT!

        In general, avoid touching the log table entirely. SELECT queries
        do not appear to block with INSERTs. If possible, touch the log table
        in autocommit mode only.

    `db_settings` is passed to :meth:`psycopg2.connect` as kwargs
    (``connect(**db_settings)``).
    """

    _query = "INSERT INTO job_log " \
                "(job_id, type, level, message) " \
             "VALUES " \
                "(%(job_id)s, %(type)s, %(level)s, %(message)s)"

    # see TYPE log_level
    _levels = ('debug', 'info', 'warning', 'error', 'critical')

    def __init__(self, db_settings):
        super(PostgreSQLHandler, self).__init__()
        self.db_settings = db_settings
        self.connection = None
        self.cursor = None

    def emit(self, record):
        try:
            level = record.levelname.lower()
            if level not in self._levels:
                level = "debug"

            if record.exc_info:
                lines = traceback.format_exception(*record.exc_info)
                traceback_text = ''.join(lines)
            else:
                traceback_text = None

            args = {
                "job_id": getattr(record, "job_id", None),
                "type": getattr(record, "type", None),
                "level": level,
                "message": record.getMessage(),
            }

            try:
                if self.connection is None:
                    raise psycopg2.OperationalError

                self.cursor.execute(self._query, args)

            except psycopg2.OperationalError:
                self.connection = psycopg2.connect(**self.db_settings)
                self.connection.autocommit = True
                self.cursor = self.connection.cursor()

                self.cursor.execute(self._query, args)

        except Exception:
            self.handleError(record)
