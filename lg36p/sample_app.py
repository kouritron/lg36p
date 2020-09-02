import time
import os
import sys
import subprocess as sp

from dataclasses import dataclass
import typing
import enum

from pathlib import Path

import traceback
import inspect

from lg36p import lg36 as log

if __name__ == "__main__":

    log.dbg_dump_lg36_knobs()

    log.dbg('dddddd')
    log.info('iiiiii')
    log.warn('wwwww')
    log.err('eeeeeee')
    log.crit('cccc cccc CCCC')
    log.err('eeeeeee')
    log.warn('wwwwww')
    log.crit('cccc\ncccc CCCC 22112312321321')
    log.dbg(None)
    log.warn(None)

    log.warn('wwww')

    log.dbg_dump_lg36()
