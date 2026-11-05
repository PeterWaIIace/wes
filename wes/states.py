from wes.tasks.states import State

FINISHED_STATES = (State.COMPLETED, State.FAILED, State.CANCELLED)

__all__ = ["State", "FINISHED_STATES"]
