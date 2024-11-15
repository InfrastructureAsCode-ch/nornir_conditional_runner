import logging
from concurrent.futures import ThreadPoolExecutor
from threading import Semaphore, Condition
from typing import Optional, List, Dict
from nornir.core.inventory import Host
from nornir.core.task import AggregatedResult, Task

logger = logging.getLogger(__name__)


class ConditionalRunner:
    """A runner that enforces concurrency limits based on host groups."""

    def __init__(
        self,
        num_workers: int = 100,
        group_limits: Optional[Dict[str, int]] = None,
        conditional_group_key: Optional[str] = None,
    ) -> None:
        """Initialize the ConditionalRunner with concurrency limit semaphores and conditions and group key."""
        self.num_workers = num_workers
        self.group_limits = group_limits or {}
        self.group_key = conditional_group_key
        self.group_semaphores: Dict[str, Semaphore] = {}
        self.group_conditions: Dict[str, Condition] = {}

        if not self.group_limits:
            logger.warning(
                "No group limits specified. Default limits will be applied to all groups."
            )
        else:
            # Initialize semaphores and conditions for each group
            for group, limit in self.group_limits.items():
                if not isinstance(limit, int) or limit <= 0:
                    raise ValueError(
                        f"Invalid limit for group '{group}': {limit}. Limit must be a positive integer."
                    )
                self.group_semaphores[group] = Semaphore(limit)
                self.group_conditions[group] = Condition()

    def run(self, task: Task, hosts: List[Host]) -> AggregatedResult:
        """Run the task for each host while respecting group-based concurrency limits."""
        logger.info("Running task with ConditionalRunner using semaphores")
        result = AggregatedResult(task.name)

        with ThreadPoolExecutor(self.num_workers) as pool:
            futures = []
            for host in hosts:
                # If the group_key is in host.data, use it; otherwise, fall back to groups
                groups = host.data.get(
                    self.group_key, [group.name for group in host.groups]
                )
                if groups == [group.name for group in host.groups] and self.group_key:
                    logger.warning(
                        f"Host '{host.name}' has no '{self.group_key}' attribute. Using groups instead."
                    )

                # dispatch_task_and_wait is called in a separate thread to avoid blocking the main thread
                futures.append(
                    pool.submit(self._dispatch_task_and_wait, task, host, groups)
                )

            # Wait for all futures to complete and collect the results
            for future in futures:
                worker_result = future.result()
                if worker_result:
                    result[worker_result.host.name] = worker_result

        return result

    def _dispatch_task_and_wait(
        self, task: Task, host: Host, groups: List[str]
    ) -> AggregatedResult:
        """Dispatch task in a separate thread and wait for the semaphore condition."""
        # Ensure semaphores and conditions are initialized for all groups
        for group in groups:
            if str(group) not in self.group_semaphores:
                logger.warning(
                    f"No limit for group '{group}'. Using default limit of {self.num_workers}."
                )
                self.group_semaphores[group] = Semaphore(self.num_workers)
                self.group_conditions[group] = Condition()

            # Wait for each group's semaphore to be available
            with self.group_conditions[group]:
                while self.group_semaphores[group]._value <= 0:
                    self.group_conditions[group].wait()

        return self._run_task_with_semaphores(task, host, groups)

    def _run_task_with_semaphores(
        self, task: Task, host: Host, groups: List[str]
    ) -> AggregatedResult:
        """Run the task for a host while respecting group-based concurrency."""
        # Acquire semaphores for each group
        acquired_semaphores = []
        for group in groups:
            self.group_semaphores[group].acquire()
            acquired_semaphores.append(group)

        try:
            # Execute the task
            result = task.copy().start(host)
        finally:
            # Release semaphores after task completion
            for group in acquired_semaphores:
                self.group_semaphores[group].release()

            # Notify other threads that may be waiting for the semaphore
            for group in groups:
                with self.group_conditions[group]:
                    self.group_conditions[group].notify_all()

        return result
