"""Domain models for flights, time options, and schedules."""
from airline_optimizer.domain.flights import FlightInstance, TimeOption
from airline_optimizer.domain.solutions import ScheduleMetrics, ScheduleState

__all__ = ["FlightInstance", "TimeOption", "ScheduleMetrics", "ScheduleState"]
