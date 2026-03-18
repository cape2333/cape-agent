from enum import Enum


class Status(str, Enum):
    classifying = "classifying"
    decomposing = "decomposing"
    executing = "executing"
    done = "done"
