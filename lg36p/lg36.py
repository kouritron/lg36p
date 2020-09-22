"""
A Simple logging system 4 python based around the power of sqlite3.

Advantages over python's built in logging module:
1. With logging I've often found myself going back to the config dict constantly to increase verbosity or
remove noise and have to restart the program every time to find out whats going on. This is system can be
less productive than just print statements being commented in/out.
With lg36 you can log often and in detail, and then just create views to for example:
- exclude a noisy file.
- exclude a noisy file but re-include warn+ msgs from it.
- append logs from multiple program runs and separate them into sessions.
- view only the last session.
- compare current session to one before it, and see the extra stuff that happened now.
- You can dump the sql db into a text file and text search.
- sqlite3 offers FTS to top it all up.

2. It turns out, 90% of the time, ppl dont use logging because they want to write custom handlers that do all sorts of
exotic behavior. If you want that then go ahead and use logging. Most often ppl use logging to achieve one very simple
thing, to log into stdout (possibly not so verbosely) and to log a more complete version to a file somewhere.
sqlite3 is just a superior version of that log file.

3. code over configuration. lg36 is a small file that you can drag and drop into your project. a huge amount
of functionality is achieved in roughly 200 lines, ignoring comments/whitespace and some formalities.
You can customize lg36 too even more easily.

----------
TODO: add a periodic job system, that would run, say, every 1000 msgs (user knob), or every 600 seconds (user knob),
that would clean up the DSS DB. i.e. by trimming old msgs to prevent the db from growing unbounded or would export a
JSON or dump into log stash, or s3 or something like that.

TODO: maybe add a db file sync feature for each log record that is > INFO

TODO: integrate the knobs here with "knob man"

"""

import os
import sys
import time
import shutil

from dataclasses import dataclass
import typing

from pathlib import Path
import enum
import inspect
import traceback
import multiprocessing
import threading
import queue

import sqlite3

# ======================================================================================================================
# ======================================================================================================================
# ================================================================================================================ Knobs

# Enable/Disable any log sinks.
_STDOUT_LOGGING_ENABLED = True
_DSS_ENABLED = True

# ******************** level filters
_STDOUT_LVL_FILTER_STRING = "INFO"

# DSS is supposed to be a full detail dump into sqlite3. This should generally be set to dbug always, and feel free
# to be very verbose. If you want a filtered version, add views under the deep knobs section.
_DSS_LVL_FILTER_STRING = "DBUG"

# ******************** log file/dir, disk or ram, must be string.
#_DSS_LOG_DIR = f'/tmp/mnlogs/app_{int(time.time())}_{os.urandom(4).hex()}/'
_DSS_LOG_DIR = f'/home/zu/x1ws/lg36p/ignoreme/'

# _DSS_LOG_FILE = ':memory:'
_DSS_LOG_FILE = os.path.join(_DSS_LOG_DIR, 'mnlogs.sqlite3')

# ******************** additional options.

_SQLITE_PRAGMAS = [

    # if sqlite performance is poor, dont change isolation_level=None (autocommit essentially),
    # instead disable synchronous writes. I believe its issuing a sync syscall after each transaction.
    # I once measured 2 seconds to flush ~ 500 msgs if this is left ON.
    "PRAGMA synchronous = OFF"
]

# Comment/Uncomment to start with fresh files or possibly append existing logs.
try:
    shutil.rmtree(_DSS_LOG_DIR, ignore_errors=True)
except:
    pass

# ======================================================================================================================
# ======================================================================================================================
# ======================================================================================== HIGHLY COOL Knobs (SQL views)
# This is the most magical thing about lg36. Instead of writing file handlers, subsystem filters, level this, subclass
# that, format this format that. Declare any views you want here. All of these views will be created during init.
# These views would correspond to the different ways you could've configured logging with various config dicts,
# except you dont have to constantly change these to see whats going on. All the facts are saved, you just choose
# which view you want to look at at any moment in time. The idea is you can declare lots of views during dev and just
# leave them there later on also. No need to drop the ones you are not using, because its just a free view.
# You can control dev/prod/release differences with debug functions at the bottom of this file or somewhere else.
# It just a matter of dumping a view to stdout during dev maybe and not doing that later.

# For lg36 table schema look below this section.
_DEEP_VIEWS = [

    # ******************************************************************************************************************
    # *********************************************************************************************** DEFAULT LG36 Views
    # ******************************************************************************************************************
    # these are just some common/basic views provided by lg36. You can add/remove to this list as needed.
    # half verbose
    """ CREATE VIEW IF NOT EXISTS lg36_med AS
SELECT mid, msg_lvl, session_id, unix_time, SUBSTR(caller_filename, -20) AS fname_last20, caller_lineno,
caller_funcname, pname, tname, log_msg
FROM lg36;
    """,

    # short, most useful columns
    """ CREATE VIEW IF NOT EXISTS lg36_shrt AS
SELECT mid, msg_lvl, SUBSTR(caller_filename, -20) AS fname_last20, caller_lineno, caller_funcname, log_msg
FROM lg36;
    """,

    # short last session only (most recent session), dont use select *, column names will be lost at least in DB brwser
    """ CREATE VIEW IF NOT EXISTS lg36_shrt_ls AS
SELECT mid, msg_lvl, SUBSTR(caller_filename, -20) AS fname_last20, caller_lineno, caller_funcname, log_msg
FROM lg36
WHERE session_id IN (SELECT session_id FROM lg36 ORDER BY mid DESC LIMIT 1);
    """,

    # warn level or higher
    """ CREATE VIEW IF NOT EXISTS lg36_shrt_ls_warn AS
SELECT mid, msg_lvl, SUBSTR(caller_filename, -20) AS fname_last20, caller_lineno, caller_funcname, log_msg
FROM lg36
WHERE session_id IN (SELECT session_id FROM lg36 ORDER BY mid DESC LIMIT 1)
AND msg_lvl NOT IN ('DBUG', 'INFO');
""",

    # exclude some files, LIKE rules:
    # wildcard char % matches zero or more of any char
    # wildcard char _ matches exactly one single of any char
#     """
# CREATE VIEW IF NOT EXISTS lg36_shrt_ls_no_x_file AS

# SELECT mid, msg_lvl, SUBSTR(caller_filename, -1, -20), caller_lineno, caller_funcname, log_msg
# FROM lg36
# WHERE session_id IN (SELECT session_id FROM lg36 ORDER BY mid DESC LIMIT 1)
# AND caller_filename NOT LIKE "%my_demo_xcluded_file.py";
# """,


    # ********** stats and distinct info threads and process
    """ CREATE VIEW IF NOT EXISTS stats_tname AS SELECT tname, count(tname) FROM lg36 GROUP BY tname; """,
    """ CREATE VIEW IF NOT EXISTS stats_tid AS SELECT tid, count(tid) FROM lg36 GROUP BY tid; """,
    """ CREATE VIEW IF NOT EXISTS stats_pname AS SELECT pname, count(pname) FROM lg36 GROUP BY pname; """,
    """ CREATE VIEW IF NOT EXISTS stats_pid AS SELECT pid, count(pid) FROM lg36 GROUP BY pid; """,

    # ******************************************************************************************************************
    # **************************************************************************************************#* DBG/DEV views
    # ******************************************************************************************************************
    # Add additional views here that can help inspect each subsystem separately.
]


# ======================================================================================================================
# ======================================================================================================================
# ======================================================================================================================
# ======================================================================================================================
# ======================================================================================================================
# ======================================================================================================================
# ======================================================================================================================
# ======================================================================================================================
# =============================================================================================== CONSTANTS, ENUMS, MISC

# ******************** lg 36 table
# SQLite natively supports only the types TEXT, INTEGER, REAL, BLOB and NULL.
# mid:              message id.
# session_id:       unique id created at init time, therefore unique to each init.
# unix_time:        unix time stamp with max available precision cast to string.
# msg_lvl:          log level of the msg. i.e. DBUG, INFO, WARN, ERRR, CRIT (yes all are 4 chars).
# caller_filename:  reflection derived information on who made the log call.
# caller_lineno:    reflection derived information on who made the log call.
# pname:            process name
# tname:            thread name
_LG36_SCHEMA = """
CREATE TABLE IF NOT EXISTS lg36(
    mid              INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id       TEXT,
    unix_time        TEXT,
    msg_lvl          TEXT,
    caller_filename  TEXT,
    caller_lineno    TEXT,
    caller_funcname  TEXT,
    pname            TEXT,
    pid              TEXT,
    tname            TEXT,
    tid              TEXT,
    log_msg          TEXT);
"""

# ANSI color sequences
_ANSI_RED = "\u001b[31m"
_ANSI_GREEN = "\u001b[32m"
_ANSI_YELLOW = "\u001b[33m"
_ANSI_BLUE = "\u001b[34m"
_ANSI_MAGENTA = "\u001b[35m"
_ANSI_CYAN = "\u001b[36m"
_ANSI_RESET = "\u001b[0m"


# You can do > < >= <= == comparison on these like so:
# lvl_1.value >= lvl_2.value:
class LGLVL(enum.Enum):

    DBUG = 10  # A filter set to LGLVL.DEBUG means filter nothing.
    INFO = 20
    WARN = 30
    ERRR = 40
    CRIT = 50

    def __str__(self):
        return super().__str__()[6:]  # chopping i.e. "LGLVL.DBUG", to "DBUG"


# DSS runs in a daemonic thread with this name.
_DSS_THREAD_NAME = 'data_sink_service'

# A queue for the data sink service, dss runs on its own thread and will consume this queue, app threads can
# produce to it via dbg,info,warn,... calls, objects put into it are either LOG_RECORD or meta request
_dssq = None

# not used often, just make sure in case of lazy init, you dont init in parallel.
_lg36_initialized = False
_lg36_init_lock = threading.Lock()

# these will be set to user supplied knobs during init. until then default to None or DBUG
# _SINK_STDOUT_LVL_FILTER = LGLVL.DBUG
_STDOUT_LVL_FILTER = None
_DSS_LVL_FILTER = None


# ======================================================================================================================
# ======================================================================================================================
# =========================================================================================================== Log Record
# Log record generated by lg36
@dataclass(frozen=True)
class LOG_RECORD:
    " An Immutable complete record generated for each logging message sent to lg36."

    unix_time: float

    # level attached to this log msg. i.e. if user said: log.dbg() then this is set to LGLVL.DEBUG
    msg_lvl: LGLVL

    # caller file name, line number and function name.
    caller_filename: str
    caller_lineno: str
    caller_funcname: str

    # the log msg issued to lg36.
    log_msg: str

    # process info
    pname: str
    pid: str

    # thread info
    tname: str
    tid: str


def _mk_lgr(msg_lvl, log_msg) -> LOG_RECORD:
    """ Generate a complete log record. This function should be called immediately after a log msg was called on
    mnlogger. (i.e. after a log.dbg(), log.info(), log.warn() call took place). This is because this function
    will look up the call stack to try and locate the stack frame of the function that issued the log call. """

    # inspect docs: https://docs.python.org/3/library/inspect.html
    # inspect.stack() returns a list of FrameInfo Objects, the first one (idx==0) belongs to this function itself
    # _mk_lgr -> idx_0                      (this func)
    # {dbg,info,warn,...} -> idx_1          (this func caller)
    # lg36 user -> idx_2
    tmp_inspect_res = inspect.stack()
    caller_frame_info = tmp_inspect_res[2]

    unix_time = time.time()

    caller_filename = caller_frame_info.filename
    caller_lineno = str(caller_frame_info.lineno)
    caller_funcname = caller_frame_info.function
    # caller_funcname = inspect.currentframe().f_back.f_back.f_code.co_name

    # this is always going to the one line of code that looks like log.dbg('...')
    # caller_code_cntxt = caller_frame_info.code_context

    cp = multiprocessing.current_process()
    ct = threading.current_thread()
    pname = cp.name
    pid = str(cp.pid)

    tname = ct.name
    tid = str(ct.ident)

    # Now Create the log record.
    lgr = LOG_RECORD(
        unix_time=unix_time,
        msg_lvl=msg_lvl,
        caller_filename=caller_filename,
        caller_lineno=caller_lineno,
        caller_funcname=caller_funcname,
        log_msg=log_msg,
        pname=pname,
        pid=pid,
        tname=tname,
        tid=tid,
    )

    return lgr


# ======================================================================================================================
# ======================================================================================================================
# =============================================================================================================== Format
# all formatting logic should be here. lg36 will use this.
def _get_stdout_msg_fmt(lgr: LOG_RECORD) -> str:

    # time_str = str(lgr.unix_time).ljust(18)  # at least 18 chars, does not shorten
    # msg_builder = f"{time_str}|{lgr.caller_filename}:{lgr.caller_lineno}"
    # msg_builder += f"|P:{lgr.pname}:{lgr.pid}|T:{lgr.tname}:{lgr.tid}|{lgr.log_msg}"

    fbasename = os.path.basename(lgr.caller_filename)
    msg_builder = f"{int(lgr.unix_time)}|{fbasename}:{lgr.caller_lineno}|{lgr.log_msg}"

    if lgr.msg_lvl == LGLVL.DBUG:
        msg_builder = f'DBUG|{msg_builder}'

    if lgr.msg_lvl == LGLVL.INFO:
        msg_builder = f'{_ANSI_GREEN}INFO|{msg_builder}{_ANSI_RESET}'

    if lgr.msg_lvl == LGLVL.WARN:
        msg_builder = f'{_ANSI_BLUE}WARN|{msg_builder}{_ANSI_RESET}'

    if lgr.msg_lvl == LGLVL.ERRR:
        msg_builder = f'{_ANSI_YELLOW}ERRR|{msg_builder}{_ANSI_RESET}'

    if lgr.msg_lvl == LGLVL.CRIT:
        msg_builder = f'{_ANSI_RED}CRIT|{msg_builder}{_ANSI_RESET}'

    return msg_builder


# ======================================================================================================================
# ======================================================================================================================
# ==================================================================================================== Data Sink Service
class DATA_SINK_SERVICE:
    def __init__(self):

        super().__init__()

        # 4 bytes (32 bits) is already as big as IPv4. With 6 bytes, chance of collision is "2 to the -48"
        self._session_id = str(os.urandom(6).hex())

        # ********** db connection
        try:
            # make _DSS_LOG_DIR if not exists.
            Path(_DSS_LOG_DIR).resolve().mkdir(parents=True, exist_ok=True)
        except Exception as ex:
            # this is happening during init, print if something happens
            print(f'Error creating parent directory for lg36 db file: {ex}')

        # Isolation_level=None means autocommit. IMO autocommit should be preferred, despite widespread misconceptions.
        # Bad idea to keep transaction open unless you rly need them. Request one with BEGIN and COMMIT, if necessary.
        self._db_conn = sqlite3.connect(str(_DSS_LOG_FILE), isolation_level=None)

        cursr = self._db_conn.cursor()

        # ********** PRAGMA if any
        for prag in _SQLITE_PRAGMAS:
            cursr.execute(prag)

        # ********** Schema
        cursr.execute(_LG36_SCHEMA)

        # ********** deep views
        for deep_view in _DEEP_VIEWS:
            cursr.execute(deep_view)

        cursr.close()  # unnecessary but do it anyway

    def _save_lgr(self, lgr: LOG_RECORD):
        """ Save the given log record into the log records table."""

        cursr = self._db_conn.cursor()

        query = """ INSERT INTO lg36(session_id, unix_time, msg_lvl, caller_filename, caller_lineno, caller_funcname,
        pname, pid, tname, tid, log_msg) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) """

        row = (self._session_id, str(lgr.unix_time), str(lgr.msg_lvl), lgr.caller_filename, lgr.caller_lineno,
               lgr.caller_funcname, lgr.pname, lgr.pid, lgr.tname, lgr.tid, lgr.log_msg)

        cursr.execute(query, row)

        # not needed in sqlite, but do it anyway.
        cursr.close()

    def process_req(self, req):
        """ Process a request that was sent to the DSS Queue. The request must be an instance of:
        - LOG_RECORD
        - DSS_META_REQUEST
        """

        # ******************** LOG_RECORD
        if isinstance(req, LOG_RECORD):
            self._save_lgr(req)

        # ******************** DSS_META_REQUEST
        # NOTE: we might never really need this. I can only think of a flush() call from lg36 user needing
        # to send meta request to DSS, but flush is already done automatically every few seconds.
        # still we might add something else in the future, so here is a mechanism by which to send requests to
        # the data sink service.


# ======================================================================================================================
# ======================================================================================================================
# ======================================================================================================== DSS/LG36 INIT
def _dss_entry():
    """ Entry point for the data sink service daemon. This service will poll the dss queue for work and perform it. """

    # init dss, init the service itself. db conn.
    dss = DATA_SINK_SERVICE()

    # dss thread (which is daemonic) never leaves this loop
    while True:

        try:
            # block until an item is available
            next_req = _dssq.get(block=True)
        # except queue.Empty as ex:
        except Exception as ex:
            print(f"DSS Error: {ex}")

        # process next_req
        dss.process_req(req=next_req)


def _lg36_internal_init():

    global _dssq
    global _lg36_init_lock
    global _lg36_initialized
    global _STDOUT_LVL_FILTER
    global _DSS_LVL_FILTER

    # make sure, you dont do multiple inits concurrently on multiple threads
    with _lg36_init_lock:

        # check again, after getting the lock, to make sure we are not initialized.
        if not _lg36_initialized:

            # ******************** knobs init
            _STDOUT_LVL_FILTER = _string_2_lglvl(_STDOUT_LVL_FILTER_STRING)
            _DSS_LVL_FILTER = _string_2_lglvl(_DSS_LVL_FILTER_STRING)

            # ******************** dss init
            _dssq = queue.Queue()
            t = threading.Thread(target=_dss_entry, name=_DSS_THREAD_NAME)
            t.setDaemon(True)
            t.start()

            # set the init flag to true, so it doesnt init again (unless someone cleared it knowingly)
            _lg36_initialized = True


# ======================================================================================================================
# ======================================================================================================================
# ============================================================================================================== Utility
# To make knobs easier to work with, we allow them to be set as string (i.e. "DBUG") instead of later declared types
def _string_2_lglvl(lvl_str: str) -> LGLVL:

    if lvl_str in {"DBUG", "dbug", 'DBG', 'dbg', 'DEBUG', 'debug'}:
        return LGLVL.DBUG

    if lvl_str in {"INFO", "info"}:
        return LGLVL.INFO

    if lvl_str in {"WARN", "warn", 'WARNING', 'warning'}:
        return LGLVL.WARN

    if lvl_str in {"ERRR", "err", "ERROR", "error"}:
        return LGLVL.ERRR

    if lvl_str in {"CRIT", "crit"}:
        return LGLVL.CRIT

    # if none of settle for a default.
    print("Invalid log level string. Must be one of DBUG, INFO, WARN, ERRR, CRIT.")
    return LGLVL.DBUG


def _process_lgr(lgr: LOG_RECORD):

    # lazy init if needed
    if not _lg36_initialized:
        _lg36_internal_init()

    # **************************************** stdout sink
    if _STDOUT_LOGGING_ENABLED and (lgr.msg_lvl.value >= _STDOUT_LVL_FILTER.value):

        fmt_msg_str = _get_stdout_msg_fmt(lgr=lgr)
        print(fmt_msg_str)  # print good enof for stdout.

    # **************************************** dss sink
    if _DSS_ENABLED and (lgr.msg_lvl.value >= _DSS_LVL_FILTER.value):

        # post it into the dss queue. Dont want logging to crash the application even if something goes wrong
        # later at runtime. Ignore the errors if they arise, but maybe print something to stdout.
        try:
            _dssq.put_nowait(lgr)
        except Exception as ex:
            print(f"lg36 error: unable to write to dss queue. Exception: {ex}")


# ======================================================================================================================
# ======================================================================================================================
# ==================================================================================================== lg36 exported API
def dbg(msg=None):

    lgr = _mk_lgr(msg_lvl=LGLVL.DBUG, log_msg=msg)
    _process_lgr(lgr)


def info(msg=None):

    lgr = _mk_lgr(msg_lvl=LGLVL.INFO, log_msg=msg)
    _process_lgr(lgr)


def warn(msg=None):

    lgr = _mk_lgr(msg_lvl=LGLVL.WARN, log_msg=msg)
    _process_lgr(lgr)


def err(msg=None):

    lgr = _mk_lgr(msg_lvl=LGLVL.ERRR, log_msg=msg)
    _process_lgr(lgr)


def crit(msg=None):

    lgr = _mk_lgr(msg_lvl=LGLVL.CRIT, log_msg=msg)
    _process_lgr(lgr)


def init_lg36(init_conf=None):
    """ Optional init call to let lg36 know it can go ahead and init itself now. If this call is never made, lg36
    would initialize lazily as necessary.

    init_conf is optional also, if it is None, this call reduces to just a trigger to run the init procedure now
    as opposed to later.
    """
    # TODO set global opts to whats in init_conf
    _ = init_conf

    _lg36_internal_init()


def flush_curr_thread():

    # TODO The correct flush implementation would be:
    # - generate a random string called sentinel.
    # - post the sentinel to the dssq as a meta request, not a log record.
    # - DSS, upon seeing a sentinel would add it to a global set. thats it just a set.
    # - sleep wait and poll that set here, until it shows up. once it shows up, discard it from the set, return
    # to user current threads msgs must have all been seen by the DSS, therefore we are flushed out.

    # a crude alternative
    time.sleep(0.3)


# ======================================================================================================================
# ============================================================================================================== DEV/DBG
# ======================================================================================================================
# These functions are used just for convenience during debugging/dev. These should be no part of productionized
# operations or any release packages. You can use the search tool (gdz_search) to check that calls to these are outside
# production code paths. Normally its just called from a unit test file or a ignorable "__main__" section.

# we could put whole queries here and add convenient formatting but if you do create useful views,
# its better to declare them under deep knobs so it gets saved in the sqlite file for later viewing also.
# dont worry about not saving some quick and dirty formatting.

_SEP_LINE = '-' * 80


# quick and dirty fmt for dbg.
def _db_row_to_string(row):

    msg_builder = ""

    for cell in row:
        msg_builder = f"{msg_builder}|{cell}"

    # this is not correct always, but good enof for dbg
    if "INFO" in msg_builder:
        msg_builder = f'{_ANSI_GREEN}{msg_builder}{_ANSI_RESET}'
    elif "WARN" in msg_builder:
        msg_builder = f'{_ANSI_BLUE}{msg_builder}{_ANSI_RESET}'
    elif "ERRR" in msg_builder:
        msg_builder = f'{_ANSI_YELLOW}{msg_builder}{_ANSI_RESET}'
    elif "CRIT" in msg_builder:
        msg_builder = f'{_ANSI_RED}{msg_builder}{_ANSI_RESET}'

    return msg_builder


def _get_ro_db_conn_if_possible():

    # db_conn = sqlite3.connect(_DSS_LOG_FILE)
    # sqlite3.connect('file:path/to/database?mode=ro', uri=True) # uri added to sqlite in version 3.4

    # To open in read only (works on linux and OS/X)
    db_fd_ro = os.open(_DSS_LOG_FILE, os.O_RDONLY)

    # db_conn.close() can be called as many times as you want after this. worst case its a NOP
    db_conn = sqlite3.connect(f"/dev/fd/{db_fd_ro}")

    # not needed anymore.
    os.close(db_fd_ro)

    return db_conn


def dump_lg36_knobs():

    print(f"\n# {_SEP_LINE}>>>>> dbg_dump_lg36_knobs(): ")

    print(f"_STDOUT_LOGGING_ENABLED: {_STDOUT_LOGGING_ENABLED}")
    print(f"_DSS_ENABLED: {_DSS_ENABLED}")
    print()

    print(f"_STDOUT_LVL_FILTER_STRING: {_STDOUT_LVL_FILTER_STRING}")
    print(f"_DSS_LVL_FILTER_STRING: {_DSS_LVL_FILTER_STRING}")
    print()

    print(f"_DSS_LOG_DIR: {_DSS_LOG_DIR}")
    print(f"_DSS_LOG_FILE: {_DSS_LOG_FILE}")
    print()

    print(f"# {_SEP_LINE}<<<<<\n")


def dump_lg36():

    flush_curr_thread()

    view_name = "lg36"
    print(f"\n# {_SEP_LINE}>>>>> {view_name}: ")

    try:
        db_conn = _get_ro_db_conn_if_possible()
        cursr = db_conn.execute(f'SELECT * FROM {view_name};')

        rows = cursr.fetchall()
        for row in rows:
            print(_db_row_to_string(row))

    except Exception as ex:
        print(f'Error: {ex}')
    finally:
        # this is the correct way to handle this. close db_conn in the finally clause. You can repeat
        # db_conn.close() as many times as you like, its either a NOP or it will release resources it maybe holding.
        db_conn.close()

    print(f"# {_SEP_LINE}<<<<<\n")


# **********************************************************************************************************************
# **********************************************************************************************************************
# ********************************************************************************************* subsystem dbg view dumps

# Add whatever you need.
